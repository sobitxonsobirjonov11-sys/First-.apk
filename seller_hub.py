from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
import requests

# =====================================================================
# 1. ASOSIY SOZLAMALAR (BU YERNI O'ZINGIZGA MOSLAB SOZLANG)
# =====================================================================
APP_VERSION = "1.1.0"
HOST = "127.0.0.1"
PORT = 8765

# Eski versiyani bloklash uchun version.json havolasi (ixtiyoriy)
# JSON formati: {"min_version": "1.1.0", "latest_version": "1.1.0", "update_url": "https://...", "message": "..."}
VERSION_CHECK_URL = os.getenv("VERSION_CHECK_URL", "").strip()

# TAVSIYA / TAKLIFLAR UCHUN SIZNING MAXFIY BOTINGIZ VA CHAT ID'INGIZ
# (Tashqi serversiz, to'g'ridan-to'g'ri shu bot orqali sizga keladi)
FEEDBACK_BOT_TOKEN = os.getenv("FEEDBACK_BOT_TOKEN", "8956765524:AAHI3tEe-9mKnWqKAEpx2Q-2DoPUaaKxxq0").strip()
FEEDBACK_CHAT_ID = os.getenv("FEEDBACK_CHAT_ID", "-1004304501846").strip()

# Foydalanuvchi lokal ma'lumotlari va versiya keshi fayllari
DATA_FILE = "local_seller_data.json"
VERSION_CACHE_FILE = "version_cache.json"
OFFLINE_GRACE_SECONDS = 86400  # 24 soat

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)


# =====================================================================
# 2. VERSIYA NAZORATI (ESKI VERSIYANI BLOKLASH)
# =====================================================================
def parse_version(v: str) -> tuple[int, ...]:
  parts = []
  for x in str(v).strip().split("."):
    try:
      parts.append(int(x))
    except ValueError:
      parts.append(0)
  return tuple(parts)


def check_version_policy() -> dict:
  if not VERSION_CHECK_URL:
    return {
        "allowed": True,
        "status": "local_only",
        "message": f"Versiya {APP_VERSION} (lokal rejim)",
        "update_url": "",
    }

  now = time.time()
  info = None

  try:
    r = requests.get(VERSION_CHECK_URL, timeout=8)
    r.raise_for_status()
    info = r.json()
    with open(VERSION_CACHE_FILE, "w", encoding="utf-8") as f:
      json.dump({"checked_at": now, "info": info}, f)
  except Exception:
    if os.path.exists(VERSION_CACHE_FILE):
      try:
        with open(VERSION_CACHE_FILE, "r", encoding="utf-8") as f:
          cached = json.load(f)
        if now - float(cached.get("checked_at", 0)) <= OFFLINE_GRACE_SECONDS:
          info = cached.get("info")
      except Exception:
        info = None

  if not info:
    return {
        "allowed": False,
        "status": "offline_blocked",
        "message": "Versiyani tekshirish uchun internetga ulaning.",
        "update_url": "",
    }

  min_v = info.get("min_version", APP_VERSION)
  latest_v = info.get("latest_version", APP_VERSION)
  upd_url = info.get("update_url", "")
  custom_msg = info.get("message", "")

  if parse_version(APP_VERSION) < parse_version(min_v):
    return {
        "allowed": False,
        "status": "outdated",
        "message": (
            f"Sizdagi {APP_VERSION} versiya eskirgan. "
            f"Minimal talab etiladigan versiya: {min_v}. {custom_msg}"
        ).strip(),
        "update_url": upd_url,
    }

  if parse_version(APP_VERSION) < parse_version(latest_v):
    return {
        "allowed": True,
        "status": "update_available",
        "message": f"Yangi {latest_v} versiya mavjud! {custom_msg}".strip(),
        "update_url": upd_url,
    }

  return {
      "allowed": True,
      "status": "ok",
      "message": f"Faol versiya: {APP_VERSION}",
      "update_url": "",
  }


# =====================================================================
# 3. LOKAL XOTIRA (HAR BIR ILOVA O'ZIDA SAQLAYDI)
# =====================================================================
def default_state() -> dict:
  return {
      "settings": {
          "copy_to_group": False,
          "user_bot_token": "",
          "user_group_id": "",
          "gemini_api_key": "",
      },
      "products": {},
      "alerts": [],
  }


def load_state() -> dict:
  if not os.path.exists(DATA_FILE):
    st = default_state()
    save_state(st)
    return st
  try:
    with open(DATA_FILE, "r", encoding="utf-8") as f:
      data = json.load(f)
      base = default_state()
      base["settings"].update(data.get("settings", {}))
      base["products"] = data.get("products", {})
      base["alerts"] = data.get("alerts", [])
      return base
  except Exception:
    return default_state()


def save_state(state: dict) -> None:
  with open(DATA_FILE, "w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False, indent=2)


# =====================================================================
# 4. TELEGRAM YUBORISH (FOYDALANUVCHI GURUHI VA MAXFIY TAKLIF BOTI)
# =====================================================================
def tg_send(bot_token: str, chat_id: str, text: str) -> tuple[bool, str]:
  if not bot_token or bot_token.startswith("YOUR_"):
    return False, "Bot token sozlanmagan."
  if not chat_id or chat_id.startswith("YOUR_"):
    return False, "Chat ID sozlanmagan."
  try:
    r = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=15,
    )
    d = r.json()
    if d.get("ok"):
      return True, "Yuborildi."
    return False, f"Telegram xatosi: {d.get('description', d)}"
  except Exception as exc:
    return False, f"Tarmoq xatosi: {exc}"


def send_group_copy(text: str) -> tuple[bool, str]:
  cfg = load_state()["settings"]
  if not cfg.get("copy_to_group"):
    return False, "Guruhga nusxa o'chirilgan."
  token = str(cfg.get("user_bot_token", "")).strip()
  gid = str(cfg.get("user_group_id", "")).strip()
  return tg_send(token, gid, text)


def send_feedback_to_owner(category: str, message: str, contact: str = "") -> tuple[bool, str]:
  now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
  text = (
      f"#TAKLife / #TAVSIYA\n"
      f"Tur: {category}\n"
      f"Ilova versiyasi: {APP_VERSION}\n"
      f"Aloqa: {contact or 'ko‘rsatilmagan'}\n"
      f"Vaqt: {now_str}\n"
      f"-----------------------------\n"
      f"{message}"
  )
  return tg_send(FEEDBACK_BOT_TOKEN, FEEDBACK_CHAT_ID, text)


# =====================================================================
# 5. BIZNES MANTIQI: KALKULYATOR, KUZATUV, AI TAVSIF
# =====================================================================
def calc_profit(
    sell_price: float,
    cost_price: float,
    logistics: float,
    commission_pct: float,
    tax_pct: float,
    ads_pct: float,
) -> dict:
  if sell_price <= 0:
    raise ValueError("Sotuv narxi 0 dan katta bo'lishi kerak.")
  total_pct = commission_pct + tax_pct + ads_pct
  share = total_pct / 100.0
  if share >= 1.0:
    raise ValueError("Foizli xarajatlar yig'indisi 100% dan oshmasligi kerak.")

  pct_amount = sell_price * share
  fixed_amount = cost_price + logistics
  net_profit = sell_price - pct_amount - fixed_amount
  margin_pct = (net_profit / sell_price) * 100.0
  min_price = fixed_amount / (1.0 - share)

  return {
      "sell_price": sell_price,
      "fixed_amount": fixed_amount,
      "pct_amount": pct_amount,
      "total_pct": total_pct,
      "net_profit": net_profit,
      "margin_pct": round(margin_pct, 2),
      "min_price": round(min_price, 0),
  }


def fetch_price_from_url(url: str) -> float | None:
  try:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                "Chrome/120.0.0.0 Mobile Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
      html = resp.read().decode("utf-8", errors="ignore")
    matches = re.findall(
        r'"(?:price|sellPrice|minPrice)"\s*:\s*(\d+(?:\.\d+)?)', html
    )
    for m in matches:
      val = float(m)
      if val > 100:
        return val
    return None
  except Exception:
    return None


def generate_ai_or_template(name: str, features: str, audience: str) -> dict:
  api_key = str(load_state()["settings"].get("gemini_api_key", "")).strip()
  target = audience.strip() or "xaridorlar"
  feats = [x.strip() for x in features.split(",") if x.strip()]

  if api_key:
    prompt = (
        "Marketpleys (Uzum/WB) uchun o'zbekcha tavsif tayyorla.\n"
        'Faqat JSON qaytar: {"title":"...","description":"...","keywords":["..."]}\n'
        f"Mahsulot: {name}\nXususiyatlar: {', '.join(feats) or 'yoq'}\nKim uchun: {target}"
    )
    try:
      r = requests.post(
          f"{GEMINI_URL}?key={api_key}",
          json={
              "contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"responseMimeType": "application/json"},
          },
          timeout=20,
      )
      r.raise_for_status()
      raw = r.json()["candidates"][0]["content"]["parts"][0]["text"]
      parsed = json.loads(raw)
      return {
          "source": "gemini",
          "title": parsed.get("title", name),
          "description": parsed.get("description", ""),
          "keywords": parsed.get("keywords", feats[:8]),
      }
    except Exception:
      pass

  bullets = "\n".join(f"• {f}" for f in feats)
  return {
      "source": "template",
      "title": f"{name} — {target} uchun",
      "description": (
          f"{name} ({target} uchun).\n{bullets}" if bullets else f"{name} — {target} uchun."
      ),
      "keywords": [name.lower()] + [f.lower() for f in feats],
  }


# =====================================================================
# 6. ILOVA INTERFEYSI (TUGMALI MENYU + KLAVIATURA + TAKLIFLAR)
# =====================================================================
APP_HTML = """<!doctype html>
<html lang="uz">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Seller Hub</title>
<style>
  * { box-sizing: border-box; font-family: system-ui, sans-serif; }
  body { margin: 0; background: #101418; color: #f1f5f9; padding: 14px; }
  .hidden { display: none !important; }
  .menu-btn { width: 100%; padding: 15px; margin: 7px 0; font-size: 16px; border: 0; border-radius: 10px; background: #1e293b; color: #fff; text-align: left; cursor: pointer; }
  .menu-btn:hover { background: #334155; }
  .back-btn { padding: 10px 14px; border: 0; border-radius: 8px; background: #334155; color: #fff; cursor: pointer; margin-bottom: 12px; }
  .action-btn { width: 100%; padding: 12px; margin-top: 8px; border: 0; border-radius: 8px; background: #2563eb; color: #fff; font-size: 15px; cursor: pointer; }
  input, select, textarea { width: 100%; padding: 10px; margin: 6px 0; border-radius: 8px; border: 1px solid #334155; background: #0f172a; color: #fff; font-size: 15px; }
  .active-field { border-color: #38bdf8; outline: 2px solid #0284c7; }
  .keypad { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 10px; }
  .key { padding: 13px; font-size: 17px; border: 0; border-radius: 8px; background: #1e293b; color: #fff; cursor: pointer; }
  .key:active { background: #475569; }
  .out { background: #0f172a; padding: 12px; border-radius: 8px; margin-top: 10px; white-space: pre-wrap; border: 1px solid #1e293b; }
  .banner { background: #172554; border: 1px solid #1d4ed8; padding: 10px; border-radius: 8px; margin-bottom: 10px; font-size: 13px; }
  .blocked { background: #450a0a; border: 1px solid #dc2626; color: #fecaca; padding: 16px; border-radius: 10px; }
</style>
</head>
<body>

<div id="blockedView" class="blocked hidden"></div>

<div id="mainApp">
  <div id="verBanner" class="banner"></div>

  <div id="homeView">
    <h3>Qaysi amalga kirmoqchisiz?</h3>
    <button class="menu-btn" onclick="openView('calcView')">🧮 Foyda kalkulyatori</button>
    <button class="menu-btn" onclick="openView('trackView')">🔗 Mahsulot kuzatuvi (URL)</button>
    <button class="menu-btn" onclick="openView('aiView')">🤖 AI Tavsif va kalit so'z</button>
    <button class="menu-btn" onclick="openView('fbView')">💡 Tavsiya / Takliflar</button>
    <button class="menu-btn" onclick="openView('cfgView')">⚙️ Sozlamalar (Bot, Guruh, AI)</button>
  </div>

  <div id="calcView" class="hidden">
    <button class="back-btn" onclick="openView('homeView')">← Menyu</button>
    <h3>Foyda kalkulyatori</h3>
    <input id="f_sell" class="calc-inp active-field" placeholder="Sotuv narxi" onclick="focusInp(this)">
    <input id="f_cost" class="calc-inp" placeholder="Tan narx" onclick="focusInp(this)">
    <input id="f_log" class="calc-inp" placeholder="Logistika" value="0" onclick="focusInp(this)">
    <input id="f_comm" class="calc-inp" placeholder="Komissiya %" value="15" onclick="focusInp(this)">
    <input id="f_tax" class="calc-inp" placeholder="Soliq %" value="0" onclick="focusInp(this)">
    <input id="f_ads" class="calc-inp" placeholder="Reklama %" value="0" onclick="focusInp(this)">
    <label><input type="checkbox" id="f_grp"> Guruhga nusxa yuborilsin</label>

    <div class="keypad">
      <button class="key" onclick="pressKey('7')">7</button>
      <button class="key" onclick="pressKey('8')">8</button>
      <button class="key" onclick="pressKey('9')">9</button>
      <button class="key" onclick="pressKey('4')">4</button>
      <button class="key" onclick="pressKey('5')">5</button>
      <button class="key" onclick="pressKey('6')">6</button>
      <button class="key" onclick="pressKey('1')">1</button>
      <button class="key" onclick="pressKey('2')">2</button>
      <button class="key" onclick="pressKey('3')">3</button>
      <button class="key" onclick="pressKey('0')">0</button>
      <button class="key" onclick="pressKey('000')">000</button>
      <button class="key" onclick="pressKey('.')">.</button>
      <button class="key" onclick="pressKey('C')">C</button>
      <button class="key" onclick="pressKey('BACK')">←</button>
      <button class="key" onclick="nextInp()">→</button>
    </div>

    <button class="action-btn" onclick="submitCalc()">Hisoblash</button>
    <div id="calcOut" class="out hidden"></div>
  </div>

  <div id="trackView" class="hidden">
    <button class="back-btn" onclick="openView('homeView')">← Menyu</button>
    <h3>Mahsulot kuzatuvi (havola bilan)</h3>
    <input id="t_url" placeholder="Mahsulot havolasi (https://...)">
    <input id="t_name" placeholder="Tovar nomi">
    <input id="t_price" placeholder="Narx (so'm — bo'sh qolsa havoladan olinadi)">
    <button class="action-btn" onclick="submitTrack()">Tekshirish va saqlash</button>
    <div id="trackOut" class="out hidden"></div>
  </div>

  <div id="aiView" class="hidden">
    <button class="back-btn" onclick="openView('homeView')">← Menyu</button>
    <h3>AI Tavsif va kalit so'z</h3>
    <input id="a_name" placeholder="Mahsulot nomi">
    <input id="a_feat" placeholder="Xususiyatlar (vergul bilan)">
    <input id="a_aud" placeholder="Kim uchun">
    <button class="action-btn" onclick="submitAi()">Tayyorlash</button>
    <div id="aiOut" class="out hidden"></div>
  </div>

  <div id="fbView" class="hidden">
    <button class="back-btn" onclick="openView('homeView')">← Menyu</button>
    <h3>Tavsiya / Takliflar</h3>
    <select id="fb_cat">
      <option value="Tavsiya">Tavsiya</option>
      <option value="Yangi funksiya taklifi">Yangi funksiya taklifi</option>
      <option value="Xato haqida xabar">Xato haqida xabar</option>
    </select>
    <input id="fb_contact" placeholder="Aloqa (ixtiyoriy: @username yoki tel)">
    <textarea id="fb_msg" rows="5" placeholder="Taklif yoki tavsiyangizni yozing..."></textarea>
    <button class="action-btn" onclick="submitFeedback()">Maxfiy botga yuborish</button>
    <div id="fbOut" class="out hidden"></div>
  </div>

  <div id="cfgView" class="hidden">
    <button class="back-btn" onclick="openView('homeView')">← Menyu</button>
    <h3>Sozlamalar</h3>
    <label><input type="checkbox" id="s_copy"> Guruhga nusxa yuborilsin</label>
    <input id="s_tok" type="password" placeholder="Foydalanuvchi Bot Token">
    <input id="s_gid" placeholder="Guruh Chat ID (-100...)">
    <input id="s_ai" type="password" placeholder="Gemini API kalit (ixtiyoriy)">
    <button class="action-btn" onclick="submitCfg()">Saqlash</button>
    <div id="cfgOut" class="out hidden"></div>
  </div>
</div>

<script>
let activeInp = document.getElementById('f_sell');
const inpList = Array.from(document.querySelectorAll('.calc-inp'));

async function bootApp() {
  const r = await fetch('/api/status');
  const d = await r.json();
  const vp = d.version_policy || { allowed: true, message: '' };
  if (!vp.allowed) {
    document.getElementById('mainApp').classList.add('hidden');
    const bv = document.getElementById('blockedView');
    bv.classList.remove('hidden');
    bv.innerHTML = `<h3>Ilova yangilanishi shart</h3><p>${vp.message}</p>` +
      (vp.update_url ? `<a href="${vp.update_url}" target="_blank" style="color:#38bdf8;">Yuklab olish</a>` : '');
    return;
  }
  document.getElementById('verBanner').innerText = vp.message;
  const s = d.settings || {};
  document.getElementById('s_copy').checked = !!s.copy_to_group;
  document.getElementById('s_tok').value = s.user_bot_token || '';
  document.getElementById('s_gid').value = s.user_group_id || '';
  document.getElementById('s_ai').value = s.gemini_api_key || '';
}

function openView(id) {
  ['homeView','calcView','trackView','aiView','fbView','cfgView'].forEach(v => {
    document.getElementById(v).classList.toggle('hidden', v !== id);
  });
}

function focusInp(el) {
  inpList.forEach(x => x.classList.remove('active-field'));
  el.classList.add('active-field');
  activeInp = el;
}

function nextInp() {
  const idx = inpList.indexOf(activeInp);
  focusInp(inpList[(idx + 1) % inpList.length]);
}

function pressKey(k) {
  if (!activeInp) return;
  if (k === 'C') { activeInp.value = ''; return; }
  if (k === 'BACK') { activeInp.value = activeInp.value.slice(0, -1); return; }
  if (k === '.' && activeInp.value.includes('.')) return;
  activeInp.value += k;
}

async function submitCalc() {
  const r = await fetch('/api/calc', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      sell_price: Number(document.getElementById('f_sell').value || 0),
      cost_price: Number(document.getElementById('f_cost').value || 0),
      logistics: Number(document.getElementById('f_log').value || 0),
      commission_pct: Number(document.getElementById('f_comm').value || 0),
      tax_pct: Number(document.getElementById('f_tax').value || 0),
      ads_pct: Number(document.getElementById('f_ads').value || 0),
      send_group: document.getElementById('f_grp').checked
    })
  });
  const out = document.getElementById('calcOut');
  out.classList.remove('hidden');
  out.innerText = JSON.stringify(await r.json(), null, 2);
}

async function submitTrack() {
  const r = await fetch('/api/track', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      url: document.getElementById('t_url').value.trim(),
      name: document.getElementById('t_name').value.trim(),
      price: document.getElementById('t_price').value.trim()
    })
  });
  const out = document.getElementById('trackOut');
  out.classList.remove('hidden');
  out.innerText = JSON.stringify(await r.json(), null, 2);
}

async function submitAi() {
  const r = await fetch('/api/ai', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      name: document.getElementById('a_name').value.trim(),
      features: document.getElementById('a_feat').value.trim(),
      audience: document.getElementById('a_aud').value.trim()
    })
  });
  const out = document.getElementById('aiOut');
  out.classList.remove('hidden');
  out.innerText = JSON.stringify(await r.json(), null, 2);
}

async function submitFeedback() {
  const r = await fetch('/api/feedback', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      category: document.getElementById('fb_cat').value,
      contact: document.getElementById('fb_contact').value.trim(),
      message: document.getElementById('fb_msg').value.trim()
    })
  });
  const out = document.getElementById('fbOut');
  out.classList.remove('hidden');
  out.innerText = JSON.stringify(await r.json(), null, 2);
}

async function submitCfg() {
  const r = await fetch('/api/settings', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      copy_to_group: document.getElementById('s_copy').checked,
      user_bot_token: document.getElementById('s_tok').value.trim(),
      user_group_id: document.getElementById('s_gid').value.trim(),
      gemini_api_key: document.getElementById('s_ai').value.trim()
    })
  });
  const out = document.getElementById('cfgOut');
  out.classList.remove('hidden');
  out.innerText = JSON.stringify(await r.json(), null, 2);
}

bootApp();
</script>
</body>
</html>
"""


# =====================================================================
# 7. LOKAL HTTP SERVER
# =====================================================================
class Handler(BaseHTTPRequestHandler):
  def _json(self, data: dict, code: int = 200) -> None:
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    self.send_response(code)
    self.send_header("Content-Type", "application/json; charset=utf-8")
    self.send_header("Content-Length", str(len(raw)))
    self.end_headers()
    self.wfile.write(raw)

  def _body(self) -> dict:
    ln = int(self.headers.get("Content-Length", 0))
    return json.loads(self.rfile.read(ln).decode("utf-8")) if ln > 0 else {}

  def do_GET(self) -> None:
    p = urllib.parse.urlparse(self.path).path
    if p == "/":
      raw = APP_HTML.encode("utf-8")
      self.send_response(200)
      self.send_header("Content-Type", "text/html; charset=utf-8")
      self.send_header("Content-Length", str(len(raw)))
      self.end_headers()
      self.wfile.write(raw)
    elif p == "/api/status":
      st = load_state()
      self._json({
          "version": APP_VERSION,
          "version_policy": check_version_policy(),
          "settings": st["settings"],
      })
    else:
      self._json({"error": "Not found"}, 404)

  def do_POST(self) -> None:
    vp = check_version_policy()
    if not vp["allowed"]:
      self._json(vp, 426)
      return

    p = urllib.parse.urlparse(self.path).path
    d = self._body()

    if p == "/api/calc":
      try:
        res = calc_profit(
            float(d["sell_price"]),
            float(d["cost_price"]),
            float(d.get("logistics", 0)),
            float(d.get("commission_pct", 0)),
            float(d.get("tax_pct", 0)),
            float(d.get("ads_pct", 0)),
        )
        if d.get("send_group"):
          txt = (
              f"#CALC\nSotuv: {res['sell_price']:,.0f} | "
              f"Sof foyda: {res['net_profit']:,.0f} | "
              f"Marja: {res['margin_pct']}% | Min: {res['min_price']:,.0f}"
          )
          ok, msg = send_group_copy(txt)
          res["group_copy"] = {"ok": ok, "message": msg}
        self._json(res)
      except Exception as exc:
        self._json({"error": str(exc)}, 400)

    elif p == "/api/track":
      url = str(d.get("url", "")).strip()
      name = str(d.get("name", "")).strip() or url
      raw_price = str(d.get("price", "")).strip()
      price = float(raw_price) if raw_price else fetch_price_from_url(url)
      if not url or not price or price <= 0:
        self._json(
            {"error": "Havola va narx kerak (havoladan narx topilmadi)."}, 400
        )
        return
      st = load_state()
      now = datetime.now().strftime("%Y-%m-%d %H:%M")
      item = st["products"].get(url)
      alert = None
      if not item:
        st["products"][url] = {
            "url": url,
            "name": name,
            "price": price,
            "updated_at": now,
        }
        msg = "Kuzatuvga qo'shildi."
      else:
        old = float(item["price"])
        diff = price - old
        item["price"] = price
        item["name"] = name
        item["updated_at"] = now
        if diff != 0:
          state_txt = "OSDI" if diff > 0 else "TUSHDI"
          alert = (
              f"NARX {state_txt}!\n{name}\n{old:,.0f} -> {price:,.0f} "
              f"({diff:+,.0f} so'm)\n{url}"
          )
          st["alerts"].insert(0, alert)
          ok, gmsg = send_group_copy(alert)
          msg = f"Narx {state_txt}. Guruh: {gmsg} (ok={ok})"
        else:
          msg = "Narx o'zgarmadi."
      save_state(st)
      self._json({"status": msg, "alert": alert, "item": st["products"][url]})

    elif p == "/api/ai":
      try:
        self._json(
            generate_ai_or_template(
                str(d.get("name", "")),
                str(d.get("features", "")),
                str(d.get("audience", "")),
            )
        )
      except Exception as exc:
        self._json({"error": str(exc)}, 400)

    elif p == "/api/feedback":
      msg_txt = str(d.get("message", "")).strip()
      if not msg_txt:
        self._json({"error": "Taklif yoki tavsiya matnini kiriting."}, 400)
        return
      ok, status_msg = send_feedback_to_owner(
          category=str(d.get("category", "Tavsiya")).strip(),
          message=msg_txt,
          contact=str(d.get("contact", "")).strip(),
      )
      self._json({"ok": ok, "message": status_msg})

    elif p == "/api/settings":
      st = load_state()
      st["settings"]["copy_to_group"] = bool(d.get("copy_to_group", False))
      st["settings"]["user_bot_token"] = str(d.get("user_bot_token", "")).strip()
      st["settings"]["user_group_id"] = str(d.get("user_group_id", "")).strip()
      st["settings"]["gemini_api_key"] = str(d.get("gemini_api_key", "")).strip()
      save_state(st)
      self._json({"ok": True, "message": "Saqlandi."})

    else:
      self._json({"error": "Not found"}, 404)

  def log_message(self, format: str, *args) -> None:
    return


def run_server() -> None:
  srv = ThreadingHTTPServer((HOST, PORT), Handler)
  srv.serve_forever()


if __name__ == "__main__":
  threading.Thread(target=run_server, daemon=True).start()
  try:
    import webview

    webview.create_window("Seller Hub", f"http://{HOST}:{PORT}", width=420, height=780)
    webview.start()
  except Exception:
    print(f"Oyna kutubxonasi topilmadi, manzil: http://{HOST}:{PORT}")
    while True:
      time.sleep(1)

import threading
import time
from jnius import autoclass
from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import platform

import seller_hub_app

WebView = autoclass("android.webkit.WebView")
WebViewClient = autoclass("android.webkit.WebViewClient")
WebChromeClient = autoclass("android.webkit.WebChromeClient")
activity = autoclass("org.kivy.android.PythonActivity").mActivity


def start_backend():
  seller_hub_app.HOST = "127.0.0.1"
  seller_hub_app.PORT = 8765
  seller_hub_app.run_server()


class WebViewHolder(BoxLayout):
  def __init__(self, **kwargs):
    super().__init__(**kwargs)
    self.webview = None
    if platform == "android":
      Clock.schedule_once(self._create_webview, 0.5)

  def _create_webview(self, _dt):
    wv = WebView(activity)
    settings = wv.getSettings()
    settings.setJavaScriptEnabled(True)
    settings.setDomStorageEnabled(True)
    wv.setWebViewClient(WebViewClient())
    wv.setWebChromeClient(WebChromeClient())
    activity.setContentView(wv)
    wv.loadUrl(f"http://{seller_hub_app.HOST}:{seller_hub_app.PORT}")
    self.webview = wv


class SellerHubMobileApp(App):
  def build(self):
    threading.Thread(target=start_backend, daemon=True).start()
    time.sleep(0.5)
    return WebViewHolder()


if __name__ == "__main__":
  SellerHubMobileApp().run()

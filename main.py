import io
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.utils import platform

import seller_hub


BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8765
BACKEND_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"


def start_backend(data_dir: str | None = None):
    seller_hub.HOST = BACKEND_HOST
    seller_hub.PORT = BACKEND_PORT
    if data_dir:
        seller_hub.configure_storage_dir(data_dir)
    seller_hub.run_server()


class WebViewHolder(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.webview = None
        self.add_widget(Label(text="Server ishga tushmoqda..."))
        if platform == "android":
            threading.Thread(target=self._wait_for_backend, daemon=True).start()
        else:
            self.add_widget(Label(text=f"Brauzerda oching: {BACKEND_URL}"))

    def _wait_for_backend(self):
        for _ in range(150):
            try:
                with urllib.request.urlopen(
                    f"{BACKEND_URL}/api/status",
                    timeout=0.5,
                ):
                    Clock.schedule_once(self._open_webview_on_ui, 0)
                    return
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)

        Clock.schedule_once(self._show_startup_error, 0)

    def _show_startup_error(self, _dt):
        self.clear_widgets()
        self.add_widget(
            Label(text="Server ishga tushmadi. Ilovani qayta oching.")
        )

    def _open_webview_on_ui(self, _dt):
        if platform != "android":
            return

        from android.runnable import run_on_ui_thread
        from jnius import PythonJavaClass, autoclass, java_method

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        WebView = autoclass("android.webkit.WebView")
        WebChromeClient = autoclass("android.webkit.WebChromeClient")
        WebViewClient = autoclass("android.webkit.WebViewClient")
        WebResourceResponse = autoclass("android.webkit.WebResourceResponse")
        ByteArrayInputStream = autoclass("java.io.ByteArrayInputStream")

        class LocalInterceptorClient(PythonJavaClass):
            __javainterfaces__ = ["android/webkit/WebViewClient"]
            __javacontext__ = "app"

            @java_method("(Landroid/webkit/WebView;Landroid/webkit/WebResourceRequest;)Landroid/webkit/WebResourceResponse;", name="shouldInterceptRequest")
            def shouldInterceptRequest_req(self, view, request):
                url_str = request.getUrl().toString()
                parsed = urllib.parse.urlparse(url_str)
                if parsed.hostname in ("127.0.0.1", "localhost") and parsed.port == BACKEND_PORT:
                    if parsed.path in ("", "/"):
                        raw = seller_hub.APP_HTML.encode("utf-8")
                        stream = ByteArrayInputStream(raw)
                        return WebResourceResponse("text/html", "utf-8", stream)
                return None

        @run_on_ui_thread
        def attach_webview():
            activity = PythonActivity.mActivity
            webview = WebView(activity)
            settings = webview.getSettings()
            settings.setJavaScriptEnabled(True)
            settings.setDomStorageEnabled(True)
            settings.setMixedContentMode(0)
            webview.setWebViewClient(LocalInterceptorClient())
            webview.setWebChromeClient(WebChromeClient())
            activity.setContentView(webview)
            webview.loadUrl(BACKEND_URL)
            self.webview = webview

        attach_webview()


class SellerHubMobileApp(App):
    def build(self):
        data_dir = self.user_data_dir if platform == "android" else "."
        threading.Thread(
            target=start_backend,
            args=(data_dir,),
            daemon=True,
        ).start()
        return WebViewHolder()


if __name__ == "__main__":
    SellerHubMobileApp().run()

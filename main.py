import threading
import time
import urllib.error
import urllib.request

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import platform

import seller_hub


BACKEND_URL = f"http://127.0.0.1:8765"


def start_backend():
    seller_hub.HOST = "127.0.0.1"
    seller_hub.PORT = 8765
    seller_hub.run_server()


class WebViewHolder(BoxLayout):
    def __init__(**kwargs):
        super().__init__(**kwargs)
        self.webview = None
        if platform == "android":
            threading.Thread(target=self._wait_for_backend, daemon=True).start()

    def _wait_for_backend(self):
        for _ in range(100):
            try:
                with urllib.request.urlopen(
                    f"{BACKEND_URL}/api/status",
                    timeout=0.5,
                ):
                    Clock.schedule_once(self._create_webview, 0)
                    return
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)

        Clock.schedule_once(self._show_startup_error, 0)

    def _show_startup_error(self, _dt):
        from kivy.uix.label import Label
        self.clear_widgets()
        self.add_widget(
            Label(text="Server ishga tushmadi. Ilovani qayta oching.")
        )

    def _create_webview(self, _dt):
        if platform != "android":
            return

        from jnius import autoclass

        WebView = autoclass("android.webkit.WebView")
        WebViewClient = autoclass("android.webkit.WebViewClient")
        WebChromeClient = autoclass("android.webkit.WebChromeClient")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")

        activity = PythonActivity.mActivity
        webview = WebView(activity)
        settings = webview.getSettings()
        settings.setJavaScriptEnabled(True)
        settings.setDomStorageEnabled(True)
        webview.setWebViewClient(WebViewClient())
        webview.setWebChromeClient(WebChromeClient())

        activity.setContentView(webview)
        webview.loadUrl(BACKEND_URL)
        self.webview = webview


class SellerHubMobileApp(App):
    def build(self):
        seller_hub.HOST = "127.0.0.1"
        seller_hub.PORT = 8765
        threading.Thread(target=start_backend, daemon=True).start()
        return WebViewHolder()


if __name__ == "__main__":
    SellerHubMobileApp().run()

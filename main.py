from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.utils import platform


class LauncherRoot(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.webview = None
        if platform == "android":
            Clock.schedule_once(self._attach_webview, 0.1)
        else:
            self.add_widget(Label(text="A32 Smart Launcher (Android uchun)"))

    def _attach_webview(self, _dt):
        from android.runnable import run_on_ui_thread
        from jnius import PythonJavaClass, autoclass, java_method

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        WebView = autoclass("android.webkit.WebView")
        WebViewClient = autoclass("android.webkit.WebViewClient")
        WebChromeClient = autoclass("android.webkit.WebChromeClient")
        Intent = autoclass("android.content.Intent")
        Uri = autoclass("android.net.Uri")

        class AndroidBridge(PythonJavaClass):
            __javainterfaces__ = ["java/lang/Object"]
            __javacontext__ = "app"

            @java_method("(Ljava/lang/String;)Z")
            def launchApp(self, pkg_name):
                try:
                    activity = PythonActivity.mActivity
                    pm = activity.getPackageManager()
                    intent = pm.getLaunchIntentForPackage(pkg_name)
                    if intent is not None:
                        activity.startActivity(intent)
                        return True
                except Exception:
                    pass
                return False

            @java_method("(Ljava/lang/String;)V")
            def dialNumber(self, phone):
                try:
                    activity = PythonActivity.mActivity
                    intent = Intent(Intent.ACTION_DIAL)
                    intent.setData(Uri.parse(f"tel:{phone}"))
                    activity.startActivity(intent)
                except Exception:
                    pass

        @run_on_ui_thread
        def create():
            activity = PythonActivity.mActivity
            webview = WebView(activity)
            settings = webview.getSettings()
            settings.setJavaScriptEnabled(True)
            settings.setDomStorageEnabled(True)
            settings.setAllowFileAccess(True)
            settings.setAllowContentAccess(True)
            settings.setDatabaseEnabled(True)

            webview.setWebViewClient(WebViewClient())
            webview.setWebChromeClient(WebChromeClient())
            webview.addJavascriptInterface(AndroidBridge(), "AndroidBridge")

            activity.setContentView(webview)
            webview.loadUrl("file:///android_asset/index.html")
            self.webview = webview

        create()


class A32SmartLauncherApp(App):
    def build(self):
        return LauncherRoot()


if __name__ == "__main__":
    A32SmartLauncherApp().run()

[app]
title = A32 Smart Launcher
package.name = a32launcher
package.domain = org.a32smart.launcher

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,html

version = 1.0.0
requirements = python3,kivy,pyjnius

orientation = portrait
fullscreen = 0

android.permissions = INTERNET,ACCESS_NETWORK_STATE,CALL_PHONE
android.api = 33
android.minapi = 21
android.ndk = 25b
android.accept_sdk_license = True
android.archs = arm64-v8a
android.add_assets = assets/index.html:index.html

[buildozer]
log_level = 2
warn_on_root = 1

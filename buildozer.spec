[app]
title = MonBudget
package.name = monbudget
package.domain = org.example
source.dir = .
source.include_exts = py,png,jpg,kv,txt,json
version = 0.1
requirements = python3,kivy,plyer
orientation = portrait

[buildozer]
log_level = 2

android.permissions = USE_FINGERPRINT, INTERNET, WRITE_EXTERNAL_STORAGE
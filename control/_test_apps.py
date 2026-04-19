# control/_test_apps.py

import asyncio
import psutil

from control.apps import (
    is_running,

    minimize,
    is_running_smart,
    minimize_by_title,
    launch,
    launch_and_intent,
    kill,
    close,
    hide_by_title,
    _iter_windows,
    normalize_app
)

app ={
      "name": "RustRover 2025.3",
      "exe_name": "rustrover64.exe",
      "full_path": "D:\\RustRover 2025.3\\bin\\rustrover64.exe",
      "resolved_path": "D:\\RustRover 2025.3\\bin\\rustrover64.exe",
      "args": [],
      "app_type": "exe",
      "publisher": "JetBrains s.r.o."
    }


async def main(app):
    name = app["name"]
    title = app.get("window_title")
    exe_name = app["exe_name"]

    app = normalize_app(app)
    print(app)
    print(await launch(app))




if __name__ == "__main__":
    asyncio.run(main(app))




"""
# 1. Check if a window handle is valid
if not user32.IsWindow(hwnd):
    print(f"  hwnd {hwnd} is invalid (window destroyed)")

# 2. Get extended error info after Win32 API failure
import ctypes
error_code = ctypes.get_last_error()  # Requires API call to set SetLastError=True
print(f"  Win32 error {error_code}: {ctypes.FormatError(error_code)}")

# 3. List all windows for debugging
for w in _iter_windows():
    print(f"  [{w['hwnd']}] '{w['title']}' exe={w['exe']} visible={w['visible']}")

# 4. Test focus restrictions
#    Run this from a background process — SetForegroundWindow will likely fail
#    Then add the ALT workaround and retry
"""
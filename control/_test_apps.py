# control/_test_apps.py

import asyncio
import psutil

from control.apps import (
    is_running,
    is_pwa_running,
    minimize,
    is_running_smart,
    minimize_by_title,
    launch,
    launch_and_intent,
    kill,
    close,
    hide_by_title
)

app = {
        "name": "Discord",
        "exe_name": "Discord.exe",
        "full_path": "C:\\Users\\Admin\\AppData\\Local\\Discord\\app-1.0.9188\\Discord.exe",
        "resolved_path": "C:\\Users\\Admin\\AppData\\Local\\Discord\\app-1.0.9188\\Discord.exe",
        "args": [],
        "app_type": "exe",
        "publisher": "Discord Inc."
      }


async def main(app):
    name = app["name"]
    title = app.get("window_title")
    await launch(app)


if __name__ == "__main__":
    asyncio.run(main(app))
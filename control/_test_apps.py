# control/_test_apps.py

import asyncio
import psutil

from control.apps import (
    is_running,
    is_pwa_running,
    minimize,
    minimize_by_title,
    launch,
    kill,
    close,
    hide_by_title
)

app = {
        "name": "Discord",
        "exe": "Discord.exe",
        "path": "C:\\Users\\Admin\\AppData\\Local\\Discord\\Update.exe",
        "args": [
          "--processStart Discord.exe"
        ],
        "type": "exe",
        "action": "close",
        "action_wait_time": 15,
        "launch_timeout": 5,
        "launch_interval": 2,
        "method": "shell",
        "reopen": "no"
      }


async def main(app):
    name = app["name"]
    title = app.get("window_title")
    await launch(app)


if __name__ == "__main__":
    asyncio.run(main(app))
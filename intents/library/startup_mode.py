# intents/library/startup_mode.py

import asyncio
from config import config
from control.apps import launch_and_close

async def run():
    """
    Startup mode — runs on boot.
    Launches all configured apps and minimizes them to tray.
    Clean desktop. Everything running. Nothing in the way.
    """
    apps = config.startup_apps

    print("\n HELL — Startup Mode")
    print("─" * 30)

    tasks = []
    for app in apps:
        # run each app launch concurrently
        # all apps launch at the same time
        # instead of one by one
        tasks.append(launch_and_close(app))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # summary
    print("─" * 30)
    success = sum(1 for r in results if r is True)
    failed  = len(results) - success
    print(f" {success} apps ready  |  {failed} failed")
    print("─" * 30)

if __name__ == "__main__":
    asyncio.run(run())
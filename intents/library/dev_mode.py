# intents/library/dev_mode.py

import asyncio
from config import config
from control.apps import launch


def _resolve_trigger_apps() -> list:
    """
    Trigger apps in config are bare exe/lnk names.
    Resolve them to full app dicts from installed_apps.
    """
    triggers     = set(t.lower() for t in config.dev_trigger_apps())
    installed    = config.get("installed_apps", default=[])
    resolved     = []

    for app in installed:
        if app["exe"].lower() in triggers:
            resolved.append(app)

    return resolved


async def run(entities: dict = None) -> dict:
    apps = _resolve_trigger_apps()

    if not apps:
        print("  dev mode — no trigger apps found in installed_apps")
        return {"success": False, "reason": "no_apps_resolved"}

    print("\n HELL — Dev Mode")
    print("─" * 30)

    tasks   = [launch(app) for app in apps]
    results = await asyncio.gather(*tasks)

    success = sum(1 for r in results if r is True)
    failed  = len(results) - success

    print("─" * 30)
    print(f"  {success} apps ready  |  {failed} failed")
    print("─" * 30)
    for app in apps:
        print(app)

    return {"success": failed == 0}


if __name__ == "__main__":
    asyncio.run(run())
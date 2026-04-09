# intents/library/dev_mode.py

import asyncio
from config import config
from control.apps import launch


def _resolve_trigger_apps() -> list:
    """
    Trigger apps in config are bare exe/lnk names.
    Resolve them to full app dicts from installed_apps.
    """
    triggers  = set(t.lower() for t in config.dev_trigger_apps())
    installed = config.get("installed_apps", default=[])
    resolved  = []

    for app in installed:
        if app["exe_name"].lower() in triggers:
            resolved.append(app)

    return resolved


async def run(logger, entities: dict = None) -> dict:
    apps = _resolve_trigger_apps()

    if not apps:
        logger.warning("dev_mode_no_apps")
        print("  dev mode — no trigger apps found in installed_apps")
        return {"success": False, "reason": "no_apps_resolved"}

    logger.info("dev_mode_begin", count=len(apps))

    print("\n HELL — Dev Mode")
    print("─" * 30)

    async def _launch(app):
        logger.info("dev_launch_begin", app=app["name"])

        try:
            result = await launch(app)

            if result:
                logger.info("dev_launch_success", app=app["name"])
            else:
                logger.warning("dev_launch_failed", app=app["name"])

            return result

        except Exception as e:
            logger.error(
                "dev_launch_exception",
                app=app["name"],
                error=str(e)
            )
            return False

    tasks   = [_launch(app) for app in apps]
    results = await asyncio.gather(*tasks)

    success = sum(1 for r in results if r is True)
    failed  = len(results) - success

    logger.info(
        "dev_mode_complete",
        success=success,
        failed=failed
    )

    print("─" * 30)
    print(f"  {success} apps ready  |  {failed} failed")
    print("─" * 30)

    return {"success": failed == 0}


if __name__ == "__main__":
    from core.logger import Logger
    logger = Logger(debug=True)
    asyncio.run(run(logger))
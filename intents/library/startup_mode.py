# intents/library/startup_mode.py

import asyncio
from config import config
from control.apps import launch_and_intent
from core.log import logger




async def run(entities: dict = None):
    """
    Startup mode — runs on boot.
    Launches all configured apps and minimizes them to tray.
    Clean desktop. Everything running. Nothing in the way.
    """
    apps = config.startup_apps

    logger.info("startup_mode_begin", count=len(apps))

    print("\n HELL — Startup Mode")
    print("─" * 30)

    async def _launch(app):
        logger.info("startup_launch_begin", app=app)

        try:
            result = await asyncio.to_thread(
                lambda: asyncio.run(launch_and_intent(app))
            )

            if result is True:
                logger.info("startup_launch_success", app=app)
            else:
                logger.warning("startup_launch_failed", app=app, result=result)

            return result

        except Exception as e:
            logger.error(
                "startup_launch_exception",
                app=app,
                error=str(e)
            )
            return False

    tasks = [_launch(app) for app in apps]

    results = await asyncio.gather(*tasks)

    # summary
    success = sum(1 for r in results if r is True)
    failed  = len(results) - success

    logger.info(
        "startup_mode_complete",
        success=success,
        failed=failed
    )

    print("─" * 30)
    print(f" {success} apps ready  |  {failed} failed")
    print("─" * 30)


if __name__ == "__main__":
    asyncio.run(run())

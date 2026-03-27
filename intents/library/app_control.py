# intents/library/app_control.py

import asyncio

from control.apps import (
    launch,
    launch_and_intent,
    minimize,
    close,
    hide_by_title,
    is_running,
    kill,
)


async def run(entities: dict) -> dict:
    """
    Handles open_app, close_app, hide_app intents.
    Gets app entry from entities extracted by orchestrator.
    """
    intent = entities.get("intent")
    app = entities.get("app")

    if not app:
        print("  which app? not found in config")
        return {
            "success": False,
            "reason": "app_not_found",
            "response": "I couldn't find that app in your config.",
        }

    name = app["name"]
    exe = (
            app.get("exe")
            or app.get("resolved_path")
            or app.get("full_path")
    )
    app_type = app.get("type", "exe")
    hide_by = app.get("hide_by", "exe")
    title = app.get("window_title", name)

    if intent == "open_app":
        result = await launch(app)
        return {
            "success": result,
            "response": f"Opening {name}" if result else f"Could not open {name}",
        }

    elif intent == "close_app":
        result = close(app)
        return {
            "success": result,
            "response": f"Closing {name}" if result else f"Could not close {name}",
        }

    elif intent == "kill_app":
        result = kill(app)
        return {
            "success": result,
            "response": f"Closing {name}" if result else f"Could not kill {name}",
        }

    elif intent == "minimize_app":
        result = minimize(app)
        return {
            "success": result,
            "response": f"Minimizing {name}" if result else f"Could not minimize {name}",
        }

    elif intent == "hide_app":
        # if hide_by == "title" or app_type == "pwa":
        result = hide_by_title(app)
        # else:
        #     result = hide(exe)
        return {
            "success": result,
            "response": f"Hiding {name}" if result else f"Could not hide {name}",
        }

    return {
        "success": False,
        "reason": "unknown_action",
        "response": "Not sure what to do with that app.",
    }

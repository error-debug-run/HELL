# finderr/finder.py

import app_finder
from collections import defaultdict
import json
import os
from core.log import logger


apps = app_finder.scan_apps()
logger.info("apps_scanned", count=len(apps))

def _normalize_app(app):
    """
    Convert Rust object → clean Python dict
    Future-proof: handles new fields like args
    """
    return {
        "name": app.name,
        "exe_name": app.exe_name,
        "full_path": app.full_path,
        "resolved_path": getattr(app, "full_path", ""),
        "args": getattr(app, "args", []),
        "app_type": app.app_type,
        "publisher": app.publisher,
    }


def _deduplicate_apps(apps):
    logger.info("deduplication_start", input_count=len(apps))
    by_path = {}

    for app in apps:
        app = _normalize_app(app)

        key = (app["resolved_path"] or app["full_path"]).lower()

        if key not in by_path:
            by_path[key] = app

    logger.debug("dedup_by_path_complete", unique_paths=len(by_path))

    # group by name
    grouped = defaultdict(list)
    for app in by_path.values():
        grouped[app["name"].lower()].append(app)

    logger.debug("grouped_by_name", groups=len(grouped))

    result = []

    for group in grouped.values():
        # prefer real exe over wrappers
        exe_apps = [
            a for a in group
            if a["resolved_path"].lower().endswith(".exe")
        ]

        if exe_apps:
            result.append(exe_apps[0])
        else:
            result.append(group[0])

    logger.info("deduplication_complete", output_count=len(result))

    return sorted(result, key=lambda x: x["name"].lower())


def run_finder(apps):
    logger.info("run_finder_start", input_count=len(apps))
    filtered_apps = _deduplicate_apps(apps)
    logger.info("apps_filtered", count=len(filtered_apps))
    # ─────────────────────────────────────────
    # SAVE TO CONFIG
    # ─────────────────────────────────────────

    file = "../config.json"

    # load existing
    if os.path.exists(file):
        with open(file, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = {}
    else:
        data = {}

    # update only installed_apps
    data["installed_apps"] = filtered_apps

    # write back
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


if __name__ == "__main__":
    run_finder(apps)
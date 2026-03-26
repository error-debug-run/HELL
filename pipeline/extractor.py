# hell/pipeline/extractor.py

import re
from config import config
from difflib import get_close_matches

# ─────────────────────────────────────────────
# APP NAME EXTRACTOR
# ─────────────────────────────────────────────

# words that appear before or after app names in commands
APP_TRIGGERS = [
    "open", "launch", "start", "run", "close",
    "kill", "stop", "hide", "minimize", "exit",
    "shut down", "shutdown", "switch to", "load"
]

def get_known_apps():
    """
    Pull all app names from config.
    Returns dict of lowercase name → original config entry.
    """
    apps = {}

    # installed_apps has everything — primary source
    for app in config.get("installed_apps", default=[]):
        apps[app["name"].lower()] = app

    # startup apps override — they have richer entries
    # (action, args, launch_timeout etc.)
    for app in config.startup_apps:
        apps[app["name"].lower()] = app

    return apps

def extract_app(text: str) -> dict | None:
    """
    Extract app name from command text.
    Option A — direct extraction from text
    Option B — fuzzy match against config apps
    Returns matching config app entry or None.
    """
    text       = text.lower().strip()
    known_apps = get_known_apps()

    # ── Option A — direct extraction ──────────────
    # strip trigger words and check what's left
    clean = text
    for trigger in APP_TRIGGERS:
        clean = clean.replace(trigger, "").strip()

    # check if remaining text matches a known app
    if clean in known_apps:
        return known_apps[clean]

    # check if any known app name appears in text
    for app_name, app_entry in known_apps.items():
        if app_name in text:
            return app_entry

    # ── Option B — fuzzy match ─────────────────────
    candidates = list(known_apps.keys())
    words      = clean.split()

    # try fuzzy match on each word
    for word in words:
        matches = get_close_matches(word, candidates, n=1, cutoff=0.7)
        if matches:
            return known_apps[matches[0]]

    # try fuzzy match on full cleaned text
    matches = get_close_matches(clean, candidates, n=1, cutoff=0.6)
    if matches:
        return known_apps[matches[0]]

    return None


# ─────────────────────────────────────────────
# GENERAL ENTITY EXTRACTOR
# ─────────────────────────────────────────────

APP_INTENTS = {
    "open_app", "close_app", "hide_app",
    "kill_app", "minimize_app", "restart_app",
    "show_app"
}

def extract_entities(intent: str, text: str) -> dict:
    """
    Extract relevant entities based on intent.
    Returns dict of extracted values.
    """
    entities = {}

    if intent in APP_INTENTS:
        app = extract_app(text)
        if app:
            entities["app"] = app
        else:
            entities["app"] = None

    return entities


if __name__ == "__main__":
    tests = [
        ("open_app",  "open spotify"),
        ("open_app",  "launch discord"),
        ("close_app", "close steam"),
        ("hide_app",  "hide discord"),
        ("open_app",  "open spotfy"),     # typo — fuzzy match
        ("open_app",  "run the music app"), # indirect
        ("open_app",  "open something"),   # unknown
        ("kill_app",  "kill discord"),
        ("minimize_app", "minimize discord"),
    ]

    print("Entity Extractor Test")
    print("─" * 40)
    for intent, text in tests:
        entities = extract_entities(intent, text)
        app      = entities.get("app")
        result   = app["name"] if app else "not found"
        print(f"'{text}'")
        print(f"  → {result}")
    print("─" * 40)

    result = extract_entities('kill_app', 'kill discord')
    print('entities:', result)
    print('app:', result.get('app'))
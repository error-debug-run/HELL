# hell/config.py

import json
from pathlib import Path

# Always finds config.json relative to this file
# Works on any machine, any directory
CONFIG_PATH = Path(__file__).parent / "config.json"

class Config:
    def __init__(self):
        self._data = self._load()

    def _load(self):
        if not CONFIG_PATH.exists():
            raise FileNotFoundError(
                f"config.json not found at {CONFIG_PATH}\n"
                f"Create one before running HELL."
            )
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)

    # ── top level ────────────────────────────────
    @property
    def os(self):
        return self._data["hell"]["os"]

    @property
    def version(self):
        return self._data["hell"]["version"]

    @property
    def log_level(self):
        return self._data["hell"]["log_level"]

    # ── startup ───────────────────────────────────
    @property
    def startup_apps(self):
        return self._data["startup"]["minimize_on_boot"]

    # ── dev mode ──────────────────────────────────
    @property
    def dev_default_tabs(self):
        return self._data["dev_mode"]["default_tabs"]

    def dev_project(self, name):
        return self._data["dev_mode"]["projects"].get(name)

    def dev_project_tabs(self, name):
        project = self.dev_project(name)
        return project["tabs"] if project else self.dev_default_tabs

    def dev_trigger_apps(self):
        apps = []
        for project in self._data["dev_mode"]["projects"].values():
            apps.extend(project.get("trigger_apps", []))
        return list(set(apps))  # deduplicate

    # ── game mode ─────────────────────────────────
    @property
    def game_servers(self):
        return self._data["game_mode"]["servers"]

    @property
    def game_trigger_apps(self):
        return self._data["game_mode"]["trigger_apps"]

    @property
    def game_minimize_apps(self):
        return self._data["game_mode"]["minimize_on_game"]

    @property
    def ping_warn(self):
        return self._data["game_mode"]["ping_threshold_warn"]

    @property
    def ping_bad(self):
        return self._data["game_mode"]["ping_threshold_bad"]

    @property
    def packet_loss_warn(self):
        return self._data["game_mode"]["packet_loss_warn"]

    @property
    def stt(self):
        return self._data["stt"]

    # ── raw access for anything not covered ───────
    def get(self, *keys, default=None):
        data = self._data
        for key in keys:
            if isinstance(data, dict):
                data = data.get(key, default)
            else:
                return default
        return data


# Single instance — every file imports this one object
# No one ever reads config.json directly except this file
config = Config()


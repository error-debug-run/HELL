# control/launch_rating.py

import os
import sys
import json


class LaunchRatingStore:
    def _ensure_file(self):
        try:
            if not os.path.exists(self.file):
                with open(self.file, "w", encoding="utf-8") as f:
                    json.dump({}, f)
        except Exception as e:
            print(f"[rating_store] _ensure_file FAILED: {e}")
            print(f"[rating_store] tried path: {self.file}")

    def __init__(self):
        self.base_dir = self._get_base_dir()
        self.ratings_dir = os.path.join(self.base_dir, "attemptRatings")

        os.makedirs(self.ratings_dir, exist_ok=True)
        self.file = os.path.join(self.ratings_dir, "ratings.json")
        self._ensure_file()
        # print(f"[rating_store] base_dir   -> {self.base_dir}")
        # print(f"[rating_store] ratings_dir-> {self.ratings_dir}")
        # print(f"[rating_store] file       -> {self.file}")

    def _get_base_dir(self):
        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def load(self):
        self._ensure_file()
        try:
            with open(self.file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}

    def save(self, data):
        with open(self.file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def reorder_attempts(self, app_name, attempts):
        try:
            data = self.load()
            scores = data.get(app_name)

            # no ratings yet → keep original order
            if not scores:
                return attempts

            return sorted(
                attempts,
                key=lambda a: scores.get(a["method"], 0),
                reverse=True
            )
        except Exception:
            # absolutely never block launching
            return attempts

    def record_success(self, app_name, method):
        data = self.load()
        app = data.setdefault(app_name, {})
        app[method] = app.get(method, 0) + 1
        self.save(data)


rating_store = LaunchRatingStore()
# core/logger.py

import os
import json
import time
import threading
import zipfile
from datetime import datetime
from queue import Queue, Empty

# -------- PATHS (temporary, can be upgraded later) --------
BASE_DIR = os.path.dirname(os.path.dirname((__file__)))
LOG_DIR = os.path.join(BASE_DIR, "runtime", "logs")

os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "app.log")

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
MAX_BACKUPS = 3


class Logger:
    def __init__(self, debug=False):
        self.debug_mode = debug
        self.session_id = self._new_session()

        self.queue = Queue()
        self.running = True

        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()

    # ---------------- PUBLIC ---------------- #

    def debug(self, msg, **ctx):
        if self.debug_mode:
            self._push("DEBUG", msg, ctx)

    def info(self, msg, **ctx):
        self._push("INFO", msg, ctx)

    def warning(self, msg, **ctx):
        self._push("WARNING", msg, ctx)

    def error(self, msg, **ctx):
        self._push("ERROR", msg, ctx)

    def critical(self, msg, **ctx):
        self._push("CRITICAL", msg, ctx)

    def set_debug(self, enabled: bool):
        self.debug_mode = enabled
        self.info("debug_mode_changed", enabled=enabled)

    def export_logs(self):
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        zip_path = os.path.join(LOG_DIR, f"logs_{ts}.zip")

        with zipfile.ZipFile(zip_path, "w") as z:
            for f in os.listdir(LOG_DIR):
                if f.endswith(".log"):
                    z.write(os.path.join(LOG_DIR, f), f)

            meta = {
                "session_id": self.session_id,
                "timestamp": ts
            }

            meta_file = os.path.join(LOG_DIR, "meta.json")
            with open(meta_file, "w") as mf:
                json.dump(meta, mf, indent=2)

            z.write(meta_file, "meta.json")

        return zip_path

    def stop(self):
        self.running = False
        self.worker.join()

    # ---------------- INTERNAL ---------------- #

    def _push(self, level, msg, ctx):
        entry = {
            "time": datetime.utcnow().isoformat(),
            "level": level,
            "session": self.session_id,
            "msg": msg,
            "ctx": ctx
        }
        self.queue.put(entry)

    def _worker(self):
        while self.running:
            try:
                entry = self.queue.get(timeout=1)
                self._write(entry)
            except Empty:
                continue

    def _write(self, entry):
        self._rotate()

        line = json.dumps(entry, ensure_ascii=False)

        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _rotate(self):
        if not os.path.exists(LOG_FILE):
            return

        if os.path.getsize(LOG_FILE) < MAX_FILE_SIZE:
            return

        for i in range(MAX_BACKUPS, 0, -1):
            src = f"{LOG_FILE}.{i-1}" if i > 1 else LOG_FILE
            dst = f"{LOG_FILE}.{i}"

            if os.path.exists(src):
                os.replace(src, dst)

    def _new_session(self):
        return hex(int(time.time() * 1000))[2:]
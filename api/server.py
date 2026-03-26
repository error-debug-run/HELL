# hell/api/server.py

import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psutil
import time
import numpy as np



app = FastAPI(title="HELL API", version="0.1.0")

# allow GUI to talk to it
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── request models ────────────────────────────────────────

class IntentRequest(BaseModel):
    input: str

# ── in memory state ───────────────────────────────────────

state = {
    "current_mode": "IDLE",
    "jobs":         [],
    "start_time":   time.time(),
}

# ── routes ────────────────────────────────────────────────

import sounddevice as sd

@app.get("/audio/devices")
def audio_devices():
    devices = sd.query_devices()
    inputs  = []
    for i, device in enumerate(devices):
        if device["max_input_channels"] > 0:
            inputs.append({
                "index": i,
                "name":  device["name"],
            })
    return {"devices": inputs}

@app.post("/audio/device")
def set_audio_device(body: dict):
    """Save selected mic device to config."""
    import json
    from pathlib import Path

    config_path = Path(__file__).parent.parent / "config.json"
    with open(config_path) as f:
        config = json.load(f)

    config["stt"]["mic_device"] = body.get("index")

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    return {"success": True, "device": body.get("index")}

@app.get("/health")
def health():
    return {
        "status":  "running",
        "version": "0.1.0",
        "uptime":  int(time.time() - state["start_time"]),
    }

@app.get("/status")
def status():
    cpu = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory()
    gpu = "RTX 3060"   # placeholder until GPU monitoring added

    return {
        "mode":    state["current_mode"],
        "cpu":     f"{int(cpu)}%",
        "ram":     f"{int(ram.percent)}%",
        "gpu":     gpu,
        "uptime":  int(time.time() - state["start_time"]),
    }

@app.post("/intent")
async def intent(req: IntentRequest):

    from pipeline.intent import detect

    result = detect(req.input)

    # log the job
    job = {
        "id":         len(state["jobs"]) + 1,
        "intent":     result["intent"],
        "confidence": result["confidence"],
        "input":      req.input,
        "understood": result["understood"],
        "timestamp":  time.time(),
        "status":     "running",
    }
    state["jobs"].insert(0, job)

    # keep last 50 jobs
    state["jobs"] = state["jobs"][:50]

    if result["understood"]:
        state["current_mode"] = result["intent"]
        # route to orchestrator (async, don't wait)
        asyncio.create_task(route_intent(result))
        job["status"] = "dispatched"
    else:
        job["status"] = "not_understood"

    return {
        "intent":     result["intent"],
        "confidence": result["confidence"],
        "understood": result["understood"],
        "job_id":     job["id"],
    }


# shared audio state — STT writes here, API reads here
audio_state = {
    "db_level":  -60.0,    # current db level
    "recording": False,    # is STT active
    "mode":      "idle",   # idle / listening / command
}

@app.get("/audio/level")
def audio_level():
    return {
        "db":        audio_state["db_level"],
        "recording": audio_state["recording"],
        "mode":      audio_state["mode"],
    }



@app.get("/jobs")
def jobs():
    return {
        "jobs":  state["jobs"][:20],
        "total": len(state["jobs"]),
    }

@app.post("/apps/write")
def write_apps(body: dict):
    """Write scanned app list to config.json."""
    import json
    from pathlib import Path

    config_path = Path(__file__).parent.parent / "config.json"

    with open(config_path) as f:
        config = json.load(f)

    # write all found apps to config
    config["installed_apps"] = body.get("apps", [])

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    return {"success": True, "count": len(body.get("apps", []))}


@app.post("/apps/assign_mode")
def assign_mode(body: dict):
    """Assign an app to a specific mode in config.json."""
    import json
    from pathlib import Path

    config_path = Path(__file__).parent.parent / "config.json"

    with open(config_path) as f:
        config = json.load(f)

    app  = body.get("app", {})
    mode = body.get("mode", "")

    # build the app entry
    entry = {
        "name":   app.get("name", ""),
        "exe":    app.get("exe", ""),
        "path":   app.get("full_path", ""),
        "type":   app.get("type_", "exe"),
        "action": "hide",
    }

    # add to the right mode
    if mode == "startup":
        config.setdefault("startup", {})
        config["startup"].setdefault("minimize_on_boot", [])
        # avoid duplicates
        existing = [a["name"] for a in
                    config["startup"]["minimize_on_boot"]]
        if entry["name"] not in existing:
            config["startup"]["minimize_on_boot"].append(entry)

    elif mode == "game":
        config.setdefault("game_mode", {})
        config["game_mode"].setdefault("minimize_on_game", [])
        existing = [a["name"] for a in
                    config["game_mode"]["minimize_on_game"]]
        if entry["name"] not in existing:
            config["game_mode"]["minimize_on_game"].append(entry)

    elif mode == "dev":
        config.setdefault("dev_mode", {})
        config["dev_mode"].setdefault("trigger_apps", [])
        if entry["exe"] not in config["dev_mode"]["trigger_apps"]:
            config["dev_mode"]["trigger_apps"].append(entry["exe"])

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    return {"success": True, "app": entry["name"], "mode": mode}


# ── intent router ─────────────────────────────────────────

async def route_intent(result: dict):
    """Route detected intent to the correct handler."""
    intent = result["intent"]

    try:
        if intent == "startup_mode":
            from intents.library.startup_mode import run
            await run()

        # elif intent == "dev_mode":
        #     from intents.library.dev_mode import run
        #     await run()
        #
        # elif intent == "game_mode":
        #     from intents.library.game_mode import run
        #     await run()

        elif intent in ("open_app", "close_app", "hide_app"):
            from intents.library.app_control import run
            from pipeline.extractor import extract_entities
            entities          = extract_entities(intent, result["text"])
            entities["intent"] = intent
            await run(entities)

    except Exception as e:
        print(f"  handler error [{intent}]: {e}")
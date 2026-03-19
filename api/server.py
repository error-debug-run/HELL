# hell/api/server.py

import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psutil
import time

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

@app.get("/jobs")
def jobs():
    return {
        "jobs":  state["jobs"][:20],
        "total": len(state["jobs"]),
    }

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
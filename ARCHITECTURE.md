# HELL System — Full Python Architecture Reference

> Voice-Driven Windows Automation System

---

## 1. Overview

HELL is a voice-driven automation system for Windows that operates as a fully offline, modular pipeline — from audio capture through intelligent intent routing to system-level execution.

- Listens continuously for a configurable wake word
- Converts speech to text (STT) using a local transcription engine
- Detects user intent via a dual-engine NLP pipeline (MiniLM semantic + TF-IDF fallback)
- Routes commands to registered handlers through a central orchestrator
- Executes system- and application-level actions
- Exposes a FastAPI backend for GUI integration and live monitoring

---

## 2. Core Flow (End-to-End)

```text
User Speech
   ↓
Wake Word Detector                 (stt/detector.py)
   ↓
Command Extraction                 (removes wake word prefix)
   ↓
Intent Detection Pipeline          (pipeline/pipeline.py → classifier.py)
   ↓
Orchestrator Routing               (core/orchestrator.py)
   ↓
Intent Handler Execution           (intents/library/*.py)
   ↓
System Action / API Response
```

---

## 3. API Layer (`api/server.py`)

The FastAPI server is the bridge between the frontend GUI and the running HELL backend. It exposes read/write endpoints for system state, audio control, intent dispatch, and app configuration.

### Endpoints

**System Monitoring**
- `GET /health` — API liveness check + uptime
- `GET /status` — CPU, RAM, GPU (placeholder), current mode

**Audio Control**
- `GET /audio/devices` — List available microphones
- `POST /audio/device` — Set active microphone
- `GET /audio/level` — Live dB level and recording state

**Intent Processing**
- `POST /intent` — Manual command dispatch: detects intent, logs a job, and dispatches async execution

**Job Tracking**
- `GET /jobs` — Last 20 commands with full execution history

**App Management**
- `POST /apps/write` — Scan and persist the installed app list
- `POST /apps/assign_mode` — Assign apps to `startup`, `game`, or `dev` mode

### Shared State

Two dictionaries are shared across the API and STT subsystems:

```python
# General system state
state = {
    "current_mode": "IDLE",
    "jobs": [],
    "start_time": "..."
}

# Shared with STT subsystem
audio_state = {
    "db_level": -60.0,
    "recording": False,
    "mode": "idle"          # "idle" | "active" | "command"
}
```

---

## 4. Orchestrator (`core/orchestrator.py`)

The central routing layer. Receives a resolved intent, extracts entities, selects the matching handler, and dispatches execution asynchronously.

### Handler Mapping

| Intent | Handler |
| :----- | :------ |
| `startup_mode` | `startup_mode.run()` |
| `dev_mode` | `dev_mode.run()` |
| `open_app` | `app_control.open()` |
| `close_app` | `app_control.close()` |
| `hide_app` | `app_control.hide()` |
| `system_status` | internal handler |

### Execution Flow

1. Receive resolved intent from pipeline
2. Extract entities (e.g. app name, mode)
3. Look up handler in registry
4. Execute handler asynchronously
5. Return result or error to caller

### Error Handling

- **Unknown intent** — safe fail with logged warning; no crash
- **Handler exception** — caught, logged, and returned as an error result

---

## 5. App Finder (`finderr/finder.py`)

Discovers, normalises, deduplicates, and persists the list of installed applications on the host machine.

### Pipeline

**Step 1 — Scan**
Calls the Rust backend (`app_finder` crate) to enumerate installed apps.

**Step 2 — Normalise**
Maps raw objects to a consistent schema:

```json
{
  "name":          "...",
  "exe_name":      "...",
  "full_path":     "...",
  "resolved_path": "...",
  "args":          "...",
  "app_type":      "...",
  "publisher":     "..."
}
```

**Step 3 — Deduplicate**
Removes duplicates by path, groups entries by name, and prefers `.exe` over launcher wrappers.

**Step 4 — Save**
Writes the final list to `config.json` under `"installed_apps": [...]`.

---

## 6. NLP Layer (`pipeline/classifier.py`)

Intent detection uses two engines in tandem, with MiniLM as the primary and TF-IDF as the fallback.

### Engine 1 — MiniLM (Primary)

- Semantic embedding model; runs fully offline (~5–10 ms on CPU)
- Handles synonyms and paraphrases — e.g. `"terminate spotify"` correctly resolves to `close_app`
- **Workflow:** load model → encode training sentences into embeddings → encode input → compute cosine similarity → vote among top candidates → return `(intent, confidence%)`

### Engine 2 — TF-IDF (Fallback)

- Keyword-based matching using unigrams, bigrams, and trigrams
- Cosine similarity scoring with majority voting among top results
- Used when MiniLM confidence falls below threshold

### Output

Both engines return the same structure: `(intent: str, confidence: float)`.

---

## 7. Pipeline Entry (`pipeline/pipeline.py`)

The single entry point for all text commands — whether sourced from STT or the `/intent` API endpoint.

### Flow

```text
raw_command
   ↓  strip wake word
clean_command
   ↓  detect intent  (MiniLM → TF-IDF fallback)
(intent, confidence)
   ↓  confidence check
if low → REJECT  (no fallback guess)
if ok  → forward to orchestrator
```

> **Key Rule:** Low-confidence commands are strictly rejected. The system does not guess.

---

## 8. Speech System (`stt/detector.py`)

The `WakeWordDetector` manages all audio input, mode transitions, and command hand-off to the pipeline.

### Operating Modes

| Mode | Trigger | Behaviour |
| :--- | :------ | :-------- |
| **IDLE** | Default / after sleep word | Monitors audio energy; transcribes short windows; checks for wake word |
| **ACTIVE** | Wake word detected | Listens continuously; captures full command audio window |
| **COMMAND** | Non-empty speech detected | Transcribes captured audio; dispatches to pipeline |

### Command Classification

| Result | Action |
| :----- | :----- |
| Empty | Ignore |
| Hallucination | Ignore (filtered) |
| Sleep word | Transition back to IDLE |
| Valid command | Forward to pipeline |

### Hallucination Filtering

Filters out common Whisper hallucinations: YouTube-style filler phrases, single repeated words, and very short or noisy inputs.

### Component Responsibilities

- **`AudioListener` (`listener.py`)** — Captures raw audio from the selected microphone
- **`Transcriber` (`transcriber.py`)** — Converts audio buffers to text
- **`WakeWordDetector` (`detector.py`)** — Orchestrates modes and dispatches commands

### Real-Time State Updates

The detector writes continuously to `audio_state`:
- `mode`: `"idle"` / `"active"` / `"command"`
- `recording`: `True` / `False`
- `db_level`: live dB float

---

## 9. Intent Routing — Runtime Example

Full trace for the command: `"hey hell, open spotify"`

```text
"hey hell, open spotify"
   ↓  WakeWordDetector strips wake word
"open spotify"
   ↓  pipeline.detect()
intent     = "open_app"
confidence = 97%
   ↓  pipeline.extract_entities()
entities   = { "app": "spotify" }
   ↓  orchestrator.route("open_app", entities)
handler    = app_control.open
   ↓  async execution
subprocess / OS call → Spotify launches
   ↓
result     = { "status": "ok", "app": "spotify" }
```

---

## 10. Logging System

All modules use a unified logger (`core/logger.py`). Log levels:

```python
logger.info("Intent detected: open_app (97%)")
logger.debug("Entity extracted: { app: 'spotify' }")
logger.warning("Low confidence intent rejected: 0.42")
logger.error("Handler failed: app_control.open — FileNotFoundError")
```

Logs cover: command receipt, intent detection, handler dispatch, execution results, and errors.

---

## 11. Key Design Principles

| Principle | Description |
| :-------- | :---------- |
| **Modular Architecture** | API, NLP, STT, and Orchestrator are fully isolated; each can be tested or replaced independently |
| **Async Execution** | Intent handling is non-blocking; the pipeline returns immediately while actions run in the background |
| **Offline-First** | MiniLM runs locally with no external API dependency |
| **Strict Confidence Gating** | Low-confidence commands are rejected rather than guessed; reliability over coverage |
| **Extensible Intent Registry** | Adding a new capability requires only: a new handler file and a single orchestrator registration |

---

## 12. System Capabilities

- Voice-controlled app launch, close, and hide
- Mode-based automation (startup / dev / game)
- Real-time system monitoring via REST API
- Intelligent intent recognition with semantic fallback
- App discovery and mode assignment via config

---

## 13. Future Expansion

| Area | Description |
| :--- | :---------- |
| GPU Monitoring | Replace placeholder in `/status` with real GPU usage |
| Game Mode Handler | Implement `game_mode.run()` in `intents/library/` |
| Dev Workflow Automation | Terminal commands, git ops, editor control |
| Context Memory | Allow multi-turn commands referencing prior state |
| Entity Extraction | Improve beyond simple keyword matching (e.g. fuzzy app name lookup) |
| GUI Dashboard | Connect Avalonia GUI to live API state and job history |

---

## 14. Directory Structure

Includes build artifacts (`bin/`, `obj/`, `target/`) and `runtime/` from Version B.

```text
D:\HELL/
├── api/
│   ├── __init__.py
│   └── server.py
|
├── control/
│   ├── _experimental_apps.py
│   ├── _test_apps.py
│   ├── almost_apps.py
│   └── apps.py
|
├── core/
│   ├── log.py
│   ├── logger.py
│   ├── orchestrator.py
│   └── postLog_orchestrator.py
├── finderr/
│   └── finder.py
|
├── gui/
|
├── hell-rm/
|
├── intents/
│   └── library/
│       ├── app_control.py
│       ├── dev_mode.py
│       └── startup_mode.py
|
├── pipeline/
│   ├── classifier.py
│   ├── dataset.py
│   ├── extractor.py
│   ├── intent.py
│   └── pipeline.py
|
├── runtime/
|
├── stt/
│   ├── detector.py
│   ├── listener.py
│   └── transcriber.py
|
├── .gitignore
├── README.md
├── config.json
├── config.py
├── hell-cert.cer
├── main.py
├── project-structure.txt
└── sign.ps1
```
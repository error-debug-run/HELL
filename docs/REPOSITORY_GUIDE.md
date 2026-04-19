# HELL Repository Guide

## What This Repo Is

HELL is a Windows-first local automation system made of three major runtime surfaces:

- A Python backend that owns speech input, intent detection, orchestration, config, and OS actions.
- An Avalonia desktop GUI in C# that starts the backend, polls its API, and exposes controls/status to the user.
- A Rust extension module that scans installed Windows applications and exposes them back to Python through PyO3.

At a high level, the repo is trying to act like a local operating layer:

1. Listen for audio.
2. Detect a wake word.
3. Transcribe the follow-up command.
4. Resolve the command into an intent.
5. Route that intent to a handler.
6. Launch, hide, minimize, or close applications.
7. Expose the same backend state to the GUI over HTTP.

## Top-Level Map

| Path | Purpose |
| --- | --- |
| `main.py` | Python runtime entry point; starts FastAPI and STT together |
| `api/` | FastAPI server and shared in-memory API/audio state |
| `core/` | Logging and orchestrator |
| `pipeline/` | Intent dataset, classifier engines, detection entrypoint, entity extraction |
| `stt/` | Audio capture, transcription, wake-word loop |
| `intents/library/` | Intent handlers for startup/dev/app control |
| `control/` | Low-level Windows app automation and launch logic |
| `finderr/` | Python wrapper layer around Rust app scanning |
| `hell-rm/` | Rust crates, especially the `app_finder` PyO3 module |
| `gui/` | Avalonia desktop app and service layer |
| `runtime/` | Log output location |
| `config.json` | Central runtime configuration and discovered apps |

## Runtime Architecture

### 1. Python Process Startup

`main.py` is the Python entry point.

- It enables debug logging.
- It starts the FastAPI app on `127.0.0.1:8000` in a background thread.
- It creates the STT runtime in the main async loop.
- It wires `WakeWordDetector.on_command` to `pipeline.pipeline.handle_command`.

This means the Python backend is really two subsystems in one process:

- API server thread
- STT/event loop thread of control

### 2. API Layer

`api/server.py` exposes the backend to the GUI.

Key responsibilities:

- Health/status endpoints for GUI polling
- Audio device enumeration and microphone selection
- Manual intent submission via `POST /intent`
- Job history tracking in memory
- App scanning and mode assignment APIs
- Shared `audio_state` dictionary for live STT status

Important in-memory state:

- `state`
  - `current_mode`
  - `jobs`
  - `start_time`
- `audio_state`
  - `db_level`
  - `recording`
  - `mode`

Current API endpoints:

| Endpoint | Role |
| --- | --- |
| `GET /health` | Backend liveness/uptime |
| `GET /status` | Mode and machine summary |
| `GET /audio/devices` | List input devices from `sounddevice` |
| `POST /audio/device` | Save selected microphone index into `config.json` |
| `GET /audio/level` | Current dB level and STT mode |
| `POST /intent` | Manual text intent detection and dispatch |
| `GET /jobs` | Recent intent/job history |
| `POST /apps/write` | Refresh installed apps through Rust-backed scanner |
| `POST /apps/assign_mode` | Push an app into startup/game/dev config |

### 3. STT Pipeline

The STT subsystem is split across three files:

- `stt/listener.py`
  - Opens a low-latency `sounddevice.InputStream`
  - Maintains a rolling float32 audio buffer
  - Computes dB level and writes into `api.server.audio_state`
- `stt/transcriber.py`
  - Wraps `faster_whisper.WhisperModel`
  - Uses local model path if configured, otherwise model name loading
- `stt/detector.py`
  - Owns the wake-word loop and mode machine
  - Switches between `idle`, `active`, and `command`
  - Filters hallucinated transcripts
  - Recognizes wake word, sleep word, and `stop hell`
  - Hands valid commands to `on_command`

The detector flow is:

1. Sleep for the configured slide interval.
2. Ignore silent windows.
3. In `idle`, transcribe a short window and search for the wake word.
4. On wake word, enter `active`.
5. In `active`, capture a command window and transcribe it.
6. If the transcript is valid, forward it to `pipeline.pipeline.handle_command`.
7. Stay active until the sleep word is heard or the detector is stopped.

### 4. Intent Detection Pipeline

Intent resolution is spread across:

- `pipeline/dataset.py`
- `pipeline/classifier.py`
- `pipeline/intent.py`
- `pipeline/extractor.py`
- `pipeline/pipeline.py`

#### Dataset

`pipeline/dataset.py` contains the training phrases for supported intents. It is a large hand-authored dataset and effectively defines the language surface of the assistant.

Examples of represented intents:

- `startup_mode`
- `dev_mode`
- `game_mode`
- `open_app`
- `close_app`
- `kill_app`
- `minimize_app`
- `hide_app`
- `show_app`
- `system_status`

#### Classifier Engines

`pipeline/classifier.py` provides two engines:

- `MiniLMEngine`
  - Preferred engine
  - Uses local `sentence-transformers`
  - Encodes the entire training set into embeddings
- `TFIDFEngine`
  - Fallback engine
  - Uses token, bigram, and trigram features

`pipeline/intent.py` selects MiniLM if `models/minilm` exists, otherwise TF-IDF.

Detection output shape:

```python
{
    "intent": str,
    "confidence": float,
    "text": str,
    "understood": bool,
}
```

#### Entity Extraction

`pipeline/extractor.py` resolves app references from text.

It does this by:

- Reading `installed_apps` from `config.json`
- Merging in startup apps as additional known entries
- Stripping trigger verbs like `open`, `close`, `hide`, `kill`
- Trying direct matches first
- Falling back to fuzzy matching via `difflib.get_close_matches`

#### Pipeline Entry

`pipeline/pipeline.py` is the text-command entry point used by STT.

It:

1. Cleans out wake-word bleed from the command.
2. Calls `pipeline.intent.detect`.
3. Rejects low-confidence commands.
4. Hands successful results to `core.orchestrator.Orchestrator.route`.

### 5. Orchestration Layer

`core/orchestrator.py` is the canonical runtime router for STT commands.

Registered handlers today:

| Intent | Handler |
| --- | --- |
| `startup_mode` | `intents.library.startup_mode.run` |
| `dev_mode` | `intents.library.dev_mode.run` |
| `open_app` | `intents.library.app_control.run` |
| `kill_app` | `intents.library.app_control.run` |
| `minimize_app` | `intents.library.app_control.run` |
| `close_app` | `intents.library.app_control.run` |
| `hide_app` | `intents.library.app_control.run` |
| `system_status` | Internal `_system_status` method |

Route behavior:

1. Receive `intent`, `confidence`, and `text`.
2. Extract entities from the text.
3. Add `intent` back into the entity payload.
4. Look up the handler.
5. Await the handler.
6. Return a success/failure result.

### 6. Intent Handlers

#### `intents/library/startup_mode.py`

Purpose:

- Load `config.startup_apps`
- Launch each configured app
- Run them concurrently
- Use `launch_and_intent` from `control/apps.py`

The current behavior is closer to "launch, wait, then attempt graceful close" than "launch and minimize to tray", because `launch_and_intent()` currently waits and then calls `close()`.

#### `intents/library/dev_mode.py`

Purpose:

- Read `dev_mode.trigger_apps` from config
- Resolve them into full installed-app objects by matching `exe_name`
- Launch them concurrently through `control.apps.launch`

#### `intents/library/app_control.py`

Purpose:

- Dispatch concrete app actions based on `entities["intent"]`

Supported actions in the handler:

- `open_app`
- `close_app`
- `kill_app`
- `minimize_app`
- `hide_app`

### 7. Windows App Control Layer

`control/apps.py` is the deepest OS-facing layer in the Python backend.

Its job is to normalize app metadata and turn it into real Windows actions.

Major capabilities:

- Launching `.exe` applications
- Launching `shell:AppsFolder\...` UWP entries
- Launching URI protocols
- Enumerating windows with Win32 APIs
- Matching windows by process or title
- Showing/focusing windows
- Minimizing/hiding windows
- Gracefully closing windows with `WM_CLOSE`
- Force-killing processes with `taskkill`
- Waiting for UI readiness
- Relaunching apps if focus/restore fails

This module is effectively the Windows automation engine for the repo.

### 8. Application Discovery

App discovery spans Python and Rust.

#### Python Side

`finderr/finder.py`:

- Imports the compiled `app_finder` module
- Reads `app_finder.scan_apps()`
- Normalizes Rust-returned objects into Python dicts
- Deduplicates by path and then by app name
- Writes the final result back into `config.json` as `installed_apps`

#### Rust Side

`hell-rm/crates/app_finder/` is the scanner implementation.

`src/lib.rs`:

- Defines a shared `AppEntry`
- Exposes `scan_apps()` and `resolve_lnk()` to Python using PyO3

`src/windowsapps.rs`:

- Scans uninstall registry hives
- Scans Start Menu `.lnk` shortcuts
- Resolves shortcut targets through COM shell link APIs
- Enumerates UWP/MSIX packages through PowerShell `Get-AppxPackage`
- Parses `AppxManifest.xml` to extract launchable application IDs
- Produces normalized `AppEntry` records

This is the source of truth for populating `installed_apps`.

### 9. Logging

Logging is centralized in:

- `core/log.py`
- `core/logger.py`

Characteristics:

- Async queue-based file logging
- JSON lines format
- Per-process session ID
- Rotation in `runtime/logs/app.log`
- Optional debug mode
- Zip export support

### 10. GUI Architecture

The Avalonia app in `gui/` is a companion frontend, not the main automation engine.

#### Startup Model

`gui/Program.cs`

- Enforces a single-instance desktop app via a named mutex

`gui/App.axaml.cs`

- Creates one shared `MainWindowViewModel`
- Opens `StartupWindow` first
- Initializes a tray icon with mode and dashboard commands

#### ViewModel

`gui/ViewModels/MainWindowViewModel.cs` is the frontend coordinator.

It owns:

- Current tab state
- Displayed system stats
- Mic visualizer state
- API connection state
- Backend running state
- Audio level state
- Mic device list

It delegates work into services:

- `HellProcessService`
- `AudioService`
- `HardwareService`

#### Services

`gui/Services/HellProcessService.cs`

- Starts the Python backend via `python.exe main.py`
- Waits until `GET /health` returns success
- Stops the backend by killing the full process tree

`gui/Services/AudioService.cs`

- Calls `/audio/devices`
- Calls `/audio/device`
- Polls `/audio/level`

`gui/Services/HardwareService.cs`

- Reads CPU name and GPU name from the Windows registry
- Uses Windows performance counters for CPU and RAM usage

#### Views

`gui/Views/StartupWindow.axaml.cs`

- Uses the shared view model
- Transitions into the main dashboard window

`gui/Views/MainWindow.axaml.cs`

- Overrides close behavior to hide to tray instead of exiting

### 11. Config Model

`config.py` is the single config reader abstraction.

It wraps `config.json` and exposes:

- top-level HELL metadata
- startup app config
- dev mode project/browser config
- game mode network config
- STT config
- generic nested lookup with `get()`

Runtime features depend heavily on config sections like:

- `startup.minimize_on_boot`
- `dev_mode.trigger_apps`
- `game_mode.*`
- `stt.*`
- `installed_apps`

## End-to-End Workflows

### Voice Command Workflow

1. `main.py` starts FastAPI and STT.
2. `AudioListener` captures microphone data.
3. `WakeWordDetector` checks for the wake word.
4. `Transcriber` converts speech to text.
5. `pipeline.pipeline.handle_command()` cleans and classifies text.
6. `Orchestrator.route()` extracts entities and selects a handler.
7. An intent module in `intents/library/` executes the action.
8. `control/apps.py` performs OS-level app automation if needed.
9. Logs are written to `runtime/logs/`.

### GUI-Initiated Workflow

1. The Avalonia app launches.
2. `HellProcessService` starts `python main.py`.
3. The GUI waits for `/health`.
4. The view model begins polling:
   - `/status` every 2 seconds
   - `/audio/level` every 100ms while running
5. User actions trigger HTTP calls like:
   - `/intent`
   - `/audio/devices`
   - `/audio/device`
6. The backend updates in-memory state, which the GUI then reflects.

### App Discovery Workflow

1. API receives `POST /apps/write`.
2. Python imports `finderr.finder.run_finder`.
3. Rust `app_finder.scan_apps()` enumerates installed apps.
4. Python deduplicates and normalizes the results.
5. `config.json` is updated with `installed_apps`.

## Current Gaps And Mismatches

This section matters because several docs in the repo describe the intended architecture, but the code currently diverges in a few places.

### API Routing vs Orchestrator Routing

There are two intent execution paths:

- STT path: `pipeline.pipeline.handle_command()` -> `core.orchestrator.Orchestrator`
- API path: `POST /intent` -> local `route_intent()` inside `api/server.py`

That means the backend currently has duplicated routing logic instead of a single intent-dispatch path.

### API Route Coverage Is Narrower Than Orchestrator Coverage

`api/server.py` currently dispatches:

- `startup_mode`
- `open_app`
- `close_app`
- `hide_app`

But it does not currently dispatch:

- `dev_mode` (commented out)
- `game_mode`
- `kill_app`
- `minimize_app`
- `system_status`

So voice commands through STT and commands submitted through the API do not have identical behavior.

### `POST /apps/write` Looks Broken In Current Code

`api/server.py` calls `run_finder()` with no arguments, but `finderr/finder.py` currently defines:

```python
def run_finder(apps):
```

That mismatch likely causes a runtime error unless the function is changed or called differently.

### Startup Mode Behavior Does Not Match Its Description

The comments describe startup mode as launching apps and minimizing them to tray, but the current implementation calls `launch_and_intent()`, which:

1. launches the app,
2. waits for a window,
3. sleeps for 15 seconds,
4. attempts to close it.

So the implementation and the intended mode semantics are not aligned yet.

### GUI Uses Fixed Local Paths

`gui/Services/HellProcessService.cs` currently hardcodes:

- Python executable path
- Working directory
- localhost API URL

That is fine for the current workstation setup, but it is not portable yet.

## Directory-by-Directory Notes

### `api/`

- Backend surface for the GUI
- Holds mutable in-memory runtime state
- Also contains an alternate intent router

### `core/`

- Logging and orchestration
- `core/orchestrator.py` is the cleanest central dispatch abstraction in the repo

### `pipeline/`

- Pure language understanding layer
- Best place to extend when adding new natural-language intents

### `stt/`

- Audio IO and Whisper integration
- Owns the continuous listening loop

### `intents/library/`

- Business-level automation actions
- Best place to add new user-facing modes/behaviors

### `control/`

- Windows-specific operational logic
- Most complex low-level behavior in the Python codebase

### `finderr/` and `hell-rm/`

- Cross-language app discovery pipeline
- Rust is used here for Windows enumeration and PyO3 exposure

### `gui/`

- Operator console for HELL
- Starts/stops the backend, shows status, and exposes tray actions

## If You Want To Extend The Repo

### Add a new intent

1. Add training phrases in `pipeline/dataset.py`.
2. Update extraction logic in `pipeline/extractor.py` if entities are needed.
3. Add a handler in `intents/library/`.
4. Register it in `core/orchestrator.py`.
5. Mirror support in `api/server.py` if API-submitted intents should also run.

### Add a new app action

1. Extend `control/apps.py`.
2. Add intent mappings and examples in the dataset.
3. Route the new intent in `app_control.py` and the orchestrator.

### Add a new GUI control

1. Add a command/property to `MainWindowViewModel`.
2. Put external or process/API logic into a service under `gui/Services/`.
3. Bind the control in the relevant Avalonia view.

## Recommended Next Cleanup Steps

- Unify all command execution through `core.orchestrator.Orchestrator`.
- Fix the `run_finder()` signature mismatch.
- Decide whether startup mode should minimize apps or intentionally close them.
- Make GUI backend paths configurable.
- Add API support for the same full intent set as STT.

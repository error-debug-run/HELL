# HELL Workflow Diagram

## System Workflow

```mermaid
flowchart TD
    User[User]
    GUI[Avalonia GUI]
    Python[Python Backend main.py]
    API[FastAPI api/server.py]
    STT[WakeWordDetector stt/detector.py]
    Listener[AudioListener stt/listener.py]
    Whisper[Transcriber stt/transcriber.py]
    Pipeline[pipeline/pipeline.py]
    Intent[pipeline/intent.py]
    Extractor[pipeline/extractor.py]
    Orch[core/orchestrator.py]
    Handlers[intents/library/*.py]
    Control[control/apps.py]
    FinderPy[finderr/finder.py]
    FinderRs[hell-rm app_finder Rust crate]
    Config[config.json]
    Logs[runtime/logs/app.log]

    GUI -->|start backend| Python
    Python --> API
    Python --> STT
    STT --> Listener
    STT --> Whisper
    Whisper --> STT
    STT -->|valid command| Pipeline
    Pipeline --> Intent
    Pipeline --> Orch
    Orch --> Extractor
    Orch --> Handlers
    Handlers --> Control
    Control --> Config
    API -->|manual intent| Intent
    API -->|local route_intent| Handlers
    API -->|read/write state| Config
    API -->|POST /apps/write| FinderPy
    FinderPy --> FinderRs
    FinderRs --> FinderPy
    FinderPy --> Config
    API --> GUI
    Python --> Logs
    API --> Logs
    STT --> Logs
    Pipeline --> Logs
    Orch --> Logs
    Handlers --> Logs
    Control --> Logs
```

## Voice Command Path

```mermaid
sequenceDiagram
    participant U as User
    participant L as AudioListener
    participant D as WakeWordDetector
    participant T as Transcriber
    participant P as pipeline.handle_command
    participant I as pipeline.intent.detect
    participant O as Orchestrator
    participant H as Intent Handler
    participant C as control/apps

    U->>L: Speak audio
    L->>D: Rolling audio buffer + energy
    D->>T: Transcribe wake-word window
    T-->>D: Transcript
    D->>D: Wake word matched
    D->>T: Transcribe command window
    T-->>D: Command text
    D->>P: on_command(command)
    P->>I: detect(command)
    I-->>P: intent + confidence
    P->>O: route(result)
    O->>H: await handler(entities)
    H->>C: launch/close/hide/minimize
    C-->>H: action result
    H-->>O: success/failure
```

## GUI Control Path

```mermaid
sequenceDiagram
    participant G as GUI
    participant HP as HellProcessService
    participant M as main.py
    participant A as FastAPI
    participant VM as MainWindowViewModel

    G->>HP: StartAsync()
    HP->>M: python main.py
    M->>A: start API thread
    HP->>A: poll /health
    A-->>HP: 200 OK
    HP-->>VM: backend ready
    VM->>A: poll /status every 2s
    VM->>A: poll /audio/level every 100ms
    VM->>A: POST /intent on tray/dashboard actions
    A-->>VM: current state and job results
```

## App Discovery Path

```mermaid
sequenceDiagram
    participant GUI as GUI or caller
    participant API as FastAPI
    participant PY as finderr/finder.py
    participant RS as Rust app_finder
    participant CFG as config.json

    GUI->>API: POST /apps/write
    API->>PY: run_finder(...)
    PY->>RS: scan_apps()
    RS-->>PY: registry + Start Menu + UWP app entries
    PY->>PY: normalize + deduplicate
    PY->>CFG: write installed_apps
    PY-->>API: result
    API-->>GUI: success/failure
```

## Notes

- STT-submitted commands go through `core/orchestrator.py`.
- API-submitted commands currently use a separate local router in `api/server.py`.
- The app discovery diagram reflects the intended flow, but the current `/apps/write` implementation needs a small code fix because `run_finder()` is called without the `apps` argument its current signature expects.

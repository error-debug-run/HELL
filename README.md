# HELL System 

> **The operating layer that should have existed between humans and their computers from the beginning.**

**Status:** `v0.1 — Active Development (GUI Refactor)`  
**Platform:** Windows 10/11  
**Stack:** **_Python_** (Core) • **_Rust_** (app discovery, via PyO3/maturin)) • **_C#_** (GUI)

---

## 1. What is HELL?

Your computer runs everything the same way — whether you're gaming, developing, designing, or just listening to music.

HELL fixes that. It's a voice-driven automation system that understands what you're doing and configures your entire machine to match — so you stop adapting to your computer and it starts adapting to you.

**Core Value:**
- **Voice-Driven:** Natural language control via local wake word detection.
- **Context-Aware:** Modes for Startup, Dev, and Gaming that reconfigure system state.
- **Offline-First:** No cloud, no API calls, no data leaving your machine.

---

## 2. Architecture Overview

### Core Flow (End-to-End)
```text
User Speech
   ↓
Wake Word Detector (stt/detector.py)
   ↓
Command Extraction (removes wake word)
   ↓
Intent Pipeline (pipeline/pipeline.py → classifier.py)
   ↓
Orchestrator (core/orchestrator.py)
   ↓
Intent Handlers (intents/library/*.py)
   ↓
System Action / API Response
```

### Component Responsibilities
| Component | Path | Responsibility |
| :--- | :--- | :--- |
| **API Server** | `api/server.py` | FastAPI bridge for GUI & monitoring |
| **Orchestrator** | `core/orchestrator.py` | Routes intents to handlers asynchronously |
| **NLP Engine** | `pipeline/classifier.py` | MiniLM (Semantic) + TF-IDF (Fallback) |
| **App Finder** | `finderr/finder.py` | Rust-backed app discovery & normalization |
| **Speech System** | `stt/detector.py` | Wake word detection & audio state management |
| **GUI** | `gui/` | Avalonia (C#) frontend for control & monitoring |

---

## 3. GUI Integration Specification

> **⚠️ Critical for Frontend Refactor**  
> The following specs define how the Avalonia GUI communicates with the Python backend.

### 3.1 Communication Protocol

| Data Type | Method | Endpoint / Channel | Frequency |
| :--- | :--- | :--- | :--- |
| **Commands** | HTTP POST | `/intent` | On user action |
| **System Status** | HTTP GET | `/status` | On load / 5s poll |
| **Audio Levels** | **WebSocket** | `/ws/audio` | **Real-time (30fps)** |
| **Job Logs** | WebSocket | `/ws/logs` | Push on event |

> **Note:** Do not poll `/audio/level` via HTTP. Use the WebSocket stream for the GUI visualizer to prevent UI lag.

### 3.2 Shared State Schema (C# Models)

Ensure your C# ViewModels match these Python dictionaries exactly.

**AudioState (`audio_state`)**
```json
{
  "db_level": -45.2,      // float
  "recording": false,     // bool
  "mode": "idle"          // enum: ["idle", "active", "command"]
}
```

**SystemStatus (`state`)**
```json
{
  "current_mode": "DEV",  // string
  "cpu_usage": 12.5,      // float
  "ram_usage": 45.0,      // float
  "jobs": []              // list
}
```

### 3.3 Process Lifecycle

1.  **GUI Starts First:** The Avalonia app launches the Python backend (`main.py`) as a subprocess.
2.  **Handshake:** GUI waits for `GET /health` on `localhost:8000` before enabling UI controls.
3.  **Shutdown:** GUI sends `POST /shutdown` (if implemented) or gracefully kills subprocess.
4.  **Dev Mode:** Backend runs on `localhost:8000`.
5.  **Production:** Backend runs hidden; GUI connects via localhost or named pipe.

### 3.4 Configuration & Paths

| Environment | Config Path | Log Path |
| :--- | :--- | :--- |
| **Dev (Source)** | `./config.json` | `./logs/` |
| **Production (Installer)** | `%APPDATA%\HELL\config.json` | `%APPDATA%\HELL\logs\` |

> **GUI Logic:** Use `Environment.SpecialFolder.ApplicationData` for production builds. Do not attempt to write to `Program Files`.

### 3.5 Developer Overlay (Dev Builds Only)

- **Toggle:** `Ctrl + Shift + D`
- **Features:**
  - Shows raw JSON payloads from backend.
  - Displays WebSocket connection status.
  - Allows manual intent triggering (bypasses STT) for testing UI states.

---

## 4. Current Capabilities (v0.1)

- **Startup Mode** — All startup apps launch silently to tray. Clean desktop.
- **Dev Mode** — Opens IDE + browser with project-specific tabs automatically.
- **Game Mode** — Pings game servers pre-load; reports latency/packet loss.
- **Voice Control** — Wake word detection + local intent recognition.
- **App Management** — Scan, assign, and launch installed applications via voice.

---

## 5. Technology Stack

| Layer | Technology | Notes |
| :---- | :--------- | :---- |
| **Core Runtime** | Python 3.10+ | asyncio for concurrent jobs |
| **Intent Detection** | MiniLM + TF-IDF | Local, offline, ~50ms latency |
| **App Discovery** | Rust (`app_finder`) | Via PyO3/maturin for speed |
| **System APIs** | pywin32, psutil | Windows process & hardware control |
| **API Server** | FastAPI | REST + WebSocket support |
| **GUI** | Avalonia (C#) | .NET 10, cross-platform UI framework |

---

## 6. Roadmap & In-Progress

| Feature | Status | Notes |
| :--- | :--- | :--- |
| **GUI Refactor** | 🟡 In Progress | Binding to new FastAPI state dicts |
| **WebSocket Audio** | 🟡 In Progress | Real-time dB visualization |
| **GPU Monitoring** | 🔴 Planned | Replace placeholder in `/status` |
| **Context Memory** | 🔴 Planned | Multi-turn command support |
| **Installer Signing** | 🟢 Done | `hell-cert.cer` ready for deployment |

---

## 7. Philosophy

**Offline first. Private by design.**

- **You own everything:** Your data, your config, your machine.
- **No Telemetry:** HELL never calls home.
- **No Cloud:** Voice processing happens locally on your CPU.
- **No Accounts:** No login, no signup, no tracking.

---

## 8. Troubleshooting (Dev)

| Issue | Solution |
| :--- | :--- |
| **GUI won't connect** | Ensure `main.py` is running and `GET /health` returns 200 OK. |
| **Audio visualizer static** | Check WebSocket connection (`/ws/audio`); HTTP polling is too slow. |
| **Config not saving** | Verify write permissions in `%APPDATA%\HELL\` (Prod) or root (Dev). |
| **App not found** | Run `POST /apps/write` to refresh the Rust-backed app scanner. |

---

## 9. Directory Structure (Source)

```text
D:\HELL/
├── api/                  # FastAPI backend
├── core/                 # Orchestrator & Logging
├── finderr/              # Rust app finder bindings
├── gui/                  # Avalonia C# Frontend
├── intents/              # Action handlers
├── pipeline/             # NLP & Intent Classification
├── stt/                  # Speech-to-Text & Wake Word
├── config.json           # User configuration
├── main.py               # Entry point
└── requirements.txt      # Python dependencies
```

---


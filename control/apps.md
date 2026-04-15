# Windows Application Control Module - Workflow Documentation

## Overview
This module provides async/sync APIs to launch, close, kill, minimize, and manage Windows applications at the OS level. It bridges Python to the Win32 API via ctypes.

## 1. Main Architecture Flowchart

```mermaid
flowchart TD
    A[User Request] --> B{Operation Type}
    
    B -->|Launch| C[launch]
    B -->|Close| D[close]
    B -->|Kill| E[kill]
    B -->|Minimize| F[minimize]
    B -->|Hide| G[hide_by_title]
    B -->|Show/Focus| H[show_app_interactive]
    
    C --> C1[normalize_app]
    C1 --> C2{is_running_smart?}
    C2 -->|Yes| C3[show_app_interactive]
    C2 -->|No| C4[_build_launch_attempts]
    C4 --> C5[Try Each Strategy]
    C5 --> C6{_popen success?}
    C6 -->|No| C7[Try Next Strategy]
    C6 -->|Yes| C8[_wait_for_verified_window]
    C8 --> C9{Window Ready?}
    C9 -->|Yes| C10[Record Success & Return True]
    C9 -->|No| C7
    C7 --> C11{All Attempts Failed?}
    C11 -->|Yes| C12[Return False]
    
    D --> D1[normalize_app]
    D1 --> D2{is_running_smart?}
    D2 -->|No| D3[Return True - Nothing to Close]
    D2 -->|Yes| D4{App Type?}
    D4 -->|PWA| D5[_close_pwa_by_pid]
    D4 -->|Discord| D6[hide_by_title]
    D4 -->|Other| D7[_close_by_window WM_CLOSE]
    D5 --> D8{Window Gone?}
    D6 --> D8
    D7 --> D8
    D8 -->|No| D9[Escalate to Next Method]
    D8 -->|Yes| D10[Return True]
    D9 --> D11{All Methods Failed?}
    D11 -->|Yes| D12[Return False]
    
    E --> E1[normalize_app]
    E1 --> E2[_taskkill /F /IM exe]
    E2 --> E3[Return Success/Failure]
    
    F --> F1[normalize_app]
    F1 --> F2[_iter_windows by exe]
    F2 --> F3[ShowWindow SW_MINIMIZE]
    F3 --> F4[Return True if Minimized]
    
    G --> G1[normalize_app]
    G1 --> G2[_iter_windows by title]
    G2 --> G3[ShowWindow SW_HIDE]
    G3 --> G4[Return True if Hidden]
    
    H --> H1[_best_matching_window]
    H1 --> H2{Window Found?}
    H2 -->|No| H3[Return False]
    H2 -->|Yes| H4[Send ALT Key]
    H4 --> H5[ShowWindow SW_RESTORE]
    H5 --> H6[SetForegroundWindow]
    H6 --> H7[Release ALT Key]
    H7 --> H8[Return True]
```

## 2. Launch Workflow Detail

```mermaid
sequenceDiagram
    participant U as User
    participant L as launch()
    participant N as normalize_app()
    participant R as is_running_smart()
    participant B as _build_launch_attempts()
    participant P as _popen()
    participant W as _wait_for_verified_window()
    participant S as _rating_store
    participant I as show_app_interactive()
    
    U->>L: launch app config
    L->>N: normalize_app app
    N->>L: normalized app dict
    L->>R: is_running_smart?
    R->>L: True/False
    
    alt App Already Running
        L->>I: show_app_interactive
        I->>U: Return True
    else App Not Running
        L->>B: _build_launch_attempts
        B->>L: List of strategies
        
        loop For Each Attempt
            L->>P: _popen attempt
            P->>L: PID dict or False
            
            alt Launch Success
                L->>W: _wait_for_verified_window
                W->>L: True/False
                
                alt Window Ready
                    L->>S: record_success method
                    S->>L: Success recorded
                    L->>I: show_app_interactive
                    I->>U: Return True
                else Timeout
                    L->>L: Try Next Strategy
                end
            else Launch Failed
                L->>L: Try Next Strategy
            end
        end
        
        L->>U: Return False - All Failed
    end
```

## 3. App Type Detection & Launch Strategy

```mermaid
flowchart LR
    A[App Config] --> B{Path Starts With?}
    
    B -->|shell:AppsFolder| C[UWP App]
    B -->|protocol: spotify:| D[Protocol Handler]
    B -->|.exe or file exists| E[Win32 Executable]
    B -->|Other| F{App Type Config}
    
    C --> C1[Launch: explorer.exe shell:URI]
    C --> C2[Detection: _is_uwp_running]
    
    D --> D1[Launch: cmd /C start URI]
    D --> D2[Detection: is_running_by_title]
    
    E --> E1[Launch: Direct Execute<br/>DETACHED + NO_WINDOW flags]
    E --> E2[Detection: is_running by exe]
    
    F -->|pwa| G[PWA App]
    F -->|exe| E
    G --> G1[Launch: shell URI or path]
    G --> G2[Detection: is_running_by_title]
    
    C1 --> H[Launch Attempt]
    D1 --> H
    E1 --> H
    G1 --> H
```

## 4. Close/Escalation Workflow

```mermaid
flowchart TD
    A[close Request] --> B[normalize_app]
    B --> C{is_running_smart?}
    C -->|No| D[Return True - Nothing to Close]
    C -->|Yes| E{App Type/Name?}
    
    E -->|PWA| F[Method: pwa_pid]
    E -->|Discord| G[Method: hide_by_title]
    E -->|Other| H[Method: window_close]
    
    F --> I[Find Windows by Title]
    G --> J[Hide Windows by Title]
    H --> K[PostMessage WM_CLOSE]
    
    I --> L[Terminate PIDs via psutil]
    J --> M[ShowWindow SW_HIDE]
    K --> N[Wait 0.3s]
    
    L --> O{Window Visible?}
    M --> O
    N --> O
    
    O -->|Yes - Still Visible| P{Timeout Reached?}
    O -->|No - Closed| Q[Return True]
    
    P -->|No| R[Wait interval]
    R --> O
    
    P -->|Yes| S{More Methods?}
    S -->|Yes| T[Try Next Method]
    T --> E
    S -->|No| U[Return False - All Failed]
```

## 5. Window Matching & Ranking System

```mermaid
flowchart TD
    A[_iter_windows] --> B[Collect All Top-Level Windows]
    B --> C{Filter Criteria}
    
    C -->|match_exe| D[Filter by Executable Name]
    C -->|match_title| E[Filter by Title Substring]
    C -->|None| F[No Filter - All Windows]
    
    D --> G[Gather Window Metadata]
    E --> G
    F --> G
    
    G --> H[hwnd - Window Handle]
    G --> I[title - Window Title]
    G --> J[pid - Process ID]
    G --> K["exe - Executable Name (None if inaccessible)"]
    G --> L["area - Window Size (px2)"]
    G --> M[visible - Is Visible]
    G --> N[responded - Is Responsive]
    G --> O[appwindow - Has Taskbar Button]
    
    H --> P[_match_window]
    I --> P
    J --> P
    K --> P
    
    P --> Q{Match Criteria}
    Q -->|window_title in title| R[Candidate]
    Q -->|app name in title| R
    Q -->|exe match| R
    Q -->|base exe in path| R
    
    R --> S[_rank_window Scoring]
    S --> T["responded x 1000"]
    S --> U["visible x 500"]
    S --> V["appwindow x 200"]
    S --> W["area / 10000"]
    
    T --> X[Total Score]
    U --> X
    V --> X
    W --> X
    
    X --> Y[max Score = Best Window]
    Y --> Z[Return Best Window or None]
```

## 6. Focus Stealing Workaround (ALT Key Trick)

```mermaid
sequenceDiagram
    participant A as show_app_interactive()
    participant W as Win32 API
    participant O as Windows OS
    participant T as Target Window
    
    A->>W: SendInput VK_MENU Press
    W->>O: Simulate ALT Key Press
    O->>O: Set "ALT Pressed" Flag
    
    Note over O: Windows Rule: If ALT pressed,<br/>next SetForegroundWindow succeeds
    
    A->>W: ShowWindow SW_RESTORE
    W->>T: Restore Window
    
    A->>W: BringWindowToTop
    W->>T: Move to Top of Z-Order
    
    A->>W: SetForegroundWindow
    W->>O: Request Input Focus
    O->>O: Check ALT Flag ✓
    O->>T: Grant Focus
    
    A->>W: SetFocus
    W->>T: Set Keyboard Focus
    
    A->>W: SendInput VK_MENU Release
    W->>O: Simulate ALT Key Release
    O->>O: Clear "ALT Pressed" Flag
    
    A->>A: Return True - Focus Successful
```

## 7. Security & Sanitization Flow

```mermaid
flowchart TD
    A["App Config Args"] --> B["sanitize_args()"]
    B --> C{"Args Empty?"}
    C -->|Yes| D["Return Empty List"]
    C -->|No| E["Iterate Each Arg"]
    
    E --> F["Strip and Lowercase"]
    F --> G{"Empty or Whitespace?"}
    G -->|Yes| H["Skip Arg"]
    G -->|No| I{"In BLOCKED_ARGS?"}
    
    I -->|Yes| J["Block - Skip Arg"]
    I -->|No| K{"Process Injection Pattern?"}
    
    K -->|Yes| J
    K -->|No| L["Keep Original Arg"]
    
    H --> M{"More Args?"}
    J --> M
    L --> M
    
    M -->|Yes| E
    M -->|No| N["Return Cleaned List"]
    
    subgraph BLOCKED_ARGS
        O["--uninstall"]
        P["--force-uninstall"]
        Q["--remove"]
        R["--processstart"]
        S["/uninstall"]
    end
    
    I -.-> O
    I -.-> P
    I -.-> Q
    I -.-> R
    I -.-> S
```

## 8. Complete Module API Summary

```mermaid
classDiagram
    class AppControl {
        +async launch(app, timeout, interval) bool
        +async close(app, timeout, interval) bool
        +kill(app) bool
        +minimize(app) bool
        +hide_by_title(app) bool
        +show_app(app, exe, title) bool
        +show_app_interactive(app, exe, title) bool
        +is_running_smart(app) bool
        +launch_and_intent(app, wait) bool
    }
    
    class Win32Wrappers {
        +_enum_windows(callback)
        +_get_window_text(hwnd) str
        +_get_window_pid(hwnd) int
        +_get_exe_for_pid(pid) Optional[str]
        +_show_window(hwnd, cmd) bool
    }
    
    class AppNormalization {
        +normalize_app(app) dict
        +sanitize_args(args, exe, name) list
        +_is_protocol(path) bool
    }
    
    class WindowDiscovery {
        +_iter_windows(match_exe, match_title) list
        +_match_window(window, app) bool
        +_rank_window(window) int
        +_best_matching_window(app, exe, title) Optional[dict]
    }
    
    class ProcessDetection {
        +is_running(exe_name, path) bool
        +is_running_by_path(path) bool
        +is_running_by_title(title) bool
        +_is_uwp_running(app) bool
        +is_running_smart(app) bool
    }
    
    class LaunchMechanics {
        +_popen(attempt, name) dict|bool
        +_build_launch_attempts(app) list
        +_wait_for_verified_window(app, timeout, interval) bool
    }
    
    AppControl --> Win32Wrappers
    AppControl --> AppNormalization
    AppControl --> WindowDiscovery
    AppControl --> ProcessDetection
    AppControl --> LaunchMechanics
```

## 9. README Quick Reference

### Installation & Dependencies

```python
# Required packages
psutil      # Cross-platform process library
ctypes      # Built-in Win32 API bridge
asyncio     # Async operations
subprocess  # Process management
```

### Basic Usage

```python
from control.apps import launch, close, kill, minimize, show_app_interactive

# Launch an application
app_config = {
    "name": "Chrome",
    "exe": "chrome.exe",
    "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "args": ["--new-window"]
}

await launch(app_config, timeout=10)

# Close gracefully
await close(app_config, timeout=10)

# Force kill
kill(app_config)

# Minimize all windows
minimize(app_config)

# Show and focus
show_app_interactive(app_config)
```

### App Configuration Schema

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Display name for logging |
| `exe` | Yes | Executable filename |
| `path` | Recommended | Full path to executable |
| `args` | No | Launch arguments (sanitized) |
| `app_type` | No | `exe`, `uwp`, `pwa`, `protocol` |
| `window_title` | No | Title for window matching |
| `launch_timeout` | No | Override default timeout |
| `close_timeout` | No | Override close timeout |
| `classification` | Auto | Auto-detected app category |

### App Type Detection

| Type | Path Pattern | Launch Method | Detection |
|------|--------------|---------------|-----------|
| UWP | `shell:AppsFolder\...` | `explorer.exe` | By name/base |
| Protocol | `spotify:`, `ms-settings:` | `cmd /C start` | By title |
| PWA | Custom | Shell URI | By title |
| Win32 | `.exe` or file path | Direct execute | By exe/path |

### Security Features

- **Argument Sanitization**: Blocks uninstall/self-modification flags
- **Blocked Args**: `--uninstall`, `--remove`, `--processstart`, `/uninstall`
- **Process Isolation**: `DETACHED` + `NO_WINDOW` flags for silent launches
- **Access Control**: Handles `AccessDenied` for protected processes
- **Type Safety**: `_get_exe_for_pid()` returns `Optional[str]` (None on error)

## 10. Error Handling Matrix

```mermaid
flowchart LR
    subgraph Launch Errors
        L1[FileNotFoundError] --> L2[Log & Try Next Strategy]
        L3[PermissionError] --> L2
        L4[TimeoutError] --> L2
    end
    
    subgraph Close Errors
        C1[Window Not Found] --> C2[Return True - Already Closed]
        C3[Process Access Denied] --> C4[Skip & Continue]
        C5[Timeout] --> C6[Escalate to Kill]
    end
    
    subgraph Kill Errors
        K1[Process Not Found] --> K2[Return True - Already Gone]
        K3[Access Denied] --> K4[Log Warning]
    end
    
    subgraph Show Errors
        S1[No Window Found] --> S2[Trigger Relaunch]
        S2 --> S3[Kill & Launch Fresh]
    end
```

## 11. Key Changes in Refactored Version

### Code Quality Improvements
- ✅ **Removed duplicate imports** - Single source of truth
- ✅ **Removed duplicate WIN32 constants** - Consolidated definitions
- ✅ **Removed duplicate helper functions** - One canonical implementation
- ✅ **Fixed type annotations** - `_get_exe_for_pid()` returns `Optional[str]`
- ✅ **Better error handling** - None vs empty string for inaccessible processes

### Architecture Improvements
- 📦 **Single `_iter_windows()` function** - Comprehensive metadata collection
- 📦 **Single `_CATEGORY_RUNNING_CHECKS`** - Unified dispatch table
- 📦 **Cleaner module structure** - No redundant code blocks

### Behavior Changes
- ⚠️ **None** - All workflows and APIs remain identical
- ⚠️ **Backward compatible** - No breaking changes to public API


---
*This documentation provides a complete visual and textual reference for the Windows Application Control Module workflow. All diagrams can be rendered in any Mermaid-compatible viewer (GitHub, VS Code, Mermaid Live Editor, etc.).*


# control/almost_apps.py
"""
Windows Application Control Module
==================================
This module provides async/sync APIs to launch, close, kill, minimize, and manage
Windows applications at the OS level. It bridges Python to the Win32 API via ctypes,
handling the complexity of:
  - Traditional Win32 executables (.exe)
  - UWP/Store apps (shell:AppsFolder protocol)
  - PWA/browser-hosted apps (window title matching)
  - URI protocol handlers (spotify:, ms-settings:, etc.)

Key Low-Level Concepts Used:
  - HWND (Handle to Window): Opaque integer identifying a top-level window in Win32
  - Message Queue: Windows apps receive input via messages (WM_CLOSE, etc.)
  - Desktop Heap: Each window belongs to a session/desktop; we operate on the current one
  - Foreground Restrictions: Windows prevents arbitrary focus stealing; we use Alt-key workaround
  - Process/Window Decoupling: A single process can have 0, 1, or many top-level windows
"""

__all__ = [
    "launch",  # Async: Launch app with fallback strategies, wait for window readiness
    "close",  # Async: Graceful close via WM_CLOSE, escalate to PID termination
    "kill",  # Sync: Force-kill via taskkill /F (immediate, no cleanup)
    "minimize",  # Sync: Minimize windows by exe name enumeration
    "hide_by_title",  # Sync: Hide windows by title substring (SW_HIDE)
]

import os
import subprocess
import time
import asyncio
import ctypes
import ctypes.wintypes
from typing import Optional

try:
    from control.launch_rating import rating_store as _rating_store
except Exception:
    _rating_store = None
import psutil  # Cross-platform process library; we use it for PID->exe name resolution

from core.log import logger  # Your structured logging wrapper

# ─────────────────────────────────────────
# WIN32 CONSTANTS — LOW-LEVEL MEANING
# ─────────────────────────────────────────

# Process creation flags (passed to CreateProcess via subprocess)
# ─────────────────────────────────────────
DETACHED = 0x00000008  # CREATE_DETACHED: Process has no console; runs independently
#   - Why? Prevents spawned apps from inheriting our console window or blocking I/O
#   - Without this, a console app launched from our script could steal stdin/stdout

NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW: Don't create a window for console apps
#   - Critical for background launches: prevents flash of cmd.exe when launching .exe
#   - Combined with DETACHED, ensures truly silent process creation

# ShowWindow() commands (nCmdShow parameter)
# ─────────────────────────────────────────
SW_HIDE = 0  # Hide window, activate another (sends WM_ACTIVATE to next window)
SW_RESTORE = 9  # Restore minimized/maximized window to normal size + activate
SW_MINIMIZE = 6  # Minimize window to taskbar; activates next top-level window
#   - These are NOT just visual: they trigger WM_SIZE, WM_ACTIVATE, WM_SHOWWINDOW messages
#   - Apps can override/handle these; some (like Electron) may ignore SW_RESTORE

# Window messaging
# ─────────────────────────────────────────
WM_CLOSE = 0x0010  # Standard "please close" message sent to window procedure
#   - Graceful shutdown: app receives WM_CLOSE -> can prompt "save changes?" -> calls DestroyWindow()
#   - NOT the same as WM_QUIT (posted to thread message queue) or WM_DESTROY (sent after window destroyed)
#   - Some apps (e.g., tray-only apps) may ignore WM_CLOSE; that's why we escalate to PID kill

# SendInput() constants for keyboard simulation (focus workaround)
# ─────────────────────────────────────────
INPUT_KEYBOARD = 1  # Type field for INPUT structure: indicates keyboard event
KEYEVENTF_KEYUP = 0x0002  # Flag: key is being released (vs pressed)
VK_MENU = 0x12  # Virtual-key code for ALT key (used in focus-stealing workaround)
#   - Windows restricts SetForegroundWindow() to the process that last received input
#   - Workaround: simulate ALT press/release to "trick" OS into allowing focus change
#   - This exploits the rule: "if user pressed ALT, next SetForegroundWindow succeeds"

# Window style constants for filtering "real" app windows
# ─────────────────────────────────────────
WS_EX_APPWINDOW = 0x00040000  # Extended style: window should appear in taskbar
GWL_EXSTYLE = -20  # Index for GetWindowLong() to retrieve extended window styles
#   - Why filter? Many windows are toolbars, notifications, hidden helpers
#   - We want only user-facing app windows: visible + responded + has taskbar button + reasonable size

# Global handle to user32.dll — the core Win32 UI library
# ─────────────────────────────────────────
user32 = ctypes.windll.user32
#   - ctypes.windll: loads DLLs using stdcall calling convention (Windows API standard)
#   - user32.dll contains: EnumWindows, ShowWindow, SendMessage, GetWindowText, etc.
#   - We cache the handle to avoid repeated LoadLibrary() calls

# ─────────────────────────────────────────
# SECURITY: Blocked launch arguments
# ─────────────────────────────────────────
_BLOCKED_ARGS = {
    "--uninstall", "--uninstall-app-id", "--force-uninstall", "--remove",
    "--processstart", "--process-start", "--original-process-start-time",
    "-removeonly", "/uninstall",
}


#   - Prevent accidental/malicious self-uninstall or process injection via app config
#   - These args are commonly used by installers (MSI, Squirrel) or updaters
#   - We filter them at the Python layer BEFORE passing to subprocess


# ─────────────────────────────────────────
# WIN32 WRAPPERS — ctypes -> C API Bridge
# ─────────────────────────────────────────
# These helpers abstract the verbose ctypes boilerplate for common Win32 operations.
# Each wraps a C function with proper argument/return type declarations.

def _enum_windows(callback):
    """
    Enumerate all top-level windows on the current desktop.

    Low-level mechanics:
    - EnumWindows() is a Win32 API function that iterates windows in Z-order (front to back)
    - For each window, it calls your callback(hwnd, lParam) with:
        - hwnd: Handle to Window (opaque integer, unique per window instance)
        - lParam: User-defined value we pass as 0 (unused here)
    - Callback must return True to continue enumeration, False to stop early

    ctypes details:
    - WNDENUMPROC is a function pointer type: BOOL CALLBACK EnumWindowsProc(HWND, LPARAM)
    - ctypes.WINFUNCTYPE creates a Python callable that matches the C signature
    - The callback runs in Python but is invoked from C code — hence the strict signature
    """
    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool,  # Return type: BOOL (int in C, but ctypes.c_bool for clarity)
        ctypes.wintypes.HWND,  # Param 1: HWND (handle to window)
        ctypes.wintypes.LPARAM  # Param 2: LPARAM (long pointer, we pass 0)
    )
    # Cast Python callback to C function pointer, then call EnumWindows
    user32.EnumWindows(WNDENUMPROC(callback), 0)


def _get_window_text(hwnd) -> str:
    """
    Retrieve the visible title text of a window.

    Low-level mechanics:
    - GetWindowTextLengthW(hwnd): Returns length of title in Unicode characters (W = wide/UTF-16)
      - Returns 0 if window has no title or is invisible
      - Does NOT include null terminator
    - GetWindowTextW(hwnd, buffer, nMaxCount): Copies title into pre-allocated buffer
      - Buffer MUST be large enough: length + 1 for null terminator
      - Uses UTF-16LE encoding (Windows native); ctypes handles conversion to Python str

    Why create_unicode_buffer?
    - Windows API expects writable memory; Python str is immutable
    - create_unicode_buffer(n) allocates n * sizeof(wchar_t) bytes on the C heap
    - After the call, buf.value automatically converts UTF-16 -> Python str
    """
    length = user32.GetWindowTextLengthW(hwnd)
    if not length:
        return ""
    # Allocate buffer: length chars + 1 for null terminator (wchar_t = 2 bytes on Windows)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value  # Auto-converts from UTF-16 wchar_t* to Python str


def _get_window_pid(hwnd) -> int:
    """
    Get the Process ID that owns a window.

    Low-level mechanics:
    - GetWindowThreadProcessId(hwnd, &pid): Returns thread ID, outputs process ID via pointer
    - We only care about the process ID (pid output parameter)
    - A single process can own multiple top-level windows (e.g., Chrome: each tab is a window)
    - A window can be owned by a different process than its creator (e.g., dialog boxes)

    ctypes pointer handling:
    - ctypes.wintypes.DWORD() creates a 32-bit unsigned integer container
    - ctypes.byref(pid) passes a pointer to that container (like &pid in C)
    - After the call, pid.value holds the output value
    """
    pid = ctypes.wintypes.DWORD()  # 32-bit unsigned int container
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))  # Pass pointer via byref()
    return pid.value


def _get_exe_for_pid(pid: int) -> Optional[str]:
    """
    Resolve a PID to its executable filename using psutil.

    Why psutil instead of Win32 API?
    - Win32: QueryFullProcessImageName() requires process handle + complex access rights
    - psutil: Cross-platform, handles access denied gracefully, caches process info
    - Trade-off: psutil is slower but more robust for our use case

    Error handling:
    - Process may exit between PID retrieval and query -> NoSuchProcess
    - System processes may deny access -> AccessDenied
    - We silently return None; caller should handle missing exe names
    """
    try:
        if pid > 0:  # PID 0 is System Idle Process; skip to avoid errors
            return psutil.Process(pid).name()  # Returns just the exe filename (e.g., "chrome.exe")
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass  # Process vanished or inaccessible — expected in concurrent environments
    return None


def _show_window(hwnd: int, cmd: int) -> bool:
    """
    Change window state via ShowWindow(hwnd, nCmdShow).

    Low-level mechanics:
    - ShowWindow() returns BOOL: non-zero if window was previously visible, zero if hidden
    - We ignore the return value here; caller cares about side effects, not prior state
    - This function triggers a cascade of messages:
        - WM_SHOWWINDOW (before visibility changes)
        - WM_SIZE (if restoring/minimizing/maximizing)
        - WM_ACTIVATE (if bringing to foreground)
    - Apps can override WndProc to ignore/handle these — we can't force compliance

    Note: ShowWindow is asynchronous — it posts messages, doesn't wait for processing.
    That's why we sometimes add time.sleep(0.3) after sending WM_CLOSE: give app time to react.
    """
    return bool(user32.ShowWindow(hwnd, cmd))


# ─────────────────────────────────────────
# APP NORMALIZATION — Unified Data Model
# ─────────────────────────────────────────

def normalize_app(app: dict) -> dict:
    """
    Normalize heterogeneous app configurations into a consistent internal schema.

    Why normalize?
    - Input may come from YAML, JSON, CLI args, or other modules with varying key names
    - We unify: path/resolved_path/full_path -> path, exe/exe_name -> exe, etc.
    - This prevents duplication: every function can assume app has "name", "exe", "path", etc.

    App type detection logic (critical for launch strategy):
    - shell:AppsFolder\... -> UWP/Store app (launched via explorer.exe shell URI)
    - protocol: (spotify:, ms-settings:) -> URI handler (launched via cmd /C start)
    - .exe or file exists -> traditional Win32 executable
    - fallback -> assume exe, let launch attempts handle failure

    Security note:
    - We sanitize args HERE, before any subprocess call, to block dangerous flags
    - This is a defense-in-depth layer: even if config is compromised, args are cleaned
    """
    import acm

    # Resolve path with fallback chain: most specific -> most generic
    path = (
            app.get("resolved_path")  # Post-resolution absolute path (preferred)
            or app.get("full_path")  # Alternative absolute path key
            or app.get("path")  # Generic path key
            or ""  # Fallback to empty string
    )

    # Resolve executable name: from config or derive from path
    exe = app.get("exe") or app.get("exe_name") or os.path.basename(path)

    # App display name: explicit name or fallback to exe filename
    name = app.get("name") or exe

    # Determine app_type for launch strategy selection
    if path.startswith("shell:"):
        app_type = "uwp"  # Microsoft Store / UWP app
    elif _is_protocol(path):
        app_type = "protocol"  # URI scheme handler (e.g., spotify:, http:)
    elif path.endswith(".exe") or os.path.exists(path):
        app_type = "exe"  # Traditional Win32 executable
    else:
        app_type = app.get("type", app.get("app_type", "exe"))  # Fallback to config or default

    classification = acm.classify_py(app)

    # Return normalized dict with all expected keys present
    return {
        **app,  # Preserve any extra keys the caller provided
        "name": name,
        "exe": exe,
        "path": path,
        "args": sanitize_args(app.get("args", []), exe, name),  # Security: clean args
        "type": app_type,  # Legacy key for backward compatibility
        "app_type": app_type,  # Preferred key for new code
        "window_title": app.get("window_title", name),  # Title to match for window ops
        "classification": classification,
    }


# ─────────────────────────────────────────
# ARGUMENT SANITIZATION — Prevent Dangerous Launches
# ─────────────────────────────────────────

def sanitize_args(args: list, exe: str, app_name: str = "") -> list:
    """
    Filter launch arguments to block uninstall/self-modification flags.

    Threat model:
    - A compromised config file could try to uninstall apps or spawn malicious processes
    - We block known-dangerous flags used by installers (MSI, Squirrel, Inno Setup)
    - This is NOT a security boundary — just a safety net for trusted configs

    Why lowercase comparison?
    - Windows CLI args are case-insensitive: --Uninstall == --uninstall
    - We normalize to lowercase for consistent matching

    Why skip empty args?
    - Prevents passing empty strings that could shift argument positions
    - Example: ["app.exe", "", "--flag"] might be interpreted as ["app.exe", "--flag"] with shifted index
    """
    if not args:
        return []

    cleaned = []
    for arg in args:
        a = arg.strip().lower()  # Normalize for comparison
        if not a:  # Skip empty/whitespace-only args
            continue
        if a in _BLOCKED_ARGS:  # Block known-dangerous flags
            continue
        # Block process injection patterns (used by updaters to spawn child processes)
        if a.startswith(("--processstart", "--process-start")):
            continue
        cleaned.append(arg)  # Keep original casing for actual launch (some apps are case-sensitive)

    return cleaned


# ─────────────────────────────────────────
# PROTOCOL DETECTION — URI Scheme Handling
# ─────────────────────────────────────────

def _is_protocol(path: str) -> bool:
    """
    Detect if a path is a URI protocol handler (spotify:, ms-settings:, etc.).

    Heuristic logic:
    - Contains ":" -> potential URI scheme
    - BUT exclude:
        - Drive letters: C:\, D:\ (false positive: "C:" looks like a scheme)
        - UNC paths: \\server\share (also contain backslashes, not schemes)
        - shell: prefix -> handled separately as UWP launcher

    Why does this matter?
    - Protocol handlers are launched via `cmd /C start "" <uri>`, not direct execution
    - Windows resolves the registered app for the scheme (via HKCR\<scheme>\shell\open\command)
    - This allows launching apps without knowing their install path (e.g., "spotify:" works regardless of install location)
    """
    return (
            ":" in path  # Basic URI scheme indicator
            and not path.startswith(("C:\\", "D:\\", "\\\\"))  # Exclude file paths
            and not path.startswith("shell:")  # UWP apps use shell: but need different handling
    )


# ─────────────────────────────────────────
# WINDOW ENUMERATION — The Core Discovery Engine
# ─────────────────────────────────────────

def _iter_windows(match_exe: Optional[str] = None, match_title: Optional[str] = None):
    """
    Enumerate top-level windows with optional filtering by exe name or title substring.

    Low-level enumeration mechanics:
    - EnumWindows() walks the window station's window list in Z-order (front to back)
    - For each window, we gather metadata via multiple Win32 API calls:
        1. GetWindowTextW() -> visible title (what user sees in taskbar)
        2. GetWindowThreadProcessId() -> owning PID
        3. psutil.Process(pid).name() -> exe filename (human-readable)
        4. GetWindowRect() -> window dimensions (to filter tiny/helper windows)
        5. SendMessageTimeout() -> check if window is responsive (not hung)
        6. IsWindowVisible() -> is window shown (not minimized/hidden)?
        7. GetWindowLong(GWL_EXSTYLE) -> does it have taskbar button (WS_EX_APPWINDOW)?

    Filtering strategy:
    - We apply match_exe/match_title filters EARLY to avoid unnecessary work
    - But we still gather ALL metadata for matching windows — needed for ranking later

    Why SendMessageTimeout with 0x0000 (WM_NULL)?
    - Sends a no-op message to test if window procedure is responsive
    - Timeout: 1000ms; flags: 0x0002 (SMTO_ABORTIFHUNG) — don't wait if app is frozen
    - If the call fails/times out, responded=False -> likely a hung or background window

    Return structure:
    - List of dicts with window metadata — this becomes the single source of truth for all window ops
    - Each field is pre-computed to avoid repeated API calls in downstream functions
    """
    results = []

    def callback(hwnd, _):
        # Gather window identity
        title = _get_window_text(hwnd)  # Visible title (may be empty for hidden windows)
        pid = _get_window_pid(hwnd)  # Owning process ID
        exe = _get_exe_for_pid(pid)  # Executable filename (e.g., "chrome.exe")

        # Apply early filters to skip non-matching windows
        if match_exe and exe and exe.lower() != match_exe.lower():
            return True  # Continue enumeration (don't add to results)
        if match_title and match_title.lower() not in title.lower():
            return True

        # Gather window geometry and state
        rect = ctypes.wintypes.RECT()  # C struct: left, top, right, bottom (in screen coordinates)
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        area = (rect.right - rect.left) * (rect.bottom - rect.top)  # Pixel area

        # Test window responsiveness (critical for distinguishing real apps from helpers)
        dummy = ctypes.wintypes.DWORD()  # Output parameter for SendMessageTimeout (unused)
        responded = user32.SendMessageTimeoutW(
            hwnd,  # Target window
            0x0000,  # WM_NULL: no-op message to test responsiveness
            0, 0,  # wParam, lParam: unused for WM_NULL
            0x0002,  # SMTO_ABORTIFHUNG: return immediately if window is hung
            1000,  # Timeout: 1 second
            ctypes.byref(dummy)  # Receives result (we ignore it; care about return value)
        )

        # Determine if window should appear in taskbar (user-facing vs helper)
        appwindow = bool(user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_APPWINDOW)

        # Add to results if it passed filters
        results.append({
            "hwnd": hwnd,  # Opaque handle — use for all subsequent Win32 calls
            "title": title,  # Human-readable title
            "pid": pid,  # Process ID for process-level ops
            "exe": exe,  # Executable name for matching
            "area": area,  # Window size in pixels (filter tiny windows)
            "visible": bool(user32.IsWindowVisible(hwnd)),  # Is window shown?
            "responded": bool(responded),  # Did window procedure respond to WM_NULL?
            "appwindow": appwindow,  # Does it have a taskbar button?
        })
        return True  # Continue enumeration

    _enum_windows(callback)  # Start the enumeration
    return results


import ctypes
import ctypes.wintypes
import psutil
from typing import Optional

# ─────────────────────────────────────────
# WIN32 API BOILERPLATE & CONSTANTS
# ─────────────────────────────────────────

user32 = ctypes.windll.user32
GWL_EXSTYLE = -20
WS_EX_APPWINDOW = 0x00040000


def _enum_windows(callback):
    """Ctypes wrapper for EnumWindows."""
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    user32.EnumWindows(EnumWindowsProc(callback), 0)


def _get_window_text(hwnd) -> str:
    """Safely extract window text."""
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _get_window_pid(hwnd) -> int:
    """Get the owning PID of a window."""
    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _get_exe_for_pid(pid: int) -> str:
    """Fetch executable name from PID safely."""
    try:
        return psutil.Process(pid).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return ""


# ─────────────────────────────────────────
# WINDOW ENUMERATION — The Core Discovery Engine
# ─────────────────────────────────────────

def _iter_windows(match_exe: Optional[str] = None, match_title: Optional[str] = None):
    """
    Enumerate top-level windows with optional filtering by exe name or title substring.
    """
    results = []

    def callback(hwnd, _):
        # Gather window identity
        title = _get_window_text(hwnd)
        pid = _get_window_pid(hwnd)
        exe = _get_exe_for_pid(pid)

        # Apply early filters to skip non-matching windows
        if match_exe and exe and exe.lower() != match_exe.lower():
            return True
        if match_title and match_title.lower() not in title.lower():
            return True

        # Gather window geometry and state
        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        area = (rect.right - rect.left) * (rect.bottom - rect.top)

        # Test window responsiveness
        dummy = ctypes.wintypes.DWORD()
        responded = user32.SendMessageTimeoutW(
            hwnd, 0x0000, 0, 0, 0x0002, 1000, ctypes.byref(dummy)
        )

        # Determine if window should appear in taskbar
        appwindow = bool(user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_APPWINDOW)

        results.append({
            "hwnd": hwnd,
            "title": title,
            "pid": pid,
            "exe": exe,
            "area": area,
            "visible": bool(user32.IsWindowVisible(hwnd)),
            "responded": bool(responded),
            "appwindow": appwindow,
        })
        return True

    _enum_windows(callback)
    return results


# ─────────────────────────────────────────
# PROCESS DETECTION — Is App Running?
# ─────────────────────────────────────────

def is_running(exe_name: str, path: str = None) -> bool:
    if not exe_name and not path:
        return False

    exe_name = (exe_name or "").lower()
    path = (path or "").lower()

    for proc in psutil.process_iter(["name", "exe"]):
        try:
            pname = (proc.info["name"] or "").lower()
            pexe = (proc.info["exe"] or "").lower()

            if exe_name and pname == exe_name:
                return True

            if path and pexe and path in pexe:
                return True

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    return False


def is_running_by_path(path: str) -> bool:
    if not path:
        return False
    for proc in psutil.process_iter(["exe"]):
        try:
            if proc.info["exe"] and path.lower() in proc.info["exe"].lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False


def is_running_by_title(match_title: str) -> bool:
    if not match_title:
        return False
    target = match_title.lower()
    for w in _iter_windows():
        title = (w["title"] or "").lower()
        if target in title:
            if w["visible"] and w["responded"] and w["area"] > 10000:
                return True
    return False


def _is_uwp_running(app: dict) -> bool:
    name = (app.get("name") or "").lower()
    base = (app.get("exe_name") or "").split("!")[-1].replace(".exe", "").lower()

    return any(
        w["visible"] and w["responded"] and w["area"] > 100
        and (
                (name and name in (w["title"] or "").lower())
                or (base and base in (w["exe"] or "").lower())
        )
        for w in _iter_windows()
    )


def _extract_keywords(app):
    name = (app.get("name") or "").lower()
    exe = (app.get("exe") or app.get("exe_name") or "").lower()
    name = name.split("(")[0].strip()
    tokens = set(name.split())
    if exe:
        tokens.add(exe.replace(".exe", ""))
    return tokens


# ─────────────────────────────────────────────────────────
# AREA PROFILES (single source of truth)
# ─────────────────────────────────────────────────────────

CATEGORY_MIN_AREA = {
    "electron": 8000,
    "chromium": 10000,
    "browser": 10000,
    "web": 10000,
    "pwa": 10000,
    "uwp": 5000,
    "win32": 1000,
    "jvm_desktop": 8000,
    "dotnet_desktop": 6000,
    "game_engine": 20000,
    "native_cross_platform": 5000,
    "tray_app": 0,
    "installer": 3000,
    "console_hybrid": 4000,
}


def _get_min_area(category: str, fallback: int = 8000) -> int:
    return CATEGORY_MIN_AREA.get(category, fallback)


# ─────────────────────────────────────────────────────────
# CORE HELPERS
# ─────────────────────────────────────────────────────────

def _get_app_core_name(app: dict) -> str:
    name = (app.get("name") or "").lower()
    name = name.split("(")[0].strip()

    if "visual studio code" in name or "vscode" in name:
        return "code"
    if "microsoft edge" in name:
        return "edge"
    if "chrome" in name:
        return "chrome"

    return name


# ─────────────────────────────────────────────────────────
# SAFE WRAPPER
# ─────────────────────────────────────────────────────────

def _match_window_ready(win: dict, app: dict, category: str = None) -> bool:
    exe = (app.get("exe") or "").lower()
    name = (app.get("name") or "").lower()
    win_title = (app.get("window_title") or "").lower()
    title = (win.get("title") or "").lower()
    win_exe = (win.get("exe") or "").lower()

    matched = False

    if exe and _exe_loose_match(exe, win_exe):
        matched = True
    elif win_title and win_title in title:
        matched = True
    elif not exe and name and name in title:
        matched = True

    if not matched:
        return False

    if not win.get("visible") or not win.get("responded"):
        return False

    min_area = _get_min_area(category)
    if win.get("area", 0) < min_area:
        return False

    return True


# ─────────────────────────────────────────────────────────
# GENERIC WINDOW MATCH
# ─────────────────────────────────────────────────────────

def _check_by_window(app: dict, category: str, allow_partial=True) -> bool:
    core = _get_app_core_name(app)
    win_title = (app.get("window_title") or app.get("name") or "").lower()

    for w in _iter_windows():
        title = (w["title"] or "").lower()
        match = False

        if allow_partial and core and core in title:
            match = True
        if win_title and win_title in title:
            match = True

        if match and _match_window_ready(w, app, category):
            return True

    return False


def _exe_loose_match(app_exe: str, win_exe: str) -> bool:
    if not app_exe or not win_exe:
        return False
    app_exe = app_exe.lower()
    win_exe = win_exe.lower()
    if app_exe == win_exe:
        return True
    if app_exe in win_exe or win_exe in app_exe:
        return True
    return False


# ─────────────────────────────────────────────────────────
# SPECIALIZED CHECKS
# ─────────────────────────────────────────────────────────

def _check_browser(app: dict) -> bool:
    exe = (app.get("exe") or "").lower()
    if not exe:
        return False
    for w in _iter_windows():
        if (w["exe"] or "").lower() == exe and _match_window_ready(w, app, "browser"):
            return True
    return False


def _check_pwa(app: dict) -> bool:
    win_title = (app.get("window_title") or app.get("name") or "").lower()
    if not win_title:
        return False
    for w in _iter_windows():
        title = (w["title"] or "").lower()
        if win_title in title and _match_window_ready(w, app, "web"):
            return True
    return False


def _check_uwp(app: dict) -> bool:
    return _is_uwp_running(app)


def _check_win32(app: dict) -> bool:
    exe = app.get("exe")
    return is_running(exe)


# ─────────────────────────────────────────────────────────
# ADVANCED CHECKS
# ─────────────────────────────────────────────────────────

def _check_jvm(app: dict) -> bool:
    return _check_by_window(app, "jvm_desktop")


def _check_dotnet(app: dict) -> bool:
    return _check_by_window(app, "dotnet_desktop")


def _check_game_engine(app: dict) -> bool:
    min_area = _get_min_area("game_engine")
    for w in _iter_windows():
        if w["visible"] and w["area"] > min_area:
            return True
    return False


def _check_native_cross(app: dict) -> bool:
    return _check_by_window(app, "native_cross_platform")


def _check_tray_app(app: dict) -> bool:
    exe = app.get("exe")
    if is_running(exe):
        for w in _iter_windows():
            if (w["exe"] or "").lower() == (exe or "").lower():
                if w["visible"]:
                    return True
        return True
    return False


def _check_installer(app: dict) -> bool:
    min_area = _get_min_area("installer")
    count = 0
    for w in _iter_windows():
        if w["visible"] and w["area"] > min_area:
            count += 1
        if count >= 2:
            return True
    return False


def _check_console_hybrid(app: dict) -> bool:
    return _check_by_window(app, "console_hybrid")


# ─────────────────────────────────────────────────────────
# DISPATCHER
# ─────────────────────────────────────────────────────────

# Note: Merged the duplicate _CATEGORY_RUNNING_CHECKS dictionary
_CATEGORY_RUNNING_CHECKS = {
    "electron": lambda app: _check_by_window(app, "electron"),
    "chromium": lambda app: _check_by_window(app, "chromium"),
    "browser": _check_browser,
    "web": _check_pwa,
    "pwa": _check_pwa,
    "uwp": _check_uwp,
    "win32": _check_win32,
    "jvm_desktop": _check_jvm,
    "dotnet_desktop": _check_dotnet,
    "game_engine": _check_game_engine,
    "native_cross_platform": _check_native_cross,
    "tray_app": _check_tray_app,
    "installer": _check_installer,
    "console_hybrid": _check_console_hybrid,
}


def is_running_smart(app: dict) -> bool:
    category = (app.get("classification") or {}).get("category", "win32")
    strategy = _CATEGORY_RUNNING_CHECKS.get(category, _CATEGORY_RUNNING_CHECKS["win32"])
    return strategy(app)


# ─────────────────────────────────────────
# LAUNCH MECHANICS — Process Creation Strategies
# ─────────────────────────────────────────

READINESS_PROFILES = {
    "electron": {
        "title_min_length": 2, "min_area_px": 8000, "strip_no_window": True,
        "ignore_cli_flags": ["--type=renderer", "--type=gpu-process"], "timeout": 12
    },
    "chromium": {
        "title_min_length": 3, "min_area_px": 10000, "strip_no_window": True,
        "ignore_cli_flags": ["--type=renderer", "--type=gpu-process", "--type=crashpad"], "timeout": 15
    },
    "browser": {
        "title_min_length": 3, "min_area_px": 10000, "strip_no_window": True,
        "ignore_cli_flags": ["--type=renderer", "--type=gpu-process", "--type=crashpad"], "timeout": 15
    },
    "web": {
        "title_min_length": 2, "min_area_px": 8000, "strip_no_window": True,
        "ignore_cli_flags": ["--type=renderer", "--type=gpu-process"], "timeout": 12
    },
    "uwp": {
        "title_min_length": 0, "min_area_px": 5000, "strip_no_window": False,
        "check_dwm_uncloak": True, "timeout": 10
    },
    "win32": {
        "title_min_length": 1, "min_area_px": 1000, "strip_no_window": False, "timeout": 8
    },
    "dotnet_desktop": {
        "title_min_length": 2, "min_area_px": 6000, "strip_no_window": False,
        "timeout": 12, "grace_period": 2
    },
    "jvm_desktop": {
        "title_min_length": 2, "min_area_px": 8000, "strip_no_window": False,
        "timeout": 20, "grace_period": 5
    },
    "game_engine": {
        "title_min_length": 0, "min_area_px": 20000, "strip_no_window": False,
        "timeout": 20, "allow_fullscreen": True, "dynamic_window": True
    },
    "native_cross_platform": {
        "title_min_length": 1, "min_area_px": 5000, "strip_no_window": False, "timeout": 10
    },
    "tray_app": {
        "title_min_length": 0, "min_area_px": 0, "strip_no_window": False,
        "allow_no_window": True, "timeout": 5
    },
    "installer": {
        "title_min_length": 1, "min_area_px": 3000, "strip_no_window": False,
        "timeout": 15, "multi_window": True, "ephemeral": True
    },
    "console_hybrid": {
        "title_min_length": 0, "min_area_px": 0, "strip_no_window": False,
        "spawn_delayed_window": True, "timeout": 10
    }
}


def _popen(attempt: dict, name: str):
    """
    Launch a process using the strategy specified in `attempt`.

    Strategy dispatch:
    - shell:AppsFolder\... -> Launch via explorer.exe (required for UWP apps)
    - protocol: (spotify:, etc.) -> Launch via `cmd /C start` (uses URI handler registration)
    - file exists -> Direct execution with DETACHED|NO_WINDOW flags (silent background launch)
    - fallback -> `cmd /C start` as last resort (handles shortcuts, batch files, etc.)

    Error handling philosophy:
    - Log structured errors for observability (logger.error with context)
    - Print user-friendly messages for CLI feedback
    - Return False to signal failure; caller decides whether to retry with next strategy

    Why suppress stdout/stderr?
    - Prevent child process output from cluttering our console
    - Avoid deadlocks: if child writes to pipe and we don't read, it can block
    - Use subprocess.DEVNULL to discard output at OS level (more efficient than PIPE + ignore)
    """
    path = attempt["path"]
    args = attempt.get("args", [])
    method = attempt.get("method", "unknown")

    try:
        if path.startswith("shell:"):
            # UWP apps MUST be launched via explorer.exe with the shell URI
            # This triggers the ShellExecute API which handles AppContainer setup
            proc = subprocess.Popen(
                ["explorer.exe", path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif _is_protocol(path):
            # Protocol handlers require the `start` command to resolve the registered app
            # Empty string "" is the window title parameter for `start` (required syntax)
            proc = subprocess.Popen(
                ["cmd", "/C", "start", "", path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,  # Avoid double shell invocation; cmd.exe is explicit
            )
        elif os.path.exists(path):
            # Direct execution: most efficient for known executables.
            # Avoid CREATE_NO_WINDOW for GUI apps like browsers because it can
            # interfere with how they attach to the interactive desktop session.
            # ─────────────────────────────────────
            # DYNAMIC FLAGS BASED ON CATEGORY
            # ─────────────────────────────────────
            category = attempt.get("category", "win32")

            # Logic: NO_WINDOW causes black screens in Electron/Chromium.
            # We strip it for these categories but keep it for standard Win32 apps.
            strip_no_window = category in ("electron", "chromium", "browser", "pwa")
            flags = DETACHED if strip_no_window else (DETACHED | NO_WINDOW)

            # Direct execution with dynamic flags
            proc = subprocess.Popen(
                [path] + args,
                executable=path,
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,  # 🆕 Uses category-aware flags
            )
        else:
            # Fallback: let Windows resolve the path via `start` (handles shortcuts, associations)
            proc = subprocess.Popen(
                ["cmd", "/C", "start", "", path] + args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
        return {
            "pid": proc.pid,
            "method": method,
            "path": path,
        }  # Process creation succeeded (not necessarily that app is ready)

    except FileNotFoundError:
        print(f"  {name} -> {method} failed: not found")
        logger.error("popen_failed_not_found", app=name, method=method, path=path)
    except PermissionError:
        print(f"  {name} -> {method} failed: permission denied")
        logger.error("popen_failed_permission", app=name, method=method, path=path)
    except Exception as e:
        print(f"  {name} -> {method} failed: {e}")
        logger.error("popen_failed", app=name, method=method, error=str(e))

    return False  # Launch failed; caller should try next strategy


def _build_launch_attempts(app: dict) -> list:
    """
    Build a prioritized list of launch strategies for the given app.

    Strategy priority (most specific -> most generic):
    1. UWP: shell: URI via explorer.exe (only valid method for Store apps)
    2. PWA: shell: URI or path via explorer.exe (browser-hosted apps)
    3. Direct exe execution (fastest, most reliable for Win32)
    4. Launch by exe name alone (relies on PATH or App Paths registry)
    5. Fallback: cmd /C start (handles shortcuts, file associations, etc.)

    Why multiple attempts?
    - App config may be incomplete (e.g., missing full path but has exe name)
    - Environment may vary (PATH changes, app moved, permissions differ)
    - Graceful degradation: if direct launch fails, try shell resolution

    Return format:
    - List of dicts with "method" (for logging), "path", "args", "shell" flag
    - Caller iterates and tries each until one succeeds
    """
    path = app.get("resolved_path") or app.get("full_path")
    exe = app.get("exe_name")
    args = app.get("args", [])
    t = app.get("app_type")

    # ─────────────────────────────────────
    # INJECT CATEGORY INTO ATTEMPT
    # ─────────────────────────────────────
    # Read from root 'category' key or nested 'classification.category'
    category = app.get("category") or (app.get("classification") or {}).get("category", "win32")

    # UWP apps: only shell: URI works
    if t == "uwp":
        return [{"method": "uwp_shell", "path": path, "args": [], "shell": True, "category": category}] if path else []

    # PWA apps: launch via shell URI
    if t == "pwa":
        return [
            {"method": "pwa_shell", "path": path, "args": args, "shell": True, "category": category}] if path else []

    # Traditional Win32: try multiple strategies
    attempts = []
    if path and os.path.exists(path):
        # Pass category to the attempt dict
        attempts.append({"method": "path", "path": path, "args": args, "shell": False, "category": category})
    if exe:
        attempts.append({"method": "exe", "path": exe, "args": [], "shell": False, "category": category})
    if path:
        attempts.append({"method": "shell", "path": path, "args": args, "shell": True, "category": category})

    return attempts


# ─────────────────────────────────────────
# LAUNCH — High-Level Async API
# ─────────────────────────────────────────

async def launch(app: dict, timeout: int = 5, interval: int = 2) -> bool:
    """
    Launch an application with fallback strategies and wait for window readiness.

    Async design rationale:
    - Launching apps is I/O-bound (waiting for process start, window creation)
    - asyncio allows other tasks to run while we poll for readiness
    - timeout/interval prevent infinite hangs on unresponsive apps

    Workflow:
    1. Normalize app config -> consistent internal schema
    2. Check if already running -> if yes, just show/focus existing window (idempotent)
    3. Build launch attempts -> prioritized list of strategies
    4. Try each attempt:
        a. Spawn process via _popen()
        b. Poll is_running_smart() until success or timeout
        c. If successful, return True; else try next strategy
    5. If all fail, log error and return False

    Why wait for "running" not "window ready"?
    - Some apps spawn a process first, then create window later (e.g., updaters, launchers)
    - We separate "process launched" from "window visible" for flexibility
    - Caller can use _wait_for_window() if they need UI readiness
    """
    appl = normalize_app(app)
    name = appl["name"]
    exe = appl.get("exe_name")
    path = appl.get("resolved_path") or appl.get("full_path")
    app_type = appl.get("app_type")
    win_title = appl.get("window_title")
    # Extract the category, fallback to win32
    category = appl.get("category") or (appl.get("classification") or {}).get("category", "win32")
    profile = READINESS_PROFILES.get(category, READINESS_PROFILES["win32"])

    # Order of precedence: explicit config -> profile timeout -> default (5s)
    actual_timeout = appl.get("launch_timeout") or profile.get("timeout", timeout)
    actual_interval = appl.get("launch_interval", interval)

    logger.info("launch_start", app=name, path=path, exe=exe, args=appl.get("args"), timeout=actual_timeout)
    print(
        f"\n  Launching: {name}\n    path : {path}\n    exe  : {exe}\n    type : {app_type}\n    timeout: {actual_timeout}s")

    # Idempotency: if already running, just focus existing window
    if is_running_smart(appl):
        print(f"  {name} already running -> showing window")
        await _show(appl, app_type, exe, win_title)
        logger.info("app_already_running", app=name)
        return True

    attempts = _build_launch_attempts(appl)

    # Reorder attempts by historical success rate — most successful method tried first.
    # Failures here are non-critical: if rating store is unavailable, original order is preserved.
    try:
        if _rating_store is not None:
            attempts = _rating_store.reorder_attempts(name, attempts)
    except Exception as e:
        logger.warning("rating_reorder_failed", app=name, error=str(e))

    if not attempts:
        print(f"  {name} -> no valid launch method")
        return False

    # Try each launch strategy until one succeeds
    for attempt in attempts:
        print(f"  {name} -> trying {attempt['method']}: {attempt['path']}")
        logger.info("launch_attempt", app=name, method=attempt["method"], path=attempt["path"])

        launch_result = _popen(attempt, name)
        if not launch_result:
            continue  # Strategy failed; try next

        # Inject the PID so lvm.verify can use it!
        if isinstance(launch_result, dict) and "pid" in launch_result:
            appl["launched_pid"] = launch_result["pid"]
        # Wait for a visible, responsive UI window instead of only a process.
        # Chromium browsers often spawn helper/background processes before the
        # real top-level window is ready, which can lead to premature success.
        if await _wait_for_verified_window(appl, timeout=timeout, interval=interval):
            print(f"  {name} -> confirmed window ready")
            logger.info("launch_success", app=name)
            show_app_interactive(appl, exe, win_title)
            # Record successful method so future launches try it first.
            # Non-critical: a storage failure must never prevent a successful launch returning True.
            try:
                if _rating_store is not None:
                    print(f"  {name} -> recording success for {attempt['method']}")
                    _rating_store.record_success(name, attempt["method"])
                    print(f"  {name} -> rating recorded")
            except Exception as e:
                logger.warning("rating_record_failed", app=name, error=str(e))
                print(f"  {name} -> rating failed: {e}")
            return True

        print(f"  {name} -> {attempt['method']} timed out")
        logger.warning("launch_timeout", app=name, method=attempt["method"])

    print(f"  {name} -> all launch methods failed")
    logger.error("launch_failed_all_methods", app=name)
    return False


async def _wait_until_running(app: dict, timeout: int, interval: int) -> bool:
    """
    Poll is_running_smart() until app is detected or timeout expires.

    Why async sleep?
    - Blocking sleep would freeze the entire event loop
    - asyncio.sleep() yields control to other tasks while waiting
    - Interval trade-off: too short -> busy-wait CPU waste; too long -> slow feedback

    Timeout calculation:
    - deadline = time.time() + timeout -> absolute end time (resilient to clock skew)
    - while time.time() < deadline -> check remaining time each iteration
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_running_smart(app):
            return True
        await asyncio.sleep(interval)  # Non-blocking wait
    return False


# ─────────────────────────────────────────
# CLOSE — Graceful Shutdown with Escalation
# ─────────────────────────────────────────

async def close(app: dict, timeout: int = 10, interval: int = 1) -> bool:
    """
    Close an application gracefully, escalating to force-kill if needed.

    Graceful vs forceful:
    - Graceful: Send WM_CLOSE -> app can save state, prompt user, clean up resources
    - Forceful: taskkill /F -> immediate termination, no cleanup (risk of data loss)

    Escalation strategy:
    1. window_close: Send WM_CLOSE to all matching windows (standard graceful shutdown)
    2. pwa_pid: Terminate PIDs owning windows with matching title (for browser-hosted apps)
    3. [Optional] taskkill: Force-kill by exe name (commented out; use kill() explicitly)

    Why per-app strategy?
    - Discord: Prefers hide_by_title (minimizes to tray instead of closing)
    - PWA: No unique exe; must target by window title + PID
    - Win32: Standard WM_CLOSE works for most apps

    Polling loop:
    - After triggering close, poll _is_visible() until window disappears
    - Timeout prevents hanging on unresponsive apps
    - Escalate to next strategy if current one times out
    """
    app = normalize_app(app)
    name = app["name"]
    exe = app["exe"]
    app_type = app["type"]
    timeout = app.get("close_timeout", timeout)
    interval = app.get("close_interval", interval)

    print(f"\n  Closing: {name}")
    logger.info("close_attempt", app=name)

    # Early exit: nothing to close if not running
    if not is_running_smart(app):
        print(f"  {name} -> not running, nothing to close")
        return True

    # Build escalation strategy list based on app type
    if app_type == "pwa":
        attempts = [{"method": "pwa_pid", "fn": lambda: _close_pwa_by_pid(app)}]
    elif name.lower() == "discord":
        attempts = [{"method": "hide_by_title", "fn": lambda: hide_by_title(app)}]
    else:
        attempts = [
            {"method": "window_close", "fn": lambda: _close_by_window(app)},
            {"method": "pwa_pid", "fn": lambda: _close_pwa_by_pid(app)},
        ]

    # Try each strategy until one succeeds
    for attempt in attempts:
        method = attempt["method"]
        print(f"  {name} -> trying {method}")

        try:
            triggered = attempt["fn"]()  # Execute the close action
        except Exception as e:
            print(f"  {name} -> {method} raised: {e}")
            logger.warning(method, app=name, error=str(e))
            continue

        if not triggered:
            print(f"  {name} -> {method} found nothing, skipping")
            continue

        # Poll until window is no longer visible (or timeout)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not _is_visible(app):
                print(f"  {name} -> confirmed closed   ({method})")
                logger.info(method, app=name)
                return True
            print(f"  {name} -> waiting for exit ({interval}s)...")
            await asyncio.sleep(interval)

        print(f"  {name} -> {method} timed out, escalating")

    print(f"  {name} -> all close methods failed")
    return False


def _close_by_window(app: dict) -> bool:
    """
    Send WM_CLOSE to all windows matching the app's exe name.

    Low-level mechanics:
    - PostMessageW(hwnd, WM_CLOSE, 0, 0): Posts message to window's message queue
      - Asynchronous: returns immediately, doesn't wait for processing
      - WM_CLOSE is handled by the window procedure (WndProc) — app can ignore it
    - time.sleep(0.3): Brief pause to let app process the message
      - Not perfect: some apps take longer to react; caller's polling loop handles this
    - IsWindow(hwnd): Check if window still exists after WM_CLOSE
      - If DestroyWindow() was called, hwnd becomes invalid -> IsWindow returns False

    Why iterate all matching windows?
    - App may have multiple top-level windows (e.g., main + settings dialog)
    - We close all of them to ensure full shutdown
    """
    app = normalize_app(app)
    windows = _iter_windows(match_exe=app["exe"])
    if not windows:
        return False

    closed_any = False
    for w in windows:
        hwnd = w["hwnd"]
        if user32.PostMessageW(hwnd, WM_CLOSE, 0, 0):  # Post graceful close message
            time.sleep(0.3)  # Let app process the message (imperfect but practical)
            if not user32.IsWindow(hwnd):  # Check if window was destroyed
                closed_any = True
    return closed_any


def _is_visible(app: dict) -> bool:
    """
    Check if any window matching the app is currently visible (not closed/minimized).

    Why check both IsWindow() and IsWindowVisible()?
    - IsWindow(hwnd): Returns False if window was destroyed (handle invalid)
    - IsWindowVisible(hwnd): Returns False if window is hidden/minimized (but still exists)
    - We want to know if the user can see/interact with the window -> both must be True

    Use case:
    - Polling loop in close(): wait until all windows are gone/hidden
    - Distinguish between "closed" (destroyed) and "minimized" (still running)
    """
    app = normalize_app(app)
    exe = app["exe"]
    win_title = app.get("window_title") or app.get("name")

    return any(
        user32.IsWindow(w["hwnd"]) and user32.IsWindowVisible(w["hwnd"])
        for w in _iter_windows(match_exe=exe, match_title=win_title)
    )


def _close_pwa_by_pid(app: dict) -> bool:
    """
    Terminate processes that own windows with matching title (for PWA/browser apps).

    Why target by PID?
    - PWA apps run inside browser processes (chrome.exe, msedge.exe)
    - We can't close just the PWA via exe name (would kill entire browser)
    - Instead: find windows with matching title -> get their PIDs -> terminate only those PIDs

    Safety note:
    - We only terminate PIDs that actually own a matching window
    - Still risky: browser may multiplex multiple PWAs in one process (rare but possible)
    - Mitigation: Use narrow title matching; caller should verify app identity first

    Error handling:
    - Process may exit between window enumeration and termination -> NoSuchProcess
    - System processes may deny termination -> AccessDenied
    - We silently skip these; return True if at least one PID was targeted
    """
    window_title = app["name"]
    pids = []

    def callback(hwnd, _):
        title = _get_window_text(hwnd)
        # Case-insensitive substring match: flexible for dynamic titles
        if title and window_title.lower() in title.lower():
            pids.append(_get_window_pid(hwnd))
        return True

    _enum_windows(callback)  # Collect PIDs of windows with matching title

    # Terminate each targeted PID
    for pid in pids:
        try:
            psutil.Process(pid).terminate()  # Graceful termination (SIGTERM on Unix, WM_CLOSE on Windows)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass  # Process already gone or protected

    return bool(pids)  # True if we found and targeted at least one PID


def _taskkill(exe: str) -> bool:
    """
    Force-kill all processes with the given exe name via taskkill /F.

    Why use taskkill instead of psutil.terminate()?
    - taskkill /F: Sends TerminateProcess() at OS level — immediate, no cleanup
    - psutil.terminate(): Sends WM_CLOSE first (graceful), then TerminateProcess() after timeout
    - We want immediate force-kill here; caller explicitly requested "kill", not "close"

    Command breakdown:
    - /F: Force termination (no graceful shutdown)
    - /IM: Match by image name (exe filename)
    - Affects ALL processes with that exe name — use with caution!

    Return value:
    - True if taskkill returned 0 (success), False otherwise
    - Note: taskkill returns 0 even if no matching processes found — we don't distinguish here
    """
    result = subprocess.run(
        ["taskkill", "/F", "/IM", exe],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


# ─────────────────────────────────────────
# KILL — Immediate Force Termination
# ─────────────────────────────────────────

def kill(app: dict) -> bool:
    """
    Force-kill an application by exe name — no grace, no cleanup.

    When to use:
    - App is hung/unresponsive to WM_CLOSE
    - Testing: need to ensure clean state between runs
    - Emergency: app is misbehaving and must be stopped immediately

    Warning:
    - No chance for app to save data, release locks, or clean up temp files
    - May leave orphaned resources (mutexes, shared memory, registry keys)
    - Use only when graceful close() has failed or is inappropriate
    """
    app = normalize_app(app)
    logger.warning("kill_app", app=app["exe"])  # Log for audit trail
    return _taskkill(app["exe"])


# ─────────────────────────────────────────
# MINIMIZE / HIDE — Window State Management
# ─────────────────────────────────────────

def minimize(app: dict) -> bool:
    """
    Minimize all visible windows belonging to the app's exe name.

    Low-level mechanics:
    - Enumerate all windows, filter by exe name (via PID -> exe resolution)
    - For each matching visible window: call ShowWindow(hwnd, SW_MINIMIZE)
    - SW_MINIMIZE: Minimizes window to taskbar; activates next top-level window

    Why match by exe name, not window title?
    - Exe name is stable; window title may change dynamically (e.g., document name in title)
    - Ensures we minimize ALL windows of the app, not just one with a specific title

    Return value:
    - True if at least one window was minimized, False if none found/matched
    """
    app = normalize_app(app)
    exe_name = app["exe"]
    minimized = 0

    def callback(hwnd, _):
        nonlocal minimized
        pid = _get_window_pid(hwnd)
        exe = _get_exe_for_pid(pid)
        # Match by exe name (case-insensitive) and visibility
        if exe and exe.lower() == exe_name.lower() and user32.IsWindowVisible(hwnd):
            _show_window(hwnd, SW_MINIMIZE)
            minimized += 1
        return True

    _enum_windows(callback)
    logger.info("minimize_attempt", app=exe_name)
    return minimized > 0


def minimize_by_title(window_title: str) -> bool:
    """
    Minimize windows whose title contains the given substring.

    Use case:
    - When exe name is ambiguous (e.g., multiple chrome.exe instances)
    - Target a specific document/window within an app (e.g., "Report - Excel")

    Why substring match?
    - Window titles often include dynamic content: "Document1 - Word", "Inbox (3) - Outlook"
    - Substring match allows flexible targeting without exact title knowledge
    """
    minimized = 0

    def callback(hwnd, _):
        nonlocal minimized
        if user32.IsWindowVisible(hwnd):
            title = _get_window_text(hwnd)
            # Case-insensitive substring match
            if title and window_title.lower() in title.lower():
                _show_window(hwnd, SW_MINIMIZE)
                minimized += 1
        return True

    _enum_windows(callback)
    return minimized > 0


def hide_by_title(app: dict) -> bool:
    """
    Hide (SW_HIDE) windows whose title contains the given substring.

    SW_HIDE vs SW_MINIMIZE:
    - SW_HIDE: Removes window from screen AND taskbar; app still running
    - SW_MINIMIZE: Shows minimized window in taskbar; user can restore easily
    - Use hide_by_title for "tray-style" behavior (e.g., Discord minimize-to-tray)

    Note: Hidden windows can be restored via ShowWindow(hwnd, SW_SHOW) or SW_RESTORE.
    We don't provide a direct "unhide" because show_app() already handles restoration.
    """
    app = normalize_app(app)
    window_title = app["window_title"]
    hidden = 0

    def callback(hwnd, _):
        nonlocal hidden
        if user32.IsWindowVisible(hwnd):
            title = _get_window_text(hwnd)
            if title and window_title.lower() in title.lower():
                _show_window(hwnd, SW_HIDE)
                hidden += 1
        return True

    _enum_windows(callback)
    return hidden > 0


# ─────────────────────────────────────────
# SHOW / FOCUS — Bring Window to Foreground
# ─────────────────────────────────────────

def _match_window(win: dict, app: dict) -> bool:
    """
    Determine if a window matches the app by name, exe base, or title.

    Matching priority (first match wins):
    1. window_title: Explicit title substring match (most specific)
    2. app name: Display name in window title (e.g., "Spotify" in "Spotify • Premium")
    3. exe base: Derived exe name in window's exe path (for UWP fallback)

    Why multiple heuristics?
    - Windows have varied title formats; no single rule works for all apps
    - Fallback chain increases robustness across app types (Win32, UWP, PWA)
    """
    exe = (app.get("exe") or "").lower()
    name = (app.get("name") or "").lower()
    title = (win.get("title") or "").lower()
    win_exe = (win.get("exe") or "").lower()

    # 1. STRICT: exe must match
    if exe and exe == win_exe:
        return True

    # 2. fallback: name in title (ONLY if exe missing)
    if not exe and name and name in title:
        return True

    return False


def _rank_window(w: dict) -> int:
    """
    Score a window for "best match" selection — higher score = better candidate.

    Ranking weights (tuned empirically):
    - responded * 1000: Responsive windows are 2x more valuable than visible ones
    - visible * 500: Visible windows are preferred over hidden/minimized
    - appwindow * 200: Taskbar windows are more likely to be user-facing
    - area // 10000: Larger windows are more likely to be main app windows

    Why integer scoring?
    - Simple, fast, deterministic — no floating-point precision issues
    - Easy to adjust weights by changing multipliers
    - max() with key=_rank_window is O(n) and efficient for typical window counts (<100)
    """
    return (
            w["responded"] * 1000  # Highest priority: responsive windows
            + w["visible"] * 500  # Second: visible windows
            + w["appwindow"] * 200  # Third: has taskbar button
            + (w["area"] // 10000)  # Fourth: larger windows
    )


def _best_matching_window(app: dict, exe: Optional[str], window_title: Optional[str]):
    """
    Find the single best window to show/focus for the given app.

    Selection logic:
    1. Filter all windows via _match_window() -> candidates
    2. If no candidates: return None (caller handles "not found")
    3. If multiple candidates: pick highest-scoring via _rank_window()

    Why pick one window?
    - SetForegroundWindow() only works on one window at a time
    - User expects one window to be focused, not multiple
    - If caller needs all windows, they can use _iter_windows() directly
    """
    candidates = [w for w in _iter_windows() if _match_window(w, app)]
    return max(candidates, key=_rank_window) if candidates else None


def show_app(app: dict, exe: Optional[str] = None, window_title: Optional[str] = None) -> bool:
    """
    Restore and focus the best-matching window for the app (basic version).

    What "focus" means in Windows:
    - SetForegroundWindow(hwnd): Requests that window receive user input focus
    - BUT: Windows restricts this to prevent focus hijacking (malware prevention)
    - Restrictions: Only the foreground process can set foreground window, OR
      the process received last input event, OR the user pressed ALT (our workaround)

    This basic version does NOT use the ALT workaround — may fail if app isn't foreground.
    Use show_app_interactive() for reliable focus stealing.
    """
    best = _best_matching_window(app, exe, window_title)
    if not best:
        return False

    hwnd = best["hwnd"]
    print(f"  showing: '{best['title']}' hwnd={hwnd}")
    _show_window(hwnd, SW_RESTORE)  # Restore if minimized/maximized
    user32.SetForegroundWindow(hwnd)  # Request focus (may fail due to restrictions)
    logger.info("show_window", title=best["title"], hwnd=hwnd)
    return True


def show_app_interactive(app: dict, exe: Optional[str] = None, window_title: Optional[str] = None) -> bool:
    """
    Restore and forcefully focus the best-matching window (with ALT-key workaround).

    Focus-stealing workaround mechanics:
    1. Simulate ALT key press via SendInput() -> tricks Windows into thinking user pressed ALT
    2. Windows rule: "If ALT is pressed, next SetForegroundWindow() succeeds"
    3. Call ShowWindow(SW_RESTORE), BringWindowToTop(), SetForegroundWindow(), SetFocus()
    4. Simulate ALT key release to restore normal keyboard state

    Why SendInput() instead of keybd_event()?
    - keybd_event() is legacy; SendInput() is the modern, reliable API
    - SendInput() inserts events into the hardware input stream — harder for apps to detect as synthetic

    ctypes structure setup:
    - KEYBDINPUT: Matches C struct for keyboard input (wVk, wScan, dwFlags, etc.)
    - INPUT: Wrapper struct with type discriminator + union (we use ki field for keyboard)
    - SendInput(1, &inp, sizeof(INPUT)): Send one keyboard event
    """

    # Define C structs to match Windows API expectations
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),  # Virtual-key code (e.g., VK_MENU for ALT)
            ("wScan", ctypes.c_ushort),  # Hardware scan code (0 for VK-based input)
            ("dwFlags", ctypes.c_ulong),  # Key flags (KEYEVENTF_KEYUP for release)
            ("time", ctypes.c_ulong),  # Timestamp (0 = let system generate)
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),  # Extra info (unused)
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("ki", KEYBDINPUT)]  # type=1 for keyboard

    def send_key(vk: int, flags: int = 0):
        """Helper: send a single keyboard event via SendInput()."""
        inp = INPUT()
        inp.type = INPUT_KEYBOARD  # 1 = keyboard event
        inp.ki.wVk = vk  # Virtual-key code
        inp.ki.dwFlags = flags  # KEYEVENTF_KEYUP for release
        # SendInput returns number of events successfully inserted
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    best = _best_matching_window(app, exe, window_title)
    if not best:
        print(f"  no window found for exe={exe} title={window_title}")
        logger.warning("show_no_window_found", exe=exe, title=window_title)
        return False

    hwnd = best["hwnd"]
    print(f"  target: '{best['title']}' hwnd={hwnd}")
    logger.info("show_interactive_target", title=best["title"], hwnd=hwnd)

    # Focus workaround: simulate ALT press to bypass foreground restrictions
    send_key(VK_MENU)  # Press ALT
    time.sleep(0.05)  # Brief pause: let OS process the key event

    # Restore and focus the window
    _show_window(hwnd, SW_RESTORE)
    user32.BringWindowToTop(hwnd)  # Ensure window is at top of Z-order
    user32.SetForegroundWindow(hwnd)  # Request input focus (now allowed due to ALT)
    user32.SetFocus(hwnd)  # Set keyboard focus to this window

    send_key(VK_MENU, KEYEVENTF_KEYUP)  # Release ALT
    return True


# ─────────────────────────────────────────
# ASYNC HELPERS — Coordination Logic
# ─────────────────────────────────────────

async def _show(app: dict, app_type: Optional[str], exe: Optional[str], window_title: Optional[str]):
    """
    Async wrapper: show app window interactively, relaunch if not found.

    Fallback logic:
    - If show_app_interactive() fails (no matching window), assume app crashed/exited
    - Call _relaunch() to kill any zombie processes and start fresh
    - This makes launch() idempotent: "ensure app is running and focused"

    Error handling:
    - Catch all exceptions to prevent one failed show from crashing the entire workflow
    - Log errors for observability; print user-friendly message for CLI feedback
    """
    try:
        if not show_app_interactive(app=app, exe=exe, window_title=window_title):
            await _relaunch(app)  # Fallback: kill and restart app
    except Exception as e:
        print(f"  show failed: {e}")


async def _relaunch(app: dict) -> bool:
    """
    Force-relaunch an app: kill existing processes, wait, then launch fresh.

    Why kill before launch?
    - Ensure clean state: no zombie processes holding locks/resources
    - Avoid "already running" detection false positives
    - Guarantees fresh process tree (important for apps that don't allow multiple instances)

    Timing:
    - asyncio.sleep(1): Brief pause to let OS clean up terminated process resources
    - Too short: new process may conflict with old handles
    - Too long: user perceives delay; 1s is a practical compromise
    """
    app = normalize_app(app)
    logger.warning("relaunch_app", app=app["name"])
    print(f"  {app['name']} -> relaunching...")
    kill(app)  # Force-kill any existing instances
    await asyncio.sleep(1)  # Let OS clean up
    return await launch(app)  # Launch fresh instance


async def _wait_for_verified_window(appl, timeout=5, interval=0.5):
    import time
    import lvm

    start = time.time()

    while time.time() - start < timeout:
        try:
            result = lvm.verify({
                "title": appl.get("window_title"),
                "pid": appl.get("launched_pid"),
                "exe": appl.get("exe_name", "").replace(".exe", "").lower()
            })
        except Exception as e:
            logger.error("lvm_verify_error", error=str(e))
            result = None

        if result:
            score = result.get("score", 0)

            if score >= 0.85:
                return True

        await asyncio.sleep(interval)

    return False


# ─────────────────────────────────────────
# LAUNCH AND INTENT — High-Level Workflow
# ─────────────────────────────────────────

async def launch_and_intent(app: dict, wait: int = 5) -> bool:
    """
    Launch app, wait for UI readiness, perform implicit "intent" (close after delay).

    Use case:
    - Automated testing: launch app, let it initialize, then close to verify clean shutdown
    - Workflow automation: open app for user, auto-close after expected interaction time

    Hardcoded wait (15s):
    - Assumption: most apps are ready for interaction within 15 seconds of launch
    - Not configurable here; caller can implement custom timing with launch() + sleep + close()

    Return value:
    - Result of close() operation — did the app shut down cleanly?
    - Caller can use this to verify app stability (e.g., in CI/CD tests)
    """
    app = normalize_app(app)
    name = app["name"]
    logger.info("launch_and_intent_start", app=name)

    await launch(app)  # Launch with fallback strategies
    await _wait_for_verified_window(app)  # Wait for UI readiness
    await asyncio.sleep(15)  # Let user interact / app initialize

    result = await close(app)  # Attempt graceful shutdown
    logger.info(
        "launch_and_intent_result" if result else "launch_and_intent_success",
        app=name, success=result,
    )
    print(f"  {name} -> {'closed' if result else 'could not close'}")
    return result

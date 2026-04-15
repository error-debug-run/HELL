# control/apps.py
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
DETACHED = 0x00000008  # CREATE_DETACHED: Process has no console; runs independently
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW: Don't create a window for console apps

# ShowWindow() commands (nCmdShow parameter)
SW_HIDE = 0  # Hide window, activate another
SW_RESTORE = 9  # Restore minimized/maximized window to normal size + activate
SW_MINIMIZE = 6  # Minimize window to taskbar; activates next top-level window

# Window messaging
WM_CLOSE = 0x0010  # Standard "please close" message sent to window procedure

# SendInput() constants for keyboard simulation (focus workaround)
INPUT_KEYBOARD = 1  # Type field for INPUT structure: indicates keyboard event
KEYEVENTF_KEYUP = 0x0002  # Flag: key is being released (vs pressed)
VK_MENU = 0x12  # Virtual-key code for ALT key (used in focus-stealing workaround)

# Window style constants for filtering "real" app windows
WS_EX_APPWINDOW = 0x00040000  # Extended style: window should appear in taskbar
GWL_EXSTYLE = -20  # Index for GetWindowLong() to retrieve extended window styles

# Global handle to user32.dll — the core Win32 UI library
user32 = ctypes.windll.user32

# ─────────────────────────────────────────
# SECURITY: Blocked launch arguments
# ─────────────────────────────────────────
_BLOCKED_ARGS = {
    "--uninstall", "--uninstall-app-id", "--force-uninstall", "--remove",
    "--processstart", "--process-start", "--original-process-start-time",
    "-removeonly", "/uninstall",
}


# ─────────────────────────────────────────
# WIN32 WRAPPERS — ctypes -> C API Bridge
# ─────────────────────────────────────────

def _enum_windows(callback):
    """
    Enumerate all top-level windows on the current desktop.
    """
    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        ctypes.wintypes.HWND,
        ctypes.wintypes.LPARAM
    )
    user32.EnumWindows(WNDENUMPROC(callback), 0)


def _get_window_text(hwnd) -> str:
    """
    Retrieve the visible title text of a window.
    """
    length = user32.GetWindowTextLengthW(hwnd)
    if not length:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _get_window_pid(hwnd) -> int:
    """
    Get the Process ID that owns a window.
    """
    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _get_exe_for_pid(pid: int) -> Optional[str]:
    """
    Resolve a PID to its executable filename using psutil.
    """
    try:
        if pid > 0:
            return psutil.Process(pid).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass
    return None


def _show_window(hwnd: int, cmd: int) -> bool:
    """
    Change window state via ShowWindow(hwnd, nCmdShow).
    """
    return bool(user32.ShowWindow(hwnd, cmd))


# ─────────────────────────────────────────
# APP NORMALIZATION — Unified Data Model
# ─────────────────────────────────────────

def normalize_app(app: dict) -> dict:
    """
    Normalize heterogeneous app configurations into a consistent internal schema.
    """
    import acm

    path = (
            app.get("resolved_path")
            or app.get("full_path")
            or app.get("path")
            or ""
    )

    exe = app.get("exe") or app.get("exe_name") or os.path.basename(path)
    name = app.get("name") or exe

    if path.startswith("shell:"):
        app_type = "uwp"
    elif _is_protocol(path):
        app_type = "protocol"
    elif path.endswith(".exe") or os.path.exists(path):
        app_type = "exe"
    else:
        app_type = app.get("type", app.get("app_type", "exe"))

    classification = acm.classify_py(app)

    return {
        **app,
        "name": name,
        "exe": exe,
        "path": path,
        "args": sanitize_args(app.get("args", []), exe, name),
        "type": app_type,
        "app_type": app_type,
        "window_title": app.get("window_title", name),
        "classification": classification,
    }


# ─────────────────────────────────────────
# ARGUMENT SANITIZATION — Prevent Dangerous Launches
# ─────────────────────────────────────────

def sanitize_args(args: list, exe: str, app_name: str = "") -> list:
    """
    Filter launch arguments to block uninstall/self-modification flags.
    """
    if not args:
        return []

    cleaned = []
    for arg in args:
        a = arg.strip().lower()
        if not a:
            continue
        if a in _BLOCKED_ARGS:
            continue
        if a.startswith(("--processstart", "--process-start")):
            continue
        cleaned.append(arg)

    return cleaned


# ─────────────────────────────────────────
# PROTOCOL DETECTION — URI Scheme Handling
# ─────────────────────────────────────────

def _is_protocol(path: str) -> bool:
    """
    Detect if a path is a URI protocol handler (spotify:, ms-settings:, etc.).
    """
    return (
            ":" in path
            and not path.startswith(("C:\\", "D:\\", "\\\\"))
            and not path.startswith("shell:")
    )


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
    """
    path = attempt["path"]
    args = attempt.get("args", [])
    method = attempt.get("method", "unknown")

    try:
        if path.startswith("shell:"):
            proc = subprocess.Popen(
                ["explorer.exe", path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif _is_protocol(path):
            proc = subprocess.Popen(
                ["cmd", "/C", "start", "", path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
        elif os.path.exists(path):
            category = attempt.get("category", "win32")
            strip_no_window = category in ("electron", "chromium", "browser", "pwa")
            flags = DETACHED if strip_no_window else (DETACHED | NO_WINDOW)

            proc = subprocess.Popen(
                [path] + args,
                executable=path,
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
            )
        else:
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
        }

    except FileNotFoundError:
        print(f"  {name} -> {method} failed: not found")
        logger.error("popen_failed_not_found", app=name, method=method, path=path)
    except PermissionError:
        print(f"  {name} -> {method} failed: permission denied")
        logger.error("popen_failed_permission", app=name, method=method, path=path)
    except Exception as e:
        print(f"  {name} -> {method} failed: {e}")
        logger.error("popen_failed", app=name, method=method, error=str(e))

    return False


def _build_launch_attempts(app: dict) -> list:
    """
    Build a prioritized list of launch strategies for the given app.
    """
    path = app.get("resolved_path") or app.get("full_path")
    exe = app.get("exe_name")
    args = app.get("args", [])
    t = app.get("app_type")

    category = app.get("category") or (app.get("classification") or {}).get("category", "win32")

    if t == "uwp":
        return [{"method": "uwp_shell", "path": path, "args": [], "shell": True, "category": category}] if path else []

    if t == "pwa":
        return [
            {"method": "pwa_shell", "path": path, "args": args, "shell": True, "category": category}] if path else []

    attempts = []
    if path and os.path.exists(path):
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
    """
    appl = normalize_app(app)
    name = appl["name"]
    exe = appl.get("exe_name")
    path = appl.get("resolved_path") or appl.get("full_path")
    app_type = appl.get("app_type")
    win_title = appl.get("window_title")
    category = appl.get("category") or (appl.get("classification") or {}).get("category", "win32")
    profile = READINESS_PROFILES.get(category, READINESS_PROFILES["win32"])

    actual_timeout = appl.get("launch_timeout") or profile.get("timeout", timeout)
    actual_interval = appl.get("launch_interval", interval)

    logger.info("launch_start", app=name, path=path, exe=exe, args=appl.get("args"), timeout=actual_timeout)
    print(
        f"\n  Launching: {name}\n    path : {path}\n    exe  : {exe}\n    type : {app_type}\n    timeout: {actual_timeout}s")

    if is_running_smart(appl):
        print(f"  {name} already running -> showing window")
        await _show(appl, app_type, exe, win_title)
        logger.info("app_already_running", app=name)
        return True

    attempts = _build_launch_attempts(appl)

    try:
        if _rating_store is not None:
            attempts = _rating_store.reorder_attempts(name, attempts)
    except Exception as e:
        logger.warning("rating_reorder_failed", app=name, error=str(e))

    if not attempts:
        print(f"  {name} -> no valid launch method")
        return False

    for attempt in attempts:
        print(f"  {name} -> trying {attempt['method']}: {attempt['path']}")
        logger.info("launch_attempt", app=name, method=attempt["method"], path=attempt["path"])

        launch_result = _popen(attempt, name)
        if not launch_result:
            continue

        if isinstance(launch_result, dict) and "pid" in launch_result:
            appl["launched_pid"] = launch_result["pid"]
        if await _wait_for_verified_window(appl, timeout=timeout, interval=interval):
            print(f"  {name} -> confirmed window ready")
            logger.info("launch_success", app=name)
            show_app_interactive(appl, exe, win_title)
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
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_running_smart(app):
            return True
        await asyncio.sleep(interval)
    return False


# ─────────────────────────────────────────
# CLOSE — Graceful Shutdown with Escalation
# ─────────────────────────────────────────

async def close(app: dict, timeout: int = 10, interval: int = 1) -> bool:
    """
    Close an application gracefully, escalating to force-kill if needed.
    """
    app = normalize_app(app)
    name = app["name"]
    exe = app["exe"]
    app_type = app["type"]
    timeout = app.get("close_timeout", timeout)
    interval = app.get("close_interval", interval)

    print(f"\n  Closing: {name}")
    logger.info("close_attempt", app=name)

    if not is_running_smart(app):
        print(f"  {name} -> not running, nothing to close")
        return True

    if app_type == "pwa":
        attempts = [{"method": "pwa_pid", "fn": lambda: _close_pwa_by_pid(app)}]
    elif name.lower() == "discord":
        attempts = [{"method": "hide_by_title", "fn": lambda: hide_by_title(app)}]
    else:
        attempts = [
            {"method": "window_close", "fn": lambda: _close_by_window(app)},
            {"method": "pwa_pid", "fn": lambda: _close_pwa_by_pid(app)},
        ]

    for attempt in attempts:
        method = attempt["method"]
        print(f"  {name} -> trying {method}")

        try:
            triggered = attempt["fn"]()
        except Exception as e:
            print(f"  {name} -> {method} raised: {e}")
            logger.warning(method, app=name, error=str(e))
            continue

        if not triggered:
            print(f"  {name} -> {method} found nothing, skipping")
            continue

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
    """
    app = normalize_app(app)
    windows = _iter_windows(match_exe=app["exe"])
    if not windows:
        return False

    closed_any = False
    for w in windows:
        hwnd = w["hwnd"]
        if user32.PostMessageW(hwnd, WM_CLOSE, 0, 0):
            time.sleep(0.3)
            if not user32.IsWindow(hwnd):
                closed_any = True
    return closed_any


def _is_visible(app: dict) -> bool:
    """
    Check if any window matching the app is currently visible (not closed/minimized).
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
    """
    window_title = app["name"]
    pids = []

    def callback(hwnd, _):
        title = _get_window_text(hwnd)
        if title and window_title.lower() in title.lower():
            pids.append(_get_window_pid(hwnd))
        return True

    _enum_windows(callback)

    for pid in pids:
        try:
            psutil.Process(pid).terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    return bool(pids)


def _taskkill(exe: str) -> bool:
    """
    Force-kill all processes with the given exe name via taskkill /F.
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
    """
    app = normalize_app(app)
    logger.warning("kill_app", app=app["exe"])
    return _taskkill(app["exe"])


# ─────────────────────────────────────────
# MINIMIZE / HIDE — Window State Management
# ─────────────────────────────────────────

def minimize(app: dict) -> bool:
    """
    Minimize all visible windows belonging to the app's exe name.
    """
    app = normalize_app(app)
    exe_name = app["exe"]
    minimized = 0

    def callback(hwnd, _):
        nonlocal minimized
        pid = _get_window_pid(hwnd)
        exe = _get_exe_for_pid(pid)
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
    """
    minimized = 0

    def callback(hwnd, _):
        nonlocal minimized
        if user32.IsWindowVisible(hwnd):
            title = _get_window_text(hwnd)
            if title and window_title.lower() in title.lower():
                _show_window(hwnd, SW_MINIMIZE)
                minimized += 1
        return True

    _enum_windows(callback)
    return minimized > 0


def hide_by_title(app: dict) -> bool:
    """
    Hide (SW_HIDE) windows whose title contains the given substring.
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
    """
    exe = (app.get("exe") or "").lower()
    name = (app.get("name") or "").lower()
    title = (win.get("title") or "").lower()
    win_exe = (win.get("exe") or "").lower()

    if exe and exe == win_exe:
        return True

    if not exe and name and name in title:
        return True

    return False


def _rank_window(w: dict) -> int:
    """
    Score a window for "best match" selection — higher score = better candidate.
    """
    return (
            w["responded"] * 1000
            + w["visible"] * 500
            + w["appwindow"] * 200
            + (w["area"] // 10000)
    )


def _best_matching_window(app: dict, exe: Optional[str], window_title: Optional[str]):
    """
    Find the single best window to show/focus for the given app.
    """
    candidates = [w for w in _iter_windows() if _match_window(w, app)]
    return max(candidates, key=_rank_window) if candidates else None


def show_app(app: dict, exe: Optional[str] = None, window_title: Optional[str] = None) -> bool:
    """
    Restore and focus the best-matching window for the app (basic version).
    """
    best = _best_matching_window(app, exe, window_title)
    if not best:
        return False

    hwnd = best["hwnd"]
    print(f"  showing: '{best['title']}' hwnd={hwnd}")
    _show_window(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    logger.info("show_window", title=best["title"], hwnd=hwnd)
    return True


def show_app_interactive(app: dict, exe: Optional[str] = None, window_title: Optional[str] = None) -> bool:
    """
    Restore and forcefully focus the best-matching window (with ALT-key workaround).
    """

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("ki", KEYBDINPUT)]

    def send_key(vk: int, flags: int = 0):
        """Helper: send a single keyboard event via SendInput()."""
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.ki.wVk = vk
        inp.ki.dwFlags = flags
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    best = _best_matching_window(app, exe, window_title)
    if not best:
        print(f"  no window found for exe={exe} title={window_title}")
        logger.warning("show_no_window_found", exe=exe, title=window_title)
        return False

    hwnd = best["hwnd"]
    print(f"  target: '{best['title']}' hwnd={hwnd}")
    logger.info("show_interactive_target", title=best["title"], hwnd=hwnd)

    send_key(VK_MENU)
    time.sleep(0.05)

    _show_window(hwnd, SW_RESTORE)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.SetFocus(hwnd)

    send_key(VK_MENU, KEYEVENTF_KEYUP)
    return True


# ─────────────────────────────────────────
# ASYNC HELPERS — Coordination Logic
# ─────────────────────────────────────────

async def _show(app: dict, app_type: Optional[str], exe: Optional[str], window_title: Optional[str]):
    """
    Async wrapper: show app window interactively, relaunch if not found.
    """
    try:
        if not show_app_interactive(app=app, exe=exe, window_title=window_title):
            await _relaunch(app)
    except Exception as e:
        print(f"  show failed: {e}")


async def _relaunch(app: dict) -> bool:
    """
    Force-relaunch an app: kill existing processes, wait, then launch fresh.
    """
    app = normalize_app(app)
    logger.warning("relaunch_app", app=app["name"])
    print(f"  {app['name']} -> relaunching...")
    kill(app)
    await asyncio.sleep(1)
    return await launch(app)


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
    """
    app = normalize_app(app)
    name = app["name"]
    logger.info("launch_and_intent_start", app=name)

    await launch(app)
    await _wait_for_verified_window(app)
    await asyncio.sleep(15)

    result = await close(app)
    logger.info(
        "launch_and_intent_result" if result else "launch_and_intent_success",
        app=name, success=result,
    )
    print(f"  {name} -> {'closed' if result else 'could not close'}")
    return result
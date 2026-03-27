# control/apps.py

__all__ = [
    "launch",
    "close",
    "kill",
    "minimize",
    "hide_by_title",
]

import os
import subprocess
import time
import asyncio
import ctypes
import ctypes.wintypes

import psutil


# ─────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────

DETACHED   = 0x00000008
NO_WINDOW  = 0x08000000
SW_HIDE    = 0
SW_RESTORE = 9
SW_MINIMIZE = 6
WM_CLOSE   = 0x0010


# ─────────────────────────────────────────
# NORMALIZATION  (single definition)
# ─────────────────────────────────────────

def normalize_app(app):
    path = (
        app.get("resolved_path")
        or app.get("full_path")
        or app.get("path")
        or ""
    )

    exe = (
        app.get("exe")
        or app.get("exe_name")
        or os.path.basename(path)
    )

    name = app.get("name") or exe

    return {
        **app,
        "name":         name,
        "exe":          exe,
        "path":         path,
        "args":         sanitize_args(app.get("args", []), exe, name),
        "type":         app.get("type", app.get("app_type", "exe")),
        "window_title": app.get("window_title", name),
    }


# ─────────────────────────────────────────
# ARG SANITIZATION
# Only strips genuinely harmful launcher junk.
# Preserves legitimate args like -tab, --cd-to-home, etc.
# ─────────────────────────────────────────

# Args that are only meaningful to uninstallers / Squirrel launchers
# and must never be passed when launching normally.
_BLOCKED_ARGS = {
    "--uninstall",
    "--uninstall-app-id",
    "--force-uninstall",
    "--remove",
    "--processstart",          # Squirrel: start a sub-process
    "--process-start",
    "--original-process-start-time",
    "-removeonly",
    "/uninstall",
}

def sanitize_args(args, exe, app_name=""):
    if not args:
        return []

    cleaned = []
    skip_next = False

    for i, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue

        a = arg.strip().lower()

        if not a:
            continue

        # block known uninstall/launcher flags
        if a in _BLOCKED_ARGS:
            continue

        # block --processStart Discord.exe style (value in same token)
        if a.startswith("--processstart") or a.startswith("--process-start"):
            continue

        cleaned.append(arg)

    return cleaned


# ─────────────────────────────────────────
# PROCESS DETECTION
# ─────────────────────────────────────────

def is_running(exe_name):
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"] and \
               proc.info["name"].lower() == exe_name.lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def is_running_by_path(path):
    if not path:
        return False
    for proc in psutil.process_iter(["exe"]):
        try:
            if proc.info["exe"] and path.lower() in proc.info["exe"].lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def is_pwa_running(match_title=None):
    return bool(_iter_windows(match_title=match_title))


def is_running_smart(app):
    exe        = app["exe"]
    path       = app["path"]
    app_type   = app["type"]
    win_title  = app["window_title"]

    if app_type == "pwa" or path == "explorer.exe":
        return is_pwa_running(match_title=win_title)

    return is_running(exe) or is_running_by_path(path)


# ─────────────────────────────────────────
# POPEN  (single definition)
# Builds the subprocess command from attempt dict.
# attempt keys: method, path, args, shell
# ─────────────────────────────────────────

def _popen(attempt, name):
    path  = attempt["path"]
    args  = attempt.get("args", [])
    shell = attempt.get("shell", False)
    method = attempt["method"]

    try:
        if shell:
            # shell=True: pass as a single string so the shell handles quoting
            quoted = f'"{path}"'
            if args:
                quoted += " " + " ".join(
                    f'"{a}"' if " " in a else a for a in args
                )
            subprocess.Popen(
                quoted,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                [path] + args,
                executable=path,
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=DETACHED | NO_WINDOW,
            )
        return True

    except FileNotFoundError:
        print(f"  {name} → {method} failed: not found")
    except PermissionError:
        print(f"  {name} → {method} failed: permission denied")
    except Exception as e:
        print(f"  {name} → {method} failed: {e}")

    return False


# ─────────────────────────────────────────
# LAUNCH
# ─────────────────────────────────────────

async def launch(app, timeout=30, interval=2):
    app = normalize_app(app)

    name       = app["name"]
    exe        = app["exe"]
    path       = app["path"]
    args       = app["args"]
    app_type   = app["type"]
    win_title  = app["window_title"]

    timeout  = app.get("launch_timeout",  timeout)
    interval = app.get("launch_interval", interval)

    print(f"\n  Launching: {name}")
    print(f"    path : {path}")
    print(f"    exe  : {exe}")
    print(f"    args : {args}")

    # ── already running ───────────────────
    if is_running_smart(app):
        if name == "discord":
            print(f"\n  Relaunching Discord")
            kill(app)
        else:
            print(f"  {name} already running → showing window")
            await _show(app, app_type, exe, win_title)
            return True

    # ── build attempts ────────────────────
    attempts = []

    if app_type == "pwa":
        # PWAs launched via explorer.exe — must use shell=True
        # to avoid passing creationflags that break explorer
        if path and args:
            attempts.append({
                "method": "pwa_explorer",
                "path":   path,          # explorer.exe
                "args":   args,          # ["shell:appsFolder\\..."]
                "shell":  True,
            })

    else:
        # 1. direct path (best)
        if path and os.path.exists(path):
            attempts.append({
                "method": "path",
                "path":   path,
                "args":   args,
                "shell":  False,
            })

        # 2. exe name on PATH fallback
        if exe:
            attempts.append({
                "method": "exe",
                "path":   exe,
                "args":   [],
                "shell":  False,
            })

        # 3. shell fallback (handles edge cases)
        base = path if path else exe
        if base:
            attempts.append({
                "method": "shell",
                "path":   base,
                "args":   args,
                "shell":  True,
            })

    if not attempts:
        print(f"  {name} → no valid launch path found")
        return False

    success = False

    for attempt in attempts:
        print(f"  {name} → trying {attempt['method']}: {attempt['path']} {attempt['args']}")

        if not _popen(attempt, name):
            continue

        deadline = time.time() + timeout

        while time.time() < deadline:
            if is_running_smart(app):
                print(f"  {name} → confirmed running ✓")
                success = True
                break
            print(f"  {name} → waiting ({interval}s)...")
            await asyncio.sleep(interval)

        if success:
            break

        print(f"  {name} → {attempt['method']} timed out")

    if not success:
        print(f"  {name} → all launch methods failed")
        return False

    return True


# ─────────────────────────────────────────
# CLOSE
# ─────────────────────────────────────────

def close(app):
    name = app["name"]
    exe = app["exe"]

    # approach 1 — WM_CLOSE via window handle
    try:
        result = _close_by_window(app)
        if result:
            print(f"  {name} → closed via window ✓")
            return True
    except Exception as e:
        print(f"  {name} → window close failed: {e}")

    # approach 2 — terminate by PID
    try:
        result = _close_pwa_by_pid(app)
        if result:
            print(f"  {name} → closed via PID ✓")
            return True
    except Exception as e:
        print(f"  {name} → PID close failed: {e}")

    try:
        result = hide_by_title(app)
        if result:
            print(f"  {name} → closed via title ✓")
            return True
    except Exception as e:
        print(f"  {name} → title close failed: {e}")

    # approach 4 — taskkill force
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", exe],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print(f"  {name} → force closed ✓")
        return True
    except Exception as e:
        print(f"  {name} → taskkill failed: {e}")

    print(f"  {name} → all close methods failed")
    return False


# ─────────────────────────────────────────
# KILL
# ─────────────────────────────────────────

def kill(app):
    app      = normalize_app(app)
    exe_name = app["exe"]

    result = subprocess.run(
        ["taskkill", "/F", "/IM", exe_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


# ─────────────────────────────────────────
# MINIMIZE
# ─────────────────────────────────────────

def minimize(app):
    app      = normalize_app(app)
    exe_name = app["exe"]

    user32    = ctypes.windll.user32
    minimized = 0

    def callback(hwnd, _):
        nonlocal minimized
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            proc = psutil.Process(pid.value)
            if proc.name().lower() == exe_name.lower():
                if user32.IsWindowVisible(hwnd):
                    user32.ShowWindow(hwnd, SW_MINIMIZE)
                    minimized += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return minimized > 0


def minimize_by_title(window_title):
    user32    = ctypes.windll.user32
    minimized = 0

    def callback(hwnd, _):
        nonlocal minimized
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if window_title.lower() in buf.value.lower():
                    user32.ShowWindow(hwnd, SW_MINIMIZE)
                    minimized += 1
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return minimized > 0


# ─────────────────────────────────────────
# HIDE BY TITLE
# ─────────────────────────────────────────

def hide_by_title(app):
    app          = normalize_app(app)
    window_title = app["window_title"]

    user32 = ctypes.windll.user32
    hidden = 0

    def callback(hwnd, _):
        nonlocal hidden
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if window_title.lower() in buf.value.lower():
                    user32.ShowWindow(hwnd, SW_HIDE)
                    hidden += 1
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return hidden > 0


# ─────────────────────────────────────────
# SHOW
# ─────────────────────────────────────────

def show_app(exe=None, window_title=None):
    candidates = _iter_windows(match_exe=exe, match_title=window_title)
    if not candidates:
        return False

    best = max(candidates, key=lambda c: (
        c["responded"] * 1000 +
        c["appwindow"] * 100  +
        (not c["visible"]) * 10 +
        c["area"] // 10000
    ))

    print(f"  showing: '{best['title']}' hwnd={best['hwnd']}")
    ctypes.windll.user32.ShowWindow(best["hwnd"], SW_RESTORE)
    ctypes.windll.user32.SetForegroundWindow(best["hwnd"])
    return True


def show_app_interactive(exe=None, window_title=None):
    """Bring window to foreground using SendInput to bypass focus-steal prevention."""
    user32 = ctypes.windll.user32

    INPUT_KEYBOARD   = 1
    KEYEVENTF_KEYUP  = 0x0002
    VK_MENU          = 0x12

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk",         ctypes.c_ushort),
            ("wScan",       ctypes.c_ushort),
            ("dwFlags",     ctypes.c_ulong),
            ("time",        ctypes.c_ulong),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("ki", KEYBDINPUT)]

    def send_key(vk, flags=0):
        inp = INPUT()
        inp.type    = INPUT_KEYBOARD
        inp.ki.wVk  = vk
        inp.ki.dwFlags = flags
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    candidates = _iter_windows(match_exe=exe, match_title=window_title)
    if not candidates:
        print(f"  no window found for exe={exe} title={window_title}")
        return False

    best = max(candidates, key=lambda c: (
        c["responded"] * 1000 +
        c["appwindow"] * 100  +
        (not c["visible"]) * 10 +
        c["area"] // 10000
    ))

    hwnd = best["hwnd"]
    print(f"  target: '{best['title']}' hwnd={hwnd}")

    send_key(VK_MENU)
    time.sleep(0.05)
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    user32.SetFocus(hwnd)
    send_key(VK_MENU, KEYEVENTF_KEYUP)

    return True


async def _show(app, app_type, exe, window_title):
    try:
        if app_type == "pwa":
            show_app(window_title=window_title)
            return

        result = show_app_interactive(exe=exe, window_title=window_title)
        if not result:
            await _relaunch(app)
    except Exception as e:
        print(f"  show failed: {e}")


async def _relaunch(app):
    app  = normalize_app(app)
    name = app["name"]
    print(f"  {name} → relaunching...")
    kill(app)
    await asyncio.sleep(1)
    return await launch(app)


async def _wait_for_window(app, timeout=15, interval=1):
    """
    Wait until the app has at least one visible window, or timeout.
    Falls back gracefully — if no window appears we still proceed.
    For tray-only apps (no visible window) this will timeout and that's fine.
    """
    exe       = app["exe"]
    win_title = app["window_title"]
    app_type  = app["type"]

    deadline = time.time() + timeout

    while time.time() < deadline:
        if app_type == "pwa":
            windows = _iter_windows(match_title=win_title)
        else:
            windows = _iter_windows(match_exe=exe)

        # at least one visible, responsive window
        ready = any(w["visible"] and w["responded"] for w in windows)

        if ready:
            print(f"  {app['name']} → window ready ✓")
            return True

        await asyncio.sleep(interval)

    print(f"  {app['name']} → window wait timed out (proceeding anyway)")
    return False

# ─────────────────────────────────────────
# LAUNCH AND INTENT
# ─────────────────────────────────────────

async def launch_and_intent(app, wait=5):
    app = normalize_app(app)

    name             = app["name"]
    exe              = app["exe"]
    app_type         = app["type"]
    win_title        = app["window_title"]
    action           = app.get("action", "close")
    action_wait_time = app.get("action_wait_time", 15)

    if is_running_smart(app):
        if name == "discord":
            print(f"\n  Relaunching Discord")
            kill(app)
        else:
            print(f"  {name} already running → showing window")
            await _show(app, app_type, exe, win_title)
            return True
    else:
        launched = await launch(app)
        if not launched:
            print(f"  {name} → all launch methods failed")
            return False

    await _wait_for_window(app)

    result = close(app) or _close_pwa_by_pid(app)
    print(f"  {name} → {'closed ✓' if result else 'could not close'}")
    return result


# ─────────────────────────────────────────
# INTERNAL — WINDOW ENUMERATION
# ─────────────────────────────────────────

def _iter_windows(match_exe=None, match_title=None):
    user32  = ctypes.windll.user32
    results = []

    WS_EX_APPWINDOW = 0x00040000
    GWL_EXSTYLE     = -20

    def callback(hwnd, _):
        # title
        length = user32.GetWindowTextLengthW(hwnd)
        title  = ""
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value

        # pid → exe name
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = None
        try:
            exe = psutil.Process(pid.value).name()
        except Exception:
            pass

        # area
        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        area = (rect.right - rect.left) * (rect.bottom - rect.top)

        # apply filters
        if match_exe and exe and exe.lower() != match_exe.lower():
            return True
        if match_title and match_title.lower() not in title.lower():
            return True

        # responsiveness check (reuses pid DWORD as output buffer)
        responded = user32.SendMessageTimeoutW(
            hwnd, 0x0000, 0, 0, 0x0002, 1000, ctypes.byref(pid)
        )

        results.append({
            "hwnd":      hwnd,
            "title":     title,
            "pid":       pid.value,
            "exe":       exe,
            "area":      area,
            "visible":   bool(user32.IsWindowVisible(hwnd)),
            "responded": bool(responded),
            "appwindow": bool(user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_APPWINDOW),
        })
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return results

def _close_by_window(app):
    exe = app["exe"]
    user32 = ctypes.windll.user32
    WM_CLOSE = 0x0010

    windows = _iter_windows(match_exe=exe)

    for w in windows:
        user32.PostMessageW(w["hwnd"], WM_CLOSE, 0, 0)

    return len(windows) > 0

# find pwahelper.exe pids
# but only the one whose window title matches "Instagram"
# terminate that specific pid

def _close_pwa_by_pid(app):


    window_title = app["name"]

    user32 = ctypes.windll.user32
    pids = _iter_windows(match_exe=app["exe"], match_title=window_title)
    # terminate only the pids that own Instagram windows
    for pid in pids:
        try:
            psutil.Process(pid).terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return len(pids) > 0
# control/almost_apps.py
"""
    A file where half written and almost working app.py file is kept.
    Where upto this point of the update work the file was working correctly.
    Just paste this and work over this if any-day something breaks.


"""


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

DETACHED    = 0x00000008
NO_WINDOW   = 0x08000000
SW_HIDE     = 0
SW_RESTORE  = 9
SW_MINIMIZE = 6
WM_CLOSE    = 0x0010


# ─────────────────────────────────────────
# NORMALIZATION
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
# ─────────────────────────────────────────

_BLOCKED_ARGS = {
    "--uninstall",
    "--uninstall-app-id",
    "--force-uninstall",
    "--remove",
    "--processstart",
    "--process-start",
    "--original-process-start-time",
    "-removeonly",
    "/uninstall",
}

def sanitize_args(args, exe, app_name=""):
    if not args:
        return []

    cleaned   = []
    skip_next = False

    for arg in args:
        if skip_next:
            skip_next = False
            continue

        a = arg.strip().lower()

        if not a:
            continue

        if a in _BLOCKED_ARGS:
            continue

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
    exe       = app["exe_name"]
    path      = app["resolved_path"]
    app_type  = app["app_type"]
    win_title = app.get("window_title") or app.get("name")

    if app_type == "pwa" or path == "explorer.exe":
        return is_pwa_running(match_title=win_title)

    return is_running(exe) or is_running_by_path(path)


# ─────────────────────────────────────────
# POPEN
# ─────────────────────────────────────────

def _popen(attempt, name):
    path   = attempt["path"]
    args   = attempt.get("args", [])
    shell  = attempt.get("shell", False)
    method = attempt["method"]

    try:
        if shell:
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

    name      = app["name"]
    exe       = app["exe"]
    path      = app["path"]
    args      = app["args"]
    app_type  = app["type"]
    win_title = app["window_title"]

    timeout  = app.get("launch_timeout",  timeout)
    interval = app.get("launch_interval", interval)

    print(f"\n  Launching: {name}")
    print(f"    path : {path}")
    print(f"    exe  : {exe}")
    print(f"    args : {args}")

    # ── already running ───────────────────
    if is_running_smart(app):
        if name.lower() == "discord":
            print(f"\n  Relaunching Discord")
            await _relaunch(app)
        else:
            print(f"  {name} already running → showing window")
            await _show(app, app_type, exe, win_title)
            return True

    # ── build attempts ────────────────────
    attempts = []

    if app_type == "pwa":
        if path and args:
            attempts.append({
                "method": "pwa_explorer",
                "path":   path,
                "args":   args,
                "shell":  True,
            })
    else:
        if path and os.path.exists(path):
            attempts.append({
                "method": "path",
                "path":   path,
                "args":   args,
                "shell":  False,
            })

        if exe:
            attempts.append({
                "method": "exe",
                "path":   exe,
                "args":   [],
                "shell":  False,
            })

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
# CLOSE  (attempt loop mirrors launch)
# ─────────────────────────────────────────

async def close(app, timeout=10, interval=1):
    app = normalize_app(app)

    name      = app["name"]
    exe       = app["exe"]
    app_type  = app["type"]

    timeout  = app.get("close_timeout",  timeout)
    interval = app.get("close_interval", interval)

    print(f"\n  Closing: {name}")

    if not is_running_smart(app):
        print(f"  {name} → not running, nothing to close")
        return True

    # ── build close attempts ──────────────
    #
    # Each attempt has:
    #   method  – label for logging
    #   fn      – callable that triggers the close action, returns bool
    #             (True = action was dispatched, not necessarily closed yet)
    #
    # Graceful first, force last.
    # After each fn fires we poll is_running_smart until gone or timed out.
    # If timed out we escalate to the next attempt.

    if app_type == "pwa":
        # PWAs have no real exe to enumerate — skip window close
        attempts = [
            {
                "method": "pwa_pid",
                "fn":     lambda: _close_pwa_by_pid(app),
            },
            # {
            #     "method": "taskkill",
            #     "fn":     lambda: _taskkill(exe),
            # },
        ]
    else:
        attempts = [
            {
                "method": "window_close",       # WM_CLOSE to all matching hwnds
                "fn":     lambda: _close_by_window(app),
            },
            {
                "method": "pwa_pid",            # terminate PIDs owning windows
                "fn":     lambda: _close_pwa_by_pid(app),
            },
            # {
            #     "method": "taskkill",           # /F force kill — last resort
            #     "fn":     lambda: _taskkill(exe),
            # },
        ]

    success = False

    for attempt in attempts:
        method = attempt["method"]
        print(f"  {name} → trying {method}")

        try:
            triggered = attempt["fn"]()
        except Exception as e:
            print(f"  {name} → {method} raised: {e}")
            continue

        if not triggered:
            print(f"  {name} → {method} found nothing, skipping")
            continue

        # poll until gone or timeout
        deadline = time.time() + timeout

        while time.time() < deadline:
            if not _is_visible(app):
                print(f"  {name} → confirmed closed ✓  ({method})")
                success = True
                break
            print(f"  {name} → waiting for exit ({interval}s)...")
            await asyncio.sleep(interval)

        if success:
            break

        print(f"  {name} → {method} timed out, escalating")

    if not success:
        print(f"  {name} → all close methods failed")
        return False

    return True


def _close_by_window(app):
    app     = normalize_app(app)
    user32  = ctypes.windll.user32
    WM_CLOSE = 0x0010

    windows = _iter_windows(match_exe=app["exe"])

    if not windows:
        return False

    closed_any = False

    for w in windows:
        hwnd = w["hwnd"]

        # post close
        posted = user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)

        if not posted:
            continue

        # give app time to react
        time.sleep(0.3)  # 300ms

        # verify window disappeared
        if not user32.IsWindow(hwnd):
            closed_any = True

    return closed_any

def _is_visible(app):
    app = normalize_app(app)

    exe       = app["exe_name"]
    win_title = app.get("window_title") or app.get("name")

    user32 = ctypes.windll.user32

    windows = _iter_windows(match_exe=exe, match_title=win_title)

    for w in windows:
        hwnd = w["hwnd"]

        if user32.IsWindow(hwnd) and user32.IsWindowVisible(hwnd):
            return True

    return False


def _close_pwa_by_pid(app):

    window_title = app["name"]

    user32 = ctypes.windll.user32
    pids = []

    def callback(hwnd, _):
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value

        if window_title.lower() in title.lower():
            pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            pids.append(pid.value)
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool,
                                     ctypes.wintypes.HWND,
                                     ctypes.wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(callback), 0)

    # terminate only the pids that own Instagram windows
    for pid in pids:
        try:
            psutil.Process(pid).terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return len(pids) > 0

def _taskkill(exe):
    result = subprocess.run(
        ["taskkill", "/F", "/IM", exe],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


# ─────────────────────────────────────────
# KILL  (immediate, no confirmation loop)
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
    user32 = ctypes.windll.user32

    INPUT_KEYBOARD  = 1
    KEYEVENTF_KEYUP = 0x0002
    VK_MENU         = 0x12

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
        inp            = INPUT()
        inp.type       = INPUT_KEYBOARD
        inp.ki.wVk     = vk
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
    exe       = app["exe"]
    win_title = app["window_title"]
    app_type  = app["type"]

    deadline = time.time() + timeout

    while time.time() < deadline:
        if app_type == "pwa":
            windows = _iter_windows(match_title=win_title)
        else:
            windows = _iter_windows(match_exe=exe)

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

    name      = app["name"]
    exe       = app["exe"]
    app_type  = app["type"]
    win_title = app["window_title"]

    await launch(app)

    await _wait_for_window(app)
    await asyncio.sleep(15)

    result = await close(app)
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
        length = user32.GetWindowTextLengthW(hwnd)
        title  = ""
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value

        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = None
        try:
            exe = psutil.Process(pid.value).name()
        except Exception:
            pass

        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        area = (rect.right - rect.left) * (rect.bottom - rect.top)

        if match_exe and exe and exe.lower() != match_exe.lower():
            return True
        if match_title and match_title.lower() not in title.lower():
            return True

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



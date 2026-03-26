# control/apps.py

# PUBLIC API
__all__ = [
    "launch",
    "close",
    "kill",
    "minimize",
    "hide_by_title",
]


import subprocess
import psutil
import time
import asyncio
import ctypes
import ctypes.wintypes


# ─────────────────────────────────────────
# Core Functions OR Functions called by orchestrator.py
# ─────────────────────────────────────────

async def launch(app, timeout=30, interval=2):
    """
    Launch an app and keep trying until confirmed running.
    If already running — show it.
    Each attempt gets its own independent timeout.
    """

    name = app["name"]
    exe = app["exe"]
    path = app.get("path")
    args = app.get("args", [])
    app_type = app.get("type", "exe")
    window_title = app.get("window_title", name)
    timeout = app.get("launch_timeout", timeout)
    interval = app.get("launch_interval", interval)

    DETACHED = 0x00000008
    NO_WINDOW = 0x08000000

    # ── already running — just show it ───────────────────
    already = (
        is_pwa_running(window_title)
        if app_type == "pwa"
        else is_running(exe)
    )

    if already:
        print(f"  {name} already running → showing window")
        _show(app, app_type, exe, window_title)
        return True

    # ── build attempt chain ───────────────────────────────
    attempts = []

    if path:
        attempts.append({
            "method": "path",
            "executable": path,
            "args": args,
            "shell": False,
            "timeout": timeout,
            "interval": interval,
        })

    attempts.append({
        "method": "shell",
        "executable": " ".join([path or exe] + args),
        "args": [],
        "shell": True,
        "timeout": timeout,
        "interval": interval,
    })

    # ── try each attempt ──────────────────────────────────
    for attempt in attempts:
        launched = _popen(attempt, name, DETACHED, NO_WINDOW)
        if not launched:
            continue

        print(f"  {name} → launched via {attempt['method']}, waiting...")

        # poll until confirmed running
        attempt_start = time.time()
        while time.time() - attempt_start < attempt["timeout"]:

            running = (
                is_pwa_running(window_title)
                if app_type == "pwa"
                else is_running(exe)
            )

            if running:
                print(f"  {name} → confirmed running ✓")

                return True

            print(f"  {name} → not running yet, "
                  f"retrying in {attempt['interval']}s...")
            await asyncio.sleep(attempt["interval"])

        print(f"  {name} → timed out on "
              f"{attempt['method']} after {attempt['timeout']}s")

    print(f"  {name} → all launch methods failed")
    return False

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


def kill(app):
    """
    Kill all processes matching exe name.
    Uses taskkill which handles multi-process apps
    like Discord, Steam, Spotify cleanly.
    """

    exe_name = app["exe"]

    result = subprocess.run(
        ["taskkill", "/F", "/IM", exe_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return result.returncode == 0



def minimize(app):
    """Minimize all windows belonging to a process."""
    exe_name = app["name"]


    SW_MINIMIZE = 6

    user32 = ctypes.windll.user32
    minimized = 0

    def callback(hwnd, _):
        nonlocal minimized
        # get the process id of this window
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        # find if this pid matches our target exe
        try:
            proc = psutil.Process(pid.value)
            if proc.name().lower() == exe_name.lower():
                if user32.IsWindowVisible(hwnd):
                    user32.ShowWindow(hwnd, SW_MINIMIZE)
                    minimized += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return True

    # enumerate all open windows
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool,
                                     ctypes.wintypes.HWND,
                                     ctypes.wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return minimized > 0


def hide_by_title(app):
    """Hide a window by its title — for apps where exe doesn't own the window."""


    window_title = app["name"]

    SW_HIDE = 0
    user32 = ctypes.windll.user32
    hidden = 0

    def callback(hwnd, _):
        nonlocal hidden
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value

            if window_title.lower() in title.lower():
                user32.ShowWindow(hwnd, SW_HIDE)
                hidden += 1
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool,
                                     ctypes.wintypes.HWND,
                                     ctypes.wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return hidden > 0



# ─────────────────────────────────────────
# ─────────────────────────────────────────










# ─────────────────────────────────────────
# INTERNAL FUNCTIONS
# ─────────────────────────────────────────

def is_running(exe_name):
    """Check if a process is currently running by exe name."""
    for proc in psutil.process_iter(["name"]):
        if proc.info["name"] and \
                proc.info["name"].lower() == exe_name.lower():
            return True
    return False


def is_pwa_running(match_exe=None, match_title=None):
    """Check if a PWA is running by looking for its window title."""

    if _iter_windows(match_title):
        return True
    return False


def minimize_by_title(window_title):
    """
    Minimize a window by its title.
    Used for PWA apps where the exe hosts multiple apps
    e.g. Instagram running under pwahelper.exe
    """

    SW_MINIMIZE = 6
    user32 = ctypes.windll.user32
    minimized = 0


    return minimized > 0





def show_app_interactive(exe=None, window_title=None):
    """
    Bring window to foreground with full interactivity.
    Finds the best matching window, then uses SendInput
    to bypass Windows focus stealing prevention.
    """



    user32 = ctypes.windll.user32

    # ── constants ─────────────────────────────────────
    SW_RESTORE = 9
    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    VK_MENU = 0x12  # Alt key

    # ── input structures ──────────────────────────────
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [
            ("type", ctypes.c_ulong),
            ("ki", KEYBDINPUT),
        ]

    # ── find best matching window ──────────────────────
    candidates = _iter_windows(match_exe=exe, match_title=window_title)



    if not candidates:
        print(f"  no window found for exe={exe} title={window_title}")
        return False

    # pick best window
    best = max(candidates, key=lambda c: (
            c["responded"] * 1000 +
            c["appwindow"] * 100 +
            (not c["visible"]) * 10 +
            c["area"] // 10000
    ))

    hwnd = best["hwnd"]
    print(f"  target: '{best['title']}' "
          f"hwnd={hwnd} "
          f"responded={best['responded']} "
          f"appwindow={best['appwindow']}")

    # ── force focus via SendInput ──────────────────────
    def send_key(vk, flags=0):
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.ki.wVk = vk
        inp.ki.dwFlags = flags
        user32.SendInput(1, ctypes.byref(inp),
                         ctypes.sizeof(INPUT))

    # press Alt — Windows grants focus permission
    send_key(VK_MENU)
    time.sleep(0.05)

    # restore and focus
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    user32.SetFocus(hwnd)

    # release Alt
    send_key(VK_MENU, KEYEVENTF_KEYUP)

    return True



def show_app(exe=None, window_title=None):
    """
    Show a running app's main window.
    Filters for top level interactive windows only.
    Ignores child windows, overlays, and background workers.
    """


    SW_RESTORE = 9
    WS_OVERLAPPED = 0x00000000
    WS_CAPTION = 0x00C00000  # has title bar
    WS_SYSMENU = 0x00080000  # has system menu
    GWL_STYLE = -16
    GWL_EXSTYLE = -20
    WS_EX_APPWINDOW = 0x00040000  # shows in taskbar = main window
    WS_EX_TOOLWINDOW = 0x00000080  # tool window = skip these

    user32 = ctypes.windll.user32
    candidates = _iter_windows(match_exe=exe, match_title=window_title)




    if not candidates:
        return False

    # priority order for picking the right window:
    # 1. responds to messages + has WS_EX_APPWINDOW + hidden → main window
    # 2. responds to messages + hidden → probably main window
    # 3. largest area that responds → fallback

    def score(c):
        return (
                c["responded"] * 1000 +  # must respond
                c["appwindow"] * 100 +  # taskbar window = main
                (not c["visible"]) * 10 +  # hidden = what we want to show
                c["area"] // 10000  # bigger = more likely main
        )

    best = max(candidates, key=score)

    print(f"  showing: '{best['title']}' "
          f"hwnd={best['hwnd']} "
          f"area={best['area']} "
          f"responded={best['responded']}")

    user32.ShowWindow(best["hwnd"], SW_RESTORE)
    user32.SetForegroundWindow(best["hwnd"])
    return True





def _popen(attempt, name, DETACHED, NO_WINDOW):
    """Fire a single Popen attempt. Returns True if no exception."""
    try:
        if attempt["shell"]:
            subprocess.Popen(
                attempt["executable"],
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                [attempt["executable"]] + attempt["args"],
                executable=attempt["executable"],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=DETACHED | NO_WINDOW,
            )
        return True

    except FileNotFoundError:
        print(f"  {name} → {attempt['method']} failed: not found")
    except PermissionError:
        print(f"  {name} → {attempt['method']} failed: permission denied")
    except Exception as e:
        print(f"  {name} → {attempt['method']} failed: {e}")

    return False


async def _show(app, app_type, exe, window_title):
    """
    Show app window after confirming running.
    Tries window-based show first.
    Falls back to relaunch if window show fails.
    """
    try:
        if app_type == "pwa":
            show_app(window_title=window_title)
            return

        # try interactive show first
        result = show_app_interactive(exe=exe, window_title=window_title)

        if not result:
            # window show failed — relaunch as fallback
            await _relaunch(app)

    except Exception as e:
        print(f"  show failed: {e}")


async def _relaunch(app):
    """
    Kill and relaunch an app to bring it to foreground.
    Reuses existing kill() and launch() functions.
    """
    name = app["name"]
    exe = app["exe"]

    print(f"  {name} → relaunching...")

    # kill existing instance
    kill(app)

    # small wait for process to fully die
    await asyncio.sleep(1)

    # launch fresh — launch() already handles
    # confirmation and show_app
    return await launch(app)



async def launch_and_intent(app, wait=5):
    """
       Launch an app then close it.
       Async — all apps launch concurrently.
       app = one entry from config close_on_boot list
    """

    name = app["name"]
    exe = app["exe"]
    app_type = app.get("type", "exe")
    window_title = app.get("window_title", name)
    action = app.get("action", "close")
    action_wait_time = app.get("action_wait_time", 15)

    # check if already running
    if app_type == "pwa":
        already_running = is_pwa_running(window_title)
        _show(app, app_type, exe, window_title)
    else:
        already_running = is_running(exe)
        _show(app, app_type, exe, window_title)

    # launch if not running
    if not already_running:
        launched = await launch(app)  # ← store result, no wait needed
        if not launched:
            print(f"  {name} → all launch methods failed")
            return False
    else:
        print(f"  {name} already running")

    await asyncio.sleep(action_wait_time)

    # apply action
    if action == "hide":
        hide_by = app.get("hide_by", "exe")
        if hide_by == "title" or app_type == "pwa":
            result = hide_by_title(window_title)
        else:
            result = hide_by_title(app)
        if result:
            print(f"  {name} → hidden to tray ✓")
            return True
        else:
            print(f"  {name} → could not hide, may already be hidden")
            return True

    elif action == "minimize":
        if app_type == "pwa":
            result = minimize_by_title(window_title)
        else:
            result = minimize(exe)
        if result:
            print(f"  {name} → minimized ✓")
            return True
        else:
            print(f"  {name} → may already be in tray")
            return True

    elif action == "close":
        result = close(app)
        if result:
            print(f"  {name} → closed ✓")
            return True
        else:
            print(f"  {name} → could not close")
            return False

    elif action == "kill":
        result = kill(app)
        if result:
            print(f"  {name} → killed ✓")
            return True
        else:
            print(f"  {name} → could not kill")
            return False

    return True




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





def _iter_windows(match_exe=None, match_title=None):
    user32 = ctypes.windll.user32
    results = []

    def callback(hwnd, _):

        SW_RESTORE = 9
        GWL_STYLE = -16
        GWL_EXSTYLE = -20
        WS_CAPTION = 0x00C00000
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_APPWINDOW = 0x00040000
        INPUT_KEYBOARD = 1
        KEYEVENTF_KEYUP = 0x0002
        VK_MENU = 0x12

        # skip invisible windows without caption (probably not real windows)
        # title
        length = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value

        # pid
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

        # match
        if match_exe and exe and exe.lower() != match_exe.lower():
            return True

        if match_title and match_title.lower() not in title.lower():
            return True

        # check if window responds to messages
        responded = user32.SendMessageTimeoutW(
            hwnd, 0x0000, 0, 0,
            0x0002, 1000,
            ctypes.byref(pid)
        )

        results.append({
            "hwnd": hwnd,
            "title": title,
            "pid": pid.value,
            "exe": exe,
            "area": area,
            "visible": user32.IsWindowVisible(hwnd),
            "responded": bool(responded),
            "appwindow": bool(user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_APPWINDOW),
        })
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        ctypes.wintypes.HWND,
        ctypes.wintypes.LPARAM
    )

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return results
# ─────────────────────────────────────────
# ─────────────────────────────────────────

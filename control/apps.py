# control/apps.py

import subprocess
import psutil
import time
import asyncio


def is_running(exe_name):
    """Check if a process is currently running by exe name."""
    for proc in psutil.process_iter(["name"]):
        if proc.info["name"] and \
                proc.info["name"].lower() == exe_name.lower():
            return True
    return False


def minimize_by_title(window_title):
    """
    Minimize a window by its title.
    Used for PWA apps where the exe hosts multiple apps
    e.g. Instagram running under pwahelper.exe
    """
    import ctypes
    import ctypes.wintypes

    SW_MINIMIZE = 6
    user32 = ctypes.windll.user32
    minimized = 0

    def callback(hwnd, _):
        nonlocal minimized
        # get window title
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value

        # check if our target title is in the window title
        if window_title.lower() in title.lower():
            if user32.IsWindowVisible(hwnd):
                user32.ShowWindow(hwnd, SW_MINIMIZE)
                minimized += 1
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool,
                                     ctypes.wintypes.HWND,
                                     ctypes.wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return minimized > 0


def is_pwa_running(window_title):
    """Check if a PWA is running by looking for its window title."""
    import ctypes
    import ctypes.wintypes

    user32 = ctypes.windll.user32
    found = []

    def callback(hwnd, _):
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if window_title.lower() in title.lower():
            if user32.IsWindowVisible(hwnd):
                found.append(title)
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool,
                                     ctypes.wintypes.HWND,
                                     ctypes.wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return len(found) > 0


def launch(app):
    """
    Launch an app trying all available methods until one works.
    path provided → try exact path first
    fallback      → shell=True with exe name
    """
    import shutil

    name = app["name"]
    exe  = app["exe"]
    path = app.get("path")
    args = app.get("args", [])

    DETACHED  = 0x00000008
    NO_WINDOW = 0x08000000

    # build the attempt chain
    attempts = []

    if path:
        attempts.append({
            "method":     "path",
            "executable": path,
            "args":       args,
            "shell":      False,
        })

    # always add shell fallback as last resort
    attempts.append({
        "method":     "shell",
        "executable": exe,
        "args":       [],
        "shell":      True,
    })

    # try each method until one returns True
    for attempt in attempts:
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
                    attempt["args"],
                    executable=attempt["executable"],
                    shell=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=DETACHED | NO_WINDOW
                )
            print(f"  {name} launched via {attempt['method']}")
            return True                        # ← worked, stop trying

        except FileNotFoundError:
            print(f"  {name} → {attempt['method']} failed: not found")
        except PermissionError:
            print(f"  {name} → {attempt['method']} failed: permission denied")
        except Exception as e:
            print(f"  {name} → {attempt['method']} failed: {e}")

    # every attempt failed
    print(f"  {name} → all launch methods failed")
    return False


def minimize(exe_name):
    """Minimize all windows belonging to a process."""
    import ctypes
    import ctypes.wintypes

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


async def launch_and_close(app, wait=5):
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

    # check if already running
    if app_type == "pwa":
        already_running = is_pwa_running(window_title)
    else:
        already_running = is_running(exe)

    # launch if not running
    if not already_running:
        try:
            launch(app)
            print(f"  {name} launched")
        except Exception as e:
            print(f"  {name} failed to launch: {e}")
            return False

        # async sleep — doesn't block other apps launching
        print(f"  waiting {wait}s for {name} to open...")
        await asyncio.sleep(wait)
    else:
        print(f"  {name} already running")

    # apply action
    if action == "minimize":
        if app_type == "pwa":
            minimized = minimize_by_title(window_title)
        else:
            minimized = minimize(exe)

        if minimized:
            print(f"  {name} → minimized")
        else:
            print(f"  {name} → may already be in tray")

    elif action == "close":
        closed = close(exe)
        if closed:
            print(f"  {name} → closed")
        else:
            print(f"  {name} → could not close")

    elif action == "kill":
        killed = kill(exe)
        if killed:
            print(f"  {name} → killed")
        else:
            print(f"  {name} → could not kill")

    return True


def kill(exe_name):
    """
    Kill all processes matching exe name.
    Uses taskkill which handles multi-process apps
    like Discord, Steam, Spotify cleanly.
    """
    result = subprocess.run(
        ["taskkill", "/F", "/IM", exe_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return result.returncode == 0


def close(exe_name):
    """
    Close an app gracefully — same as clicking the X button.
    Sends WM_CLOSE to all windows of the process.
    App handles its own cleanup and shutdown.
    """
    import ctypes
    import ctypes.wintypes

    WM_CLOSE = 0x0010
    user32 = ctypes.windll.user32
    closed = 0

    def callback(hwnd, _):
        nonlocal closed
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            proc = psutil.Process(pid.value)
            if proc.name().lower() == exe_name.lower():
                if user32.IsWindowVisible(hwnd):
                    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                    closed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool,
                                     ctypes.wintypes.HWND,
                                     ctypes.wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return closed > 0



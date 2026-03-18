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


async def launch(app, timeout=30, interval=2):
    """
    Launch an app and keep trying until it's confirmed running.
    Each attempt gets its own independent timeout.
    timeout  = max seconds per attempt before trying next method
    interval = seconds between each running check
    """
    import shutil
    import time

    name = app["name"]
    exe  = app["exe"]
    path = app.get("path")
    args = app.get("args", [])
    timeout = app.get("launch_timeout", timeout)
    interval = app.get("launch_interval", interval)
    method = app.get("method")
    print(timeout, interval)

    DETACHED  = 0x00000008
    NO_WINDOW = 0x08000000

    # each attempt has its own timeout and interval
    attempts = []
    print(attempt for attempt in attempts)
    if path:
        attempts.append({
            "method":     "path",
            "executable": path,
            "args":       args,
            "shell":      False,
            "timeout":    timeout,        # ← same here
            "interval":   interval,       # ← same here
        })
    attempts.append({
        "method":     "shell",
        "executable": " ".join([path] + args),
        "args":       [],
        "shell":      True,
        "timeout": timeout,     # ← same here
        "interval": interval,   # ← same here
    })

    for attempt in attempts:
        if method == "shell":
            subprocess.Popen(
                attempt["executable"],  # exe name, shell resolves it
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif method == "path":
            subprocess.Popen(
                attempt["executable"],  # exe name, shell resolves it
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        try:
            if attempt["shell"]:
                subprocess.Popen(
                    attempt["executable"],  # exe name, shell resolves it
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
                    creationflags=DETACHED | NO_WINDOW
                )
            print(f"  {name} → launched via {attempt['method']}, waiting...")

        except FileNotFoundError:
            print(f"  {name} → {attempt['method']} failed: not found")
            continue
        except PermissionError:
            print(f"  {name} → {attempt['method']} failed: permission denied")
            continue
        except Exception as e:
            print(f"  {name} → {attempt['method']} failed: {e}")
            continue

        # each attempt gets its own fresh start time
        attempt_start = time.time()

        app_type = app.get("type", "exe")
        window_title = app.get("window_title", name)

        while time.time() - attempt_start < attempt["timeout"]:
            if app_type == "pwa":
                running = is_pwa_running(window_title)
            else:
                running = is_running(exe)

            if running:
                print(f"  {name} → confirmed running ✓")
                return True

            print(f"  {name} → not running yet, retrying in {attempt['interval']}s...")
            await asyncio.sleep(attempt["interval"])

        print(f"  {name} → timed out on {attempt['method']} after {attempt['timeout']}s")

    import time
    time.sleep(1)  # brief wait for OS to register process
    if is_running(exe):
        return True

    print(f"  {name} → process never registered after launch")
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


async def launch_and_intent(app, wait=5):
    """
       Launch an app then close it.
       Async — all apps launch concurrently.
       app = one entry from config close_on_boot list
    """


    name             = app["name"]
    exe              = app["exe"]
    app_type         = app.get("type", "exe")
    window_title     = app.get("window_title", name)
    action           = app.get("action", "close")
    action_wait_time = app.get("action_wait_time", 15)

    # check if already running
    if app_type == "pwa":
        already_running = is_pwa_running(window_title)
    else:
        already_running = is_running(exe)

    # launch if not running
    if not already_running:
        launched = await launch(app)          # ← store result, no wait needed
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
        result = kill(exe)
        if result:
            print(f"  {name} → killed ✓")
            return True
        else:
            print(f"  {name} → could not kill")
            return False

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


def close(app):
    name = app["name"]
    exe  = app["exe"]

    # approach 1 — WM_CLOSE via window handle
    try:
        result = close_by_window(app)
        if result:
            print(f"  {name} → closed via window ✓")
            return True
    except Exception as e:
        print(f"  {name} → window close failed: {e}")

    # approach 2 — terminate by PID
    try:
        result = close_pwa_by_pid(app)
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


def close_by_window(app):
    """
    Close an app gracefully — same as clicking the X button.
    Sends WM_CLOSE to all windows of the process.
    App handles its own cleanup and shutdown.
    """
    import ctypes
    import ctypes.wintypes

    exe = app["exe"]
    type = app["type"]

    WM_CLOSE = 0x0010
    user32 = ctypes.windll.user32
    closed = 0


    def callback(hwnd, _):
        nonlocal closed
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            proc = psutil.Process(pid.value)
            if proc.name().lower() == exe.lower():
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


# find pwahelper.exe pids
# but only the one whose window title matches "Instagram"
# terminate that specific pid

def close_pwa_by_pid(app):
    import ctypes
    import ctypes.wintypes

    window_title = app["name"]

    user32   = ctypes.windll.user32
    pids     = []

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

def is_window_visible(exe):
    """
    Check if the app has a visible window on screen.
    More reliable than just checking process exists.
    """
    import ctypes
    import ctypes.wintypes

    user32 = ctypes.windll.user32
    found  = []

    def callback(hwnd, _):
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            proc = psutil.Process(pid.value)
            if proc.name().lower() == exe.lower():
                if user32.IsWindowVisible(hwnd):
                    found.append(hwnd)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool,
                                      ctypes.wintypes.HWND,
                                      ctypes.wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return len(found) > 0


def is_window_responsive(exe):
    """
    Check if the app window is responding to messages.
    This means the app is fully loaded and ready.
    Not just visible — actually accepting input.
    """
    import ctypes
    import ctypes.wintypes

    user32    = ctypes.windll.user32
    SMTO_ABORTIFHUNG = 0x0002
    responsive = []

    def callback(hwnd, _):
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            proc = psutil.Process(pid.value)
            if proc.name().lower() == exe.lower():
                if user32.IsWindowVisible(hwnd):
                    # SendMessageTimeout — sends a harmless message
                    # if app responds within 2000ms → it's ready
                    # if app is still loading → it won't respond
                    result = ctypes.wintypes.DWORD()
                    responded = user32.SendMessageTimeoutW(
                        hwnd,
                        0x0000,          # WM_NULL — harmless ping
                        0, 0,
                        SMTO_ABORTIFHUNG,
                        2000,            # 2 second timeout
                        ctypes.byref(result)
                    )
                    if responded:
                        responsive.append(hwnd)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool,
                                      ctypes.wintypes.HWND,
                                      ctypes.wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return len(responsive) > 0


def hide_by_title(app):
    """Hide a window by its title — for apps where exe doesn't own the window."""
    import ctypes
    import ctypes.wintypes

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


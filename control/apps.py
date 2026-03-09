# control/apps.py

import subprocess
import psutil
import time

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
    user32      = ctypes.windll.user32
    minimized   = 0

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
    found  = []

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

def launch(app_name, exe_name):
    """Launch an app if it isn't already running."""
    if is_running(exe_name):
        print(f"  {app_name} already running")
        return True

    try:
        subprocess.Popen(
            exe_name,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print(f"  {app_name} launched")
        return True
    except Exception as e:
        print(f"  {app_name} failed to launch: {e}")
        return False

def minimize(exe_name):
    """Minimize all windows belonging to a process."""
    import ctypes
    import ctypes.wintypes

    SW_MINIMIZE = 6

    user32     = ctypes.windll.user32
    minimized  = 0

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

def launch_and_minimize(app, wait=3):
    """
    Launch an app then minimize it.
    Handles both regular exe apps and PWA apps.
    app = one entry from config minimize_on_boot list
    """
    name         = app["name"]
    exe          = app["exe"]
    app_type     = app.get("type", "exe")
    window_title = app.get("window_title", name)

    # check if already running
    if app_type == "pwa":
        already_running = is_pwa_running(window_title)
    else:
        already_running = is_running(exe)

    # launch if not running
    if not already_running:
        try:
            subprocess.Popen(
                exe,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            print(f"  {name} launched")
        except Exception as e:
            print(f"  {name} failed to launch: {e}")
            return False
        print(f"  waiting {wait}s for {name} to open...")
        time.sleep(wait)
    else:
        print(f"  {name} already running")

    # minimize
    if app_type == "pwa":
        minimized = minimize_by_title(window_title)
    else:
        minimized = minimize(exe)

    if minimized:
        print(f"  {name} minimized")
    else:
        print(f"  {name} window not found — may already be in tray")

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
    user32    = ctypes.windll.user32
    closed    = 0

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


if __name__ == "__main__":
    import psutil
    for proc in psutil.process_iter(["name", "pid", "status"]):
        if "discord" in proc.info["name"].lower():
            print(proc.info)

    print(close("Discord.exe"))
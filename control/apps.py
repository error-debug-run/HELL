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


def reopen_from_tray(app):
    """
    Reopen a tray app by launching it again.
    Most tray apps detect a second instance
    and bring the existing window to front
    instead of launching a new one.
    """
    import subprocess

    name = app["name"]
    exe = app["exe"]
    path = app.get("path")
    args = app.get("args", [])

    try:
        subprocess.Popen(
            [path] + args if path else exe,
            shell=not bool(path),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"  {name} → signaled from tray ✓")
        return True
    except Exception as e:
        print(f"  {name} → reopen failed: {e}")
        return False


def force_focus_via_input(hwnd):
    """
    Force focus to a window by simulating real user input.
    Uses SendInput to inject keystrokes — bypasses all
    Windows focus stealing prevention.
    """
    import ctypes
    import ctypes.wintypes
    import time

    user32 = ctypes.windll.user32

    # INPUT structure
    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    VK_MENU = 0x12  # Alt key

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

    def send_key(vk, flags=0):
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.ki.wVk = vk
        inp.ki.dwFlags = flags
        user32.SendInput(1, ctypes.byref(inp),
                         ctypes.sizeof(INPUT))

    # press Alt — makes Windows think user is switching
    send_key(VK_MENU)
    time.sleep(0.05)

    # show and focus the window
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)

    # release Alt
    send_key(VK_MENU, KEYEVENTF_KEYUP)

    return True


def show_app_interactive(exe=None, window_title=None):
    """
    Bring window to foreground with full interactivity.
    Finds the best matching window, then uses SendInput
    to bypass Windows focus stealing prevention.
    """
    import ctypes
    import ctypes.wintypes
    import time

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    # ── constants ─────────────────────────────────────
    SW_RESTORE = 9
    GWL_STYLE = -16
    GWL_EXSTYLE = -20
    WS_CAPTION = 0x00C00000
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_APPWINDOW = 0x00040000
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
    candidates = []

    def callback(hwnd, _):
        # top level windows only
        if user32.GetParent(hwnd) != 0:
            return True

        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)

        # skip tool windows and windows without title bar
        if exstyle & WS_EX_TOOLWINDOW:
            return True
        if not (style & WS_CAPTION):
            return True

        # get title
        title = ""
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value

        # match by title
        matched = (
                window_title and
                window_title.lower() in title.lower()
        )

        # match by exe if title didn't match
        if exe and not matched:
            pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                proc = psutil.Process(pid.value)
                if proc.name().lower() == exe.lower():
                    matched = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if not matched:
            return True

        # get window area
        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        area = (rect.right - rect.left) * (rect.bottom - rect.top)

        # check if window responds to messages
        result = ctypes.wintypes.DWORD()
        responded = user32.SendMessageTimeoutW(
            hwnd, 0x0000, 0, 0,
            0x0002, 1000,
            ctypes.byref(result)
        )

        candidates.append({
            "hwnd": hwnd,
            "title": title,
            "visible": bool(user32.IsWindowVisible(hwnd)),
            "area": area,
            "responded": bool(responded),
            "appwindow": bool(exstyle & WS_EX_APPWINDOW),
        })
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool,
                                     ctypes.wintypes.HWND,
                                     ctypes.wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(callback), 0)

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


def restore_from_tray(exe):
    """
    Restore an app that manages its own tray icon.
    Simulates clicking the tray icon.
    """
    import ctypes
    import ctypes.wintypes

    WM_SYSCOMMAND = 0x0112
    SC_RESTORE = 0xF120
    user32 = ctypes.windll.user32

    def callback(hwnd, _):
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            proc = psutil.Process(pid.value)
            if proc.name().lower() == exe.lower():
                # send restore system command
                user32.PostMessageW(hwnd, WM_SYSCOMMAND, SC_RESTORE, 0)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool,
                                     ctypes.wintypes.HWND,
                                     ctypes.wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(callback), 0)


def click_tray_icon(app_name):
    """
    Find and click an app's system tray icon.
    This is exactly what the user does manually —
    simulates the mouse click on the tray icon.
    Works even when window is SW_HIDE.
    """
    import ctypes
    import ctypes.wintypes

    user32 = ctypes.windll.user32
    TB_GETBUTTON = 0x417
    TB_BUTTONCOUNT = 0x418
    WM_LBUTTONDBLCLK = 0x0203

    # find the tray toolbar window
    tray_wnd = user32.FindWindowW("Shell_TrayWnd", None)
    notify_wnd = user32.FindWindowExW(tray_wnd, None,
                                      "TrayNotifyWnd", None)
    toolbar = user32.FindWindowExW(notify_wnd, None,
                                   "ToolbarWindow32", None)

    if not toolbar:
        # try overflow tray (hidden icons area)
        overflow = user32.FindWindowW(
            "NotifyIconOverflowWindow", None)
        toolbar = user32.FindWindowExW(overflow, None,
                                       "ToolbarWindow32", None)

    if not toolbar:
        return False

    # get button count
    count = user32.SendMessageW(toolbar, TB_BUTTONCOUNT, 0, 0)
    print(f"  tray icons found: {count}")

    # get tray window process
    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(toolbar, ctypes.byref(pid))

    # open tray process for memory reading
    PROCESS_ALL_ACCESS = 0x1F0FFF
    kernel32 = ctypes.windll.kernel32
    h_process = kernel32.OpenProcess(
        PROCESS_ALL_ACCESS, False, pid.value
    )

    if not h_process:
        return False

    # allocate memory in tray process to read button data
    TBBUTTON_SIZE = 32
    remote_buf = kernel32.VirtualAllocEx(
        h_process, None,
        TBBUTTON_SIZE,
        0x3000,  # MEM_COMMIT | MEM_RESERVE
        0x04  # PAGE_READWRITE
    )

    found = False

    for i in range(count):
        # tell toolbar to write button i to remote buffer
        user32.SendMessageW(toolbar, TB_GETBUTTON, i, remote_buf)

        # read button data from tray process memory
        local_buf = ctypes.create_string_buffer(TBBUTTON_SIZE)
        bytes_read = ctypes.c_size_t(0)
        kernel32.ReadProcessMemory(
            h_process, remote_buf,
            local_buf, TBBUTTON_SIZE,
            ctypes.byref(bytes_read)
        )

        # get button rect to find where to click
        rect = ctypes.wintypes.RECT()
        user32.SendMessageW(
            toolbar,
            0x433,  # TB_GETITEMRECT
            i,
            ctypes.addressof(rect)
        )

        # calculate click point center
        x = (rect.left + rect.right) // 2
        y = (rect.top + rect.bottom) // 2

        # get tooltip text to identify the icon
        tooltip_buf = ctypes.create_unicode_buffer(256)
        user32.SendMessageW(
            toolbar,
            0x41F,  # TB_GETINFOTIPW
            i,
            ctypes.addressof(tooltip_buf)
        )
        tooltip = tooltip_buf.value.lower()

        print(f"  tray [{i}]: '{tooltip}' at ({x},{y})")

        if app_name.lower() in tooltip:
            print(f"  clicking tray icon for {app_name}...")
            # simulate double click on tray icon
            import win32api
            import win32con
            win32api.SendMessage(
                toolbar,
                WM_LBUTTONDBLCLK,
                0,
                (y << 16) | x
            )
            found = True
            break

    # cleanup
    kernel32.VirtualFreeEx(h_process, remote_buf, 0, 0x8000)
    kernel32.CloseHandle(h_process)

    return found


def show_app(exe=None, window_title=None):
    """
    Show a running app's main window.
    Filters for top level interactive windows only.
    Ignores child windows, overlays, and background workers.
    """
    import ctypes
    import ctypes.wintypes

    SW_RESTORE = 9
    WS_OVERLAPPED = 0x00000000
    WS_CAPTION = 0x00C00000  # has title bar
    WS_SYSMENU = 0x00080000  # has system menu
    GWL_STYLE = -16
    GWL_EXSTYLE = -20
    WS_EX_APPWINDOW = 0x00040000  # shows in taskbar = main window
    WS_EX_TOOLWINDOW = 0x00000080  # tool window = skip these

    user32 = ctypes.windll.user32
    candidates = []

    def callback(hwnd, _):
        # must be top level — no parent
        if user32.GetParent(hwnd) != 0:
            return True

        # get styles
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)

        # skip tool windows — these are overlays and helpers
        if exstyle & WS_EX_TOOLWINDOW:
            return True

        # must have a caption (title bar) — real app windows do
        if not (style & WS_CAPTION):
            return True

        matched = False
        title = ""

        # get title
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value

        # match by window title
        if window_title and window_title.lower() in title.lower():
            matched = True

        # match by exe
        if exe and not matched:
            pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                proc = psutil.Process(pid.value)
                if proc.name().lower() == exe.lower():
                    matched = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if matched:
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            area = (rect.right - rect.left) * \
                   (rect.bottom - rect.top)
            visible = user32.IsWindowVisible(hwnd)

            # check if window responds to messages
            # SendMessageTimeout with WM_NULL
            result = ctypes.wintypes.DWORD()
            responded = user32.SendMessageTimeoutW(
                hwnd, 0x0000, 0, 0,
                0x0002,  # SMTO_ABORTIFHUNG
                1000,
                ctypes.byref(result)
            )

            candidates.append({
                "hwnd": hwnd,
                "title": title,
                "visible": visible,
                "area": area,
                "responded": bool(responded),
                "appwindow": bool(exstyle & WS_EX_APPWINDOW),
            })

        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool,
                                     ctypes.wintypes.HWND,
                                     ctypes.wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(callback), 0)

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
    Launch an app and keep trying until confirmed running.
    If already running — show it.
    Each attempt gets its own independent timeout.
    """
    import time

    name         = app["name"]
    exe          = app["exe"]
    path         = app.get("path")
    args         = app.get("args", [])
    app_type     = app.get("type", "exe")
    window_title = app.get("window_title", name)
    timeout      = app.get("launch_timeout",  timeout)
    interval     = app.get("launch_interval", interval)


    DETACHED  = 0x00000008
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
            "method":     "path",
            "executable": path,
            "args":       args,
            "shell":      False,
            "timeout":    timeout,
            "interval":   interval,
        })

    attempts.append({
        "method":     "shell",
        "executable": " ".join([path or exe] + args),
        "args":       [],
        "shell":      True,
        "timeout":    timeout,
        "interval":   interval,
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
                _show(app, app_type, exe, window_title)
                return True

            print(f"  {name} → not running yet, "
                  f"retrying in {attempt['interval']}s...")
            await asyncio.sleep(attempt["interval"])

        print(f"  {name} → timed out on "
              f"{attempt['method']} after {attempt['timeout']}s")

    print(f"  {name} → all launch methods failed")
    return False


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


def _show(app, app_type, exe, window_title):
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
            relaunch(app)

    except Exception as e:
        print(f"  show failed: {e}")


async def relaunch(app):
    """
    Kill and relaunch an app to bring it to foreground.
    Reuses existing kill() and launch() functions.
    """
    name = app["name"]
    exe  = app["exe"]

    print(f"  {name} → relaunching...")

    # kill existing instance
    kill(exe)

    # small wait for process to fully die
    await asyncio.sleep(1)

    # launch fresh — launch() already handles
    # confirmation and show_app
    return await launch(app)


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

    name = app["name"]
    exe = app["exe"]
    app_type = app.get("type", "exe")
    window_title = app.get("window_title", name)
    action = app.get("action", "close")
    action_wait_time = app.get("action_wait_time", 15)

    # check if already running
    if app_type == "pwa":
        already_running = is_pwa_running(window_title)
    else:
        already_running = is_running(exe)

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
    exe = app["exe"]

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


def is_window_visible(exe):
    """
    Check if the app has a visible window on screen.
    More reliable than just checking process exists.
    """
    import ctypes
    import ctypes.wintypes

    user32 = ctypes.windll.user32
    found = []

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

    user32 = ctypes.windll.user32
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
                        0x0000,  # WM_NULL — harmless ping
                        0, 0,
                        SMTO_ABORTIFHUNG,
                        2000,  # 2 second timeout
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


if __name__ == "__main__":
    import psutil

    for proc in psutil.process_iter(["name", "pid", "status"]):
        if "steam" in proc.info["name"].lower():
            print(proc.info)

    app = {
        "name": "Discord",
        "exe": "Discord.exe",
        "path": "C:\\Users\\Admin\\AppData\\Local\\Discord\\Update.exe",
        "args": [
          "--processStart Discord.exe"
        ],
        "type": "exe",
        "action": "close",
        "action_wait_time": 15,
        "launch_timeout": 5,
        "launch_interval": 2,
        "method": "shell",
        "reopen": "no"
      }

    print(is_window_responsive("steamwebhelper.exe") or is_window_visible("steamwebhelper.exe"))
    # close(app)
    # close(app)
    asyncio.run(launch(app))

    # import psutil
    # import time
    #
    # # run for 20 seconds, print everything discord related
    # start = time.time()
    # while time.time() - start < 20:
    #     for proc in psutil.process_iter(["name", "pid", "status"]):
    #         if any(x in proc.info["name"].lower()
    #                for x in ["discord", "update"]):
    #             print(f"{time.time() - start:.1f}s  {proc.info}")
    #     time.sleep(1)
    #     print("---")

    # for proc in psutil.process_iter(["name", "pid", "status"]):
    #     if "pwahelper" in proc.info["name"].lower():
    #         print(proc.info)

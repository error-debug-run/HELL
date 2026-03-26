import psutil


# ─────────────────────────────────────────
# UNUSED FUNCTIONS IN control/apps.py
# ─────────────────────────────────────────


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



# ─────────────────────────────────────────
# ─────────────────────────────────────────
"""Thin ctypes helpers for Windows: DPI awareness, window rects, click-through."""
import ctypes
import logging
import sys

log = logging.getLogger(__name__)
IS_WIN = sys.platform == "win32"

if IS_WIN:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi")

    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetParent.restype = wintypes.HWND
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumChildWindows.argtypes = [wintypes.HWND, WNDENUMPROC, wintypes.LPARAM]

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011
DWMWA_EXTENDED_FRAME_BOUNDS = 9
GA_ROOT = 2

# Chromium browsers (Chrome, Edge, Brave, Opera, Vivaldi, Coc Coc) expose the page area as this child window
CHROMIUM_CONTENT_CLASS = "Chrome_RenderWidgetHostHWND"


def set_dpi_awareness():
    """Must run before Tk or mss create any window, so all coordinates are physical pixels."""
    if not IS_WIN:
        return
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def get_dpi_for_window(hwnd) -> int:
    if not IS_WIN or not hwnd:
        return 96
    try:
        dpi = user32.GetDpiForWindow(wintypes.HWND(hwnd))
        return dpi or 96
    except Exception:
        return 96


def foreground_window():
    if not IS_WIN:
        return None
    return user32.GetForegroundWindow()


def root_window(hwnd):
    if not IS_WIN or not hwnd:
        return hwnd
    return user32.GetAncestor(hwnd, GA_ROOT) or hwnd


def _rect(r) -> tuple[int, int, int, int]:
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def window_rect(hwnd):
    """Visible window bounds without the invisible resize border."""
    r = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS,
                                    ctypes.byref(r), ctypes.sizeof(r)) == 0:
        return _rect(r)
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return _rect(r)


def client_rect(hwnd):
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, r.right - r.left, r.bottom - r.top


def class_name(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def find_content_child(hwnd):
    """Largest visible Chromium page-content child window, or None."""
    best = [None, 0]

    def cb(child, _lp):
        try:
            if user32.IsWindowVisible(child) and class_name(child) == CHROMIUM_CONTENT_CLASS:
                r = wintypes.RECT()
                user32.GetWindowRect(child, ctypes.byref(r))
                area = max(0, r.right - r.left) * max(0, r.bottom - r.top)
                if area > best[1]:
                    best[0], best[1] = (r.left, r.top, r.right - r.left, r.bottom - r.top), area
        except Exception:
            pass
        return True

    user32.EnumChildWindows(hwnd, WNDENUMPROC(cb), 0)
    return best[0]


def capture_rect_for_window(hwnd, top_crop_logical: int = 0):
    """Return ((x, y, w, h), dpi) in physical pixels for the page area of hwnd."""
    hwnd = root_window(hwnd)
    if user32.IsIconic(hwnd):
        raise RuntimeError("Window is minimized")
    dpi = get_dpi_for_window(hwnd)
    rect = find_content_child(hwnd)
    if rect and rect[2] > 100 and rect[3] > 100:
        return rect, dpi
    x, y, w, h = client_rect(hwnd)
    if w <= 0 or h <= 0:
        x, y, w, h = window_rect(hwnd)
    crop = int(round(top_crop_logical * dpi / 96))
    if 0 < crop < h - 100:
        y, h = y + crop, h - crop
    return (x, y, w, h), dpi


def make_overlay_window(hwnd, exclude_from_capture: bool = True):
    """Make a Tk toplevel click-through, hidden from Alt+Tab and never focused."""
    if not IS_WIN or not hwnd:
        return
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
    try:
        # Windows 10 2004+: WDA_EXCLUDEFROMCAPTURE hides the window from every screenshot,
        # WDA_NONE (0) lets Print Screen / Snipping Tool see it
        user32.SetWindowDisplayAffinity(wintypes.HWND(hwnd), WDA_EXCLUDEFROMCAPTURE if exclude_from_capture else 0)
    except Exception:
        pass


def cursor_pos():
    """Mouse position in physical screen px, or None."""
    if not IS_WIN:
        return None
    pt = wintypes.POINT()
    if user32.GetCursorPos(ctypes.byref(pt)):
        return pt.x, pt.y
    return None


def window_from_point(x, y):
    """Top-level window under a screen point (physical px)."""
    if not IS_WIN:
        return None
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    return root_window(user32.WindowFromPoint(wintypes.POINT(int(x), int(y))))


def is_own_window(hwnd) -> bool:
    """True for any window of this process (toolbar, font picker, dialogs, overlay)."""
    if not IS_WIN or not hwnd:
        return False
    import os
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return pid.value == os.getpid()


def process_name(hwnd) -> str:
    """Executable name of the process owning hwnd, lower-case (e.g. 'chrome.exe')."""
    if not IS_WIN or not hwnd:
        return ""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(520)
        size = wintypes.DWORD(520)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value.replace("/", "\\").rsplit("\\", 1)[-1].lower()
        return ""
    finally:
        kernel32.CloseHandle(h)


SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x1, 0x2, 0x10, 0x40
HWND_TOPMOST = -1


def show_no_activate(hwnd):
    """Show a window topmost without taking keyboard focus from the browser."""
    user32.ShowWindow(wintypes.HWND(hwnd), SW_SHOWNOACTIVATE)
    user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0,
                        SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_SHOWWINDOW)


def hide_window(hwnd):
    user32.ShowWindow(wintypes.HWND(hwnd), SW_HIDE)


def set_foreground(hwnd):
    try:
        user32.SetForegroundWindow(wintypes.HWND(hwnd))
    except Exception:
        pass


def set_capture_excluded(hwnd, excluded: bool):
    """Hide a window from every screen capture (OBS, Print Screen, our own OCR) or show it to them."""
    if not IS_WIN or not hwnd:
        return
    try:
        user32.SetWindowDisplayAffinity(wintypes.HWND(hwnd), WDA_EXCLUDEFROMCAPTURE if excluded else 0)
    except Exception:
        pass


def make_toolbar_window(hwnd, exclude_from_capture: bool = True):
    """Clickable but never focused (the browser keeps the keyboard), no taskbar entry,
    and invisible to screenshots so it never gets OCR'd."""
    if not IS_WIN or not hwnd:
        return
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
    set_capture_excluded(hwnd, exclude_from_capture)


def point_on_screen(x, y) -> bool:
    """True if the point lies on any connected monitor (saved positions may be stale)."""
    if not IS_WIN:
        return True
    user32.MonitorFromPoint.restype = wintypes.HANDLE
    user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    return bool(user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), 0))  # MONITOR_DEFAULTTONULL


def virtual_screen():
    """(x, y, w, h) covering all monitors, physical px."""
    if not IS_WIN:
        return None
    g = user32.GetSystemMetrics
    return g(76), g(77), g(78), g(79)  # SM_X/YVIRTUALSCREEN, SM_CX/CYVIRTUALSCREEN


def work_area(x, y):
    """(left, top, right, bottom) of the monitor work area (without the taskbar) at a point."""
    if IS_WIN:
        try:
            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
            user32.MonitorFromPoint.restype = wintypes.HANDLE
            user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
            mon = user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), 2)  # nearest
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
                r = mi.rcWork
                return r.left, r.top, r.right, r.bottom
        except Exception:
            pass
    import tkinter
    root = tkinter._default_root
    if root is not None:
        return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()
    return 0, 0, 1920, 1080


def dpi_for_point(x, y) -> int:
    if not IS_WIN:
        return 96
    try:
        user32.MonitorFromPoint.restype = wintypes.HANDLE
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        mon = user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), 2)  # MONITOR_DEFAULTTONEAREST
        dx, dy = wintypes.UINT(), wintypes.UINT()
        if ctypes.windll.shcore.GetDpiForMonitor(mon, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0:
            return dx.value or 96
    except Exception:
        pass
    return 96


def system_light_theme() -> bool:
    """True when the Windows taskbar / system UI uses the light theme."""
    if not IS_WIN:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return bool(winreg.QueryValueEx(k, "SystemUsesLightTheme")[0])
    except OSError:
        return False


def tk_toplevel_hwnd(widget):
    """Real top-level HWND of a Tk Toplevel (winfo_id is the inner child)."""
    if not IS_WIN:
        return None
    return user32.GetParent(widget.winfo_id()) or widget.winfo_id()

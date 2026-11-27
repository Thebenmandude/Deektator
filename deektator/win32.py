"""Windows keyboard state and a non-activating recording indicator."""

import ctypes
from ctypes import wintypes


class MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("monitor", wintypes.RECT),
        ("work", wintypes.RECT),
        ("flags", wintypes.DWORD),
    ]


def bind(library, name, result, *arguments):
    function = getattr(library, name)
    function.restype = result
    function.argtypes = arguments
    return function


class DesktopAPI:
    def __init__(self):
        user = ctypes.WinDLL("user32", use_last_error=True)
        hwnd, dword, uint = wintypes.HWND, wintypes.DWORD, wintypes.UINT
        integer, boolean, handle = ctypes.c_int, wintypes.BOOL, wintypes.HANDLE

        self.key_state = bind(user, "GetAsyncKeyState", wintypes.SHORT, integer)
        self.foreground = bind(user, "GetForegroundWindow", hwnd)
        self.monitor = bind(user, "MonitorFromWindow", handle, hwnd, dword)
        self.monitor_info = bind(user, "GetMonitorInfoW", boolean, handle, ctypes.POINTER(MonitorInfo))
        self.dpi = bind(user, "GetDpiForSystem", uint)
        bind(user, "SetProcessDPIAware", boolean)()

        self.create = bind(
            user, "CreateWindowExW", hwnd,
            dword, wintypes.LPCWSTR, wintypes.LPCWSTR, dword,
            integer, integer, integer, integer, hwnd, handle, handle, ctypes.c_void_p,
        )
        self.set_opacity = bind(user, "SetLayeredWindowAttributes", boolean, hwnd, dword, wintypes.BYTE, dword)
        self.position = bind(user, "SetWindowPos", boolean, hwnd, hwnd, integer, integer, integer, integer, uint)
        self.destroy_window = bind(user, "DestroyWindow", boolean, hwnd)
        message = bind(user, "SendMessageW", wintypes.LPARAM, hwnd, uint, wintypes.WPARAM, wintypes.LPARAM)
        gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        font = bind(gdi, "GetStockObject", handle, integer)(17)  # DEFAULT_GUI_FONT
        self.set_font = lambda window: message(window, 0x0030, font, 1)  # WM_SETFONT

    def key_down(self, key):
        return bool(self.key_state(key) & 0x8000)


class DictationChord:
    def __init__(self, key_down):
        self.key_down = key_down
        self.armed = False
        self.active = False

    def poll(self):
        alt = self.key_down(0x12)  # VK_MENU
        windows = self.key_down(0x5B) or self.key_down(0x5C)  # VK_LWIN, VK_RWIN
        if not alt and not windows:
            self.armed = True
        held = self.armed and alt and windows
        if held != self.active:
            self.active = held
            return held
        return None


class RecordingIndicator:
    def __init__(self, desktop):
        self.desktop = desktop
        self.window = None

    def show(self):
        area = MonitorInfo()
        area.size = ctypes.sizeof(area)
        monitor = self.desktop.monitor(self.desktop.foreground(), 2)  # MONITOR_DEFAULTTONEAREST
        if not self.desktop.monitor_info(monitor, ctypes.byref(area)):
            raise ctypes.WinError(ctypes.get_last_error())
        scale = self.desktop.dpi() / 96 or 1
        width, height = round(160 * scale), round(38 * scale)
        x = (area.work.left + area.work.right - width) // 2
        y = area.work.bottom - height - round(16 * scale)

        if not self.window:
            # NOACTIVATE, TOOLWINDOW, LAYERED and TRANSPARENT keep the badge out of input and Alt+Tab.
            styles = 0x08000000 | 0x00000080 | 0x00080000 | 0x00000020
            # WS_POPUP, WS_BORDER, SS_CENTER and SS_CENTERIMAGE.
            self.window = self.desktop.create(
                styles, "STATIC", "Recording", 0x80000000 | 0x00800000 | 0x0001 | 0x0200,
                x, y, width, height, None, None, None, None,
            )
            if not self.window:
                raise ctypes.WinError(ctypes.get_last_error())
            self.desktop.set_font(self.window)
            if not self.desktop.set_opacity(self.window, 0, 250, 2):  # LWA_ALPHA
                error = ctypes.WinError(ctypes.get_last_error())
                self.close()
                raise error
        # HWND_TOPMOST, SWP_NOACTIVATE | SWP_SHOWWINDOW.
        if not self.desktop.position(self.window, wintypes.HWND(-1), x, y, width, height, 0x0010 | 0x0040):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.window:
            self.desktop.destroy_window(self.window)
            self.window = None

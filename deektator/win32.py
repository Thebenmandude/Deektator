"""Windows keyboard state and a non-activating recording indicator."""

import ctypes
from ctypes import wintypes

from .settings import MODIFIER_KEYS, SHORTCUT_KEYS, ShortcutSettings


class MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("monitor", wintypes.RECT),
        ("work", wintypes.RECT),
        ("flags", wintypes.DWORD),
    ]


class KeyInput(ctypes.Structure):
    _fields_ = [("virtual_key", wintypes.WORD), ("scan", wintypes.WORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("extra_info", ctypes.c_size_t)]


class MouseInput(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG),
                ("mouse_data", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("extra_info", ctypes.c_size_t)]


class InputUnion(ctypes.Union):
    # SendInput requires the full INPUT size, including its largest union member.
    _fields_ = [("keyboard", KeyInput), ("mouse", MouseInput)]


class Input(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("data", InputUnion)]


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
        self.send_input = bind(user, "SendInput", uint, uint, ctypes.POINTER(Input), integer)
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
        self.set_window_text = bind(user, "SetWindowTextW", boolean, hwnd, wintypes.LPCWSTR)
        message = bind(user, "SendMessageW", wintypes.LPARAM, hwnd, uint, wintypes.WPARAM, wintypes.LPARAM)
        gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        font = bind(gdi, "GetStockObject", handle, integer)(17)  # DEFAULT_GUI_FONT
        self.set_font = lambda window: message(window, 0x0030, font, 1)  # WM_SETFONT

    def key_down(self, key):
        return bool(self.key_state(key) & 0x8000)

    def paste(self):
        # Send Ctrl+V to the currently focused control. Clipboard text is set by
        # the desktop before this call, so apps receive ordinary paste input.
        events = (Input * 4)(
            Input(1, InputUnion(keyboard=KeyInput(0x11, 0, 0, 0, 0))),
            Input(1, InputUnion(keyboard=KeyInput(0x56, 0, 0, 0, 0))),
            Input(1, InputUnion(keyboard=KeyInput(0x56, 0, 2, 0, 0))),
            Input(1, InputUnion(keyboard=KeyInput(0x11, 0, 2, 0, 0))),
        )
        return self.send_input(len(events), events, ctypes.sizeof(Input)) == len(events)


class DictationChord:
    def __init__(self, key_down, settings=None):
        self.key_down = key_down
        self.settings = settings or ShortcutSettings()
        self.reset()

    def reset(self):
        self.armed = False
        self.active = False

    def poll(self):
        pressed = {name for name, keys in MODIFIER_KEYS.items() if any(self.key_down(key) for key in keys)}
        required = set(self.settings.modifiers)
        key_down = self.settings.key is not None and self.key_down(SHORTCUT_KEYS[self.settings.key])
        if not pressed.intersection(required) and not key_down:
            self.armed = True
        held = self.settings.enabled and self.armed and pressed == required and (self.settings.key is None or key_down)
        if held != self.active:
            self.active = held
            if not held:
                self.armed = not pressed.intersection(required) and not key_down
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

    def set_text(self, value):
        if self.window and not self.desktop.set_window_text(self.window, value):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.window:
            self.desktop.destroy_window(self.window)
            self.window = None

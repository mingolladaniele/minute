"""The main window: a plain Win32 window hosting WebView2 through the webview C library (webview/webview 0.12).

No .NET in the way: pywebview reached WebView2 through WinForms and pythonnet, about a second of every start.
The page talks to Python as it did with pywebview: window.pywebview.api.<method>(...) returns a promise, and
the "pywebviewready" event fires once the bridge is there.
"""
import ctypes
import json
import logging
import os
import threading
from collections import deque
from ctypes import wintypes as wt

from minute import config

log = logging.getLogger(__name__)

DLL_DIR = config.RESOURCES / "vendor" / "webview"

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32")
shell32 = ctypes.WinDLL("shell32")

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
user32.DefWindowProcW.argtypes = (wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.argtypes = (wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID)
user32.CreateWindowExW.restype = wt.HWND
user32.LoadImageW.argtypes = (wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT)
user32.LoadImageW.restype = wt.HANDLE
user32.SetWindowPos.argtypes = (wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT)
user32.MoveWindow.argtypes = (wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.BOOL)
user32.MonitorFromWindow.restype = wt.HANDLE
user32.GetMonitorInfoW.argtypes = (wt.HANDLE, ctypes.c_void_p)
user32.SetWindowLongW.argtypes = (wt.HWND, ctypes.c_int, wt.LONG)
user32.SetLayeredWindowAttributes.argtypes = (wt.HWND, wt.DWORD, ctypes.c_ubyte, wt.DWORD)
user32.PostMessageW.argtypes = (wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
user32.GetSystemMetricsForDpi.argtypes = (ctypes.c_int, wt.UINT)
user32.ScreenToClient.argtypes = (wt.HWND, ctypes.c_void_p)
for _name in ("ShowWindow", "SetFocus", "DestroyWindow", "IsIconic", "IsZoomed", "SetForegroundWindow",
              "UpdateWindow", "GetClientRect", "GetDpiForWindow", "MonitorFromWindow"):
    _fn = getattr(user32, _name)
    _fn.argtypes = {"ShowWindow": (wt.HWND, ctypes.c_int), "GetClientRect": (wt.HWND, ctypes.c_void_p),
                    "MonitorFromWindow": (wt.HWND, wt.DWORD)}.get(_name, (wt.HWND,))

WS_OVERLAPPEDWINDOW = 0x00CF0000
CW_USEDEFAULT = -0x80000000
WM_DESTROY, WM_SIZE, WM_ACTIVATE, WM_SETFOCUS, WM_CLOSE, WM_GETMINMAXINFO, WM_DPICHANGED = 0x2, 0x5, 0x6, 0x7, 0x10, 0x24, 0x2E0
WM_NCCALCSIZE, WM_NCHITTEST, WM_SYSCOMMAND = 0x83, 0x84, 0x112
HTCLIENT, HTTOP, HTTOPLEFT, HTTOPRIGHT = 1, 12, 13, 14
SC_MINIMIZE, SC_MAXIMIZE, SC_CLOSE, SC_RESTORE = 0xF020, 0xF030, 0xF060, 0xF120
SM_CYFRAME, SM_CXPADDEDBORDER = 33, 92
SWP_NOSIZE, SWP_NOMOVE, SWP_FRAMECHANGED = 0x1, 0x2, 0x20
TOP_EDGE = 6  # px at 100%: the strip above the page that still resizes the window from the top
SW_HIDE, SW_SHOW, SW_RESTORE = 0, 5, 9
GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TOOLWINDOW, LWA_ALPHA = -20, 0x80000, 0x80, 0x2
SWP_NOZORDER, SWP_NOACTIVATE = 0x4, 0x10
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
SM_CXICON, SM_CXSMICON = 11, 49
MONITOR_DEFAULTTONEAREST = 2
IDC_ARROW = 32512
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
WEBVIEW_NATIVE_HANDLE_KIND_UI_WIDGET, WEBVIEW_NATIVE_HANDLE_KIND_BROWSER_CONTROLLER = 1, 2

# What pywebview set up for the page: no browser shortcuts (reload, print, find), menus or dev tools,
# no text selection outside fields, and the bridge's ready event.
INIT_JS = """
window.pywebview = {api: {}};
for (const name of %s) window.pywebview.api[name] = (...args) => window.__minute_api(name, args);
window.addEventListener("DOMContentLoaded", () => {
  if (%s) document.documentElement.classList.add("frameless");
  const css = document.createElement("style");
  css.textContent = "body { user-select: none; cursor: default; }";
  document.head.appendChild(css);
  window.dispatchEvent(new Event("pywebviewready"));
});
"""


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON)]


class MINMAXINFO(ctypes.Structure):
    _fields_ = [("ptReserved", wt.POINT), ("ptMaxSize", wt.POINT), ("ptMaxPosition", wt.POINT),
                ("ptMinTrackSize", wt.POINT), ("ptMaxTrackSize", wt.POINT)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]


DISPATCH_FN = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)
BIND_FN = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p)


def _load_webview():
    os.add_dll_directory(str(DLL_DIR))  # WebView2Loader.dll sits next to webview.dll
    lib = ctypes.CDLL(str(DLL_DIR / "webview.dll"))
    c_void_p, c_char_p, c_int = ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int
    lib.webview_create.restype = c_void_p
    lib.webview_get_native_handle.restype = c_void_p
    for name, args in {"create": (c_int, c_void_p), "destroy": (c_void_p,), "run": (c_void_p,),
                       "terminate": (c_void_p,), "dispatch": (c_void_p, DISPATCH_FN, c_void_p),
                       "get_native_handle": (c_void_p, c_int), "navigate": (c_void_p, c_char_p),
                       "init": (c_void_p, c_char_p), "eval": (c_void_p, c_char_p),
                       "bind": (c_void_p, c_char_p, BIND_FN, c_void_p),
                       "return": (c_void_p, c_char_p, c_int, c_char_p)}.items():
        getattr(lib, f"webview_{name}").argtypes = args
    return lib


def _com_call(obj, index, *args, argtypes=()):
    """Call method `index` of a COM interface pointer; returns the HRESULT."""
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtable[index])
    return fn(obj, *args)


def _guid(text):
    g = (ctypes.c_byte * 16)()
    ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
    return g


def _release(obj):
    if obj:
        _com_call(obj, 2)


def _lock_down(controller):
    """The WebView2 settings pywebview applied: no browser accelerator keys, context menu, dev tools or status bar.
    ICoreWebView2Controller.get_CoreWebView2 (25), ICoreWebView2.get_Settings (3), then ICoreWebView2Settings."""
    core, settings, settings3 = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    try:
        if _com_call(controller, 25, ctypes.byref(core), argtypes=(ctypes.c_void_p,)) or not core:
            return
        if _com_call(core, 3, ctypes.byref(settings), argtypes=(ctypes.c_void_p,)) or not settings:
            return
        for index in (10, 12, 14):  # put_IsStatusBarEnabled, put_AreDevToolsEnabled, put_AreDefaultContextMenusEnabled
            _com_call(settings, index, 0, argtypes=(wt.BOOL,))
        iid = _guid("{FDB5AB74-AF33-4854-84F0-0A631DEB5EBA}")  # ICoreWebView2Settings3
        if not _com_call(settings, 0, ctypes.byref(iid), ctypes.byref(settings3),
                         argtypes=(ctypes.c_void_p, ctypes.c_void_p)):
            _com_call(settings3, 24, 0, argtypes=(wt.BOOL,))  # put_AreBrowserAcceleratorKeysEnabled
    finally:
        for obj in (settings3, settings, core):
            _release(obj)


def _enable_drag_regions(controller):
    """CSS app-region: drag moves the window, as a title bar does (WebView2 runtime 123 or later).
    ICoreWebView2Settings9.put_IsNonClientRegionSupportEnabled (38). True when the runtime has it."""
    core, settings, settings9 = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    try:
        if _com_call(controller, 25, ctypes.byref(core), argtypes=(ctypes.c_void_p,)) or not core:
            return False
        if _com_call(core, 3, ctypes.byref(settings), argtypes=(ctypes.c_void_p,)) or not settings:
            return False
        iid = _guid("{0528A73B-E92D-49F4-927A-E547DDDAA37D}")  # ICoreWebView2Settings9
        if _com_call(settings, 0, ctypes.byref(iid), ctypes.byref(settings9),
                     argtypes=(ctypes.c_void_p, ctypes.c_void_p)) or not settings9:
            return False
        return _com_call(settings9, 38, 1, argtypes=(wt.BOOL,)) == 0
    finally:
        for obj in (settings9, settings, core):
            _release(obj)


def pick_folder(owner, start=None):
    """The Windows folder picker (IFileOpenDialog with FOS_PICKFOLDERS); the chosen path, or None."""
    ole32.CoInitializeEx(None, 0x2)  # apartment threaded, as the dialog wants
    dialog, item, start_item, path = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_wchar_p()
    iid_item = _guid("{43826D1E-E718-42EE-BC55-A1E261C37BFE}")
    try:
        if ole32.CoCreateInstance(ctypes.byref(_guid("{DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7}")), None, 1,
                                  ctypes.byref(_guid("{D57C7288-D4AD-4768-BE02-9D969532D960}")),
                                  ctypes.byref(dialog)):
            return None
        _com_call(dialog, 9, 0x20 | 0x40, argtypes=(wt.DWORD,))  # SetOptions: FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM
        if start and not shell32.SHCreateItemFromParsingName(ctypes.c_wchar_p(str(start)), None,
                                                             ctypes.byref(iid_item), ctypes.byref(start_item)):
            _com_call(dialog, 12, start_item, argtypes=(ctypes.c_void_p,))  # SetFolder
        if _com_call(dialog, 3, owner, argtypes=(wt.HWND,)):  # Show; cancelled is an error HRESULT
            return None
        if _com_call(dialog, 20, ctypes.byref(item), argtypes=(ctypes.c_void_p,)):  # GetResult
            return None
        if _com_call(item, 5, 0x80058000, ctypes.byref(path), argtypes=(ctypes.c_int, ctypes.c_void_p)):
            return None  # GetDisplayName(SIGDN_FILESYSPATH)
        result = path.value
        ole32.CoTaskMemFree(path)
        return result
    finally:
        for obj in (item, start_item, dialog):
            _release(obj)


class Window:
    """Created on the main thread, which then runs it with run(). Everything else is safe from any thread."""

    def __init__(self, title, size, min_size, dark, icon, hidden=False, on_closing=lambda: True):
        self.on_closing = on_closing  # () -> bool: False keeps the window (minute hides to the tray)
        self.min_size = min_size
        self.frameless = False  # the page draws the title bar: set once WebView2 can drag the window
        self._w = None
        self._widget = None
        self._controller = None
        self._queue = deque()
        self._callbacks = []  # ctypes callbacks must outlive their use

        try:
            user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        except AttributeError:  # before Windows 10 1703
            user32.SetProcessDPIAware()
        background = config.background(dark)
        # WebView2 paints this until the page does. (Its profile, kept between starts, is the webview
        # library's choice: %APPDATA%\<exe name>, which WEBVIEW2_USER_DATA_FOLDER doesn't override.)
        os.environ["WEBVIEW2_DEFAULT_BACKGROUND_COLOR"] = "FF" + background.lstrip("#")
        rgb = int(background.lstrip("#"), 16)
        hinst = kernel32.GetModuleHandleW(None)
        big = user32.LoadImageW(None, str(icon), IMAGE_ICON, user32.GetSystemMetrics(SM_CXICON),
                                user32.GetSystemMetrics(SM_CXICON), LR_LOADFROMFILE)
        small = user32.LoadImageW(None, str(icon), IMAGE_ICON, user32.GetSystemMetrics(SM_CXSMICON),
                                  user32.GetSystemMetrics(SM_CXSMICON), LR_LOADFROMFILE)
        self._wndproc = WNDPROC(self._proc)
        wc = WNDCLASSEXW(cbSize=ctypes.sizeof(WNDCLASSEXW), lpfnWndProc=self._wndproc, hInstance=hinst,
                         hIcon=big, hIconSm=small, hCursor=user32.LoadCursorW(None, IDC_ARROW),
                         hbrBackground=gdi32.CreateSolidBrush((rgb & 0xFF) << 16 | (rgb & 0xFF00) | rgb >> 16),
                         lpszClassName="MinuteWindow")
        user32.RegisterClassExW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(0, "MinuteWindow", title, WS_OVERLAPPEDWINDOW, CW_USEDEFAULT,
                                           CW_USEDEFAULT, 100, 100, None, None, hinst, None)
        value = ctypes.c_int(int(dark))
        ctypes.WinDLL("dwmapi").DwmSetWindowAttribute(self.hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                                                      ctypes.byref(value), ctypes.sizeof(value))
        self._centre(*size)
        self._hidden = hidden
        if hidden:
            # WebView2 won't start in a window that was never shown (SW_SHOWNOACTIVATE isn't enough either):
            # until it has, the window is shown fully transparent and off the taskbar.
            user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, WS_EX_LAYERED | WS_EX_TOOLWINDOW)
            user32.SetLayeredWindowAttributes(self.hwnd, 0, 0, LWA_ALPHA)
            user32.ShowWindow(self.hwnd, SW_SHOW)
        else:
            user32.ShowWindow(self.hwnd, SW_SHOW)
            user32.UpdateWindow(self.hwnd)

    def _scale(self):
        return user32.GetDpiForWindow(self.hwnd) / 96

    def _centre(self, width, height):
        s = self._scale()
        w, h = round(width * s), round(height * s)
        info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        user32.GetMonitorInfoW(user32.MonitorFromWindow(self.hwnd, MONITOR_DEFAULTTONEAREST), ctypes.byref(info))
        work = info.rcWork
        user32.SetWindowPos(self.hwnd, None, work.left + (work.right - work.left - w) // 2,
                            work.top + (work.bottom - work.top - h) // 2, w, h, SWP_NOZORDER | SWP_NOACTIVATE)

    # --- running ---------------------------------------------------------------
    def run(self, url, api):
        """Load the page and run the window's message loop until destroy(). `api`: its public methods are
        window.pywebview.api.* in the page, each call on its own thread as with pywebview."""
        lib = self._lib = _load_webview()
        self._w = lib.webview_create(0, ctypes.byref(wt.HWND(self.hwnd)))
        if not self._w:
            raise RuntimeError("WebView2 could not start: is the Microsoft Edge WebView2 Runtime installed?")
        if self._hidden:
            user32.ShowWindow(self.hwnd, SW_HIDE)
            user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, 0)
        self._widget = lib.webview_get_native_handle(self._w, WEBVIEW_NATIVE_HANDLE_KIND_UI_WIDGET)
        self._fit_widget()
        controller = lib.webview_get_native_handle(self._w, WEBVIEW_NATIVE_HANDLE_KIND_BROWSER_CONTROLLER)
        if controller:
            self._controller = controller
            try:
                _lock_down(controller)
            except OSError:
                log.exception("could not apply the WebView2 settings")
            try:
                self.frameless = _enable_drag_regions(controller)
            except OSError:
                log.exception("could not enable drag regions: keeping the Windows title bar")
            if self.frameless:  # recompute the frame without the caption (WM_NCCALCSIZE)
                user32.SetWindowPos(self.hwnd, None, 0, 0, 0, 0,
                                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        names = [n for n in dir(api) if not n.startswith("_") and callable(getattr(api, n))]
        on_call = BIND_FN(lambda seq, req, _arg: self._call(api, seq, req))
        on_dispatch = DISPATCH_FN(lambda _w, _arg: self._pump())
        self._on_dispatch = on_dispatch
        self._callbacks += [on_call, on_dispatch]
        lib.webview_bind(self._w, b"__minute_api", on_call, None)
        lib.webview_init(self._w, (INIT_JS % (json.dumps(names), json.dumps(self.frameless))).encode())
        lib.webview_navigate(self._w, url.encode())
        lib.webview_run(self._w)
        w, self._w = self._w, None
        lib.webview_destroy(w)

    def _call(self, api, seq, req):
        name, args = json.loads(req)

        def work():
            try:
                result, status = json.dumps(getattr(api, name)(*args), ensure_ascii=False, default=str), 0
            except Exception as e:  # the page's promise rejects instead of waiting forever
                log.exception("api call %s failed", name)
                result, status = json.dumps(str(e)), 1
            self._dispatch(lambda: self._w and self._lib.webview_return(self._w, seq, status, result.encode()))

        threading.Thread(target=work, name=f"minute-api-{name}", daemon=True).start()

    def _dispatch(self, fn):
        """Run fn on the window's thread, where the web view must be driven."""
        if not self._w:
            return
        self._queue.append(fn)
        self._lib.webview_dispatch(self._w, self._on_dispatch, None)

    def _pump(self):
        while self._queue:
            try:
                self._queue.popleft()()
            except Exception:
                log.exception("window task failed")

    def _top_edge(self):
        """Without the caption, the top resize border is a strip of the window above the page."""
        return round(TOP_EDGE * self._scale()) if self.frameless and not user32.IsZoomed(self.hwnd) else 0

    def _fit_widget(self):
        if self._widget:
            r = wt.RECT()
            user32.GetClientRect(self.hwnd, ctypes.byref(r))
            top = self._top_edge()
            user32.MoveWindow(self._widget, 0, top, r.right, r.bottom - top, True)

    # --- from any thread -----------------------------------------------------------
    def evaluate_js(self, script):
        self._dispatch(lambda: self._w and self._lib.webview_eval(self._w, script.encode()))

    def show(self):
        user32.ShowWindow(self.hwnd, SW_RESTORE if user32.IsIconic(self.hwnd) else SW_SHOW)
        user32.SetForegroundWindow(self.hwnd)

    def hide(self):
        user32.ShowWindow(self.hwnd, SW_HIDE)

    def control(self, action):
        """The page's title bar buttons: "min", "max" (maximize or restore), "close" (as the X: on_closing decides)."""
        command = {"min": SC_MINIMIZE, "close": SC_CLOSE,
                   "max": SC_RESTORE if user32.IsZoomed(self.hwnd) else SC_MAXIMIZE}[action]
        user32.PostMessageW(self.hwnd, WM_SYSCOMMAND, command, 0)

    def destroy(self):
        self._dispatch(lambda: user32.DestroyWindow(self.hwnd))

    # --- window procedure ------------------------------------------------------------
    def _proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_CLOSE:
            if self.on_closing():
                user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            if self._w:
                self._lib.webview_terminate(self._w)
            return 0
        if msg == WM_SIZE:
            self._fit_widget()
            if self.frameless:
                self.evaluate_js(f"document.documentElement.classList.toggle('maximized', {str(wparam == 2).lower()})")
            return 0
        if msg == WM_NCCALCSIZE and wparam and self.frameless:
            # Keep the side and bottom borders Windows computes; drop the caption. Maximized, the window
            # overhangs the screen by its frame, so the top moves in by as much as the sides do.
            r = ctypes.cast(lparam, ctypes.POINTER(wt.RECT)).contents
            top = r.top
            user32.DefWindowProcW(hwnd, msg, wparam, lparam)
            r.top = top
            if user32.IsZoomed(hwnd):
                dpi = user32.GetDpiForWindow(hwnd)
                r.top += user32.GetSystemMetricsForDpi(SM_CYFRAME, dpi) + user32.GetSystemMetricsForDpi(SM_CXPADDEDBORDER, dpi)
            return 0
        if msg == WM_NCHITTEST and self.frameless:
            hit = user32.DefWindowProcW(hwnd, msg, wparam, lparam)
            if hit != HTCLIENT:
                return hit
            p = wt.POINT(ctypes.c_short(lparam & 0xFFFF).value, ctypes.c_short(lparam >> 16 & 0xFFFF).value)
            user32.ScreenToClient(hwnd, ctypes.byref(p))
            if p.y >= self._top_edge():
                return hit
            r = wt.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(r))
            corner = round(16 * self._scale())
            return HTTOPLEFT if p.x < corner else HTTOPRIGHT if p.x >= r.right - corner else HTTOP
        if msg in (WM_SETFOCUS, WM_ACTIVATE) and self._controller and (msg == WM_SETFOCUS or wparam & 0xFFFF):
            # Keyboard to the page: ICoreWebView2Controller.MoveFocus(COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC)
            _com_call(self._controller, 12, 0, argtypes=(ctypes.c_int,))
            if msg == WM_SETFOCUS:
                return 0
        if msg == WM_GETMINMAXINFO:
            info = ctypes.cast(lparam, ctypes.POINTER(MINMAXINFO)).contents
            s = user32.GetDpiForWindow(hwnd) / 96 or 1
            info.ptMinTrackSize.x, info.ptMinTrackSize.y = round(self.min_size[0] * s), round(self.min_size[1] * s)
            return 0
        if msg == WM_DPICHANGED:
            r = ctypes.cast(lparam, ctypes.POINTER(wt.RECT)).contents
            user32.SetWindowPos(hwnd, None, r.left, r.top, r.right - r.left, r.bottom - r.top,
                                SWP_NOZORDER | SWP_NOACTIVATE)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

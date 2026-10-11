"""Recording indicator: a small pill docked to the right edge of the screen.

A native Windows layered window (per-pixel alpha, antialiased edges), rendered
with Pillow and owned by its own message-loop thread. Other threads drive it
with show() / hide() / set_level(); clicks come back through on_click / on_stop.
"""
import ctypes
import threading
from ctypes import wintypes as wt

import numpy as np
from PIL import Image, ImageDraw

from minute import config

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Logical size (scaled by the system DPI).
WIDTH, HEIGHT = 30, 66
EDGE_MARGIN = 10
PILL = (29, 29, 32, 240)
BORDER = (255, 255, 255, 38)
BARS = (91, 209, 110, 255)
ENDING = (224, 164, 58, 255)  # amber: the call app let go of the mic, auto-stop is counting down
STOP_BG = (229, 72, 77, 255)
IDLE_ALPHA, HOVER_ALPHA = 165, 255
SS = 4  # supersampling factor for smooth edges

WS_POPUP = 0x80000000
WS_EX_LAYERED, WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80000, 0x8, 0x80, 0x8000000
WM_DESTROY, WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x2, 0x200, 0x201, 0x202
WM_MOUSEACTIVATE, WM_MOUSELEAVE, WM_SETCURSOR, WM_APP = 0x21, 0x2A3, 0x20, 0x8000
MSG_RENDER, MSG_SHOW, MSG_HIDE, MSG_QUIT = WM_APP + 1, WM_APP + 2, WM_APP + 3, WM_APP + 4
MA_NOACTIVATE, TME_LEAVE, ULW_ALPHA, AC_SRC_ALPHA = 3, 0x2, 0x2, 0x1
SW_HIDE, SW_SHOWNOACTIVATE, SM_CXSCREEN, SM_CYSCREEN = 0, 4, 0, 1
SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x4, 0x10
IDC_HAND = 32649

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


class TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("dwFlags", wt.DWORD), ("hwndTrack", wt.HWND), ("dwHoverTime", wt.DWORD)]


user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
user32.CreateWindowExW.restype = wt.HWND
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.UpdateLayeredWindow.argtypes = [wt.HWND, wt.HDC, ctypes.POINTER(wt.POINT), ctypes.POINTER(wt.SIZE), wt.HDC,
                                       ctypes.POINTER(wt.POINT), wt.COLORREF, ctypes.POINTER(BLENDFUNCTION),
                                       wt.DWORD]
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
user32.GetDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.LoadCursorW.argtypes = [wt.HINSTANCE, wt.LPVOID]
user32.LoadCursorW.restype = wt.HANDLE
user32.SetCursor.argtypes = [wt.HANDLE]
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateDIBSection.argtypes = [wt.HDC, ctypes.c_void_p, wt.UINT, ctypes.POINTER(ctypes.c_void_p), wt.HANDLE,
                                   wt.DWORD]
gdi32.CreateDIBSection.restype = wt.HBITMAP
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wt.HDC]
kernel32.GetModuleHandleW.restype = wt.HMODULE


def _scale():
    try:
        return user32.GetDpiForSystem() / 96
    except AttributeError:
        return 1.0


class Indicator:
    def __init__(self, on_click, on_stop):
        self.on_click = on_click
        self.on_stop = on_stop
        self.level = 0.0
        self.ending = False
        self.hover = False
        self.visible = False
        self.hwnd = None
        self._drag = None  # (cursor x, y, window x, y) while the button is down
        self._moved = False
        self._ready = threading.Event()
        threading.Thread(target=self._loop, name="minute-indicator", daemon=True).start()
        self._ready.wait(5)

    # --- called from any thread ---------------------------------------------
    def show(self):
        self._post(MSG_SHOW)

    def hide(self):
        self._post(MSG_HIDE)

    def set_level(self, level):
        self.level = max(0.0, min(1.0, level))
        if self.visible:
            self._post(MSG_RENDER)

    def set_ending(self, ending):
        self.ending = bool(ending)
        if self.visible:
            self._post(MSG_RENDER)

    def close(self):
        self._post(MSG_QUIT)

    def _post(self, msg):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, msg, 0, 0)

    # --- window thread --------------------------------------------------------
    def _loop(self):
        s = _scale()
        self.w, self.h = round(WIDTH * s), round(HEIGHT * s)
        self.scale = s
        logo = Image.open(config.ICON).convert("RGBA")
        logo = logo.crop(logo.getchannel("A").getbbox())
        self.logo = logo.resize((round(17 * s), round(17 * s)), Image.LANCZOS)

        hinst = kernel32.GetModuleHandleW(None)
        self._wndproc = WNDPROC(self._proc)  # keep a reference: ctypes callbacks must outlive the window
        wc = WNDCLASSEXW(cbSize=ctypes.sizeof(WNDCLASSEXW), lpfnWndProc=self._wndproc, hInstance=hinst,
                         lpszClassName="MinuteIndicator")
        user32.RegisterClassExW(ctypes.byref(wc))
        ex = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        self.hwnd = user32.CreateWindowExW(ex, "MinuteIndicator", "minute indicator", WS_POPUP,
                                           0, 0, self.w, self.h, None, None, hinst, None)
        self.x = user32.GetSystemMetrics(SM_CXSCREEN) - self.w - round(EDGE_MARGIN * s)
        self.y = (user32.GetSystemMetrics(SM_CYSCREEN) - self.h) // 2
        self._ready.set()

        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _proc(self, hwnd, msg, wparam, lparam):
        if msg == MSG_SHOW:
            self.visible = True
            self._render()
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
            return 0
        if msg == MSG_HIDE:
            self.visible = False
            self.ending = False
            user32.ShowWindow(hwnd, SW_HIDE)
            return 0
        if msg == MSG_RENDER:
            self._render()
            return 0
        if msg == MSG_QUIT:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        if msg == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE  # never steal focus from the call
        if msg == WM_SETCURSOR:
            user32.SetCursor(user32.LoadCursorW(None, IDC_HAND))
            return 1
        if msg == WM_MOUSEMOVE:
            if not self.hover:
                self.hover = True
                tme = TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT), TME_LEAVE, hwnd, 0)
                user32.TrackMouseEvent(ctypes.byref(tme))
                self._render()
            if self._drag:
                pt = wt.POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                dx, dy = pt.x - self._drag[0], pt.y - self._drag[1]
                if abs(dx) + abs(dy) > 3:
                    self._moved = True
                if self._moved:
                    self.x, self.y = self._drag[2] + dx, self._drag[3] + dy
                    user32.SetWindowPos(hwnd, None, self.x, self.y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
            return 0
        if msg == WM_MOUSELEAVE:
            self.hover = False
            self._render()
            return 0
        if msg == WM_LBUTTONDOWN:
            pt = wt.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            self._drag = (pt.x, pt.y, self.x, self.y)
            self._moved = False
            user32.SetCapture(hwnd)
            return 0
        if msg == WM_LBUTTONUP:
            user32.ReleaseCapture()
            moved, self._drag = self._moved, None
            if not moved:
                y = ctypes.c_short(lparam >> 16 & 0xFFFF).value
                (self.on_stop if y > self.h * 0.5 else self.on_click)()
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _image(self):
        W, H = self.w * SS, self.h * SS
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((0, 0, W - 1, H - 1), radius=W // 2, fill=PILL, outline=BORDER, width=SS)
        cx, cy = W // 2, round(H * 0.69)
        if self.hover:
            r = round(9 * self.scale * SS)
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=STOP_BG)
            q = round(3.5 * self.scale * SS)
            d.rounded_rectangle((cx - q, cy - q, cx + q, cy + q), radius=SS * 2, fill=(255, 255, 255, 255))
        else:
            bw, gap = round(2.5 * self.scale * SS), round(2.5 * self.scale * SS)
            level = 0.25 if self.ending else min(1.0, self.level * 1.6)  # ending: still, low, amber
            for i, shape in enumerate((0.65, 1.0, 0.8)):
                h = round((3 + 11 * level * shape) * self.scale * SS)
                x = cx + (i - 1) * (bw + gap) - bw // 2
                d.rounded_rectangle((x, cy - h // 2, x + bw, cy + h // 2), radius=bw // 2,
                                    fill=ENDING if self.ending else BARS)
        im = im.resize((self.w, self.h), Image.LANCZOS)
        im.alpha_composite(self.logo, ((self.w - self.logo.width) // 2, round(self.h * 0.14)))
        return im

    def _render(self):
        px = np.asarray(self._image(), dtype=np.uint16)
        # UpdateLayeredWindow wants premultiplied BGRA.
        bgra = np.empty_like(px)
        bgra[..., :3] = px[..., 2::-1] * px[..., 3:4] // 255
        bgra[..., 3] = px[..., 3]
        data = bgra.astype(np.uint8).tobytes()

        screen = user32.GetDC(None)
        mem = gdi32.CreateCompatibleDC(screen)
        bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), self.w, -self.h, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        bmp = gdi32.CreateDIBSection(mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        ctypes.memmove(bits, data, len(data))
        old = gdi32.SelectObject(mem, bmp)
        blend = BLENDFUNCTION(0, 0, HOVER_ALPHA if self.hover else IDLE_ALPHA, AC_SRC_ALPHA)
        user32.UpdateLayeredWindow(self.hwnd, screen, ctypes.byref(wt.POINT(self.x, self.y)),
                                   ctypes.byref(wt.SIZE(self.w, self.h)), mem, ctypes.byref(wt.POINT(0, 0)), 0,
                                   ctypes.byref(blend), ULW_ALPHA)
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(None, screen)

r"""Call detection: which apps are capturing from a microphone right now.

Every capture stream on Windows is an audio session on its device (what the volume mixer lists), with
the process that owns it; an *active* session is one recording right now. Only known call apps count, so
dictation tools (Handy, Wispr Flow...), recorders and minute itself never start a note.

Windows used to also keep this in the registry (CapabilityAccessManager\ConsentStore, LastUsedTimeStop == 0
meaning "in use"), but Windows 11 26H2 stopped writing it there: audio sessions work on every version.
"""
import ctypes
import math
import os
import threading
import time
from ctypes import POINTER, byref, c_int, c_uint, c_void_p, wintypes

CALL_EXES = {
    "chrome.exe": "Chrome", "msedge.exe": "Edge", "firefox.exe": "Firefox", "brave.exe": "Brave",
    "arc.exe": "Arc", "opera.exe": "Opera", "vivaldi.exe": "Vivaldi", "comet.exe": "Comet",
    "zoom.exe": "Zoom", "teams.exe": "Teams", "ms-teams.exe": "Teams", "slack.exe": "Slack",
    "discord.exe": "Discord", "skype.exe": "Skype", "webex.exe": "Webex", "ciscocollabhost.exe": "Webex",
    "whatsapp.exe": "WhatsApp", "whatsapp.root.exe": "WhatsApp", "telegram.exe": "Telegram",
    "signal.exe": "Signal",
}


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text):
        super().__init__()
        ctypes.oledll.ole32.CLSIDFromString(f"{{{text}}}", byref(self))


CLSID_MMDeviceEnumerator = GUID("BCDE0395-E52F-467C-8E3D-C4579291692E")
IID_IMMDeviceEnumerator = GUID("A95664D2-9614-4F35-A746-DE8DB63617E6")
IID_IAudioSessionManager2 = GUID("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F")
IID_IAudioSessionControl2 = GUID("BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D")
E_CAPTURE, DEVICE_STATE_ACTIVE, CLSCTX_ALL, SESSION_ACTIVE = 1, 1, 0x17, 1
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _call(obj, index, *args):
    """Method `index` of the COM object's vtable (0-2 are IUnknown's)."""
    vtable = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
    types = [c_void_p if type(a).__name__ == "CArgObject" else type(a) for a in args]  # byref() = a pointer
    fn = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *types)(vtable[index])
    return fn(obj, *args)


def _release(obj):
    if obj:
        vtable = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
        ctypes.WINFUNCTYPE(c_uint, c_void_p)(vtable[2])(obj)


def _exe_name(pid):
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, byref(size)):
            return ""
        return os.path.basename(buf.value).lower()
    finally:
        kernel32.CloseHandle(handle)


def capturing_pids():
    """Process IDs with an active capture session on any connected microphone. The calling thread must
    have COM initialised (CallWatcher's thread does)."""
    pids = set()
    enum = c_void_p()
    ctypes.oledll.ole32.CoCreateInstance(byref(CLSID_MMDeviceEnumerator), None, CLSCTX_ALL,
                                         byref(IID_IMMDeviceEnumerator), byref(enum))
    devices = c_void_p()
    try:
        _call(enum, 3, c_int(E_CAPTURE), wintypes.DWORD(DEVICE_STATE_ACTIVE), byref(devices))
        count = c_uint()
        _call(devices, 3, byref(count))
        for i in range(count.value):
            device, manager, sessions = c_void_p(), c_void_p(), c_void_p()
            try:
                _call(devices, 4, c_uint(i), byref(device))
                _call(device, 3, byref(IID_IAudioSessionManager2), wintypes.DWORD(CLSCTX_ALL), c_void_p(),
                      byref(manager))
                _call(manager, 5, byref(sessions))
                n = c_int()
                _call(sessions, 3, byref(n))
                for j in range(n.value):
                    control, control2 = c_void_p(), c_void_p()
                    try:
                        _call(sessions, 4, c_int(j), byref(control))
                        state = c_int()
                        _call(control, 3, byref(state))
                        if state.value != SESSION_ACTIVE:
                            continue
                        _call(control, 0, byref(IID_IAudioSessionControl2), byref(control2))
                        pid = wintypes.DWORD()
                        _call(control2, 14, byref(pid))
                        if pid.value:
                            pids.add(pid.value)
                    except OSError:
                        continue  # a session that went away meanwhile
                    finally:
                        _release(control2)
                        _release(control)
            except OSError:
                continue  # a device unplugged meanwhile
            finally:
                _release(sessions)
                _release(manager)
                _release(device)
    finally:
        _release(devices)
        _release(enum)
    return pids


def active_call_apps():
    """Names of call apps recording from a microphone right now, e.g. {"Chrome"}."""
    return {app for app in (CALL_EXES.get(_exe_name(pid)) for pid in capturing_pids()) if app}


class CallWatcher:
    """Starts a note when a call app takes the mic, stops it when the call has been over for END_GRACE."""

    POLL = 2.0
    END_GRACE = 45.0  # muting or a short drop doesn't end the note

    def __init__(self, recorder, start, stop, enabled, ending=lambda seconds: None):
        self.recorder = recorder
        self.start = start      # start(app_name)
        self.stop = stop        # stop()
        self.enabled = enabled  # () -> bool, read every poll so the setting applies at once
        self.ending = ending    # ending(seconds left before the auto-stop, or None when the call is on again)
        self._ending = None
        self.apps = set()
        self._last_seen = 0.0
        self._suppressed = False
        threading.Thread(target=self._loop, name="minute-calls", daemon=True).start()

    def user_stopped(self):
        """The user stopped a note mid-call: don't start another until that call is over."""
        if self.apps:
            self._suppressed = True

    def _loop(self):
        ctypes.windll.ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED, for the audio session queries
        while True:
            try:
                self._tick()
            except Exception:
                pass  # registry hiccup: try again next poll
            time.sleep(self.POLL)

    def _tick(self):
        self.apps = active_call_apps()
        now = time.monotonic()
        if self.apps:
            self._last_seen = now
        elif self._suppressed:
            self._suppressed = False
        rec = self.recorder
        left = None
        if rec.busy and rec.auto and not self.apps:
            left = max(0, math.ceil(self.END_GRACE - (now - self._last_seen)))
        if left != self._ending:
            self._ending = left
            self.ending(left)
        if self.apps and not rec.busy and not self._suppressed and self.enabled():
            self.start(sorted(self.apps)[0])
        elif left == 0:
            self.stop()

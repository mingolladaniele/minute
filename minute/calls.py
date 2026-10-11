"""Call detection: Windows records which apps are using the microphone right now.

HKCU\\...\\CapabilityAccessManager\\ConsentStore\\microphone keeps, per app, the last time it
opened and closed the mic; LastUsedTimeStop == 0 means "in use now". Only known call apps
count, so dictation tools (Handy, Wispr Flow...), recorders and minute itself never start a note.
"""
import math
import threading
import time
import winreg

CONSENT = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"

CALL_EXES = {
    "chrome.exe": "Chrome", "msedge.exe": "Edge", "firefox.exe": "Firefox", "brave.exe": "Brave",
    "arc.exe": "Arc", "opera.exe": "Opera", "vivaldi.exe": "Vivaldi",
    "zoom.exe": "Zoom", "teams.exe": "Teams", "ms-teams.exe": "Teams", "slack.exe": "Slack",
    "discord.exe": "Discord", "skype.exe": "Skype", "webex.exe": "Webex", "ciscocollabhost.exe": "Webex",
    "whatsapp.exe": "WhatsApp", "telegram.exe": "Telegram", "signal.exe": "Signal",
}
CALL_PACKAGES = {
    "MSTeams_": "Teams", "MicrosoftTeams_": "Teams", "5319275A.WhatsAppDesktop_": "WhatsApp",
    "Microsoft.SkypeApp_": "Skype", "TelegramMessengerLLP.TelegramDesktop_": "Telegram",
    "Zoom.ZoomRooms_": "Zoom",
}


def _in_use(key):
    try:
        start = winreg.QueryValueEx(key, "LastUsedTimeStart")[0]
        stop = winreg.QueryValueEx(key, "LastUsedTimeStop")[0]
    except FileNotFoundError:
        return False
    return start > 0 and stop == 0


def _subkeys(key):
    i = 0
    while True:
        try:
            yield winreg.EnumKey(key, i)
        except OSError:
            return
        i += 1


def active_call_apps():
    """Names of call apps holding the microphone right now, e.g. {"Chrome"}."""
    found = set()
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, CONSENT)
    except FileNotFoundError:
        return found
    with root:
        for name in _subkeys(root):
            if name == "NonPackaged":
                with winreg.OpenKey(root, name) as np_key:
                    for path in _subkeys(np_key):
                        app = CALL_EXES.get(path.rsplit("#", 1)[-1].lower())
                        if app:
                            with winreg.OpenKey(np_key, path) as k:
                                if _in_use(k):
                                    found.add(app)
            else:
                app = next((a for prefix, a in CALL_PACKAGES.items() if name.startswith(prefix)), None)
                if app:
                    with winreg.OpenKey(root, name) as k:
                        if _in_use(k):
                            found.add(app)
    return found


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

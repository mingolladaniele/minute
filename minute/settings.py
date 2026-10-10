"""User settings in %APPDATA%\\minute\\settings.json, plus the Windows integrations they control."""
import json
import os
import sys
import winreg
from pathlib import Path

from minute import config

FILE = config.APP_DATA / "settings.json"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "minute"

DEFAULTS = {
    "launch_at_startup": False,
    "language": "it-IT",
    "recordings_dir": str(config.DEFAULT_RECORDINGS),
    "keep_audio": True,
    "ai_titles": True,
    "ai_base_url": "https://api.deepseek.com",
    "ai_model": "deepseek-flash",
    "ai_key_source": "pi",  # "pi": read ~/.pi/agent/auth.json at call time; "custom": ai_key below
    "ai_key": "",
}


def load():
    try:
        saved = json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        saved = {}
    values = {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}
    # The registry is the truth for autostart: the installer can set it too.
    values["launch_at_startup"] = _startup_enabled()
    return values


def save(values):
    current = load()
    current.update({k: v for k, v in values.items() if k in DEFAULTS})
    if "launch_at_startup" in values:
        _apply_startup(current["launch_at_startup"])
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps({k: v for k, v in current.items() if k != "launch_at_startup"}, indent=2),
                    encoding="utf-8")
    return current


def recordings_dir():
    return Path(os.environ.get("MINUTE_RECORDINGS") or load()["recordings_dir"])


def pi_key_available():
    return _pi_key() is not None


def _pi_key():
    try:
        auth = json.loads((Path.home() / ".pi" / "agent" / "auth.json").read_text(encoding="utf-8"))
        return auth["deepseek"]["key"] or None
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None


def ai_key(values=None):
    values = values or load()
    return _pi_key() if values["ai_key_source"] == "pi" else (values["ai_key"] or None)


def _launch_command():
    """How Windows should start minute at login: hidden, straight into the tray."""
    if config.FROZEN:
        return f'"{sys.executable}" --tray'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw}" "{config.RESOURCES / "minute.pyw"}" --tray'


def _startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_VALUE)
            return True
    except FileNotFoundError:
        return False


def _apply_startup(enabled):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, _launch_command())
        else:
            try:
                winreg.DeleteValue(k, RUN_VALUE)
            except FileNotFoundError:
                pass

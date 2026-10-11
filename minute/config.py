"""Paths and command-line options, valid both from source and inside the PyInstaller build."""
import os
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
# Bundled resources (ui/, assets/, vendor/) live next to the code, or in _MEIPASS when frozen.
RESOURCES = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
APP_DATA = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "minute"
LOCAL_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "minute"

UI = RESOURCES / "minute" / "ui"
ICON = RESOURCES / "assets" / "icon.png"
ICON_ICO = RESOURCES / "assets" / "icon.ico"
CHANGELOG = RESOURCES / "CHANGELOG.md"
DEFAULT_ENGINE = RESOURCES / "vendor" / "transcribe-native-windows-x86_64-cpu-vulkan"
DEFAULT_RECORDINGS = Path.home() / "Documents" / "minute"

MODEL_REPO = "handy-computer/nemotron-3.5-asr-streaming-0.6b-gguf"
MODEL_FILE = "nemotron-3.5-asr-streaming-0.6b-Q8_0.gguf"
MODEL_URL = f"https://huggingface.co/{MODEL_REPO}/resolve/main/{MODEL_FILE}"
DOWNLOADED_MODEL = LOCAL_DATA / "models" / MODEL_FILE


def find_model():
    """The Nemotron GGUF: minute's own copy, else the one Handy keeps in the Hugging Face cache."""
    if DOWNLOADED_MODEL.exists():
        return DOWNLOADED_MODEL
    snapshots = Path.home() / ".cache/huggingface/hub" / f"models--{MODEL_REPO.replace('/', '--')}" / "snapshots"
    found = sorted(snapshots.glob(f"*/{MODEL_FILE}"))
    return found[-1] if found else None


def add_arguments(ap):
    ap.add_argument("--model", default=os.environ.get("MINUTE_MODEL"), help="GGUF model path (default: auto)")
    ap.add_argument("--engine-dir", default=os.environ.get("MINUTE_ENGINE_DIR", str(DEFAULT_ENGINE)))
    ap.add_argument("--lang", type=lambda s: None if s == "auto" else s, default=os.environ.get("MINUTE_LANG"),
                    help='model language code (e.g. it-IT, en-US), or "auto"; default: from settings')

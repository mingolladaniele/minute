"""Shared command-line / environment settings."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENGINE = ROOT / "vendor" / "transcribe-native-windows-x86_64-cpu-vulkan"
DEFAULT_MODEL = (
    Path.home() / ".cache/huggingface/hub/models--handy-computer--nemotron-3.5-asr-streaming-0.6b-gguf"
    / "snapshots/6d44e540bc31b0de1dbe174a3cea87f53a7f22fb/nemotron-3.5-asr-streaming-0.6b-Q8_0.gguf"
)
ICON = ROOT / "assets" / "icon.png"


def add_arguments(ap):
    ap.add_argument("--model", default=os.environ.get("MINUTE_MODEL", str(DEFAULT_MODEL)))
    ap.add_argument("--engine-dir", default=os.environ.get("MINUTE_ENGINE_DIR", str(DEFAULT_ENGINE)))
    ap.add_argument("--lang", type=lambda s: None if s == "auto" else s,
                    default=os.environ.get("MINUTE_LANG", "it-IT"),
                    help='model language code (e.g. it-IT, en-US), or "auto" to autodetect')

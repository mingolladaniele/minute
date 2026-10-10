"""Calls on disk: recordings/<call_id>/ with meta.json, blocks.json, transcript.md and one WAV per track."""
import json
import os
import wave
from pathlib import Path

import numpy as np

from minute.capture import TARGET_RATE

ROOT = Path(os.environ.get("MINUTE_RECORDINGS", Path(__file__).resolve().parent.parent / "recordings"))


def new_call_id(started):
    return started.strftime("%Y-%m-%d_%H-%M-%S")


def call_dir(call_id):
    return ROOT / call_id


def merge_blocks(lines):
    """Join consecutive raw deltas of the same speaker into {t, label, text} blocks."""
    blocks = []
    for t, label, text in lines:
        if blocks and blocks[-1]["label"] == label:
            blocks[-1]["text"] += text
        else:
            blocks.append({"t": t, "label": label, "text": text})
    for b in blocks:
        b["text"] = b["text"].strip()
    return blocks


def _write_wav(path, chunks):
    pcm = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TARGET_RATE)
        w.writeframes((np.clip(pcm, -1, 1) * 32767).astype(np.int16).tobytes())


def _read_meta(call_id):
    f = call_dir(call_id) / "meta.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_meta(call_id, meta):
    d = call_dir(call_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def save_call(call_id, started, duration, lines, audio):
    d = call_dir(call_id)
    d.mkdir(parents=True, exist_ok=True)
    blocks = merge_blocks(lines)
    # The title may already have been edited while the call was live.
    title = _read_meta(call_id).get("title") or f"Call {started:%H:%M}"
    meta = {"id": call_id, "title": title, "started": started.isoformat(timespec="seconds"),
            "duration": round(duration)}
    _write_meta(call_id, meta)
    (d / "blocks.json").write_text(json.dumps(blocks, ensure_ascii=False, indent=2), encoding="utf-8")
    md = [f"# {title}, {started:%Y-%m-%d %H:%M}"]
    md += [f"**{b['label']}** `{b['t']}`\n{b['text']}" for b in blocks]
    (d / "transcript.md").write_text("\n\n".join(md) + "\n", encoding="utf-8")
    for label, chunks in audio.items():
        _write_wav(d / f"{label.lower()}.wav", chunks)
    return d


def rename_call(call_id, title):
    _write_meta(call_id, {**_read_meta(call_id), "id": call_id, "title": title.strip()})


def save_notes(call_id, text):
    d = call_dir(call_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "notes.md").write_text(text, encoding="utf-8")


def list_calls():
    """Finished calls, newest first (a live call has no duration yet)."""
    if not ROOT.exists():
        return []
    calls = []
    for meta in ROOT.glob("*/meta.json"):
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "duration" in m:
            calls.append(m)
    return sorted(calls, key=lambda c: c["started"], reverse=True)


def load_call(call_id):
    d = call_dir(call_id)
    blocks = json.loads((d / "blocks.json").read_text(encoding="utf-8"))
    notes = d / "notes.md"
    return {**_read_meta(call_id), "blocks": blocks, "notes": notes.read_text(encoding="utf-8") if notes.exists() else ""}


def delete_call(call_id):
    d = call_dir(call_id)
    for f in d.iterdir():
        f.unlink()
    d.rmdir()

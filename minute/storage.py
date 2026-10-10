"""Calls on disk: <recordings>/<call_id>/ with meta.json, blocks.json, transcript.md, notes.md and one WAV per track.

meta.json "title_source" says who named the call: "default", "user" or "ai".
AI titles never overwrite a name the user chose.
"""
import json
import shutil
import wave

import numpy as np

from minute import settings
from minute.capture import TARGET_RATE


def new_call_id(started):
    return started.strftime("%Y-%m-%d_%H-%M-%S")


def call_dir(call_id):
    return settings.recordings_dir() / call_id


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
    try:
        return json.loads((call_dir(call_id) / "meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_meta(call_id, meta):
    d = call_dir(call_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_transcript(call_id, meta, blocks):
    md = [f"# {meta['title']}", f"_{meta['started'].replace('T', ' ')}_"]
    md += [f"**{b['label']}** `{b['t']}`\n{b['text']}" for b in blocks]
    (call_dir(call_id) / "transcript.md").write_text("\n\n".join(md) + "\n", encoding="utf-8")


def save_call(call_id, started, duration, lines, audio, keep_audio=True):
    d = call_dir(call_id)
    d.mkdir(parents=True, exist_ok=True)
    blocks = merge_blocks(lines)
    # The title may already have been edited while the call was live.
    existing = _read_meta(call_id)
    meta = {
        "id": call_id,
        "title": existing.get("title") or f"Call {started:%H:%M}",
        "title_source": existing.get("title_source", "default"),
        "started": started.isoformat(timespec="seconds"),
        "duration": round(duration),
    }
    _write_meta(call_id, meta)
    (d / "blocks.json").write_text(json.dumps(blocks, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_transcript(call_id, meta, blocks)
    if keep_audio:
        for label, chunks in audio.items():
            _write_wav(d / f"{label.lower()}.wav", chunks)
    return d


def rename_call(call_id, title, source="user"):
    meta = {**_read_meta(call_id), "id": call_id, "title": title.strip(), "title_source": source}
    _write_meta(call_id, meta)
    blocks_file = call_dir(call_id) / "blocks.json"
    if "started" in meta and blocks_file.exists():
        _write_transcript(call_id, meta, json.loads(blocks_file.read_text(encoding="utf-8")))


def save_notes(call_id, text):
    d = call_dir(call_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "notes.md").write_text(text, encoding="utf-8")


def list_calls():
    """Finished calls, newest first (a live call has no duration yet)."""
    root = settings.recordings_dir()
    if not root.exists():
        return []
    calls = []
    for meta in root.glob("*/meta.json"):
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
    shutil.rmtree(call_dir(call_id))

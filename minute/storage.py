"""Calls on disk: <recordings>/<call_id>/

    meta.json      title, timing and status (see below)
    you.wav        your mic, written live (crash-safe)
    them.wav       system audio, written live (crash-safe)
    live.jsonl     raw transcript lines as they were committed during the call
    blocks.json    final speaker blocks; transcript.md is the readable copy
    notes.md       your notes
    enhanced.md    your notes completed and structured by AI (editable)

meta.json status fields:
    status         "recording" | "done"
    transcript     "live" | "done" | "pending"   (pending: audio saved, text still to come)
    transcript_error, title_status ("done" | "pending" | "off"), title_error
    title_source   "default" | "user" | "ai"     (AI titles never overwrite "user")
    enhanced_status ("done" | "pending"), enhanced_error, enhanced_edited
"""
import ctypes
import json
import os
import re
import shutil
import unicodedata
from ctypes import wintypes

from minute import settings, wavfile

TRACKS = ("you", "them")


def new_call_id(started):
    return started.strftime("%Y-%m-%d_%H-%M-%S")


def call_dir(call_id):
    return settings.recordings_dir() / call_id


def read_meta(call_id):
    try:
        return json.loads((call_dir(call_id) / "meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_meta(call_id, meta):
    d = call_dir(call_id)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "meta.json.tmp"
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(d / "meta.json")


def update_meta(call_id, **fields):
    meta = {**read_meta(call_id), **fields}
    _write_meta(call_id, meta)
    return meta


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
    return [b for b in blocks if b["text"]]


def _write_transcript_md(call_id, meta, blocks):
    md = [f"# {meta['title']}", f"_{meta['started'].replace('T', ' ')}_"]
    md += [f"**{b['label']}** `{b['t']}`\n{b['text']}" for b in blocks]
    (call_dir(call_id) / "transcript.md").write_text("\n\n".join(md) + "\n", encoding="utf-8")


# --- lifecycle -------------------------------------------------------------

def start_call(call_id, started, auto=False, app=None):
    d = call_dir(call_id)
    d.mkdir(parents=True, exist_ok=True)
    _write_meta(call_id, {
        "id": call_id, "title": f"Call {started:%H:%M}", "title_source": "default",
        "started": started.isoformat(timespec="seconds"), "status": "recording", "transcript": "live",
        "auto": auto, "app": app,
    })
    return d


def open_live_log(call_id):
    return open(call_dir(call_id) / "live.jsonl", "a", encoding="utf-8", buffering=1)


def finish_call(call_id, duration, lines, transcript_ok, transcript_error=None):
    """Close a call: final blocks when live transcription worked, otherwise mark it for a retry from audio."""
    meta = read_meta(call_id)
    meta.update(status="done", duration=round(duration))
    if transcript_ok:
        set_blocks(call_id, merge_blocks(lines), meta)
    else:
        meta.update(transcript="pending", transcript_error=transcript_error or "transcription unavailable")
        _write_meta(call_id, meta)
    return meta


def set_blocks(call_id, blocks, meta=None):
    meta = meta or read_meta(call_id)
    meta.update(transcript="done")
    meta.pop("transcript_error", None)
    _write_meta(call_id, meta)
    (call_dir(call_id) / "blocks.json").write_text(json.dumps(blocks, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_transcript_md(call_id, meta, blocks)


def recover_interrupted(active_id=None):
    """Calls left in "recording" by a crash or power loss: fix the audio and queue them for transcription."""
    recovered = []
    root = settings.recordings_dir()
    if not root.exists():
        return recovered
    for meta_file in root.glob("*/meta.json"):
        call_id = meta_file.parent.name
        meta = read_meta(call_id)
        if meta.get("status") != "recording" or call_id == active_id:
            continue
        lengths = []
        for track in TRACKS:
            wav = call_dir(call_id) / f"{track}.wav"
            if wav.exists():
                wavfile.repair(wav)
                lengths.append(wavfile.duration(wav))
        update_meta(call_id, status="done", duration=round(max(lengths, default=0)), transcript="pending",
                    transcript_error="minute closed during the call; transcribing from the saved audio")
        recovered.append(call_id)
    return recovered


def live_lines(call_id):
    """Raw (t, label, text) lines from live.jsonl, for calls whose audio is gone."""
    path = call_dir(call_id) / "live.jsonl"
    if not path.exists():
        return []
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(raw)
            lines.append((d["t"], d["label"], d["text"]))
        except (json.JSONDecodeError, KeyError):
            continue
    return lines


def raw_text_file(call_id):
    """A readable copy of the raw live text (live.jsonl), written next to it: raw-transcript.txt."""
    lines = live_lines(call_id)
    meta = read_meta(call_id)
    out = [f"{meta.get('title', call_id)}  ({meta.get('started', '').replace('T', ' ')})",
           "Raw live transcript, exactly as it was committed during the call.", ""]
    if not lines:
        out.append("(nothing was transcribed live; the audio files hold the call)")
    turns = []  # live deltas split words mid-way: rejoin consecutive pieces of the same speaker
    for t, label, text in lines:
        if turns and turns[-1][1] == label:
            turns[-1][2] += text
        else:
            turns.append([t, label, text])
    for t, label, text in turns:
        out.append(f"[{t}] {label}: {text.strip()}")
    path = call_dir(call_id) / "raw-transcript.txt"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def audio_paths(call_id):
    return {t.upper(): call_dir(call_id) / f"{t}.wav" for t in TRACKS if (call_dir(call_id) / f"{t}.wav").exists()}


def delete_audio(call_id):
    for t in TRACKS:
        (call_dir(call_id) / f"{t}.wav").unlink(missing_ok=True)


# --- user edits --------------------------------------------------------------

def rename_call(call_id, title, source="user"):
    meta = read_meta(call_id)
    meta.update(id=call_id, title=title.strip(), title_source=source)
    if source in ("user", "ai"):  # a real name: nothing left for the AI to do
        meta["title_status"] = "done"
        meta.pop("title_error", None)
    _write_meta(call_id, meta)
    blocks_file = call_dir(call_id) / "blocks.json"
    if "started" in meta and blocks_file.exists():
        _write_transcript_md(call_id, meta, json.loads(blocks_file.read_text(encoding="utf-8")))


def save_notes(call_id, text):
    d = call_dir(call_id)
    if not (d / "meta.json").exists():
        return  # discarded or deleted meanwhile: never resurrect a call for its notes
    (d / "notes.md").write_text(text, encoding="utf-8")


def save_enhanced(call_id, text, source="user"):
    """source "ai" marks a fresh generation; "user" an edit of the enhanced notes."""
    d = call_dir(call_id)
    if not (d / "meta.json").exists():
        return
    (d / "enhanced.md").write_text(text, encoding="utf-8")
    meta = read_meta(call_id)
    meta.update(enhanced_status="done")
    meta.pop("enhanced_error", None)
    if source == "user":
        meta["enhanced_edited"] = True
    _write_meta(call_id, meta)


def enhanced_of(call_id):
    f = call_dir(call_id) / "enhanced.md"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def notes_of(call_id):
    f = call_dir(call_id) / "notes.md"
    return f.read_text(encoding="utf-8") if f.exists() else ""


# --- reading -------------------------------------------------------------------

def list_calls():
    """Finished calls, newest first."""
    root = settings.recordings_dir()
    if not root.exists():
        return []
    calls = []
    for meta_file in root.glob("*/meta.json"):
        try:
            m = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if m.get("status", "done") == "done" and "duration" in m:
            calls.append(m)
    return sorted(calls, key=lambda c: c["started"], reverse=True)


def load_call(call_id):
    d = call_dir(call_id)
    blocks_file = d / "blocks.json"
    if blocks_file.exists():
        blocks = json.loads(blocks_file.read_text(encoding="utf-8"))
    else:  # transcript still pending: show what was heard live, if anything
        blocks = merge_blocks(live_lines(call_id))
    return {**read_meta(call_id), "blocks": blocks, "notes": notes_of(call_id),
            "enhanced": enhanced_of(call_id), "has_audio": bool(audio_paths(call_id)),
            "audio": [t for t in TRACKS if (d / f"{t}.wav").exists()]}


# --- search --------------------------------------------------------------------

_FOLD = {}  # code point -> its search form, filled in as new characters show up
_MD_SYNTAX = re.compile(r"(?m)^[ \t]*(?:#+|[-+*]|\d{1,3}\.)[ \t]+|\*\*|`")  # headings, list markers, bold, code
_INDEX = {}  # call folder -> (file times, texts, folded): a search reads again only the calls that changed
_INDEXED = ("notes.md", "enhanced.md", "blocks.json", "live.jsonl")
_FIELDS = ("notes", "enhanced", "transcript")  # the texts _searchable returns, in order


def _fold(text):
    """Lowercase, without accents, a space for any whitespace: "Perché?\\n" -> "perche? ". One character
    for one character, so a position in the result is the same position in text."""
    for c in set(text):
        if ord(c) not in _FOLD:
            f = "".join(x for x in unicodedata.normalize("NFD", c) if not unicodedata.combining(x)).lower()
            _FOLD[ord(c)] = " " if c.isspace() else f if len(f) == 1 else c
    return text.translate(_FOLD)


def _plain(md):
    """Markdown syntax blanked out with spaces, so positions don't move."""
    return _MD_SYNTAX.sub(lambda m: " " * len(m[0]), md)


def _word_start(text):
    """A pattern for text at the start of a word: "sync" finds "Sync" and "synchronize", not "async"."""
    return re.compile(r"(?<!\w)" + re.escape(text))


def _searchable(d):
    """A call's [notes, enhanced notes, transcript], plain and folded, kept until one of its files changes."""
    with os.scandir(d) as files:  # the listing carries each file's time: no stat per file
        times = {f.name: f.stat().st_mtime_ns for f in files if f.name in _INDEXED}
    cached = _INDEX.get(d)
    if cached and cached[0] == times:
        return cached[1], cached[2]
    call = load_call(d.name)
    texts = [unicodedata.normalize("NFC", t) for t in (
        _plain(call["notes"]), _plain(call["enhanced"]), "\n".join(b["text"] for b in call["blocks"]))]
    folded = [_fold(t) for t in texts]
    _INDEX[d] = (times, texts, folded)
    return texts, folded


def _marks(text, folded, patterns, start=0, end=None):
    """text[start:end] as [piece, bold] pairs, bold where a pattern matches."""
    end = len(text) if end is None else end
    out, at = [], start
    for a, b in sorted(m.span() for p in patterns for m in p.finditer(folded, start, end)):
        if b <= at:
            continue  # inside a word already marked
        a = max(a, at)
        if a > at:
            out.append([text[at:a], False])
        out.append([text[a:b], True])
        at = b
    if at < end:
        out.append([text[at:end], False])
    return out


def _first(folded, words, patterns):
    """(which text, position): the whole query in the first text that has it, else the earliest word in
    the first text that has any."""
    phrase = _word_start(" ".join(words))
    for i, f in enumerate(folded):
        if m := phrase.search(f):
            return i, m.start()
    for i, f in enumerate(folded):
        if found := [m.start() for p in patterns if (m := p.search(f))]:
            return i, min(found)
    return None


def _snippet(text, f, at, patterns, before=40, after=120):
    """The words around position at, on one line, as [piece, bold] pairs."""
    start, end = max(0, at - before), min(len(f), at + after)
    if start and (space := f.find(" ", start, at)) >= 0:
        start = space + 1  # don't start or end mid-word
    if end < len(f) and (space := f.rfind(" ", at, end)) > at:
        end = space
    out = [[re.sub(r"[ \t]+", " ", re.sub(r"\s*\n\s*", " · ", piece)), bold]
           for piece, bold in _marks(text, f, patterns, start, end)]
    out[0][0] = out[0][0].lstrip(" ·")
    out[-1][0] = out[-1][0].rstrip(" ·")
    return [["…", False]] * bool(start) + out + [["…", False]] * (end < len(f))


def search(query):
    """Calls with every word of query in their title, notes, enhanced notes or transcript, newest first.
    Words match from the start of a word, ignoring case and accents. Each hit: {id, title, snippet, field},
    title and snippet as [piece, bold] pairs; field ("notes", "enhanced", "transcript") is where the snippet
    comes from. Snippet and field are None when only the title matches. An empty query finds nothing but
    gets every call read, so the first word typed is fast."""
    words = _fold(unicodedata.normalize("NFC", query)).split()
    patterns = [_word_start(w) for w in words]
    root, hits = settings.recordings_dir(), []
    for meta in list_calls():
        try:
            texts, folded = _searchable(root / meta["id"])
        except OSError:
            continue  # deleted meanwhile
        title = unicodedata.normalize("NFC", meta.get("title") or "")
        folded_title = _fold(title)
        # the plain substring test first: it's fast, the word-start pattern only confirms what it finds
        if words and all(p.search(folded_title) or any(w in f and p.search(f) for f in folded)
                         for w, p in zip(words, patterns)):
            hit = {"id": meta["id"], "title": _marks(title, folded_title, patterns), "snippet": None, "field": None}
            if first := _first(folded, words, patterns):
                i, at = first
                hit.update(snippet=_snippet(texts[i], folded[i], at, patterns), field=_FIELDS[i])
            hits.append(hit)
    return hits


def delete_call(call_id):
    """Gone for good: for auto-recordings that were never a call."""
    shutil.rmtree(call_dir(call_id))


class _FileOp(ctypes.Structure):  # SHFILEOPSTRUCTW
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]


def recycle_call(call_id):
    """Move a call's folder to the Windows Recycle Bin, where it can be restored."""
    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    path = str(call_dir(call_id).resolve())
    op = _FileOp(wFunc=FO_DELETE, pFrom=path + "\0",  # the list of paths ends with an extra NUL
                 fFlags=FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI)
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if code or op.fAnyOperationsAborted or call_dir(call_id).exists():
        raise OSError(f"could not move the call to the Recycle Bin (code {code})")

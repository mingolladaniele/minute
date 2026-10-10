"""Live capture test: transcribe system audio ("loro") and mic ("tu") in real time.

    uv run python -m minute [--seconds N]

Stop with Ctrl+C. Writes the two WAVs and a transcript.md under recordings/.
"""
import argparse
import os
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
import pyaudiowpatch as pyaudio

from minute.capture import TARGET_RATE, Source, default_devices
from minute.engine import Engine

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENGINE = ROOT / "vendor" / "transcribe-native-windows-x86_64-cpu-vulkan"
DEFAULT_MODEL = (
    Path.home() / ".cache/huggingface/hub/models--handy-computer--nemotron-3.5-asr-streaming-0.6b-gguf"
    / "snapshots/6d44e540bc31b0de1dbe174a3cea87f53a7f22fb/nemotron-3.5-asr-streaming-0.6b-Q8_0.gguf"
)
FEED_SAMPLES = TARGET_RATE // 2  # feed the model in ~500 ms chunks


class Track:
    def __init__(self, source, stream):
        self.source = source
        self.stream = stream
        self.pending = []
        self.recorded = []
        self.committed = ""

    def drain(self):
        while not self.source.queue.empty():
            chunk = self.source.queue.get_nowait()
            self.pending.append(chunk)
            self.recorded.append(chunk)

    def feed(self, force=False):
        n = sum(len(c) for c in self.pending)
        if n == 0 or (n < FEED_SAMPLES and not force):
            return
        self.stream.feed(np.concatenate(self.pending))
        self.pending = []

    def new_text(self):
        committed, _ = self.stream.text()
        delta = committed[len(self.committed):]
        self.committed = committed
        return delta


def write_wav(path, chunks):
    pcm = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TARGET_RATE)
        w.writeframes((np.clip(pcm, -1, 1) * 32767).astype(np.int16).tobytes())


def write_transcript(path, lines, started):
    # Deltas are raw slices of each track's committed text: join them as-is.
    blocks = []
    for t, label, text in lines:
        if blocks and blocks[-1][1] == label:
            blocks[-1][2] += text
        else:
            blocks.append([t, label, text])
    out = [f"# Call {started:%Y-%m-%d %H:%M}"]
    out += [f"**{label}** `{t}`\n{text.strip()}" for t, label, text in blocks]
    path.write_text("\n\n".join(out) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(prog="minute")
    ap.add_argument("--seconds", type=float, help="stop after N seconds (default: until Ctrl+C)")
    ap.add_argument("--model", default=os.environ.get("MINUTE_MODEL", str(DEFAULT_MODEL)))
    ap.add_argument("--engine-dir", default=os.environ.get("MINUTE_ENGINE_DIR", str(DEFAULT_ENGINE)))
    ap.add_argument("--lang", default="it-IT", help='model language code, or "auto" to autodetect')
    ap.add_argument("--out", default=str(ROOT / "recordings"))
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    print("loading model...", flush=True)
    t0 = time.perf_counter()
    engine = Engine(args.engine_dir, args.model)
    print(f"model ready in {time.perf_counter() - t0:.1f}s")

    pa = pyaudio.PyAudio()
    loopback, mic = default_devices(pa)
    lang = None if args.lang == "auto" else args.lang
    tracks = [
        Track(Source(pa, loopback, "LORO"), engine.stream(lang)),
        Track(Source(pa, mic, "TU"), engine.stream(lang)),
    ]
    for tr in tracks:
        print(f"  {tr.source.label:<4} <- {tr.source.name} ({tr.source.rate} Hz, {tr.source.channels} ch)")

    started = datetime.now()
    start = time.perf_counter()
    lines = []

    def emit(tr):
        text = tr.new_text()
        if text.strip():
            secs = int(time.perf_counter() - start)
            stamp = f"{secs // 60:02d}:{secs % 60:02d}"
            lines.append((stamp, tr.source.label, text))
            print(f"[{stamp}] {tr.source.label:<4} {text.strip()}", flush=True)

    for tr in tracks:
        tr.source.start()
    print("\nin ascolto — Ctrl+C per fermare\n", flush=True)
    try:
        while args.seconds is None or time.perf_counter() - start < args.seconds:
            for tr in tracks:
                tr.drain()
                tr.feed()
                emit(tr)
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass

    print("\nstop, finalizzo...", flush=True)
    for tr in tracks:
        tr.source.stop()
        tr.drain()
        tr.feed(force=True)
        tr.stream.finalize()
        emit(tr)
    pa.terminate()

    out = Path(args.out) / started.strftime("%Y-%m-%d_%H-%M-%S")
    out.mkdir(parents=True, exist_ok=True)
    for tr in tracks:
        write_wav(out / f"{tr.source.label.lower()}.wav", tr.recorded)
    write_transcript(out / "transcript.md", lines, started)
    engine.close()
    print(f"salvato in {out}")


if __name__ == "__main__":
    main()

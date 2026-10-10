"""Recording session: capture both tracks, transcribe live, save the call.

The Recorder runs on a background thread and reports through a single
on_event(dict) callback, so the CLI and the GUI consume the same stream:

    {"type": "state", "state": "loading|recording|saving|idle", "call_id": ...}
    {"type": "text", "label": "YOU|THEM", "t": "mm:ss", "delta": str, "tentative": str}
    {"type": "levels", "elapsed": seconds, "YOU": 0..1, "THEM": 0..1}
"""
import threading
import time
from datetime import datetime

import numpy as np
import pyaudiowpatch as pyaudio

from minute import config, settings, storage
from minute.capture import TARGET_RATE, Source, default_devices
from minute.engine import Engine

FEED_SAMPLES = TARGET_RATE // 2  # feed the model in ~500 ms chunks
LEVEL_EVERY = 0.1


class Track:
    def __init__(self, source, stream):
        self.source = source
        self.stream = stream
        self.pending = []
        self.recorded = []
        self.committed = ""
        self.tentative = ""
        self.level = 0.0

    def drain(self):
        got = []
        while not self.source.queue.empty():
            got.append(self.source.queue.get_nowait())
        if got:
            x = np.concatenate(got)
            self.pending.append(x)
            self.recorded.append(x)
            # RMS mapped to a rough 0..1 meter (speech sits around 0.02-0.2)
            self.level = max(float(np.sqrt(np.mean(x * x))) * 6, self.level * 0.6)
        else:
            self.level *= 0.6

    def feed(self, force=False):
        n = sum(len(c) for c in self.pending)
        if n == 0 or (n < FEED_SAMPLES and not force):
            return False
        self.stream.feed(np.concatenate(self.pending))
        self.pending = []
        return True

    def update_text(self):
        """(new committed slice, tentative) or None if nothing moved."""
        committed, tentative = self.stream.text()
        delta = committed[len(self.committed):]
        if not delta and tentative == self.tentative:
            return None
        self.committed, self.tentative = committed, tentative
        return delta, tentative


class ModelMissing(RuntimeError):
    pass


class Recorder:
    """model_path / language override the settings when given (None = use settings)."""

    def __init__(self, engine_dir, on_event, model_path=None, language=None):
        self.engine_dir = engine_dir
        self.model_path = model_path
        self.language = language
        self.on_event = on_event
        self.state = "idle"
        self.call_id = None
        self._engine = None
        self._stop = threading.Event()
        self._thread = None

    @property
    def busy(self):
        return self.state != "idle"

    def _set_state(self, state):
        self.state = state
        self.on_event({"type": "state", "state": state, "call_id": self.call_id})

    def start(self, seconds=None):
        if self.busy:
            return
        self._stop.clear()
        self.call_id = None
        self.state = "loading"
        self._thread = threading.Thread(target=self._run, args=(seconds,), daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def wait(self):
        if self._thread:
            self._thread.join()

    def close(self):
        self.stop()
        self.wait()
        if self._engine:
            self._engine.close()
            self._engine = None

    def _run(self, seconds):
        try:
            self._record(seconds)
        except ModelMissing:
            self.on_event({"type": "model_missing"})
        except Exception as e:  # surface failures to the UI instead of dying silently
            self.on_event({"type": "error", "message": str(e)})
        finally:
            self._set_state("idle")

    def _record(self, seconds):
        self._set_state("loading")
        prefs = settings.load()
        language = self.language if self.language is not None else prefs["language"]
        language = None if language == "auto" else language
        if self._engine is None:
            model = self.model_path or config.find_model()
            if model is None:
                raise ModelMissing("speech model not found")
            self._engine = Engine(self.engine_dir, str(model))

        pa = pyaudio.PyAudio()
        loopback, mic = default_devices(pa)
        tracks = [
            Track(Source(pa, loopback, "THEM"), self._engine.stream(language)),
            Track(Source(pa, mic, "YOU"), self._engine.stream(language)),
        ]
        started = datetime.now()
        self.call_id = storage.new_call_id(started)
        lines = []
        start = time.perf_counter()

        def stamp():
            secs = int(time.perf_counter() - start)
            return f"{secs // 60:02d}:{secs % 60:02d}"

        def emit_text(tr):
            moved = tr.update_text()
            if moved is None:
                return
            delta, tentative = moved
            t = stamp()
            if delta.strip():
                lines.append((t, tr.source.label, delta))
            self.on_event({"type": "text", "label": tr.source.label, "t": t, "delta": delta, "tentative": tentative})

        for tr in tracks:
            tr.source.start()
        self._set_state("recording")
        last_levels = 0.0
        try:
            while not self._stop.is_set():
                elapsed = time.perf_counter() - start
                if seconds is not None and elapsed >= seconds:
                    break
                for tr in tracks:
                    tr.drain()
                    if tr.feed():
                        emit_text(tr)
                if elapsed - last_levels >= LEVEL_EVERY:
                    last_levels = elapsed
                    self.on_event({"type": "levels", "elapsed": elapsed,
                                   **{tr.source.label: min(tr.level, 1.0) for tr in tracks}})
                time.sleep(0.05)
        finally:
            self._set_state("saving")
            for tr in tracks:
                tr.source.stop()
                tr.drain()
                tr.feed(force=True)
                tr.stream.finalize()
                emit_text(tr)
            pa.terminate()
            for tr in tracks:
                self._engine.free_stream(tr.stream)
            duration = time.perf_counter() - start
            storage.save_call(self.call_id, started, duration, lines,
                              {tr.source.label: tr.recorded for tr in tracks}, keep_audio=prefs["keep_audio"])
            self.on_event({"type": "saved", "call_id": self.call_id})

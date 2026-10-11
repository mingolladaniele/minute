"""Recording session: capture both tracks to disk, transcribe live when the model is available.

Audio always wins: capture and the crash-safe WAVs start first, the model loads
meanwhile, and if it is missing or fails the call is still saved as audio and
marked for transcription later (see minute.worker).

The Recorder runs on a background thread and reports through on_event(dict):

    {"type": "state", "state": "loading|recording|saving|idle", "call_id": ...}
    {"type": "text", "label": "YOU|THEM", "t": "mm:ss", "delta": str, "tentative": str}
    {"type": "levels", "elapsed": seconds, "YOU": 0..1, "THEM": 0..1}
    {"type": "transcription_off", "reason": str}     live text unavailable, audio still recording
    {"type": "model_missing"}
    {"type": "engine", "state": "loading|ready|missing|error", "error": str|None}
    {"type": "saved" | "discarded", "call_id": ...}
"""
import json
import threading
import time
from datetime import datetime

import numpy as np
import pyaudiowpatch as pyaudio

from minute import config, settings, storage
from minute.capture import TARGET_RATE, Source, default_devices
from minute.engine import Engine
from minute.wavfile import WavWriter

FEED_SAMPLES = TARGET_RATE // 2  # feed the model in ~500 ms chunks
LEVEL_EVERY = 0.1
PAD_MARGIN = 0.5  # seconds of lag tolerated before a silent track is padded
DISCARD_AUTO_UNDER = 30  # seconds: auto-started "calls" shorter than this, with no notes, are dropped
VOICE_RMS = 0.015  # a chunk louder than this counts as someone talking
EMPTY_LIVE_SPEECH = 3.0  # seconds of speech with (almost) no live text = live transcription silently failed


class ModelMissing(RuntimeError):
    pass


class Track:
    def __init__(self, source, writer):
        self.source = source
        self.writer = writer
        self.stream = None
        self.pending = []
        self.committed = ""
        self.tentative = ""
        self.level = 0.0
        self.samples = 0
        self.voiced = 0.0  # seconds that sounded like speech

    def _append(self, x, keep_pending):
        self.writer.write(x)
        self.samples += len(x)
        if keep_pending:
            self.pending.append(x)

    def drain(self, keep_pending, elapsed):
        got = []
        while not self.source.queue.empty():
            got.append(self.source.queue.get_nowait())
        if not got:
            # WASAPI loopback sends nothing while the PC is silent: pad with silence so both
            # WAVs stay on the same clock (the worker re-transcribes from them and sorts by time).
            gap = int((elapsed - PAD_MARGIN) * TARGET_RATE) - self.samples
            if gap > 0:
                self._append(np.zeros(gap, dtype=np.float32), keep_pending)
        if got:
            x = np.concatenate(got)
            self._append(x, keep_pending)
            rms = float(np.sqrt(np.mean(x * x)))
            if rms > VOICE_RMS:
                self.voiced += len(x) / TARGET_RATE
            # RMS mapped to a rough 0..1 meter (speech sits around 0.02-0.2)
            self.level = max(rms * 6, self.level * 0.6)
        else:
            self.level *= 0.6

    def feed(self, force=False):
        n = sum(len(c) for c in self.pending)
        if self.stream is None or n == 0 or (n < FEED_SAMPLES and not force):
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


class Recorder:
    """model_path / language override the settings when given (None = use settings)."""

    def __init__(self, engine_dir, on_event, model_path=None, language=None):
        self.engine_dir = engine_dir
        self.model_path = model_path
        self.language = language
        self.on_event = on_event
        self.state = "idle"
        self.call_id = None
        self.auto = False
        self.engine_lock = threading.Lock()  # transcribe.cpp 0.x: one compute at a time per model
        self._engine = None
        self.engine_state = "unloaded"  # loading | ready | missing | error
        self.engine_error = None
        self._stop = threading.Event()
        self._thread = None

    @property
    def busy(self):
        return self.state != "idle"

    def _set_state(self, state):
        self.state = state
        self.on_event({"type": "state", "state": state, "call_id": self.call_id, "auto": self.auto})

    def _engine_event(self, state, error=None):
        self.engine_state, self.engine_error = state, error
        self.on_event({"type": "engine", "state": state, "error": error})

    def engine(self):
        """The loaded model, loading it on first use. Raises ModelMissing or the load error."""
        with self.engine_lock:
            if self._engine is None:
                model = self.model_path or config.find_model()
                if model is None:
                    self._engine_event("missing", "speech model not downloaded yet")
                    raise ModelMissing("speech model not downloaded yet")
                self._engine_event("loading")
                try:
                    self._engine = Engine(self.engine_dir, str(model))
                except Exception as e:
                    self._engine_event("error", str(e))
                    raise
                self._engine_event("ready")
            return self._engine

    def reset_engine(self, error):
        """Drop a model that failed mid-use (e.g. the GPU context was lost across sleep); the next use reloads it."""
        with self.engine_lock:
            old, self._engine = self._engine, None
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        self._engine_event("error", f"{error}. It will reload on the next call.")

    def start(self, seconds=None, auto=False, app=None):
        if self.busy:
            return False
        self._stop.clear()
        self.call_id = None
        self.auto = auto
        self.state = "loading"
        self._thread = threading.Thread(target=self._run, args=(seconds, app), daemon=True)
        self._thread.start()
        return True

    def stop(self, reason="user"):
        """reason ("window", "pill", "tray", "call ended", "quit"...) is reported once, for the log and the UI."""
        if self.busy and not self._stop.is_set():
            self.on_event({"type": "stop_requested", "reason": reason, "call_id": self.call_id})
        self._stop.set()

    def wait(self):
        if self._thread:
            self._thread.join()

    def close(self):
        self.stop("quit")
        self.wait()
        with self.engine_lock:
            if self._engine:
                self._engine.close()
                self._engine = None

    def _run(self, seconds, app):
        try:
            self._record(seconds, app)
        except Exception as e:  # surface failures to the UI instead of dying silently
            self.on_event({"type": "error", "message": str(e)})
        finally:
            self._set_state("idle")

    def _record(self, seconds, app):
        self._set_state("loading")
        prefs = settings.load()
        language = self.language if self.language is not None else prefs["language"]
        language = None if language == "auto" else language

        # 1. Audio first: devices, crash-safe WAVs, capture running.
        started = datetime.now()
        self.call_id = storage.new_call_id(started)
        call_dir = storage.start_call(self.call_id, started, auto=self.auto, app=app)
        pa = pyaudio.PyAudio()
        loopback, mic = default_devices(pa)
        tracks = [
            Track(Source(pa, loopback, "THEM"), WavWriter(call_dir / "them.wav", TARGET_RATE)),
            Track(Source(pa, mic, "YOU"), WavWriter(call_dir / "you.wav", TARGET_RATE)),
        ]
        for tr in tracks:
            tr.source.start()
        start = time.perf_counter()
        self._set_state("recording")

        # 2. Then the model. Audio captured while it loads is kept and transcribed once it's ready.
        live, error, engine = True, None, None
        try:
            engine = self.engine()
            for tr in tracks:
                tr.stream = engine.stream(language)
        except ModelMissing as e:
            live, error = False, str(e)
            self.on_event({"type": "model_missing"})
        except Exception as e:
            live, error = False, f"speech model failed to load: {e}"
        if not live:
            self.on_event({"type": "transcription_off", "reason": error})

        lines = []
        log = storage.open_live_log(self.call_id)

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
                log.write(json.dumps({"t": t, "label": tr.source.label, "text": delta}, ensure_ascii=False) + "\n")
            self.on_event({"type": "text", "label": tr.source.label, "t": t, "delta": delta, "tentative": tentative})

        def feed(tr, force=False):
            nonlocal live, error
            if not live:
                return
            try:
                with self.engine_lock:
                    fed = tr.feed(force)
                    if fed or force:
                        if force:
                            tr.stream.finalize()
                        emit_text(tr)
            except Exception as e:  # keep recording audio; the worker re-transcribes it later
                live, error = False, f"transcription stopped: {e}"
                self.on_event({"type": "transcription_off", "reason": error})
                self.reset_engine(f"the speech model stopped working ({e})")

        last_levels = 0.0
        try:
            while not self._stop.is_set():
                elapsed = time.perf_counter() - start
                if seconds is not None and elapsed >= seconds:
                    break
                for tr in tracks:
                    tr.drain(keep_pending=live, elapsed=elapsed)
                    feed(tr)
                if elapsed - last_levels >= LEVEL_EVERY:
                    last_levels = elapsed
                    self.on_event({"type": "levels", "elapsed": elapsed,
                                   **{tr.source.label: min(tr.level, 1.0) for tr in tracks}})
                time.sleep(0.05)
        finally:
            self._set_state("saving")
            for tr in tracks:
                tr.source.stop()
                tr.drain(keep_pending=live, elapsed=time.perf_counter() - start)
                tr.writer.close()
                feed(tr, force=True)
            pa.terminate()
            log.close()
            if engine is not None:
                for tr in tracks:
                    if tr.stream:
                        try:
                            engine.free_stream(tr.stream)
                        except Exception:
                            pass  # engine already reset after a failure
            duration = time.perf_counter() - start
            heard = "".join(text for _, _, text in lines).strip()
            if live and len(heard) < 10 and max(tr.voiced for tr in tracks) > EMPTY_LIVE_SPEECH:
                live, error = False, "live transcript came out empty although people were talking"
            self._finish(duration, lines, live, error)

    def _finish(self, duration, lines, live, error):
        call_id = self.call_id
        if (self.auto and duration < DISCARD_AUTO_UNDER and not storage.notes_of(call_id).strip()
                and storage.read_meta(call_id).get("title_source") != "user"):
            storage.delete_call(call_id)  # a voice note or a mic test, not a call
            self.on_event({"type": "discarded", "call_id": call_id})
            return
        storage.finish_call(call_id, duration, lines, transcript_ok=live, transcript_error=error)
        self.on_event({"type": "saved", "call_id": call_id})

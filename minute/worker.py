"""Background catch-up: nothing a failure leaves behind is lost, it is redone later.

- calls whose transcript is "pending" (model missing or broken, crash) are transcribed from their WAVs
- calls still waiting for enhanced notes or an AI title (API down, no credits, no key) get them
- with "Keep audio" off, WAVs are deleted only once their transcript is safely done

Runs at startup, after every call, when asked (kick) and every RETRY_EVERY seconds.
Steps back as soon as a recording starts: the model can only compute one thing at a time.
"""
import threading

from minute import enhance, settings, storage, titles, wavfile
from minute.capture import TARGET_RATE
from minute.recorder import ModelMissing

RETRY_EVERY = 300
CHUNK = TARGET_RATE // 2


class Interrupted(Exception):
    pass


def _stamp(samples):
    secs = int(samples / TARGET_RATE)
    return f"{secs // 60:02d}:{secs % 60:02d}"


class Worker:
    def __init__(self, recorder, on_event):
        self.recorder = recorder
        self.on_event = on_event
        self._kick = threading.Event()
        self._stop = False
        threading.Thread(target=self._loop, name="minute-worker", daemon=True).start()

    def kick(self):
        self._kick.set()

    def stop(self):
        self._stop = True
        self._kick.set()

    def _loop(self):
        while not self._stop:
            try:
                self.process()
            except Exception as e:
                self.on_event({"type": "error", "message": f"background work failed: {e}"})
            self._kick.wait(RETRY_EVERY)
            self._kick.clear()

    def process(self):
        prefs = settings.load()
        model_ok = True
        for call in reversed(storage.list_calls()):  # oldest first
            if self._stop or self.recorder.busy:
                return
            call_id = call["id"]
            if call.get("transcript") == "pending" and model_ok:
                try:
                    self._transcribe(call_id, prefs)
                except ModelMissing:
                    model_ok = False  # nothing to do until the model is downloaded
                except Interrupted:
                    return
                except Exception as e:
                    storage.update_meta(call_id, transcript_error=f"transcription failed: {e}")
                    self.on_event({"type": "call_updated", "call_id": call_id})
                    self.recorder.reset_engine(f"the speech model failed ({e})")
                    model_ok = False
            call = storage.read_meta(call_id)
            if call.get("transcript") == "done" and not prefs["keep_audio"] and storage.audio_paths(call_id):
                storage.delete_audio(call_id)
            if self._needs_enhance(call, prefs):
                self._enhance(call_id)
            if self._needs_title(call, prefs):
                self._title(call_id)

    @staticmethod
    def _needs_title(call, prefs):
        return (prefs["ai_titles"] and call.get("title_source", "default") == "default"
                and call.get("title_status") != "done" and call.get("transcript", "done") == "done")

    @staticmethod
    def _needs_enhance(call, prefs):
        return (prefs["ai_enhance"] and call.get("enhanced_status") != "done"
                and call.get("transcript", "done") == "done")

    def _enhance(self, call_id):
        self.on_event({"type": "enhancing", "call_id": call_id})
        try:
            enhance.enhance_call(call_id)
            self.on_event({"type": "enhanced", "call_id": call_id})
        except Exception as e:  # same as titles: keep everything, retry later
            storage.update_meta(call_id, enhanced_status="pending", enhanced_error=str(e))
            self.on_event({"type": "enhanced", "call_id": call_id, "error": str(e)})

    def _title(self, call_id):
        self.on_event({"type": "titling", "call_id": call_id})
        try:
            title = titles.title_call(call_id)
            if title is None and storage.read_meta(call_id).get("title_source") == "default":
                storage.update_meta(call_id, title_status="done")  # nothing to name: empty call
            self.on_event({"type": "title", "call_id": call_id, "title": title})
        except Exception as e:  # API down, credits finished, bad key: keep the call, retry later
            storage.update_meta(call_id, title_status="pending", title_error=str(e))
            self.on_event({"type": "title", "call_id": call_id, "title": None, "error": str(e)})

    def _transcribe(self, call_id, prefs):
        paths = storage.audio_paths(call_id)
        if not paths:  # audio already gone: keep whatever was heard live
            storage.set_blocks(call_id, storage.merge_blocks(storage.live_lines(call_id)))
            self.on_event({"type": "call_updated", "call_id": call_id})
            return
        with self.recorder.holding_engine() as engine:
            self._transcribe_with(engine, call_id, paths, prefs)

    def _transcribe_with(self, engine, call_id, paths, prefs):
        language = None if prefs["language"] == "auto" else prefs["language"]
        self.on_event({"type": "transcribing", "call_id": call_id})
        timed = []
        for label, path in paths.items():
            pcm, _ = wavfile.read(path)
            with self.recorder.engine_lock:
                stream = engine.stream(language)
            committed = ""
            try:
                for pos in range(0, len(pcm), CHUNK):
                    if self.recorder.busy or self._stop:
                        raise Interrupted
                    with self.recorder.engine_lock:
                        stream.feed(pcm[pos:pos + CHUNK])
                        text, _ = stream.text()
                    if len(text) > len(committed):
                        timed.append((pos, label, text[len(committed):]))
                        committed = text
                with self.recorder.engine_lock:
                    stream.finalize()
                    text, _ = stream.text()
                if len(text) > len(committed):
                    timed.append((len(pcm), label, text[len(committed):]))
            finally:
                with self.recorder.engine_lock:
                    engine.free_stream(stream)
        timed.sort(key=lambda x: x[0])
        storage.set_blocks(call_id, storage.merge_blocks([(_stamp(p), label, text) for p, label, text in timed]))
        self.on_event({"type": "call_updated", "call_id": call_id})

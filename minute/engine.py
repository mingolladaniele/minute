"""Thin ctypes wrapper around transcribe.cpp's C ABI (transcribe.dll).

One Engine loads the GGUF model once; each Stream is an independent
streaming session on that model. transcribe.cpp 0.x does not support
concurrent compute, so all Streams of an Engine must be fed from the
same thread.

Nemotron streaming only commits text at an end-of-utterance it detects, which
can take minutes in continuous speech (an interview, a video) or never come.
Stream therefore closes the utterance itself at pauses: finalize, keep the
text, begin again on the same session. Committed text stays append-only.
"""
import ctypes as C
import os
import re

import numpy as np

RATE = 16000
QUIET_RMS = 0.01  # a 100 ms window quieter than this is a pause
PAUSE = 0.7  # seconds of quiet that end an utterance...
MIN_SEGMENT = 3.0  # ...once it is this long (shorter cuts confuse language detection)
SOFT_MAX = 10.0  # past this, end at the next short breath
HARD_MAX = 20.0  # past this, end anyway
LANGUAGE_TAG = re.compile(r"\s*<[a-z]{2,3}(?:-[A-Z]{2})?>")  # e.g. <sl-SI>, leaked on short noisy utterances


class _StreamUpdate(C.Structure):
    _fields_ = [
        ("struct_size", C.c_uint64),
        ("result_changed", C.c_bool),
        ("is_final", C.c_bool),
        ("revision", C.c_int32),
        ("input_received_ms", C.c_int64),
        ("audio_committed_ms", C.c_int64),
        ("buffered_ms", C.c_int64),
        ("committed_changed", C.c_bool),
        ("tentative_changed", C.c_bool),
    ]


class _StreamText(C.Structure):
    _fields_ = [
        ("struct_size", C.c_uint64),
        ("full_text", C.c_char_p),
        ("full_text_bytes", C.c_uint64),
        ("committed_text", C.c_char_p),
        ("committed_text_bytes", C.c_uint64),
        ("tentative_text", C.c_char_p),
        ("tentative_text_bytes", C.c_uint64),
        ("raw_tentative_start_bytes", C.c_uint64),
    ]


class _RunParams(C.Structure):
    # C enums are int-sized; ctypes reproduces the header's padding.
    _fields_ = [
        ("struct_size", C.c_uint64),
        ("task", C.c_int),
        ("timestamps", C.c_int),
        ("pnc", C.c_int),
        ("itn", C.c_int),
        ("diarize", C.c_int),
        ("language", C.c_char_p),
        ("target_language", C.c_char_p),
        ("keep_special_tags", C.c_bool),
        ("family", C.c_void_p),
        ("spec_k_drafts", C.c_int32),
        ("vocabulary", C.c_void_p),
        ("n_vocabulary", C.c_int32),
        ("prompt", C.c_char_p),
        ("prefix", C.c_char_p),
    ]


def _load_lib(dll_dir):
    os.add_dll_directory(dll_dir)
    lib = C.CDLL(os.path.join(dll_dir, "transcribe.dll"))
    vp, P = C.c_void_p, C.POINTER
    lib.transcribe_status_string.restype = C.c_char_p
    lib.transcribe_model_load_file.argtypes = [C.c_char_p, vp, P(vp)]
    lib.transcribe_model_free.argtypes = [vp]
    lib.transcribe_session_init.argtypes = [vp, vp, P(vp)]
    lib.transcribe_session_free.argtypes = [vp]
    lib.transcribe_run_params_init.argtypes = [P(_RunParams)]
    lib.transcribe_stream_begin.argtypes = [vp, P(_RunParams), vp]
    lib.transcribe_stream_feed.argtypes = [vp, P(C.c_float), C.c_int, P(_StreamUpdate)]
    lib.transcribe_stream_finalize.argtypes = [vp, P(_StreamUpdate)]
    lib.transcribe_stream_get_text.argtypes = [vp, P(_StreamText)]
    lib.transcribe_stream_reset.argtypes = [vp]
    return lib


class TranscribeError(RuntimeError):
    pass


class Engine:
    def __init__(self, dll_dir, model_path):
        self._lib = _load_lib(dll_dir)
        self._check(self._lib.transcribe_init_backends_default(), "init_backends")
        self._model = C.c_void_p()
        self._check(self._lib.transcribe_model_load_file(model_path.encode(), None, C.byref(self._model)), "load_model")
        self._streams = []

    def _check(self, status, what):
        if status != 0:
            raise TranscribeError(f"{what}: {self._lib.transcribe_status_string(status).decode()}")

    def stream(self, language=None):
        """language: model code such as "it-IT", or None to autodetect."""
        s = Stream(self, language)
        self._streams.append(s)
        return s

    def free_stream(self, stream):
        stream.free()
        self._streams.remove(stream)

    def close(self):
        for s in self._streams:
            s.free()
        self._lib.transcribe_model_free(self._model)


class Stream:
    """A streaming session. feed() 16 kHz mono float32, read committed text."""

    def __init__(self, engine, language=None):
        self._e = engine
        self._lib = engine._lib
        self._session = C.c_void_p()
        engine._check(self._lib.transcribe_session_init(engine._model, None, C.byref(self._session)), "session_init")
        self._params = _RunParams()
        self._lib.transcribe_run_params_init(C.byref(self._params))
        if language:
            self._language = language.encode()  # kept alive for every begin
            self._params.language = self._language
        self._done = ""  # text of the utterances already closed
        self._segment = 0.0  # seconds fed since the current utterance began
        self._quiet = 0.0  # seconds of trailing quiet
        self._begin()

    def _begin(self):
        self._e._check(self._lib.transcribe_stream_begin(self._session, C.byref(self._params), None), "stream_begin")
        self._segment = 0.0

    def _raw_text(self):
        t = _StreamText()
        self._lib.transcribe_stream_text_init(C.byref(t))
        self._lib.transcribe_stream_get_text(self._session, C.byref(t))
        dec = lambda b: (b or b"").decode("utf-8", "replace")
        return dec(t.committed_text), dec(t.tentative_text)

    def _finalize_raw(self):
        upd = _StreamUpdate()
        self._lib.transcribe_stream_update_init(C.byref(upd))
        self._e._check(self._lib.transcribe_stream_finalize(self._session, C.byref(upd)), "stream_finalize")

    def _join(self, text):
        text = LANGUAGE_TAG.sub("", text).strip()
        if not text:
            return self._done
        return f"{self._done} {text}" if self._done else text

    def feed(self, pcm):
        pcm = np.ascontiguousarray(pcm, dtype=np.float32)
        upd = _StreamUpdate()
        self._lib.transcribe_stream_update_init(C.byref(upd))
        ptr = pcm.ctypes.data_as(C.POINTER(C.c_float))
        self._e._check(self._lib.transcribe_stream_feed(self._session, ptr, len(pcm), C.byref(upd)), "stream_feed")
        step = RATE // 10
        for i in range(0, len(pcm), step):
            w = pcm[i:i + step]
            self._quiet = self._quiet + len(w) / RATE if float(np.sqrt(np.mean(w * w))) < QUIET_RMS else 0.0
        self._segment += len(pcm) / RATE
        self._maybe_close()

    def _maybe_close(self):
        seg, quiet = self._segment, self._quiet
        if not ((quiet >= PAUSE and seg >= MIN_SEGMENT) or (seg >= SOFT_MAX and quiet >= 0.1) or seg >= HARD_MAX):
            return
        committed, tentative = self._raw_text()
        if not (committed.strip() or tentative.strip()):
            self._segment = 0.0 if quiet >= PAUSE else self._segment  # silence: nothing to close
            if seg >= HARD_MAX:
                self._lib.transcribe_stream_reset(self._session)
                self._begin()
            return
        self._finalize_raw()
        self._done = self._join(self._raw_text()[0])
        self._begin()

    def finalize(self):
        self._finalize_raw()
        self._done = self._join(self._raw_text()[0])
        self._lib.transcribe_stream_reset(self._session)

    def text(self):
        """(committed, tentative), copied out; committed only ever grows."""
        committed, tentative = self._raw_text()
        return self._join(committed), tentative

    def free(self):
        if self._session:
            self._lib.transcribe_session_free(self._session)
            self._session = C.c_void_p()

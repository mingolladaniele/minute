"""Crash-safe 16 kHz mono WAV: samples go to disk as they arrive and the header is
re-patched every few seconds, so a crash loses at most the last moments of audio."""
import struct
import time
import wave

import numpy as np

HEADER_EVERY = 5.0  # seconds


class WavWriter:
    def __init__(self, path, rate):
        self.path = path
        self.rate = rate
        self.frames = 0
        self._f = open(path, "wb")
        self._f.write(self._header())
        self._last_patch = time.monotonic()

    def _header(self):
        data = self.frames * 2
        return (b"RIFF" + struct.pack("<I", 36 + data) + b"WAVE"
                + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, self.rate, self.rate * 2, 2, 16)
                + b"data" + struct.pack("<I", data))

    def write(self, pcm):
        self._f.write((np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes())
        self.frames += len(pcm)
        if time.monotonic() - self._last_patch >= HEADER_EVERY:
            self._patch()

    def _patch(self):
        pos = self._f.tell()
        self._f.seek(0)
        self._f.write(self._header())
        self._f.seek(pos)
        self._f.flush()
        self._last_patch = time.monotonic()

    def close(self):
        if not self._f.closed:
            self._patch()
            self._f.close()


def repair(path):
    """Fix the header of a WAV left behind by a crash (size fields lag the data)."""
    with open(path, "r+b") as f:
        f.seek(0, 2)
        data = max(0, f.tell() - 44)
        data -= data % 2
        f.seek(4)
        f.write(struct.pack("<I", 36 + data))
        f.seek(40)
        f.write(struct.pack("<I", data))


def read(path):
    """float32 mono samples and the sample rate."""
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
    return pcm, rate


def duration(path):
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()

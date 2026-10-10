"""Audio capture on Windows via WASAPI: system output (loopback) and microphone.

Each Source converts what it receives to 16 kHz mono float32 and pushes
chunks onto its queue. WASAPI loopback delivers nothing while the system
is silent, so the "them" queue simply stays empty between speakers.
"""
import queue

import numpy as np
import pyaudiowpatch as pyaudio

TARGET_RATE = 16000


class Resampler:
    """Streaming linear resampler that keeps phase across chunks."""

    def __init__(self, src_rate):
        self.step = src_rate / TARGET_RATE
        self.pos = 0.0
        self.tail = np.zeros(0, dtype=np.float32)

    def __call__(self, x):
        x = np.concatenate([self.tail, x])
        idx = np.arange(self.pos, len(x) - 1, self.step)
        out = np.interp(idx, np.arange(len(x)), x).astype(np.float32)
        consumed = int(idx[-1]) if len(idx) else 0
        self.pos = (idx[-1] + self.step - consumed) if len(idx) else self.pos
        self.tail = x[consumed:]
        return out


class Source:
    def __init__(self, pa, device, label):
        self.label = label
        self.name = device["name"]
        self.channels = max(1, device["maxInputChannels"])
        self.rate = int(device["defaultSampleRate"])
        self.queue = queue.Queue()
        self._resample = Resampler(self.rate)
        self._stream = pa.open(
            format=pyaudio.paFloat32,
            channels=self.channels,
            rate=self.rate,
            input=True,
            input_device_index=device["index"],
            frames_per_buffer=self.rate // 10,
            stream_callback=self._callback,
            start=False,
        )

    def _callback(self, in_data, frame_count, time_info, status):
        x = np.frombuffer(in_data, dtype=np.float32).reshape(-1, self.channels).mean(axis=1)
        self.queue.put(self._resample(x))
        return None, pyaudio.paContinue

    def start(self):
        self._stream.start_stream()

    def stop(self):
        self._stream.stop_stream()
        self._stream.close()


def default_devices(pa):
    """(loopback of default speakers, default mic), both WASAPI."""
    wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
    speakers = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
    loopback = speakers if speakers.get("isLoopbackDevice") else None
    if loopback is None:
        for dev in pa.get_loopback_device_info_generator():
            if speakers["name"] in dev["name"]:
                loopback = dev
                break
    if loopback is None:
        raise RuntimeError(f"no WASAPI loopback device for {speakers['name']!r}")
    mic = pa.get_device_info_by_index(wasapi["defaultInputDevice"])
    return loopback, mic

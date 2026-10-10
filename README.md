# minute

Local meeting notes for Windows. `minute` listens to your calls — Meet, Zoom, Teams, anything — by capturing system audio (them) and your microphone (you), transcribes both live on your machine, and saves a transcript.

No bot joins the call, and no audio leaves your PC.

## How it works

- **Capture**: WASAPI loopback for system output and the default microphone, resampled to 16 kHz mono.
- **Transcription**: [transcribe.cpp](https://github.com/handy-computer/transcribe.cpp) (ggml, Vulkan) running NVIDIA Nemotron Speech Streaming 3.5 (0.6B, multilingual). The model is loaded once, with one streaming session per speaker track.
- **Output**: `recordings/<timestamp>/` with `loro.wav`, `tu.wav` and `transcript.md`.

## Setup

```powershell
uv sync
uv run python scripts/fetch_engine.py   # transcribe.cpp native library -> vendor/
```

The model is the GGUF that [Handy](https://handy.computer) downloads (`handy-computer/nemotron-3.5-asr-streaming-0.6b-gguf`). Point to another one with `--model` or `MINUTE_MODEL`.

## Run

```powershell
uv run python -m minute              # until Ctrl+C
uv run python -m minute --seconds 60
```

Use headphones: with speakers, the mic also picks up the other people.

<img src="assets/icon.png" width="96" alt="minute icon">

# minute

Local meeting notes for Windows. `minute` listens to your calls (Meet, Zoom, Teams, anything) by capturing system audio (them) and your microphone (you), transcribes both live on your machine, and saves a transcript.

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
uv run python -m minute                       # desktop app
uv run python -m minute record --seconds 60   # terminal only, Ctrl+C to stop
```

**The app.** Hit **New note** when your call starts. You get a page to write your own notes while minute transcribes in the background; the live transcript sits behind the **Transcript** pill at the bottom. A small pill docks to the right edge of the screen while recording: green bars mean it hears audio, hover it to stop, click it to open minute. Closing the window keeps minute in the tray.

Each call is saved to `recordings/<timestamp>/`: `notes.md`, `transcript.md`, `blocks.json`, `meta.json`, `you.wav`, `them.wav`. Set `MINUTE_RECORDINGS` to save somewhere else (an Obsidian vault, for example).

**Options:** `--lang it-IT` (default) or any model language code, `--lang auto` to autodetect; `--model` / `MINUTE_MODEL`; `--engine-dir` / `MINUTE_ENGINE_DIR`.

Use headphones: with speakers, the mic also picks up the other people.

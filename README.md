<img src="assets/icon.png" width="96" alt="minute icon">

# minute

Local meeting notes for Windows. `minute` listens to your calls (Meet, Zoom, Teams, anything) by capturing system audio (them) and your microphone (you), transcribes both live on your machine, and saves a transcript.

No bot joins the call, and no audio leaves your PC.

## Install

Run `minute-setup-<version>.exe` from `dist\` (no admin rights needed). It installs for your user, adds minute to the Start menu and, if you keep the box ticked, opens it at login in the tray.

The speech model is the GGUF that [Handy](https://handy.computer) already downloads (`handy-computer/nemotron-3.5-asr-streaming-0.6b-gguf`). On a machine without Handy, minute offers to download it once (about 750 MB).

## Use

Hit **New note** when a call starts and write your own notes while minute transcribes in the background. The live transcript sits behind the **Transcript** pill at the bottom. While recording, a small pill docks to the right edge of the screen: green bars mean it hears audio, hover it to stop, click it to open minute. Closing the window keeps minute in the tray.

When the call ends, minute names it with AI from your notes and the transcript (DeepSeek V4.1 Flash by default, using the key of your pi coding agent). Calls you rename yourself are never touched.

Each call is saved to `Documents\minute\<timestamp>\`: `notes.md`, `transcript.md`, `blocks.json`, `meta.json`, and `you.wav` / `them.wav` if you keep audio.

**Settings**: open at login, call language, recordings folder, keep audio, AI titles (on/off, key from pi or your own, model, endpoint; any OpenAI-compatible API works). They live in `%APPDATA%\minute\settings.json`.

Use headphones: with speakers, the mic also picks up the other people.

## How it works

- **Capture**: WASAPI loopback for system output and the default microphone, resampled to 16 kHz mono.
- **Transcription**: [transcribe.cpp](https://github.com/handy-computer/transcribe.cpp) (ggml, Vulkan) running NVIDIA Nemotron Speech Streaming 3.5 (0.6B, multilingual) through its C ABI. The model is loaded once, with one streaming session per speaker track.
- **App**: pywebview window, native layered-window indicator, pystray tray icon.

## Develop

```powershell
uv sync
uv run python scripts/fetch_engine.py          # transcribe.cpp native library -> vendor/
uv run python -m minute                         # the app
uv run python -m minute record --seconds 60     # terminal only, prints the live transcript
powershell -ExecutionPolicy Bypass -File scripts\build.ps1   # dist\minute\ and the installer
```

`--lang`, `--model` and `--engine-dir` (or `MINUTE_LANG`, `MINUTE_MODEL`, `MINUTE_ENGINE_DIR`) override the settings; `MINUTE_RECORDINGS` overrides the folder. Building the installer needs [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup --scope user`).

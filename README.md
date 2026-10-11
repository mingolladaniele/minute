<img src="assets/icon.png" width="96" alt="minute icon">

# minute

Local meeting notes for Windows. `minute` listens to your calls (Meet, Zoom, Teams, anything) by capturing system audio (them) and your microphone (you), transcribes both live on your machine, and saves a transcript.

No bot joins the call, and no audio leaves your PC.

## Install

Run `minute-setup-<version>.exe` from `dist\` (no admin rights needed). It installs for your user, adds minute to the Start menu and, if you keep the box ticked, opens it at login in the tray.

The speech model is the GGUF that [Handy](https://handy.computer) already downloads (`handy-computer/nemotron-3.5-asr-streaming-0.6b-gguf`). On a machine without Handy, minute offers to download it once (about 750 MB).

## Use

minute is meant to be forgotten. With **Record calls automatically** on (the default), a note starts by itself when Meet, Zoom, Teams, Slack, WhatsApp or another call app turns on your microphone, and stops 45 seconds after the call app lets go of it. Dictation tools (Handy, Wispr Flow...) never trigger it, and short auto-recordings with nothing in them are dropped. You can also hit **New note** yourself.

While recording, a small pill docks to the right edge of the screen: green bars mean it hears audio, hover it to stop, click it to open minute. In the note you write your own notes (Markdown: `- ` lists that continue on Enter, Tab to nest, `#` headings, **bold** with Ctrl+B or `**`), and the live transcript sits behind the **Transcript** pill. The home bar warns you if the speech model isn't ready; when all is well it stays quiet.

When the call ends, minute uses AI to:

- write **Enhanced** notes: your notes as the skeleton, completed with what was said, as a summary, topics, decisions and next steps. Switch between **My notes** and **Enhanced**; both are editable.
- name the call. Calls you rename yourself are never touched.

Pick the AI in **Settings > AI**, then press **Test**:

- **DeepSeek** (default): DeepSeek V4.1 Flash. Paste a key from [platform.deepseek.com](https://platform.deepseek.com/api_keys). If you use the [pi coding agent](https://github.com/badlogic/pi-mono) logged in to DeepSeek, minute can read its key instead.
- **Ollama**: a model running on your PC, free and fully offline: nothing leaves your computer. Install [Ollama](https://ollama.com/download), pull a model (`ollama pull qwen3:8b`), enter its name, and raise Ollama's context length to 32k or more so long calls fit.
- **Other**: any OpenAI-compatible chat API (OpenAI, OpenRouter, Groq, LM Studio...): endpoint, model and key.

**Ask anything**: the bar at the bottom answers questions in plain language. In a note it uses that call (notes, enhanced notes, transcript); on the home page it searches all your calls and links the ones it used.

Without AI, minute still records, transcribes and keeps your notes.

**Nothing is lost when something fails.** Audio is written to disk as it is recorded, and the raw live text line by line. If the speech model is missing or breaks, the call is kept as audio and transcribed later from it; if the live text comes out empty although people talked, it is redone from the audio too. If the AI API fails (no credits, bad key, outage), the note says why and minute retries every few minutes. Calls cut short by a crash are recovered on the next start.

Each call is saved to `Documents\minute\<timestamp>\`: `notes.md`, `enhanced.md`, `transcript.md`, `blocks.json`, `live.jsonl`, `meta.json`, and `you.wav` / `them.wav` (deleted after a successful transcript if you turn **Keep audio** off).

**Memory**: between calls minute idles at about 150 MB; the speech model (about 1 GB) is loaded when a call starts and freed after 10 minutes without calls.

**Settings**: record calls automatically, open at login, call language (detected automatically by default; a fixed language only helps if every call is in it), recordings folder, keep audio, AI titles and enhanced notes (provider, key, model). They live in `%APPDATA%\minute\settings.json`.

Use headphones: with speakers, the mic also picks up the other people. Anything else playing on the PC during a call ends up in the transcript too.

## Try it alone

No call and nobody to call? Double-click `scripts\simulate-call.cmd` (needs ffmpeg). A fake call app holds your microphone for 3 minutes, so minute starts on its own; a recording plays through the speakers as the other people (Handy's recordings by default, or `-Audio path\to\file`), and you can talk into your mic and take notes. When it ends, minute stops by itself and writes the title and the enhanced notes. Wear headphones.

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

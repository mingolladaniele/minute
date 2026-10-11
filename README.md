<p align="center">
  <img src="assets/icon.png" width="96" alt="minute icon">
</p>

<h1 align="center">minute</h1>

<p align="center"><b>minute turns every call into notes on your own PC: free, no account, no bot, and plain files you keep forever.</b></p>

<p align="center">Open-source meeting notes for Windows.</p>

- **Your files.** Every call is plain Markdown in a folder you choose. Open it in Obsidian or any editor.
- **Private.** Transcription runs on your PC, no audio leaves it. With Ollama, nothing does. Open source, so you can check.
- **Free, no limits.** Every call stays, forever. No account, no sign-up.
- **Hear it again.** Keeps the audio of each call, you and them on separate tracks, playable from the note. Turn it off in Settings.
- **Your AI.** DeepSeek, Ollama offline, or any OpenAI-compatible API.
- **Any call app.** Meet, Zoom, Teams, Slack, WhatsApp. Starts when a call takes the mic, stops when it ends. No bot joins.
- **Your notes, enriched.** Write what matters, minute completes it with the transcript: summary, decisions, next steps.
- **Ask.** Questions about one call or all of them, with links to the calls it used.
- **32 languages**, detected on their own, even when a call switches language.

## Install

Download `minute-setup-<version>.exe` from [Releases](https://github.com/mingolladaniele/minute/releases) and run it (no admin rights). The speech model (about 750 MB) downloads once.

## Choose the AI

**Settings > AI**, then **Test**:

- **DeepSeek** (default): a key from [platform.deepseek.com](https://platform.deepseek.com/api_keys).
- **Ollama** (free, offline): `ollama pull qwen3:8b`, enter `qwen3:8b`, raise Ollama's context length to 32k.
- **Other**: any OpenAI-compatible API (endpoint, model, key).

Set **Your name** too, so Ask knows which tasks are yours.

## Run from source

```powershell
uv sync
uv run python scripts/fetch_engine.py   # speech engine into vendor\
uv run python -m minute
```

## Test

```powershell
scripts\simulate-call.cmd   # a fake 3-minute call; needs ffmpeg, wear headphones
```

## Build

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1   # installer in dist\; needs Inno Setup 6
```

<img src="assets/icon.png" width="96" alt="minute icon">

# minute

**Free, open-source meeting notes for Windows. Your calls stay on your PC, in files you own.**

- **Records any call** (Meet, Zoom, Teams, Slack, WhatsApp) on its own. No bot joins.
- **Transcribes live, locally.** No audio leaves your PC.
- **AI notes**: your notes plus what was said, turned into topics, decisions and next steps. Ask anything across all your calls.
- **You own everything**: plain Markdown files in `Documents\minute\`. Fully offline with Ollama.

## Install

Download `minute-setup-<version>.exe` from [Releases](https://github.com/mingolladaniele/minute/releases) and run it (no admin rights). The speech model (about 750 MB) downloads once on first start.

## Choose the AI

**Settings > AI**, then **Test**:

- **DeepSeek** (default): paste a key from [platform.deepseek.com](https://platform.deepseek.com/api_keys).
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

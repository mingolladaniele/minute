"""Minimal client for an OpenAI-compatible chat API (DeepSeek V4.1 Flash by default), shared by titles and notes."""
import json
import urllib.error
import urllib.request

from minute import settings

HTTP_REASONS = {
    401: "the API key was rejected",
    402: "the API account has run out of credits",
    403: "the API key isn't allowed to use this model",
    404: "the model or endpoint doesn't exist",
    429: "too many requests to the AI service",
}


class AIError(RuntimeError):
    pass


def _http_reason(e):
    """A sentence a person can act on, plus the provider's own message."""
    try:
        detail = json.loads(e.read())["error"]["message"]
    except Exception:
        detail = ""
    reason = HTTP_REASONS.get(e.code) or ("the AI service is down" if e.code >= 500 else f"HTTP {e.code}")
    return f"{reason} ({detail[:120]})" if detail else reason


def transcript_text(blocks, limit):
    """Speaker-tagged transcript, trimmed from the middle so both the opening and the wrap-up survive."""
    text = "\n".join(f"{b['label']} [{b['t']}]: {b['text']}" for b in blocks if b["text"])
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n[...]\n{text[-half:]}"


def chat(system, user, max_tokens, timeout=60):
    values = settings.load()
    key = settings.ai_key(values)
    if not key:
        raise AIError("no API key: add one in Settings, or log in to DeepSeek in pi")
    body = {
        "model": values["ai_model"],
        "max_tokens": max_tokens,  # reasoning tokens count against this
        "reasoning_effort": "low",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        values["ai_base_url"].rstrip("/") + "/chat/completions",
        json.dumps(body).encode(),
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            reply = json.load(r)
    except urllib.error.HTTPError as e:
        raise AIError(_http_reason(e)) from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise AIError(f"cannot reach {values['ai_base_url']}: {getattr(e, 'reason', e)}") from e
    choice = reply["choices"][0]
    if choice.get("finish_reason") == "length" and not (choice["message"].get("content") or "").strip():
        raise AIError("the model ran out of tokens before answering")
    return choice["message"].get("content") or ""

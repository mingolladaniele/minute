"""Minimal client for an OpenAI-compatible chat API (DeepSeek V4.1 Flash by default, or a local model
through Ollama), shared by titles and notes."""
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


def chat(system, user, max_tokens, timeout=60, history=()):
    """history: earlier (user, assistant) turns of a conversation, oldest first."""
    values = settings.load()
    local = settings.ai_is_local(values)
    key = None if local else settings.ai_key(values)
    if not local and not key:
        raise AIError("no API key: add one in Settings")
    if not values["ai_base_url"].strip().startswith(("http://", "https://")):
        raise AIError("no endpoint: add the provider's address in Settings")
    if not values["ai_model"].strip():
        raise AIError("no model chosen: add one in Settings")
    body = {
        "model": values["ai_model"].strip(),
        "max_tokens": max_tokens,  # reasoning tokens count against this
        "messages": [{"role": "system", "content": system},
                     *[{"role": r, "content": c} for q, a in history for r, c in (("user", q), ("assistant", a))],
                     {"role": "user", "content": user}],
    }
    if "deepseek.com" in values["ai_base_url"]:
        body["reasoning_effort"] = "low"  # other providers may reject the field
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if local:
        timeout *= 5  # a model on this PC can be far slower than a hosted one
    req = urllib.request.Request(values["ai_base_url"].rstrip("/") + "/chat/completions",
                                 json.dumps(body).encode(), headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            reply = json.load(r)
    except urllib.error.HTTPError as e:
        raise AIError(_http_reason(e)) from e
    except (urllib.error.URLError, TimeoutError) as e:
        if local:
            raise AIError(f"the local model isn't answering at {values['ai_base_url']}: is Ollama running?") from e
        raise AIError(f"cannot reach {values['ai_base_url']}: {getattr(e, 'reason', e)}") from e
    choice = reply["choices"][0]
    if choice.get("finish_reason") == "length" and not (choice["message"].get("content") or "").strip():
        raise AIError("the model ran out of tokens before answering")
    return choice["message"].get("content") or ""

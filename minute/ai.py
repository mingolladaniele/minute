"""Minimal client for an OpenAI-compatible chat API (DeepSeek V4.1 Flash by default, or a local model
through Ollama), shared by titles and notes."""
import json
import urllib.error
import urllib.request

from pydantic import ValidationError

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


CUT = "[... part of the call left out here for length ...]"  # says what it is, so the model doesn't take it as silence


def transcript_text(blocks, limit):
    """Speaker-tagged transcript, trimmed from the middle so both the opening and the wrap-up survive."""
    text = "\n".join(f"{b['label']} [{b['t']}]: {b['text']}" for b in blocks if b["text"])
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n{CUT}\n{text[-half:]}"


def notes_and_transcript(notes, transcript):
    """The user's notes and the transcript, each in its own tags. An empty one is left out rather than marked
    "(none)": a placeholder invites the model to write that something is missing."""
    parts = [f"<notes>\n{notes}\n</notes>" if notes else "", f"<transcript>\n{transcript}\n</transcript>" if transcript else ""]
    return "\n\n".join(p for p in parts if p)


def user_name():
    """Who YOU is, from Settings; empty when the user hasn't said."""
    return settings.load()["user_name"].strip()


def chat(system, user, max_tokens, timeout=60, history=(), json_mode=False, reasoning="low"):
    """history: earlier (user, assistant) turns of a conversation, oldest first.
    reasoning: how hard a reasoning model thinks (DeepSeek: none, minimal, low, medium, high)."""
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
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if "deepseek.com" in values["ai_base_url"]:
        body["reasoning_effort"] = reasoning  # other providers may reject the field
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


def chat_typed(system, user, schema, max_tokens=2000, timeout=60, retries=2, validation_context=None,
               reasoning="low"):
    """A reply validated against a pydantic model: JSON mode, then validation; when the reply doesn't fit,
    the model is shown its reply and the validation errors and asked again (up to `retries` times)."""
    system = (f"{system}\n\nReply with a single JSON object, nothing else, matching this JSON schema:\n"
              f"{json.dumps(schema.model_json_schema(), ensure_ascii=False)}")
    history, ask = [], user
    for attempt in range(retries + 1):
        reply = chat(system, ask, max_tokens=max_tokens, timeout=timeout, history=history, json_mode=True,
                     reasoning=reasoning)
        try:
            return schema.model_validate_json(reply.strip() or "{}", context=validation_context)
        except ValidationError as e:
            problems = "; ".join(f"{'.'.join(map(str, err['loc'])) or 'reply'}: {err['msg']}" for err in e.errors())
        if attempt < retries:
            history += [(ask, reply)]
            ask = f"That reply is not valid: {problems}. Reply again with the corrected JSON object only."
    raise AIError(f"the model's reply didn't have the expected shape ({problems[:200]})")

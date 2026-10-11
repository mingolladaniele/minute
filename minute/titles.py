"""AI call titles through any OpenAI-compatible chat API (DeepSeek V4.1 Flash by default)."""
import json
import urllib.error
import urllib.request

from minute import settings, storage

MAX_TRANSCRIPT_CHARS = 12000
SYSTEM = (
    "You name meeting notes. Read the user's notes and the call transcript, then reply with a short, specific "
    "title of 3 to 7 words that says what the call was about. Write it in the language the call was held in. "
    "No quotes, no trailing punctuation, no dates, no words like 'call' or 'meeting' unless they add meaning. "
    "Reply with the title only."
)


class TitleError(RuntimeError):
    pass


def _excerpt(blocks):
    """Speaker-tagged transcript, trimmed from the middle so both the opening and the wrap-up survive."""
    text = "\n".join(f"{b['label']}: {b['text']}" for b in blocks if b["text"])
    if len(text) <= MAX_TRANSCRIPT_CHARS:
        return text
    half = MAX_TRANSCRIPT_CHARS // 2
    return f"{text[:half]}\n[...]\n{text[-half:]}"


HTTP_REASONS = {
    401: "the API key was rejected",
    402: "the API account has run out of credits",
    403: "the API key isn't allowed to use this model",
    404: "the model or endpoint doesn't exist",
    429: "too many requests to the AI service",
}


def _http_reason(e):
    """A sentence a person can act on, plus the provider's own message."""
    try:
        detail = json.loads(e.read())["error"]["message"]
    except Exception:
        detail = ""
    reason = HTTP_REASONS.get(e.code) or ("the AI service is down" if e.code >= 500 else f"HTTP {e.code}")
    return f"{reason} ({detail[:120]})" if detail else reason


def _clean(title):
    title = title.strip().splitlines()[0] if title.strip() else ""
    return title.strip().strip("\"'“”«»*#").rstrip(".").strip()[:90]


def generate(call):
    """Title for a loaded call (storage.load_call), or None when there is nothing to name."""
    transcript, notes = _excerpt(call["blocks"]), call.get("notes", "").strip()
    if not transcript and not notes:
        return None
    values = settings.load()
    key = settings.ai_key(values)
    if not key:
        raise TitleError("no API key: add one in Settings, or log in to DeepSeek in pi")
    body = {
        "model": values["ai_model"],
        "max_tokens": 1500,  # reasoning tokens count against this
        "reasoning_effort": "low",
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"My notes:\n{notes or '(none)'}\n\nTranscript:\n{transcript or '(empty)'}"},
        ],
    }
    req = urllib.request.Request(
        values["ai_base_url"].rstrip("/") + "/chat/completions",
        json.dumps(body).encode(),
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            reply = json.load(r)
    except urllib.error.HTTPError as e:
        raise TitleError(_http_reason(e)) from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise TitleError(f"cannot reach {values['ai_base_url']}: {e}") from e
    title = _clean(reply["choices"][0]["message"].get("content") or "")
    return title or None


def title_call(call_id):
    """Name a finished call with AI unless the user already did. Returns the new title or None."""
    if not settings.load()["ai_titles"]:
        return None
    call = storage.load_call(call_id)
    if call.get("title_source") == "user":
        return None
    title = generate(call)
    # The user may have renamed the call while the request was in flight.
    if not title or storage.load_call(call_id).get("title_source") == "user":
        return None
    storage.rename_call(call_id, title, source="ai")
    return title

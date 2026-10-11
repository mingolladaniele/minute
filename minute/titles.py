"""AI call titles."""
from minute import ai, settings, storage

MAX_TRANSCRIPT_CHARS = 12000
SYSTEM = (
    "You name meeting notes. Read the user's notes and the call transcript, then reply with a short, specific "
    "title of 3 to 7 words that says what the call was about. Write it in the language the call was held in. "
    "No quotes, no trailing punctuation, no dates, no words like 'call' or 'meeting' unless they add meaning. "
    "Reply with the title only."
)

TitleError = ai.AIError


def _clean(title):
    title = title.strip().splitlines()[0] if title.strip() else ""
    return title.strip().strip("\"'“”«»*#").rstrip(".").strip()[:90]


def generate(call):
    """Title for a loaded call (storage.load_call), or None when there is nothing to name."""
    transcript, notes = ai.transcript_text(call["blocks"], MAX_TRANSCRIPT_CHARS), call.get("notes", "").strip()
    if not transcript and not notes:
        return None
    reply = ai.chat(SYSTEM, f"My notes:\n{notes or '(none)'}\n\nTranscript:\n{transcript or '(empty)'}",
                    max_tokens=1500)
    return _clean(reply) or None


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

"""Enhanced notes: the user's own notes, completed and structured with what was said in the call."""
from minute import ai, settings, storage

MAX_TRANSCRIPT_CHARS = 200_000  # roughly a 3-hour call; the model's context is far larger
SYSTEM = """You write meeting notes. You get the user's own rough notes and the call transcript.

Speakers: YOU is the user (their microphone). THEM is everyone else on the call (one or more people, \
from the computer's audio); when the transcript makes names clear, use the names.

Write the notes in Markdown, in the language the call was held in:
- Start with one or two sentences saying what the call was about and how it ended. No heading for it.
- Then one "### " section per topic, in the order they came up. If the user's notes have headings or \
clear topics, use those as the sections, in their order.
- Under each section, short bullet points ("- "). Concrete beats vague: keep names, numbers, prices, \
dates, deadlines, tools and examples that were said. Sub-points indented by two spaces.
- The user's notes are the skeleton: every point they wrote must appear, in their order, kept close \
to their wording and expanded with the relevant detail from the transcript. Then add what they missed \
that matters. A single short note is a bullet, not a heading. A note the call never touched on stays \
as written, under the section it fits best or under a final section titled "From your notes" \
(translated into the call's language, like every heading).
- If decisions were made, a "### Decisions" section.
- If anything was agreed to be done, end with "### Next steps": "- **Owner**: task (by when, if said)". \
Use "You" for things the user will do.
- Use **bold** only for the few things that matter most.

Never invent anything that is not in the transcript or the notes: no guesses in brackets, and no \
sentences about what is missing (if there are no decisions, there is simply no Decisions section). \
Leave out small talk. If the transcript is unclear in places, keep what is certain and skip the rest. \
Reply with the Markdown only, no preamble and no code fences."""


def _clean(md):
    md = md.strip()
    if md.startswith("```"):
        md = md.split("\n", 1)[1] if "\n" in md else ""
        md = md.rsplit("```", 1)[0]
    return md.strip()


def generate(call):
    """Enhanced Markdown for a loaded call (storage.load_call), or None when there is nothing to work with."""
    transcript, notes = ai.transcript_text(call["blocks"], MAX_TRANSCRIPT_CHARS), call.get("notes", "").strip()
    if not transcript and not notes:
        return None
    user = (f"Call: {call.get('title', '')}, {call.get('started', '').replace('T', ' ')}, "
            f"{round(call.get('duration', 0) / 60)} min\n\n"
            f"My notes:\n{notes or '(none)'}\n\nTranscript:\n{transcript or '(empty)'}")
    return _clean(ai.chat(SYSTEM, user, max_tokens=12000, timeout=180)) or None


def enhance_call(call_id):
    """Write enhanced.md for a finished call. Returns the Markdown, or None when there was nothing to write."""
    if not settings.load()["ai_enhance"]:
        return None
    md = generate(storage.load_call(call_id))
    if md:
        storage.save_enhanced(call_id, md, source="ai")
    else:
        storage.update_meta(call_id, enhanced_status="done")  # empty call: nothing to enhance
    return md

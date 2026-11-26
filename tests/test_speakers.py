import pytest

from minute import ai, enhance, speakers

TRANSCRIPT = ("THEM [00:01]: Ciao Daniele, sono Sara di Acme.\n"
              "YOU [00:04]: Ciao Sara, grazie. Marco ci raggiunge dopo?\n"
              "THEM [00:09]: No, Marco oggi non c'è.")


def test_names_must_be_in_the_call():
    said = TRANSCRIPT
    assert speakers.clean_names(["Sara", "Giulia"], said) == ["Sara"]


def test_unsaid_surname_is_dropped():
    assert speakers.clean_names(["Sara Rossi"], TRANSCRIPT) == ["Sara"]


def test_user_is_never_them():
    assert speakers.clean_names(["Daniele", "Sara", "sara"], TRANSCRIPT, "Daniele Mingolla") == ["Sara"]


def test_accents_and_case_match():
    assert speakers.clean_names(["José"], "THEM [00:01]: hola, soy jose") == ["José"]


def test_typed_names_split():
    assert speakers.parse_typed(" Sara,  Marco Rossi e Luca ") == ["Sara", "Marco Rossi", "Luca"]
    assert speakers.parse_typed("Sara and sara") == ["Sara"]
    assert speakers.parse_typed("") == []


def test_describe():
    assert speakers.describe({}) == ""
    assert speakers.describe({"them_names": ["Sara"], "them_single": True}).startswith("THEM is one person: Sara")
    assert "include: Sara, Marco" in speakers.describe({"them_names": ["Sara", "Marco"], "them_single": False})


@pytest.fixture
def fake_ai(monkeypatch):
    sent = {}
    monkeypatch.setattr(ai, "user_name", lambda: "Daniele")
    monkeypatch.setattr(ai, "transcript_text", lambda blocks, limit: TRANSCRIPT)

    def chat_typed(system, user, schema, **kwargs):
        sent["system"] = system
        return schema.model_validate({"people": [{"name": "Sara", "quote": "sono Sara"},
                                                 {"name": "Giulia Bianchi", "quote": "made up"}],
                                      "single": True})

    def chat(system, user, **kwargs):
        sent["user"] = user
        return "- Sara sends the quote"

    monkeypatch.setattr(ai, "chat_typed", chat_typed)
    monkeypatch.setattr(ai, "chat", chat)
    return sent


def test_detect_keeps_only_real_names(fake_ai):
    assert speakers.detect({"blocks": [], "notes": ""}) == (["Sara"], True)
    assert "The user is Daniele." in fake_ai["system"]


def test_detect_skips_calls_without_them(fake_ai, monkeypatch):
    monkeypatch.setattr(ai, "transcript_text", lambda blocks, limit: "YOU [00:01]: just me")
    assert speakers.detect({"blocks": [], "notes": ""}) == ([], False)


def test_notes_prompt_gets_the_names(fake_ai):
    enhance.generate({"blocks": [], "notes": "", "them_names": ["Sara"], "them_single": True})
    assert "THEM is one person: Sara." in fake_ai["user"]
    enhance.generate({"blocks": [], "notes": ""})
    assert "THEM is" not in fake_ai["user"] and "include:" not in fake_ai["user"]

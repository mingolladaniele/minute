import pytest

from minute import ai, titles


class FakeAI:
    def __init__(self):
        self.transcript = ""
        self.sent = []


@pytest.fixture
def fake_ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(ai, "transcript_text", lambda blocks, limit: fake.transcript)

    def chat(system, user, **kwargs):
        fake.sent.append(user)
        return "Budget review with Marco"

    monkeypatch.setattr(ai, "chat", chat)
    return fake


def test_short_transcript_is_not_sent(fake_ai):
    fake_ai.transcript = "Придерживается."
    assert titles.generate({"blocks": [], "notes": "Budget review with Marco"}) == "Budget review with Marco"
    assert "Придерживается" not in fake_ai.sent[0]


def test_short_transcript_without_notes_gets_no_title(fake_ai):
    fake_ai.transcript = "Придерживается."
    assert titles.generate({"blocks": [], "notes": ""}) is None
    assert fake_ai.sent == []


def test_real_transcript_is_sent(fake_ai):
    fake_ai.transcript = " ".join(["word"] * 30)
    titles.generate({"blocks": [], "notes": ""})
    assert "word word" in fake_ai.sent[0]

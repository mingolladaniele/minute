import pytest

from minute import settings


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    monkeypatch.setattr(settings, "_startup_enabled", lambda: False)


def test_pill_pos_default_none(tmp_settings):
    assert settings.load()["pill_pos"] is None


def test_pill_pos_round_trip(tmp_settings):
    settings.save({"pill_pos": [640, 12]})
    assert settings.load()["pill_pos"] == [640, 12]

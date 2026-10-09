from backend.utils import log_text


def test_hides_text_by_default(monkeypatch):
    monkeypatch.delenv("LOG_SENTENCE_TEXT", raising=False)
    assert log_text("Die Inflation lag bei 2 Prozent.") == "<32 chars>"
    assert log_text(None) == "<0 chars>"


def test_shows_text_when_enabled(monkeypatch):
    monkeypatch.setenv("LOG_SENTENCE_TEXT", "true")
    assert log_text("Die Inflation lag bei 2 Prozent.", 13) == repr("Die Inflation")

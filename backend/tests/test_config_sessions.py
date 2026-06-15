"""Tests for Episode <-> session-row mapping."""
from config import Episode, EPISODES, episode_to_session_dict


def test_from_session_row_builds_episode():
    row = {
        "session_id": "abc",
        "title": "maischberger",
        "date": "9. Juni 2026",
        "guests": ["Sandra Maischberger (Moderatorin)", "Gast (CDU)"],
        "context": "Kontext",
        "type": "show",
    }
    ep = Episode.from_session_row(row)
    assert ep.key == "abc"
    assert ep.show == "maischberger"
    assert ep.date == "9. Juni 2026"
    assert ep.speakers == ["Sandra Maischberger", "Gast"]
    assert ep.context == "Kontext"


def test_episode_to_session_dict_roundtrip():
    ep = EPISODES["maischberger-2025-09-19"]
    d = episode_to_session_dict(ep)
    assert d["session_id"] == "maischberger-2025-09-19"
    assert d["title"] == "maischberger"
    assert d["guests"] == ep.guests
    assert d["visibility"] == "public"
    assert d["status"] == "ended"
    ep2 = Episode.from_session_row(d)
    assert ep2.speakers == ep.speakers


def test_from_session_row_reads_conversation_type():
    from config import Episode
    ep = Episode.from_session_row({"session_id": "s", "conversation_type": "interview"})
    assert ep.conversation_type == "interview"


def test_from_session_row_defaults_conversation_type():
    from config import Episode
    ep = Episode.from_session_row({"session_id": "s"})
    assert ep.conversation_type == "debate"


def test_from_session_row_reads_excluded_speakers():
    from config import Episode
    ep = Episode.from_session_row({"session_id": "s", "excluded_speakers": ["Caren Miosga"]})
    assert ep.excluded_speakers == ["Caren Miosga"]


def test_from_session_row_defaults_excluded_speakers_empty():
    from config import Episode
    ep = Episode.from_session_row({"session_id": "s"})
    assert ep.excluded_speakers == []

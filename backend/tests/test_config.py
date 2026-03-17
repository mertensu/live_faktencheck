"""Tests for Episode config dataclass."""


def test_episode_has_reference_pdfs_field():
    """Episode dataclass has reference_pdfs field defaulting to empty list."""
    from config import Episode
    ep = Episode(key="test", show="test", date="1. Jan 2025", guests=["Host (Moderator)"])
    assert ep.reference_pdfs == []


def test_episode_reference_pdfs_populated():
    """Episode reference_pdfs accepts a list of file paths."""
    from config import Episode
    ep = Episode(
        key="test", show="test", date="1. Jan 2025", guests=["Host (Moderator)"],
        reference_pdfs=["docs/wahlprogramm-afd.pdf"],
    )
    assert ep.reference_pdfs == ["docs/wahlprogramm-afd.pdf"]

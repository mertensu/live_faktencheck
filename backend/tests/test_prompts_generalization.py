"""Guards that the extraction/speaker prompts are conversation-neutral (not TV-show-only)."""
from backend.utils import load_prompt


def test_claim_extraction_prompt_is_conversation_neutral():
    p = load_prompt("claim_extraction.md")
    assert "Talkshow" not in p


def test_speaker_labels_prompt_treats_party_as_optional():
    p = load_prompt("speaker_labels.md")
    assert "falls vorhanden" in p

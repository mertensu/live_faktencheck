"""Guards that the live-lane extraction prompts are conversation-neutral (not TV-show-only)."""
import pytest

from backend.utils import load_prompt


@pytest.mark.parametrize("name", ["claim_extraction_streaming.md", "claim_reformulation.md"])
def test_extraction_prompts_are_conversation_neutral(name):
    assert "Talkshow" not in load_prompt(name)

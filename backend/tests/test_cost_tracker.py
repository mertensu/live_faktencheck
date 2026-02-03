"""
Unit tests for the CostTracker service.
"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from backend.services.cost_tracker import (
    CostTracker,
    get_cost_tracker,
)


class TestCostTrackerPricing:
    """Tests for cost calculation logic."""

    def setup_method(self):
        """Reset singleton before each test."""
        CostTracker.reset_instance()

    def test_get_pricing_exact_match(self):
        """Test pricing lookup with exact model name match."""
        tracker = CostTracker(model_name="gemini-2.5-pro")
        pricing = tracker.get_pricing()

        assert pricing["input"] == 1.25
        assert pricing["output"] == 10.00

    def test_get_pricing_prefix_match(self):
        """Test pricing lookup with model name prefix."""
        tracker = CostTracker(model_name="gemini-2.5-pro-latest")
        pricing = tracker.get_pricing()

        assert pricing["input"] == 1.25
        assert pricing["output"] == 10.00

    def test_get_pricing_unknown_model_falls_back(self):
        """Test that unknown models fall back to default pricing."""
        tracker = CostTracker(model_name="unknown-model")
        pricing = tracker.get_pricing()

        # Should fall back to gemini-2.5-pro
        assert pricing["input"] == 1.25
        assert pricing["output"] == 10.00

    def test_calculate_cost_breakdown_tokens_only(self):
        """Test cost breakdown with only token usage."""
        tracker = CostTracker(model_name="gemini-2.5-pro")

        # 1M input tokens = $1.25, 1M output tokens = $10.00
        breakdown = tracker.calculate_cost_breakdown(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            tavily_searches=0
        )

        assert breakdown["gemini_usd"] == pytest.approx(11.25, rel=0.01)
        assert breakdown["tavily_usd"] == pytest.approx(0.0, rel=0.01)
        assert breakdown["total_usd"] == pytest.approx(11.25, rel=0.01)

    def test_calculate_cost_breakdown_tavily_only(self):
        """Test cost breakdown with only Tavily searches."""
        tracker = CostTracker(model_name="gemini-2.5-pro")

        breakdown = tracker.calculate_cost_breakdown(
            input_tokens=0,
            output_tokens=0,
            tavily_searches=10
        )

        assert breakdown["gemini_usd"] == pytest.approx(0.0, rel=0.01)
        assert breakdown["tavily_usd"] == pytest.approx(0.08, rel=0.01)
        assert breakdown["total_usd"] == pytest.approx(0.08, rel=0.01)

    def test_calculate_cost_breakdown_combined(self):
        """Test cost breakdown with both tokens and searches."""
        tracker = CostTracker(model_name="gemini-2.5-pro")

        # 3000 input + 600 output tokens + 5 searches
        breakdown = tracker.calculate_cost_breakdown(
            input_tokens=3000,
            output_tokens=600,
            tavily_searches=5
        )

        expected_gemini = (3000 / 1_000_000) * 1.25 + (600 / 1_000_000) * 10.00  # 0.00975
        expected_tavily = 5 * 0.008  # 0.04
        expected_total = expected_gemini + expected_tavily

        assert breakdown["gemini_usd"] == pytest.approx(expected_gemini, rel=0.01)
        assert breakdown["tavily_usd"] == pytest.approx(expected_tavily, rel=0.01)
        assert breakdown["total_usd"] == pytest.approx(expected_total, rel=0.01)

    def test_calculate_cost_returns_total(self):
        """Test that calculate_cost returns total from breakdown."""
        tracker = CostTracker(model_name="gemini-2.5-pro")

        cost = tracker.calculate_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            tavily_searches=10
        )

        assert cost == pytest.approx(11.33, rel=0.01)


class TestCostTrackerExtraction:
    """Tests for extracting usage stats from LangGraph results."""

    def setup_method(self):
        """Reset singleton before each test."""
        CostTracker.reset_instance()

    def test_extract_usage_stats_empty_result(self):
        """Test extraction from empty result."""
        tracker = CostTracker()
        stats = tracker.extract_usage_stats({})

        assert stats["input_tokens"] == 0
        assert stats["output_tokens"] == 0
        assert stats["tavily_searches"] == 0
        assert stats["llm_calls"] == 0

    def test_extract_usage_stats_no_messages(self):
        """Test extraction when messages key is missing."""
        tracker = CostTracker()
        stats = tracker.extract_usage_stats({"other_key": "value"})

        assert stats["input_tokens"] == 0
        assert stats["output_tokens"] == 0
        assert stats["tavily_searches"] == 0
        assert stats["llm_calls"] == 0

    def test_extract_usage_stats_with_usage_metadata(self):
        """Test extraction from messages with usage_metadata attribute (multiple LLM calls)."""
        tracker = CostTracker()

        # Create mock messages with usage_metadata - simulates 2 ReAct iterations
        msg1 = MagicMock()
        msg1.usage_metadata = {"input_tokens": 100, "output_tokens": 50}
        msg1.type = "ai"

        msg2 = MagicMock()
        msg2.usage_metadata = {"input_tokens": 200, "output_tokens": 100}  # Higher input due to history
        msg2.type = "ai"

        result = {"messages": [msg1, msg2]}
        stats = tracker.extract_usage_stats(result)

        assert stats["input_tokens"] == 300
        assert stats["output_tokens"] == 150
        assert stats["tavily_searches"] == 0
        assert stats["llm_calls"] == 2  # Two LLM calls

    def test_extract_usage_stats_with_tool_messages(self):
        """Test extraction counts Tavily search tool calls."""
        tracker = CostTracker()

        # Create mock messages - simulates ReAct: LLM -> tool -> tool -> LLM
        ai_msg = MagicMock()
        ai_msg.usage_metadata = {"input_tokens": 100, "output_tokens": 50}
        ai_msg.type = "ai"

        tool_msg1 = MagicMock()
        tool_msg1.usage_metadata = None
        tool_msg1.type = "tool"
        tool_msg1.name = "fact_checker_search"

        tool_msg2 = MagicMock()
        tool_msg2.usage_metadata = None
        tool_msg2.type = "tool"
        tool_msg2.name = "fact_checker_search"

        result = {"messages": [ai_msg, tool_msg1, tool_msg2]}
        stats = tracker.extract_usage_stats(result)

        assert stats["input_tokens"] == 100
        assert stats["output_tokens"] == 50
        assert stats["tavily_searches"] == 2
        assert stats["llm_calls"] == 1

    def test_extract_usage_stats_with_dict_messages(self):
        """Test extraction from dictionary-based messages."""
        tracker = CostTracker()

        result = {
            "messages": [
                {"usage_metadata": {"input_tokens": 150, "output_tokens": 75}, "type": "ai"},
                {"type": "tool", "name": "search"},
            ]
        }
        stats = tracker.extract_usage_stats(result)

        assert stats["input_tokens"] == 150
        assert stats["output_tokens"] == 75
        assert stats["tavily_searches"] == 1
        assert stats["llm_calls"] == 1

    def test_extract_usage_stats_full_react_loop(self):
        """Test extraction from a full ReAct loop with multiple iterations."""
        tracker = CostTracker()

        # Simulate: LLM call 1 -> search -> LLM call 2 -> search -> LLM call 3 (final)
        ai_msg1 = MagicMock()
        ai_msg1.usage_metadata = {"input_tokens": 1000, "output_tokens": 100}  # Initial
        ai_msg1.type = "ai"

        tool_msg1 = MagicMock()
        tool_msg1.usage_metadata = None
        tool_msg1.type = "tool"
        tool_msg1.name = "fact_checker_search"

        ai_msg2 = MagicMock()
        ai_msg2.usage_metadata = {"input_tokens": 2500, "output_tokens": 150}  # Includes history
        ai_msg2.type = "ai"

        tool_msg2 = MagicMock()
        tool_msg2.usage_metadata = None
        tool_msg2.type = "tool"
        tool_msg2.name = "fact_checker_search"

        ai_msg3 = MagicMock()
        ai_msg3.usage_metadata = {"input_tokens": 4000, "output_tokens": 500}  # Final with all history
        ai_msg3.type = "ai"

        result = {"messages": [ai_msg1, tool_msg1, ai_msg2, tool_msg2, ai_msg3]}
        stats = tracker.extract_usage_stats(result)

        assert stats["input_tokens"] == 7500  # 1000 + 2500 + 4000
        assert stats["output_tokens"] == 750   # 100 + 150 + 500
        assert stats["tavily_searches"] == 2
        assert stats["llm_calls"] == 3


class TestCostTrackerSingleton:
    """Tests for singleton pattern."""

    def setup_method(self):
        """Reset singleton before each test."""
        CostTracker.reset_instance()

    def test_singleton_returns_same_instance(self):
        """Test that get_instance returns the same object."""
        tracker1 = CostTracker.get_instance("gemini-2.5-pro")
        tracker2 = CostTracker.get_instance("gemini-2.5-pro")

        assert tracker1 is tracker2

    def test_reset_instance_clears_singleton(self):
        """Test that reset_instance allows creating new instance."""
        tracker1 = CostTracker.get_instance("gemini-2.5-pro")
        CostTracker.reset_instance()
        tracker2 = CostTracker.get_instance("gemini-2.5-pro")

        assert tracker1 is not tracker2

    def test_get_cost_tracker_helper(self):
        """Test the get_cost_tracker helper function."""
        tracker = get_cost_tracker("gemini-2.5-pro")

        assert isinstance(tracker, CostTracker)
        assert tracker.model_name == "gemini-2.5-pro"


class TestCostTrackerPersistence:
    """Tests for JSON file persistence."""

    def setup_method(self):
        """Reset singleton before each test."""
        CostTracker.reset_instance()

    def test_log_claim_cost_updates_session_totals(self):
        """Test that log_claim_cost updates session accumulators."""
        tracker = CostTracker(model_name="gemini-2.5-pro")

        stats = {"input_tokens": 100, "output_tokens": 50, "tavily_searches": 2}
        tracker.log_claim_cost(stats, speaker="Test", claim="Test claim", consistency="hoch")

        assert tracker.total_input_tokens == 100
        assert tracker.total_output_tokens == 50
        assert tracker.total_tavily_searches == 2
        assert tracker.claims_processed == 1

    def test_log_claim_cost_accumulates(self):
        """Test that multiple claims accumulate correctly."""
        tracker = CostTracker(model_name="gemini-2.5-pro")

        stats1 = {"input_tokens": 100, "output_tokens": 50, "tavily_searches": 2}
        stats2 = {"input_tokens": 200, "output_tokens": 100, "tavily_searches": 3}

        tracker.log_claim_cost(stats1, speaker="A", claim="Claim 1", consistency="hoch")
        tracker.log_claim_cost(stats2, speaker="B", claim="Claim 2", consistency="niedrig")

        assert tracker.total_input_tokens == 300
        assert tracker.total_output_tokens == 150
        assert tracker.total_tavily_searches == 5
        assert tracker.claims_processed == 2

    def test_persist_claim_creates_file(self):
        """Test that persistence creates the JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Patch the data directory
            with patch("backend.services.cost_tracker.DATA_DIR", Path(tmpdir)):
                with patch("backend.services.cost_tracker.COST_HISTORY_FILE", Path(tmpdir) / "cost_history.json"):
                    tracker = CostTracker(model_name="gemini-2.5-pro")

                    stats = {"input_tokens": 100, "output_tokens": 50, "tavily_searches": 2, "llm_calls": 3}
                    tracker.log_claim_cost(stats, speaker="Test", claim="Test claim text", consistency="hoch")

                    # Check file was created
                    cost_file = Path(tmpdir) / "cost_history.json"
                    assert cost_file.exists()

                    # Check file contents
                    with open(cost_file, "r") as f:
                        data = json.load(f)

                    assert "session_start" in data
                    assert "session_totals" in data
                    assert "claims" in data
                    assert len(data["claims"]) == 1
                    assert data["claims"][0]["speaker"] == "Test"
                    assert data["claims"][0]["consistency"] == "hoch"
                    # Check cost breakdown fields
                    assert "gemini_usd" in data["claims"][0]
                    assert "tavily_usd" in data["claims"][0]
                    assert "total_usd" in data["claims"][0]
                    assert data["claims"][0]["llm_calls"] == 3
                    assert "gemini_usd" in data["session_totals"]
                    assert "tavily_usd" in data["session_totals"]
                    assert "total_usd" in data["session_totals"]
                    assert data["session_totals"]["llm_calls"] == 3

    def test_persist_claim_appends_to_existing(self):
        """Test that persistence appends to existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cost_file = Path(tmpdir) / "cost_history.json"

            # Create initial file with new format
            initial_data = {
                "session_start": "2026-01-01T00:00:00",
                "session_totals": {
                    "input_tokens": 0, "output_tokens": 0, "tavily_searches": 0, "llm_calls": 0,
                    "gemini_usd": 0, "tavily_usd": 0, "total_usd": 0, "claims_processed": 0
                },
                "claims": [{"speaker": "Previous", "claim_preview": "Old claim"}]
            }
            with open(cost_file, "w") as f:
                json.dump(initial_data, f)

            # Patch and add new claim
            with patch("backend.services.cost_tracker.DATA_DIR", Path(tmpdir)):
                with patch("backend.services.cost_tracker.COST_HISTORY_FILE", cost_file):
                    tracker = CostTracker(model_name="gemini-2.5-pro")

                    stats = {"input_tokens": 100, "output_tokens": 50, "tavily_searches": 2, "llm_calls": 2}
                    tracker.log_claim_cost(stats, speaker="New", claim="New claim", consistency="mittel")

                    # Check file contents
                    with open(cost_file, "r") as f:
                        data = json.load(f)

                    assert len(data["claims"]) == 2
                    assert data["claims"][0]["speaker"] == "Previous"
                    assert data["claims"][1]["speaker"] == "New"
                    # Verify new claim has cost breakdown and llm_calls
                    assert "gemini_usd" in data["claims"][1]
                    assert "tavily_usd" in data["claims"][1]
                    assert "total_usd" in data["claims"][1]
                    assert data["claims"][1]["llm_calls"] == 2

    def test_claim_preview_truncation(self):
        """Test that long claims are truncated in preview."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("backend.services.cost_tracker.DATA_DIR", Path(tmpdir)):
                with patch("backend.services.cost_tracker.COST_HISTORY_FILE", Path(tmpdir) / "cost_history.json"):
                    tracker = CostTracker(model_name="gemini-2.5-pro")

                    long_claim = "A" * 100  # 100 character claim
                    stats = {"input_tokens": 100, "output_tokens": 50, "tavily_searches": 2}
                    tracker.log_claim_cost(stats, speaker="Test", claim=long_claim, consistency="hoch")

                    cost_file = Path(tmpdir) / "cost_history.json"
                    with open(cost_file, "r") as f:
                        data = json.load(f)

                    # Should be truncated to 50 chars + "..."
                    assert len(data["claims"][0]["claim_preview"]) == 53
                    assert data["claims"][0]["claim_preview"].endswith("...")

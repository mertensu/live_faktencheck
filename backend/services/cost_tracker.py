"""
Cost Tracker Service for tracking Gemini token usage and Tavily search costs.

Logs costs to console and persists to a JSON file for historical tracking.
"""

import os
import json
import logging
import fcntl
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Pricing per 1M tokens (as of Jan 2026)
PRICING = {
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-3.0-pro": {"input": 2.00, "output": 12.00},
    # Add more models as needed
}

# Tavily pricing per search credit
TAVILY_PRICE_PER_SEARCH = 0.008

# Default data directory
DATA_DIR = Path(__file__).parent.parent / "data"
COST_HISTORY_FILE = DATA_DIR / "cost_history.json"


class CostTracker:
    """Tracks and logs API costs for Gemini and Tavily usage."""

    _instance: Optional["CostTracker"] = None

    def __init__(self, model_name: str = "gemini-2.5-pro"):
        """
        Initialize the cost tracker.

        Args:
            model_name: The Gemini model being used for pricing lookup
        """
        self.model_name = model_name
        self.session_start = datetime.now().isoformat()

        # Session accumulators
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_tavily_searches = 0
        self.total_llm_calls = 0  # Total Gemini API calls across all claims
        self.claims_processed = 0

        # Ensure data directory exists
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        logger.info(f"CostTracker initialized for model: {model_name}")

    @classmethod
    def get_instance(cls, model_name: str = "gemini-2.5-pro") -> "CostTracker":
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls(model_name)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (useful for testing)."""
        cls._instance = None

    def get_pricing(self) -> Dict[str, float]:
        """Get pricing for the current model."""
        # Try exact match first
        if self.model_name in PRICING:
            return PRICING[self.model_name]

        # Try prefix match (e.g., "gemini-2.5-pro-latest" matches "gemini-2.5-pro")
        for model_key in PRICING:
            if self.model_name.startswith(model_key):
                return PRICING[model_key]

        # Default to gemini-2.5-pro pricing
        logger.warning(f"Unknown model '{self.model_name}', using gemini-2.5-pro pricing")
        return PRICING["gemini-2.5-pro"]

    def extract_usage_stats(self, result: Dict[str, Any]) -> Dict[str, int]:
        """
        Extract token usage and search count from LangGraph result.

        In a ReAct agent loop, each iteration sends the full conversation history,
        so input tokens grow with each LLM call. This method sums usage across
        all iterations.

        Args:
            result: The result dictionary from agent.invoke()

        Returns:
            Dictionary with input_tokens, output_tokens, tavily_searches, llm_calls
        """
        input_tokens = 0
        output_tokens = 0
        tavily_searches = 0
        llm_calls = 0  # Number of LLM API calls (ReAct iterations)

        messages = result.get("messages", [])

        for msg in messages:
            # Extract token usage from message metadata
            usage_metadata = None

            # Try different ways to access usage metadata
            if hasattr(msg, "usage_metadata"):
                usage_metadata = msg.usage_metadata
            elif hasattr(msg, "response_metadata"):
                usage_metadata = getattr(msg, "response_metadata", {}).get("usage_metadata")
            elif isinstance(msg, dict):
                usage_metadata = msg.get("usage_metadata") or msg.get("response_metadata", {}).get("usage_metadata")

            if usage_metadata:
                # Each message with usage_metadata represents one LLM call
                input_tokens += usage_metadata.get("input_tokens", 0)
                output_tokens += usage_metadata.get("output_tokens", 0)
                llm_calls += 1

            # Count Tavily tool calls
            msg_type = getattr(msg, "type", None) or (msg.get("type") if isinstance(msg, dict) else None)

            if msg_type == "tool":
                # Check if this is a Tavily search result
                tool_name = getattr(msg, "name", None) or (msg.get("name") if isinstance(msg, dict) else None)
                if tool_name and "search" in tool_name.lower():
                    tavily_searches += 1

        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "tavily_searches": tavily_searches,
            "llm_calls": llm_calls
        }

    def calculate_cost_breakdown(self, input_tokens: int, output_tokens: int, tavily_searches: int) -> Dict[str, float]:
        """
        Calculate the estimated USD cost with breakdown.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            tavily_searches: Number of Tavily search calls

        Returns:
            Dictionary with gemini_usd, tavily_usd, total_usd
        """
        pricing = self.get_pricing()

        # Token costs (pricing is per 1M tokens)
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        gemini_cost = input_cost + output_cost

        # Tavily costs
        tavily_cost = tavily_searches * TAVILY_PRICE_PER_SEARCH

        return {
            "gemini_usd": gemini_cost,
            "tavily_usd": tavily_cost,
            "total_usd": gemini_cost + tavily_cost
        }

    def calculate_cost(self, input_tokens: int, output_tokens: int, tavily_searches: int) -> float:
        """
        Calculate the estimated total USD cost.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            tavily_searches: Number of Tavily search calls

        Returns:
            Estimated total cost in USD
        """
        breakdown = self.calculate_cost_breakdown(input_tokens, output_tokens, tavily_searches)
        return breakdown["total_usd"]

    def log_claim_cost(
        self,
        stats: Dict[str, int],
        speaker: str,
        claim: str,
        consistency: str
    ) -> None:
        """
        Log the cost of a single claim check and persist to file.

        Args:
            stats: Dictionary with input_tokens, output_tokens, tavily_searches, llm_calls
            speaker: The speaker who made the claim
            claim: The claim text
            consistency: The fact-check result consistency
        """
        input_tokens = stats.get("input_tokens", 0)
        output_tokens = stats.get("output_tokens", 0)
        tavily_searches = stats.get("tavily_searches", 0)
        llm_calls = stats.get("llm_calls", 0)
        total_tokens = input_tokens + output_tokens

        cost_breakdown = self.calculate_cost_breakdown(input_tokens, output_tokens, tavily_searches)

        # Update session totals
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_tavily_searches += tavily_searches
        self.total_llm_calls += llm_calls
        self.claims_processed += 1

        # Log to console with cost breakdown (shows ReAct iterations via llm_calls)
        logger.info(
            f"[COST] Claim checked ({llm_calls} LLM calls) | "
            f"Gemini: ${cost_breakdown['gemini_usd']:.6f} ({total_tokens} tokens) | "
            f"Tavily: ${cost_breakdown['tavily_usd']:.6f} ({tavily_searches} searches) | "
            f"Total: ${cost_breakdown['total_usd']:.6f}"
        )

        # Persist to file
        claim_record = {
            "timestamp": datetime.now().isoformat(),
            "speaker": speaker,
            "claim_preview": claim[:50] + "..." if len(claim) > 50 else claim,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "tavily_searches": tavily_searches,
            "llm_calls": llm_calls,
            "gemini_usd": round(cost_breakdown["gemini_usd"], 6),
            "tavily_usd": round(cost_breakdown["tavily_usd"], 6),
            "total_usd": round(cost_breakdown["total_usd"], 6),
            "consistency": consistency
        }

        self._persist_claim(claim_record)

    def log_session_totals(self) -> None:
        """Log the accumulated session totals with cost breakdown."""
        total_tokens = self.total_input_tokens + self.total_output_tokens
        cost_breakdown = self.calculate_cost_breakdown(
            self.total_input_tokens,
            self.total_output_tokens,
            self.total_tavily_searches
        )

        logger.info(
            f"[COST] Session total ({self.claims_processed} claims, {self.total_llm_calls} LLM calls) | "
            f"Gemini: ${cost_breakdown['gemini_usd']:.6f} ({total_tokens} tokens) | "
            f"Tavily: ${cost_breakdown['tavily_usd']:.6f} ({self.total_tavily_searches} searches) | "
            f"Total: ${cost_breakdown['total_usd']:.6f}"
        )

    def _persist_claim(self, claim_record: Dict[str, Any]) -> None:
        """
        Persist a claim record to the JSON history file with file locking.

        Args:
            claim_record: The claim data to persist
        """
        try:
            # Ensure data directory exists
            DATA_DIR.mkdir(parents=True, exist_ok=True)

            # Read existing data or create new structure
            if COST_HISTORY_FILE.exists():
                with open(COST_HISTORY_FILE, "r+", encoding="utf-8") as f:
                    # Acquire exclusive lock
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    try:
                        content = f.read()
                        data = json.loads(content) if content.strip() else self._create_empty_history()

                        # Add claim record
                        data["claims"].append(claim_record)

                        # Update session totals
                        data["session_start"] = self.session_start
                        session_cost = self.calculate_cost_breakdown(
                            self.total_input_tokens,
                            self.total_output_tokens,
                            self.total_tavily_searches
                        )
                        data["session_totals"] = {
                            "input_tokens": self.total_input_tokens,
                            "output_tokens": self.total_output_tokens,
                            "tavily_searches": self.total_tavily_searches,
                            "llm_calls": self.total_llm_calls,
                            "gemini_usd": round(session_cost["gemini_usd"], 6),
                            "tavily_usd": round(session_cost["tavily_usd"], 6),
                            "total_usd": round(session_cost["total_usd"], 6),
                            "claims_processed": self.claims_processed
                        }

                        # Write back
                        f.seek(0)
                        f.truncate()
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            else:
                # Create new file
                data = self._create_empty_history()
                data["claims"].append(claim_record)
                session_cost = self.calculate_cost_breakdown(
                    self.total_input_tokens,
                    self.total_output_tokens,
                    self.total_tavily_searches
                )
                data["session_totals"] = {
                    "input_tokens": self.total_input_tokens,
                    "output_tokens": self.total_output_tokens,
                    "tavily_searches": self.total_tavily_searches,
                    "llm_calls": self.total_llm_calls,
                    "gemini_usd": round(session_cost["gemini_usd"], 6),
                    "tavily_usd": round(session_cost["tavily_usd"], 6),
                    "total_usd": round(session_cost["total_usd"], 6),
                    "claims_processed": self.claims_processed
                }

                with open(COST_HISTORY_FILE, "w", encoding="utf-8") as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    try:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        except Exception as e:
            logger.error(f"Failed to persist cost data: {e}")

    def _create_empty_history(self) -> Dict[str, Any]:
        """Create an empty history structure."""
        return {
            "session_start": self.session_start,
            "session_totals": {
                "input_tokens": 0,
                "output_tokens": 0,
                "tavily_searches": 0,
                "llm_calls": 0,
                "gemini_usd": 0.0,
                "tavily_usd": 0.0,
                "total_usd": 0.0,
                "claims_processed": 0
            },
            "claims": []
        }


def get_cost_tracker(model_name: str = None) -> CostTracker:
    """
    Get the global cost tracker instance.

    Args:
        model_name: Optional model name override. If not provided,
                   uses GEMINI_MODEL_FACT_CHECKER env var or default.

    Returns:
        The CostTracker singleton instance
    """
    if model_name is None:
        model_name = os.getenv("GEMINI_MODEL_FACT_CHECKER", "gemini-2.5-pro")

    return CostTracker.get_instance(model_name)

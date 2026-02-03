"""
LangGraph Studio graph for debugging the fact-checker agent.

This module exposes a pre-configured fact-checker agent at module level
for use with LangGraph Studio (langgraph dev).

Usage:
    1. Run: langgraph dev
    2. Open: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
    3. Test with messages like:
       - **Speaker:** Christian Rieck
       - **Claim:** Die SPD will eine Erbschaftsteuerreform
       - **Context:** Video vom 17. Januar 2026

Environment variables (set in .env):
    - GEMINI_API_KEY or GOOGLE_API_KEY
    - TAVILY_API_KEY
    - LANGSMITH_API_KEY (for Studio connection)
"""

import os
from pathlib import Path
from datetime import datetime
from typing import List, Literal

from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load .env from project root (must happen before imports that read env vars)
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

from langchain_google_genai import ChatGoogleGenerativeAI  # noqa: E402
from langchain_tavily import TavilySearch  # noqa: E402
from langchain.agents import create_agent  # noqa: E402

from .fact_checker import TRUSTED_DOMAINS, DEFAULT_MODEL  # noqa: E402


class FactCheckResponse(BaseModel):
    """Structured response for fact-check results."""
    speaker: str
    original_claim: str
    consistency: Literal["hoch", "niedrig", "mittel", "unklar"] = Field(
        description="Consistency of the claim, i.e. how well it withstands scrutiny"
    )
    evidence: str = Field(
        description="Detailed German explanation using evidence-based phrasing"
    )
    sources: List[str] = Field(description="URLs to primary sources")


def _load_prompt() -> str:
    """Load the fact checker prompt template."""
    prompt_path = Path(__file__).parent.parent.parent / "prompts" / "fact_checker.md"
    if prompt_path.exists():
        template = prompt_path.read_text(encoding="utf-8")
        current_date = datetime.now().strftime("%B %Y")
        return template.replace("{current_date}", current_date)

    # Fallback minimal prompt
    return """You are a professional German fact-checker.
Verify the claim provided by the user using the search tool.
Search in German. Provide evidence-based analysis."""


def _create_studio_graph():
    """Create the fact-checker agent for Studio debugging."""
    # Get API keys
    google_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not google_api_key:
        raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY not set in .env")

    tavily_api_key = os.getenv("TAVILY_API_KEY")
    if not tavily_api_key:
        raise ValueError("TAVILY_API_KEY not set in .env")

    # Initialize LLM
    model_name = os.getenv("GEMINI_MODEL_FACT_CHECKER", DEFAULT_MODEL)
    llm = ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=google_api_key,
        temperature=0,
        max_retries=2,
    )

    # Initialize search tool
    search_tool = TavilySearch(
        name="fact_checker_search",
        description="Search the web to verify claims. Use German search queries.",
        max_results=int(os.getenv("TAVILY_MAX_RESULTS", "5")),
        search_depth=os.getenv("TAVILY_SEARCH_DEPTH", "basic"),
        include_domains=TRUSTED_DOMAINS,
    )

    # Load prompt
    system_prompt = _load_prompt()

    # Create the agent graph
    agent = create_agent(
        model=llm,
        tools=[search_tool],
        system_prompt=system_prompt,
        response_format=FactCheckResponse,
    )

    return agent


# Export the graph at module level for LangGraph Studio
# This is what langgraph.json references
graph = _create_studio_graph()

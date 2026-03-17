#!/usr/bin/env python3
"""
Index local PDFs for an episode into a FAISS vector store.

Run this once before a show if the episode has reference_pdfs configured.
Requires GEMINI_API_KEY (for embeddings).

Usage:
    uv run python index_pdfs.py <episode-key>
    uv run python index_pdfs.py <episode-key> --force    # rebuild existing index
"""

import sys

from dotenv import load_dotenv

load_dotenv()

from config import EPISODES  # noqa: E402
from backend.services.vector_store import build_index, index_exists  # noqa: E402


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    episode_key = sys.argv[1]
    force = "--force" in sys.argv

    episode = EPISODES.get(episode_key)
    if not episode:
        print(f"Error: Episode '{episode_key}' not found in config.py")
        print(f"Available: {', '.join(EPISODES.keys())}")
        sys.exit(1)

    if not episode.reference_pdfs:
        print(f"Episode '{episode_key}' has no reference_pdfs configured — nothing to index.")
        sys.exit(0)

    if index_exists(episode_key) and not force:
        print(f"Index already exists for '{episode_key}'. Use --force to rebuild.")
        sys.exit(0)

    print(f"Indexing {len(episode.reference_pdfs)} PDF(s) for '{episode_key}'...")
    for p in episode.reference_pdfs:
        print(f"  - {p}")

    try:
        build_index(episode_key, episode.reference_pdfs)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    print(f"Done! Index saved to backend/data/vector_stores/{episode_key}/")


if __name__ == "__main__":
    main()

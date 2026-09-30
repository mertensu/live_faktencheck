"""
AssemblyAI helpers for the live streaming lane: region endpoints and keyterms.

The streaming client itself lives in services/streaming.py.
"""

import os

# Data residency: ASSEMBLYAI_REGION="eu" pins streaming to AssemblyAI's EU endpoint
# (audio and transcripts stay in the EU). Unset = AssemblyAI's default (edge
# routing). Same API key for all regions.
_REGION_HOSTS = {
    "": "streaming.assemblyai.com",
    "eu": "streaming.eu.assemblyai.com",
}


def assemblyai_streaming_host() -> str:
    """Streaming api_host for ASSEMBLYAI_REGION. Raises on an unknown region rather
    than silently falling back to the US."""
    region = os.getenv("ASSEMBLYAI_REGION", "").strip().lower()
    if region not in _REGION_HOSTS:
        raise ValueError(f"Unknown ASSEMBLYAI_REGION={region!r}; use 'eu' or leave unset")
    return _REGION_HOSTS[region]


def clean_keyterms(terms: list[str]) -> list[str]:
    """Trimmed, non-empty, de-duplicated (case-insensitive, order kept)."""
    seen: set[str] = set()
    out: list[str] = []
    for term in terms or []:
        term = (term or "").strip()
        if term and term.casefold() not in seen:
            seen.add(term.casefold())
            out.append(term)
    return out


def session_keyterms(guests: list[str], extra: list[str] | None = None) -> list[str]:
    """AssemblyAI keyterms for a session: the guests' names (and parties) automatically,
    plus the operator's extra terms, e.g. people mentioned in the show."""
    return clean_keyterms(keyterms_from_guests(guests) + list(extra or []))[:1000]


def keyterms_from_guests(guests: list[str]) -> list[str]:
    """Derive AssemblyAI keyterms from formatted guest strings.

    The wizard stores guests as "Name (Party/Org, Role)". For keyterms we want
    clean proper nouns: the name plus the first parenthetical segment (party/org).
    The second segment (role, e.g. "Moderatorin") is a common word and is dropped
    per AssemblyAI guidance to avoid redundant keyterms. Empties are skipped and
    duplicates removed (order preserved); capped at 1000 terms.
    """
    terms: list[str] = []
    for guest in guests:
        guest = (guest or "").strip()
        if not guest:
            continue
        name, _, rest = guest.partition("(")
        name = name.strip()
        if name:
            terms.append(name)
        if rest:
            first = rest.rstrip(")").split(",")[0].strip()
            if first:
                terms.append(first)

    seen: set[str] = set()
    deduped: list[str] = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            deduped.append(term)
    return deduped[:1000]

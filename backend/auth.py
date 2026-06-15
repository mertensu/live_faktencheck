"""Minimal access gate (Phase 3a).

Validates an ``X-Access-Code`` header against the ``codes`` table. Used as a
FastAPI dependency on every endpoint that triggers a paid external API call or
creates a session. Fail-closed: if no codes are seeded, every gated request is
denied.
"""

import os

from fastapi import Header, HTTPException


DEFAULT_QUICK_CHECK_LIMIT = 3
DEFAULT_LIVE_AUDIO_LIMIT_MINUTES = 5


def live_audio_limit_seconds() -> int:
    """Lifetime live-audio cap in seconds, from ``LIVE_AUDIO_LIMIT_MINUTES`` (default 5)."""
    raw = os.getenv("LIVE_AUDIO_LIMIT_MINUTES")
    minutes = int(raw) if raw and raw.isdigit() else DEFAULT_LIVE_AUDIO_LIMIT_MINUTES
    return minutes * 60


def parse_access_codes(raw: str | None) -> list[tuple[str, str, int | None]]:
    """Parse ``ACCESS_CODES`` into ``[(name, code, quick_check_limit), ...]``.

    Each entry is ``name:code`` with an optional third field:
      - absent            -> default cap (DEFAULT_QUICK_CHECK_LIMIT)
      - ``unlimited``     -> None (no cap)
      - a positive int    -> that cap
      - anything else     -> default cap
    Malformed entries (no colon, empty name or code) are silently skipped.
    """
    entries: list[tuple[str, str, int | None]] = []
    if not raw:
        return entries
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" not in entry:
            continue
        parts = [p.strip() for p in entry.split(":")]
        name, code = parts[0], parts[1]
        if not name or not code:
            continue
        limit: int | None = DEFAULT_QUICK_CHECK_LIMIT
        if len(parts) >= 3:
            third = parts[2].lower()
            if third == "unlimited":
                limit = None
            elif third.isdigit():
                limit = int(third)
        entries.append((name, code, limit))
    return entries


async def seed_codes_from_env(db, raw: str | None = None) -> int:
    """Seed the codes table from ``ACCESS_CODES`` if it is empty.

    Idempotent: does nothing when the table already has codes, so revoked codes
    are never silently re-added. Returns the number of codes inserted.
    """
    if raw is None:
        raw = os.getenv("ACCESS_CODES")
    if await db.count_codes() > 0:
        return 0
    entries = parse_access_codes(raw)
    audio_limit = live_audio_limit_seconds()
    for name, code, limit in entries:
        await db.add_code(
            code,
            name,
            quick_check_limit=limit,
            audio_seconds_limit=None if limit is None else audio_limit,
        )
    return len(entries)


async def require_code(x_access_code: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: require a valid ``X-Access-Code`` header.

    Missing header -> 401; unknown/inactive code -> 403; valid -> the code row.
    """
    import backend.state as state

    if not x_access_code:
        raise HTTPException(status_code=401, detail="Zugangscode erforderlich")
    row = await state.get_db().get_code(x_access_code)
    if row is None:
        raise HTTPException(status_code=403, detail="Zugangscode ungültig")
    return row

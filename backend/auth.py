"""Minimal access gate (Phase 3a).

Validates an ``X-Access-Code`` header against the ``codes`` table. Used as a
FastAPI dependency on every endpoint that triggers a paid external API call or
creates a session. Fail-closed: if no codes are seeded, every gated request is
denied.
"""

import os

from fastapi import Header, HTTPException


def parse_access_codes(raw: str | None) -> list[tuple[str, str]]:
    """Parse ``ACCESS_CODES`` ("name:code,name:code") into ``[(name, code), ...]``.

    Malformed entries (no colon, empty name or code) are silently skipped.
    """
    pairs: list[tuple[str, str]] = []
    if not raw:
        return pairs
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" not in entry:
            continue
        name, code = (part.strip() for part in entry.split(":", 1))
        if name and code:
            pairs.append((name, code))
    return pairs


async def seed_codes_from_env(db, raw: str | None = None) -> int:
    """Seed the codes table from ``ACCESS_CODES`` if it is empty.

    Idempotent: does nothing when the table already has codes, so revoked codes
    are never silently re-added. Returns the number of codes inserted.
    """
    if raw is None:
        raw = os.getenv("ACCESS_CODES")
    if await db.count_codes() > 0:
        return 0
    pairs = parse_access_codes(raw)
    for name, code in pairs:
        await db.add_code(code, name)
    return len(pairs)


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

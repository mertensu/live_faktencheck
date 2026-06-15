"""Quick Check (Phase Q): one-shot, code-gated fact-check of a single pasted claim."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import require_code
from backend.models import QuickCheckRequest
from backend.services.registry import get_fact_checker
from backend.utils import build_fact_check_dict
import backend.state as state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["quick-check"])


@router.post("/quick-check")
async def quick_check(request: QuickCheckRequest, code: dict = Depends(require_code)):
    limit = code.get("quick_check_limit")        # None => unlimited
    used = code.get("quick_checks_used", 0)
    if limit is not None and used >= limit:
        raise HTTPException(status_code=429, detail="Kontingent aufgebraucht")

    fact_checker = get_fact_checker()
    result = await fact_checker.check_claim_async(speaker="", claim=request.claim)

    db = state.get_db()
    session_id = f"quick-{code['code']}"
    fact_check = build_fact_check_dict(result, session_id, claim_fallback=request.claim)
    new_id = await db.add_fact_check(fact_check)
    await db.increment_quick_checks(code["code"])

    remaining = None if limit is None else max(limit - (used + 1), 0)
    logger.info(f"Quick check by {code['name']}: {result.get('consistency')} (remaining={remaining})")
    return {
        "fact_check": await db.get_fact_check_by_id(new_id),
        "limit": limit,
        "remaining": remaining,
    }

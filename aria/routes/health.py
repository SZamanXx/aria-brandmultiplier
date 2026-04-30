"""Liveness and a tiny inspection endpoint so I can `curl /callers` from the road."""

from fastapi import APIRouter

import aiosqlite

from aria.config import settings

router = APIRouter()


@router.get("/health")
async def health():
    return {"ok": True, "service": "aria", "model": settings.anthropic_model}


@router.get("/callers")
async def callers():
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT phone_e164, name, summary, call_count, first_seen_at, last_seen_at "
            "FROM callers ORDER BY last_seen_at DESC"
        ) as cur:
            rows = await cur.fetchall()
    return {"callers": [dict(r) for r in rows]}

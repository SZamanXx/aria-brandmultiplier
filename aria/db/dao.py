"""Async SQLite DAO. Small, explicit, no ORM."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from aria.config import settings


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_e164(phone: str) -> str:
    """Strip everything except digits and leading +. Twilio always sends E.164 already, but defensive."""
    if not phone:
        return ""
    cleaned = "".join(c for c in phone if c.isdigit() or c == "+")
    if cleaned and not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    return cleaned


@dataclass
class Caller:
    phone_e164: str
    name: str | None
    profile: dict[str, Any]
    summary: str | None
    first_seen_at: str
    last_seen_at: str
    call_count: int

    @property
    def is_returning(self) -> bool:
        return self.call_count > 0


async def get_caller(phone_e164: str) -> Caller | None:
    phone_e164 = normalize_e164(phone_e164)
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute(
            "SELECT phone_e164, name, profile_json, summary, first_seen_at, last_seen_at, call_count "
            "FROM callers WHERE phone_e164 = ?",
            (phone_e164,),
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return Caller(
                phone_e164=row[0],
                name=row[1],
                profile=json.loads(row[2] or "{}"),
                summary=row[3],
                first_seen_at=row[4],
                last_seen_at=row[5],
                call_count=row[6],
            )


async def upsert_caller(
    phone_e164: str,
    *,
    name: str | None = None,
    profile: dict[str, Any] | None = None,
    summary: str | None = None,
    bump_call_count: bool = False,
) -> Caller:
    """Insert if not exists; otherwise update only the provided fields."""
    phone_e164 = normalize_e164(phone_e164)
    now = utcnow_iso()
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute("SELECT 1 FROM callers WHERE phone_e164 = ?", (phone_e164,)) as cur:
            exists = await cur.fetchone() is not None

        if not exists:
            await db.execute(
                "INSERT INTO callers (phone_e164, name, profile_json, summary, first_seen_at, last_seen_at, call_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    phone_e164,
                    name,
                    json.dumps(profile or {}, ensure_ascii=False),
                    summary,
                    now,
                    now,
                    1 if bump_call_count else 0,
                ),
            )
        else:
            sets = []
            params: list[Any] = []
            if name is not None:
                sets.append("name = ?")
                params.append(name)
            if profile is not None:
                sets.append("profile_json = ?")
                params.append(json.dumps(profile, ensure_ascii=False))
            if summary is not None:
                sets.append("summary = ?")
                params.append(summary)
            sets.append("last_seen_at = ?")
            params.append(now)
            if bump_call_count:
                sets.append("call_count = call_count + 1")
            params.append(phone_e164)
            await db.execute(
                f"UPDATE callers SET {', '.join(sets)} WHERE phone_e164 = ?",
                params,
            )
        await db.commit()

    fresh = await get_caller(phone_e164)
    assert fresh is not None
    return fresh


async def insert_conversation(
    *,
    conversation_id: str,
    phone_e164: str,
    is_returning_caller: bool,
) -> None:
    phone_e164 = normalize_e164(phone_e164)
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            "INSERT OR REPLACE INTO conversations "
            "(conversation_id, phone_e164, started_at, is_returning_caller) "
            "VALUES (?, ?, ?, ?)",
            (conversation_id, phone_e164, utcnow_iso(), 1 if is_returning_caller else 0),
        )
        await db.commit()


async def update_conversation(
    conversation_id: str,
    **fields: Any,
) -> None:
    if not fields:
        return
    cols, params = [], []
    for k, v in fields.items():
        cols.append(f"{k} = ?")
        if isinstance(v, (dict, list)):
            params.append(json.dumps(v, ensure_ascii=False))
        else:
            params.append(v)
    params.append(conversation_id)
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            f"UPDATE conversations SET {', '.join(cols)} WHERE conversation_id = ?",
            params,
        )
        await db.commit()


async def get_conversation(conversation_id: str) -> dict[str, Any] | None:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            d = dict(row)
            for k in ("transcript_elevenlabs_json", "extracted_json"):
                if d.get(k):
                    try:
                        d[k] = json.loads(d[k])
                    except Exception:
                        pass
            return d

"""
Twilio call-status webhook.

Twilio fires this when a call's status changes (in-progress, completed, failed).
On `completed` we look up the EL conversation_id we stored at /twilio/voice
time, fetch the transcript from ElevenLabs, run Claude extraction, merge into
the caller's profile.

This is the polling-style alternative to ElevenLabs' own post-call webhook —
needs no extra ElevenLabs UI configuration, and survives EL webhook URL
mismatches (which we hit during development).
"""

from __future__ import annotations

import asyncio
import json
import logging

import aiosqlite
import httpx
from fastapi import APIRouter, BackgroundTasks, Form

from aria.brain.extract import extract_from_transcripts
from aria.config import settings
from aria.db.dao import (
    get_caller,
    get_conversation,
    insert_conversation,
    normalize_e164,
    update_conversation,
    upsert_caller,
    utcnow_iso,
)
from aria.memory.merge import merge_profile
from aria.routes.elevenlabs_post_call import _flatten_elevenlabs_transcript, _summary_from_profile

logger = logging.getLogger(__name__)
router = APIRouter(tags=["twilio"])


async def _fetch_el_conversation(el_conv_id: str) -> dict:
    async with httpx.AsyncClient(timeout=20.0) as cli:
        r = await cli.get(
            f"https://api.elevenlabs.io/v1/convai/conversations/{el_conv_id}",
            headers={"xi-api-key": settings.elevenlabs_api_key},
        )
        r.raise_for_status()
        return r.json()


async def _process_completed_call(call_sid: str):
    """Fetch transcript from EL → extract → merge → save."""
    conv_row = await get_conversation(call_sid)
    if not conv_row:
        logger.warning("status webhook: no conv row for %s", call_sid)
        return

    el_conv_id = conv_row.get("el_conversation_id")
    phone = conv_row.get("phone_e164")
    if not el_conv_id or not phone:
        logger.warning("status webhook: missing el_conv_id or phone (call=%s)", call_sid)
        return

    # EL transcript may not be ready immediately. Poll up to 30s.
    el_conv = None
    for attempt in range(15):
        try:
            el_conv = await _fetch_el_conversation(el_conv_id)
            if el_conv.get("status") == "done" and el_conv.get("transcript"):
                break
        except Exception as e:
            logger.warning("EL fetch %s attempt %d failed: %s", el_conv_id, attempt, e)
        await asyncio.sleep(2)

    if not el_conv or not el_conv.get("transcript"):
        logger.error("EL conv %s never finalized", el_conv_id)
        return

    md = el_conv.get("metadata") or {}
    duration = md.get("call_duration_secs", 0)
    turns = el_conv.get("transcript", [])
    transcript_text = _flatten_elevenlabs_transcript(turns)

    # Existing profile for context
    caller = await get_caller(phone)
    existing_profile = caller.profile if caller else None
    is_returning = bool(caller and caller.is_returning)

    # Claude extraction
    extraction = await extract_from_transcripts(
        phone_e164=phone,
        is_returning=is_returning,
        started_at=utcnow_iso(),
        transcript_elevenlabs=transcript_text,
        transcript_whisper="",  # whisper backup not wired in for now
        existing_profile=existing_profile,
    )

    # Save raw transcript regardless
    await update_conversation(
        call_sid,
        transcript_elevenlabs_json=turns,
        duration_seconds=duration,
        extracted_json=extraction,
    )

    if not extraction or extraction.get("_parse_error"):
        logger.warning("Extraction parse-failed for %s — transcript saved, no merge", call_sid)
        return

    contradictions = extraction.pop("_contradictions", [])
    new_profile = merge_profile(existing_profile or {}, extraction)
    if contradictions:
        new_profile.setdefault("_contradictions_log", []).extend(
            [{**c, "logged_at": utcnow_iso()} for c in contradictions]
        )
    new_summary = _summary_from_profile(new_profile, extraction)
    name = new_profile.get("name") or (caller.name if caller else None)

    await upsert_caller(
        phone,
        name=name,
        profile=new_profile,
        summary=new_summary,
        bump_call_count=True,
    )
    logger.info(
        "Post-call merge complete (poll path): phone=%s call=%s contradictions=%d",
        phone, call_sid, len(contradictions),
    )


@router.post("/twilio/status")
async def twilio_status(
    background: BackgroundTasks,
    CallSid: str = Form(...),
    CallStatus: str = Form(""),
):
    logger.info("Twilio status: CallSid=%s status=%s", CallSid, CallStatus)
    if CallStatus.lower() == "completed":
        background.add_task(_process_completed_call, CallSid)
    return {"ok": True}

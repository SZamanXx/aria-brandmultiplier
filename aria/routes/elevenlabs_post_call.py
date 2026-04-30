"""
ElevenLabs post-call webhook.

Fires after every call ends with the full transcript and conversation_id.
We:
  1. Verify the HMAC signature.
  2. Look up our placeholder conversation row (by CallSid that ElevenLabs
     sends back as a custom param — fallback to creating a new row if not).
  3. Save the ElevenLabs transcript into that row.
  4. Wait briefly for the Whisper transcript (race with recording-status).
  5. Run Claude extraction on (whisper, elevenlabs, existing_profile).
  6. Apply the deterministic merge into the caller's profile.
  7. Regenerate caller.summary.
  8. Bump caller.call_count, update last_seen_at.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time

from fastapi import APIRouter, Header, HTTPException, Request

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

logger = logging.getLogger(__name__)
router = APIRouter(tags=["elevenlabs"])


def _verify_signature(payload: bytes, header: str | None, secret: str) -> bool:
    if not secret:
        return True  # not configured = skip
    if not header:
        return False
    try:
        timestamp = signature = None
        for part in header.split(","):
            part = part.strip()
            if part.startswith("t="):
                timestamp = part[2:]
            elif part.startswith("v0="):
                signature = part
        if not timestamp or not signature:
            return False
        if int(timestamp) < int(time.time()) - 30 * 60:
            return False
        message = f"{timestamp}.{payload.decode('utf-8')}"
        expected = "v0=" + hmac.new(
            secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected)
    except Exception:
        return False


def _flatten_elevenlabs_transcript(turns: list) -> str:
    lines = []
    for t in turns or []:
        role = (t.get("role") or "").upper()
        text = t.get("message") or t.get("text") or ""
        if text:
            lines.append(f"{role}: {text}")
    return "\n".join(lines)


def _summary_from_profile(profile: dict, last_extraction: dict) -> str:
    """
    Narrative running summary. Reads like reviewer notes a human can scan
    quickly to know who this caller is and what happened on the last call.
    Each section ends with a period and a newline; readability beats density.
    """
    name = profile.get("name") or "Unknown caller"
    role = profile.get("current_role") or ""
    company = profile.get("company") or ""
    built = profile.get("what_they_built") or ""
    result = profile.get("biggest_client_result") or ""
    works_with = profile.get("who_they_typically_work_with") or ""
    clients = profile.get("example_clients") or []
    verticals = profile.get("verticals") or []
    tone = profile.get("tone_notes") or []

    parts: list[str] = []

    # Identity paragraph
    ident_bits = [f"**{name}**"]
    if role and company:
        ident_bits.append(f"is {role.rstrip('.')} at {company}.")
    elif role:
        ident_bits.append(f"— {role.rstrip('.')}.")
    elif company:
        ident_bits.append(f"— at {company}.")
    else:
        ident_bits.append("— (role/company not captured yet).")
    parts.append(" ".join(ident_bits))

    if built:
        parts.append(f"**What they've built:** {built}")
    if result:
        parts.append(f"**Biggest client result they shared:** {result}")
    if works_with:
        parts.append(f"**Typical customer:** {works_with}")
    if clients:
        parts.append(f"**Example clients mentioned across calls:** {', '.join(clients)}.")
    if verticals:
        parts.append(f"**Verticals:** {', '.join(verticals)}.")
    if tone:
        parts.append(f"**Tone / how they came across:** {'; '.join(tone)}.")
    if last_extraction.get("free_text_summary"):
        parts.append(f"**Last call notes:** {last_extraction['free_text_summary']}")

    return "\n\n".join(parts)


@router.post("/elevenlabs/post-call")
async def elevenlabs_post_call(
    request: Request,
    elevenlabs_signature: str | None = Header(None, alias="ElevenLabs-Signature"),
):
    raw = await request.body()
    if not _verify_signature(raw, elevenlabs_signature, settings.elevenlabs_webhook_secret):
        logger.warning("ElevenLabs post-call signature invalid")
        raise HTTPException(status_code=401, detail="invalid signature")

    payload = json.loads(raw)
    event_type = payload.get("type")
    if event_type and event_type != "post_call_transcription":
        return {"ok": True, "skipped": event_type}

    data = payload.get("data") or payload
    conversation_id = data.get("conversation_id") or ""
    metadata = data.get("metadata") or {}
    phone_call = metadata.get("phone_call") or {}
    call_sid = phone_call.get("call_sid") or conversation_id
    external_number = phone_call.get("external_number") or ""
    caller_phone = normalize_e164(external_number)
    duration = metadata.get("call_duration_secs") or 0
    transcript_turns = data.get("transcript") or []
    transcript_el = _flatten_elevenlabs_transcript(transcript_turns)

    if not caller_phone:
        logger.warning("Post-call without caller phone (conv=%s) — best-effort skip", conversation_id)
        return {"ok": True, "skipped": "no_phone"}

    # Find or create our conversation row (we created one in /twilio/voice keyed by CallSid)
    existing_conv = None
    if call_sid:
        existing_conv = await get_conversation(call_sid)
    if existing_conv is None and conversation_id:
        existing_conv = await get_conversation(conversation_id)

    target_conv_id = call_sid or conversation_id
    if existing_conv is None:
        await insert_conversation(
            conversation_id=target_conv_id,
            phone_e164=caller_phone,
            is_returning_caller=False,
        )

    # Save ElevenLabs transcript immediately
    await update_conversation(
        target_conv_id,
        transcript_elevenlabs_json=transcript_turns,
        duration_seconds=duration,
    )

    # Wait briefly for the Whisper backup (the recording webhook may still be
    # running). 12s cap — if not ready we extract from EL only.
    whisper_text = ""
    for _ in range(12):
        conv_now = await get_conversation(target_conv_id)
        if conv_now and conv_now.get("transcript_whisper_text"):
            whisper_text = conv_now["transcript_whisper_text"]
            break
        await asyncio.sleep(1)

    # Pull existing profile for context
    caller = await get_caller(caller_phone)
    existing_profile = caller.profile if caller else None
    is_returning = bool(caller and caller.is_returning)

    # Run Claude extraction
    extraction = await extract_from_transcripts(
        phone_e164=caller_phone,
        is_returning=is_returning,
        started_at=utcnow_iso(),
        transcript_elevenlabs=transcript_el,
        transcript_whisper=whisper_text,
        existing_profile=existing_profile,
    )

    if not extraction or extraction.get("_parse_error"):
        logger.warning("Extraction failed or empty for %s — saving raw and skipping merge", caller_phone)
        await update_conversation(target_conv_id, extracted_json=extraction or {})
        return {"ok": True, "extraction_failed": True}

    # Drop bookkeeping fields before merge
    contradictions = extraction.pop("_contradictions", [])
    new_profile = merge_profile(existing_profile or {}, extraction)
    if contradictions:
        new_profile.setdefault("_contradictions_log", []).extend(
            [{**c, "logged_at": utcnow_iso()} for c in contradictions]
        )

    new_summary = _summary_from_profile(new_profile, extraction)
    name_for_caller = new_profile.get("name") or (caller.name if caller else None)

    await upsert_caller(
        caller_phone,
        name=name_for_caller,
        profile=new_profile,
        summary=new_summary,
        bump_call_count=True,
    )
    await update_conversation(target_conv_id, extracted_json=extraction)

    logger.info(
        "Post-call merge complete for %s — call_count++=%d, contradictions=%d",
        caller_phone, (caller.call_count + 1) if caller else 1, len(contradictions),
    )
    return {"ok": True, "merged": True, "contradictions": len(contradictions)}

"""
Twilio inbound-call webhook.

Flow on call pickup:
  1. Twilio POSTs the inbound webhook with From=, To=, CallSid=.
  2. Look up the caller by phone in SQLite.
  3. If returning, ask Claude to write the opener line (4s timeout, fallback).
  4. Insert a placeholder conversation row keyed by CallSid.
  5. Call ElevenLabs `register_call` with the dynamic-variable overrides
     (caller_name, is_returning, opener, returning_summary). ElevenLabs
     returns TwiML that connects Twilio to the ElevenLabs Conversational AI
     WebSocket, with overrides already wired to the agent prompt.
  6. Return that TwiML to Twilio.

Recording is enabled at the Twilio number level (not in TwiML), so Twilio
records the entire call independently and posts to /twilio/recording-status.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Form, Response

from aria.brain.opener import make_new_caller_intro, make_returning_opener
from aria.config import settings
from aria.db.dao import get_caller, insert_conversation, normalize_e164, upsert_caller

logger = logging.getLogger(__name__)
router = APIRouter(tags=["twilio"])


@router.post("/twilio/voice")
async def twilio_voice(
    From: str = Form(...),
    To: str = Form(...),
    CallSid: str = Form(...),
):
    caller_phone = normalize_e164(From)
    to_phone = normalize_e164(To)
    logger.info("Inbound call: From=%s To=%s CallSid=%s", caller_phone, to_phone, CallSid)

    caller = await get_caller(caller_phone)
    is_returning = caller is not None and caller.is_returning

    if is_returning:
        opener = await make_returning_opener(
            profile=caller.profile,
            last_summary=caller.summary,
            call_count=caller.call_count,
        )
        caller_name = caller.name or ""
        returning_summary = caller.summary or ""
    else:
        opener = make_new_caller_intro()
        caller_name = ""
        returning_summary = ""
        await upsert_caller(caller_phone)

    await insert_conversation(
        conversation_id=CallSid,
        phone_e164=caller_phone,
        is_returning_caller=is_returning,
    )

    payload = {
        "agent_id": settings.elevenlabs_agent_id,
        "from_number": caller_phone,
        "to_number": to_phone,
        "direction": "inbound",
        "conversation_initiation_client_data": {
            "dynamic_variables": {
                "caller_name": caller_name,
                "is_returning": "true" if is_returning else "false",
                "opener": opener,
                "returning_summary": returning_summary,
            },
            "conversation_config_override": {
                "agent": {
                    "first_message": opener,
                },
            },
        },
    }

    async with httpx.AsyncClient(timeout=15.0) as cli:
        r = await cli.post(
            "https://api.elevenlabs.io/v1/convai/twilio/register-call",
            headers={
                "xi-api-key": settings.elevenlabs_api_key,
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if r.status_code != 200:
        logger.error("ElevenLabs register-call failed: %s %s", r.status_code, r.text[:300])
        return Response(
            content="<Response><Say>Sorry — we hit a hiccup connecting. Try again in a moment.</Say><Hangup/></Response>",
            media_type="application/xml",
        )

    data = r.json()
    twiml = data.get("twiml") or data.get("TwiML") or ""
    if not twiml:
        logger.error("ElevenLabs register-call returned no TwiML: %s", data)
        return Response(
            content="<Response><Say>Sorry — agent not ready.</Say><Hangup/></Response>",
            media_type="application/xml",
        )
    return Response(content=twiml, media_type="application/xml")

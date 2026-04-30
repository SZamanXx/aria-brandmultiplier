"""
Helper: given a CallSid, fetch any recordings from Twilio and run Whisper.

Used as a fallback path: instead of Twilio firing recording-status webhook,
we can pull recordings from the Twilio API after the call ends. The
elevenlabs/post-call webhook calls this helper if no Whisper transcript has
landed by the time we're ready to extract.

This means we don't strictly need recording-status to be configured — we can
poll Twilio for the recording attached to the CallSid.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import httpx
from twilio.rest import Client

from aria.config import settings
from aria.whisper_local.transcribe import transcribe_file

logger = logging.getLogger(__name__)


async def fetch_and_transcribe(call_sid: str) -> str:
    """
    Look up recordings for this CallSid, download the first one, run Whisper.
    Returns the plain-text transcript or "" if no recording.
    """
    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    recs = client.recordings.list(call_sid=call_sid, limit=1)
    if not recs:
        logger.info("No Twilio recording found for CallSid=%s", call_sid)
        return ""

    rec = recs[0]
    url = f"https://api.twilio.com{rec.uri.replace('.json', '.wav')}"
    target = settings.recordings_dir / f"{rec.sid}.wav"
    target.parent.mkdir(parents=True, exist_ok=True)

    auth = (settings.twilio_account_sid, settings.twilio_auth_token)
    async with httpx.AsyncClient(timeout=60.0) as cli:
        r = await cli.get(url, auth=auth, follow_redirects=True)
        r.raise_for_status()
        target.write_bytes(r.content)
    logger.info("Downloaded recording %s (%d bytes) for CallSid=%s", target, len(r.content), call_sid)

    loop = asyncio.get_running_loop()
    text = await loop.run_in_executor(None, transcribe_file, target)
    return text

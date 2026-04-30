"""
Twilio recording download helper.

Twilio's recording webhook fires with a RecordingUrl + RecordingSid once the
audio is ready on Twilio's side. We download the .wav over Basic Auth (Twilio
account SID + auth token) and save it to our local recordings dir for Whisper.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from aria.config import settings

logger = logging.getLogger(__name__)


async def download_recording(recording_sid: str, recording_url: str) -> Path:
    """
    Twilio gives a URL like
    https://api.twilio.com/2010-04-01/Accounts/<sid>/Recordings/<rsid>
    which serves WAV when you append .wav. Auth is HTTP Basic.
    """
    url = recording_url
    if not url.endswith(".wav") and not url.endswith(".mp3"):
        url = url.rstrip("/") + ".wav"

    target = settings.recordings_dir / f"{recording_sid}.wav"
    target.parent.mkdir(parents=True, exist_ok=True)

    auth = (settings.twilio_account_sid, settings.twilio_auth_token)
    async with httpx.AsyncClient(timeout=60.0) as cli:
        r = await cli.get(url, auth=auth, follow_redirects=True)
        r.raise_for_status()
        target.write_bytes(r.content)

    logger.info("Recording downloaded: %s (%d bytes)", target, len(r.content))
    return target

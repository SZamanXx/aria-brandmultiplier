"""
Twilio recording-status webhook.

Fires once the call recording is finalized on Twilio's side. We download the
.wav, run local Whisper on it, save the text into the conversation row.

Whisper is sync + slow on CPU, so we offload to a threadpool to keep the
webhook handler from blocking. Twilio's webhook timeout is generous (15s)
but we ack fast and finish in the background.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, BackgroundTasks, Form, Response

from aria.db.dao import update_conversation
from aria.twilio_helpers.recording import download_recording
from aria.whisper_local.transcribe import transcribe_file

logger = logging.getLogger(__name__)
router = APIRouter(tags=["twilio"])

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="whisper")


async def _process_recording(call_sid: str, recording_sid: str, recording_url: str):
    try:
        path = await download_recording(recording_sid, recording_url)
    except Exception as e:
        logger.error("Recording download failed for %s: %s", recording_sid, e)
        return

    try:
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(_executor, transcribe_file, path)
    except Exception as e:
        logger.error("Whisper transcribe failed for %s: %s", recording_sid, e)
        text = ""

    await update_conversation(
        call_sid,
        transcript_whisper_text=text,
        recording_path=str(path),
    )
    logger.info("Whisper backup saved for CallSid=%s (%d chars)", call_sid, len(text))


@router.post("/twilio/recording-status")
async def recording_status(
    background: BackgroundTasks,
    CallSid: str = Form(...),
    RecordingSid: str = Form(...),
    RecordingUrl: str = Form(...),
    RecordingStatus: str = Form(""),
):
    logger.info(
        "Recording-status webhook: CallSid=%s RecordingSid=%s status=%s",
        CallSid, RecordingSid, RecordingStatus,
    )
    if RecordingStatus and RecordingStatus.lower() != "completed":
        return {"ok": True, "skipped": True}
    background.add_task(_process_recording, CallSid, RecordingSid, RecordingUrl)
    return {"ok": True}


@router.post("/twilio/recording-complete")
async def recording_complete():
    """
    The action= URL on the <Record> verb. Twilio calls this when the recording
    verb itself finishes. We don't need to do anything here — the
    recording-status webhook is what gives us the final URL. Return empty TwiML
    to keep Twilio happy.
    """
    return Response(content="<Response/>", media_type="application/xml")

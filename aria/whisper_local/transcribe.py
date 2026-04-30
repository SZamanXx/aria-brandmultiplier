"""
Local Whisper transcription — the independent backup transcript.

We use faster-whisper (CTranslate2 under the hood). Default model is `base.en`
on CPU with int8 quantization, which transcribes a 2-minute call in under a
minute on a modern laptop. Override via WHISPER_MODEL / WHISPER_DEVICE /
WHISPER_COMPUTE_TYPE env vars.

The model is loaded lazily and cached for the process lifetime.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from aria.config import settings

logger = logging.getLogger(__name__)

_model_cache: Any = None


def _get_model():
    global _model_cache
    if _model_cache is not None:
        return _model_cache
    from faster_whisper import WhisperModel  # imported lazily so unit tests don't need it
    logger.info(
        "Loading Whisper model: %s (device=%s, compute=%s)",
        settings.whisper_model, settings.whisper_device, settings.whisper_compute_type,
    )
    _model_cache = WhisperModel(
        settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )
    return _model_cache


def transcribe_file(audio_path: Path) -> str:
    """
    Synchronous Whisper transcribe. Returns plain text. We keep it sync because
    faster-whisper is sync, and we run it in a threadpool from the async route.
    """
    if not audio_path.exists():
        logger.warning("Whisper called on missing file: %s", audio_path)
        return ""
    model = _get_model()
    segments, info = model.transcribe(
        str(audio_path),
        language="en",
        vad_filter=True,
        beam_size=5,
    )
    parts: list[str] = []
    for s in segments:
        parts.append(s.text.strip())
    text = " ".join(p for p in parts if p)
    logger.info(
        "Whisper transcribed %s (lang=%s, dur=%.1fs) -> %d chars",
        audio_path.name, info.language, info.duration, len(text),
    )
    return text

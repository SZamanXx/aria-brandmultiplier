"""
Claude API: post-call structured extraction.

Reads (existing_profile, transcript_elevenlabs, transcript_whisper) and
returns a per-call delta in the shape that the merge layer expects.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from anthropic import AsyncAnthropic

from aria.config import settings
from aria.prompts.extract_call import EXTRACT_SYSTEM_PROMPT, EXTRACT_USER_PROMPT_TEMPLATE
from aria.memory.merge import render_profile_for_prompt

logger = logging.getLogger(__name__)

_client: AsyncAnthropic | None = None


def _client_singleton() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def extract_from_transcripts(
    *,
    phone_e164: str,
    is_returning: bool,
    started_at: str,
    transcript_elevenlabs: str,
    transcript_whisper: str,
    existing_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    if not transcript_elevenlabs and not transcript_whisper:
        logger.warning("Both transcripts empty for %s — skipping extraction", phone_e164)
        return {}

    if existing_profile:
        existing_profile_render = render_profile_for_prompt(existing_profile)
        existing_profile_json = (
            "(known from prior calls — treat as prior ground truth)\n\n"
            + existing_profile_render
        )
    else:
        existing_profile_json = "(no prior data — first call from this number)"

    user_prompt = EXTRACT_USER_PROMPT_TEMPLATE.format(
        phone_e164=phone_e164,
        is_returning="true" if is_returning else "false",
        started_at=started_at,
        existing_profile_json=existing_profile_json,
        transcript_elevenlabs=transcript_elevenlabs or "(not available)",
        transcript_whisper=transcript_whisper or "(not available)",
    )

    client = _client_singleton()
    message = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=2048,
        system=EXTRACT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = "".join(b.text for b in message.content if getattr(b, "type", "") == "text").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("extraction returned non-object")
        return data
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("Extraction parse failure: %s\nRaw: %s", e, text[:500])
        return {"_parse_error": str(e), "_raw": text}

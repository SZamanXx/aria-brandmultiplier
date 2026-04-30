"""
Claude API: returning-caller opener.

One Claude call, one short sentence out, fed into ElevenLabs as a dynamic var
override so ARIA opens the call by recognizing the caller without
re-introducing herself.
"""

from __future__ import annotations

import logging

from anthropic import AsyncAnthropic

from aria.config import settings
from aria.prompts.returning_opener import (
    NEW_CALLER_INTRO,
    OPENER_SYSTEM_PROMPT,
    OPENER_USER_PROMPT_TEMPLATE,
)
from aria.memory.merge import render_profile_for_prompt

logger = logging.getLogger(__name__)

_client: AsyncAnthropic | None = None


def _client_singleton() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def make_returning_opener(
    *,
    profile: dict,
    last_summary: str | None,
    call_count: int,
    timeout_s: float = 4.0,
) -> str:
    """
    Generate a one-sentence opener. If anything fails (timeout, Claude down,
    bad parse), fall back to a safe generic returning-caller line so the call
    still goes through.
    """
    fallback = (
        f"Hey {profile.get('name') or 'there'} — good to hear from you again. "
        f"What's new since we last talked?"
    )

    try:
        rendered = render_profile_for_prompt(profile)
        user_prompt = OPENER_USER_PROMPT_TEMPLATE.format(
            call_count=call_count,
            profile_render=rendered,
            last_summary=last_summary or "(no prior summary stored)",
        )
        client = _client_singleton()
        message = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=200,
            system=OPENER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            timeout=timeout_s,
        )
        line = "".join(
            b.text for b in message.content if getattr(b, "type", "") == "text"
        ).strip().strip('"').strip("'")
        if not line or len(line) < 5:
            return fallback
        return line
    except Exception as e:
        logger.warning("Opener generation failed (%s); using fallback", e)
        return fallback


def make_new_caller_intro() -> str:
    return NEW_CALLER_INTRO

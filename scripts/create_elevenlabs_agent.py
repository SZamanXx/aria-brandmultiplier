"""
Create the ARIA ElevenLabs Conversational AI agent.

Run once. Saves the agent_id into .env. Voice = my own cloned voice ("Klon MNie")
as a small Easter egg — see README "Voice clone".

Runtime config from HUMANIZATION_RESEARCH.md §4 Patch D:
  - LLM: claude-sonnet-4-5
  - max_response_tokens: 120 (enforces short turns)
  - temperature: 0.7
  - interruption_sensitivity: balanced
  - TTS model: eleven_turbo_v2_5
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from elevenlabs import ElevenLabs

from aria.config import settings
from aria.prompts.agent_system import ARIA_AGENT_SYSTEM_PROMPT

# My cloned voice — "Klon MNie", category=professional in my ElevenLabs account.
# See README: this is the small Easter egg for BrandMultiplier.
WOJCIECH_CLONE_VOICE_ID = "7VD54UQvHbPpiEXh229b"


def main():
    if "[REPLACE WITH CONTENT FROM" in ARIA_AGENT_SYSTEM_PROMPT:
        print("WARNING: agent_system.py still contains the placeholder prompt.")
        print("Update aria/prompts/agent_system.py before running this for real.")
        if os.getenv("FORCE_PLACEHOLDER", "").lower() not in ("1", "true", "yes"):
            sys.exit(1)

    client = ElevenLabs(api_key=settings.elevenlabs_api_key)

    voice_id = os.getenv("ELEVENLABS_VOICE_ID") or WOJCIECH_CLONE_VOICE_ID

    # Use raw dict for conversation_config — ElevenLabs SDK accepts a dict and
    # this is more forgiving than chasing the typed builder across SDK versions.
    conversation_config = {
        "agent": {
            "prompt": {
                "prompt": ARIA_AGENT_SYSTEM_PROMPT,
                "llm": "claude-sonnet-4-5",
                "temperature": 0.7,
                "max_tokens": 120,
            },
            "first_message": "{{opener}}",
            "language": "en",
            "dynamic_variables": {
                "dynamic_variable_placeholders": {
                    "caller_name": "",
                    "is_returning": "false",
                    "opener": (
                        "Hi, this is ARIA, calling on behalf of BrandMultiplier. "
                        "Thanks for picking up — before we dive in, who am I speaking with?"
                    ),
                    "returning_summary": "",
                }
            },
        },
        "tts": {
            "model_id": "eleven_turbo_v2",
            "voice_id": voice_id,
        },
        "asr": {
            "quality": "high",
            # CRITICAL for Twilio: Twilio Media Streams send mu-law 8kHz audio.
            # Default `pcm_16000` results in the agent hearing silence and the
            # call dropping after a few seconds with no error message.
            "user_input_audio_format": "ulaw_8000",
        },
        "turn": {
            "turn_timeout": 7.0,
            "mode": "turn",
            "turn_eagerness": "normal",
        },
    }

    agent = client.conversational_ai.agents.create(
        name="ARIA — BrandMultiplier intake (Wojciech submission)",
        conversation_config=conversation_config,
    )

    agent_id = getattr(agent, "agent_id", None) or getattr(agent, "id", None)
    print(f"\nAgent created.")
    print(f"  agent_id = {agent_id}")
    print(f"  voice_id = {voice_id}")

    # Persist to .env automatically
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        text = env_path.read_text(encoding="utf-8")
        new_lines: list[str] = []
        wrote = False
        for line in text.splitlines():
            if line.startswith("ELEVENLABS_AGENT_ID="):
                new_lines.append(f"ELEVENLABS_AGENT_ID={agent_id}")
                wrote = True
            else:
                new_lines.append(line)
        if not wrote:
            new_lines.append(f"ELEVENLABS_AGENT_ID={agent_id}")
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print(f"\n.env updated with agent_id.")


if __name__ == "__main__":
    main()

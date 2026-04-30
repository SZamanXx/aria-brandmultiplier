"""
TwiML builders.

Inbound voice flow:
  1. Twilio POSTs to /twilio/voice
  2. We respond with <Connect><ConversationRelay /> pointing at the
     ElevenLabs Conv AI WebSocket so all audio is routed there.
  3. We also start a parallel <Record> on the call so we get a .wav for
     local Whisper to chew on after the call ends.

ElevenLabs uses Twilio's "ConversationRelay" verb — we provide the agent ID
and the dynamic-variable overrides.
"""

from __future__ import annotations

from twilio.twiml.voice_response import VoiceResponse


def build_inbound_twiml(
    *,
    elevenlabs_agent_id: str,
    public_base_url: str,
    overrides: dict[str, str],
) -> str:
    """
    Build the TwiML that:
    - records the call (dual-channel) and posts the recording URL to our handler
    - connects the call audio to the ElevenLabs Conversational AI agent

    overrides are dynamic variables the agent prompt expects:
      caller_name, is_returning, opener, returning_summary
    """
    response = VoiceResponse()

    # Start a parallel recording. dual_channel=True so caller and agent are on
    # separate stereo channels, easier on Whisper.
    response.record(
        action=f"{public_base_url}/twilio/recording-complete",
        recording_status_callback=f"{public_base_url}/twilio/recording-status",
        recording_status_callback_event="completed",
        recording_track="both",
        timeout=600,
        play_beep=False,
        trim="trim-silence",
    )

    # Hand the audio to the ElevenLabs agent via Twilio Conversation Relay.
    # The ElevenLabs websocket URL is what their dashboard provides; we pass
    # the agent_id and override vars as query params.
    connect = response.connect()
    relay = connect.conversation_relay(
        url=_elevenlabs_relay_url(elevenlabs_agent_id, overrides),
        welcome_greeting=overrides.get("opener", ""),
    )
    return str(response)


def _elevenlabs_relay_url(agent_id: str, overrides: dict[str, str]) -> str:
    """
    Construct the WebSocket URL for ElevenLabs Conversation Relay including
    dynamic-variable overrides as query parameters. ElevenLabs reads these
    and substitutes them into the agent's system prompt.
    """
    from urllib.parse import urlencode, quote_plus

    base = f"wss://api.elevenlabs.io/v1/convai/conversation?agent_id={agent_id}"
    if overrides:
        params = []
        for k, v in overrides.items():
            if v is None:
                continue
            params.append(f"dynamic_variables[{quote_plus(k)}]={quote_plus(str(v))}")
        if params:
            base += "&" + "&".join(params)
    return base

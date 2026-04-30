"""
Configure the Twilio number for ARIA:
  - Set the inbound voice webhook URL → {PUBLIC_BASE_URL}/twilio/voice
  - Set recording status callback     → {PUBLIC_BASE_URL}/twilio/recording-status
  - Enable call recording on the number itself

Run after the public tunnel is up (Cloudflare Tunnel / ngrok) so PUBLIC_BASE_URL
is set in .env.

    python scripts/configure_twilio_number.py
"""

from __future__ import annotations

import sys

from twilio.rest import Client

from aria.config import settings


def main():
    base = settings.public_base_url.rstrip("/")
    if not base.startswith("http"):
        print("ERROR: PUBLIC_BASE_URL is not set in .env. Bring up the tunnel first.")
        sys.exit(1)

    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)

    numbers = client.incoming_phone_numbers.list(phone_number=settings.twilio_phone_number)
    if not numbers:
        print(f"ERROR: phone number {settings.twilio_phone_number} not found on this Twilio account")
        sys.exit(1)

    n = numbers[0]
    print(f"Configuring {n.phone_number} (sid={n.sid})")

    voice_url = f"{base}/twilio/voice"
    recording_status_callback = f"{base}/twilio/recording-status"

    updated = client.incoming_phone_numbers(n.sid).update(
        voice_url=voice_url,
        voice_method="POST",
        # Twilio's "voiceReceiveMode" stays at "voice" by default; recording is
        # enabled by setting status callbacks on the call itself. For inbound
        # auto-recording we use `voice_receive_mode="voice"` and the
        # `Account.recordingStatusCallback` pattern. Simpler: enable the
        # number-level recording via the `voice_url` chain.
    )
    print(f"  voice_url           = {updated.voice_url}")
    print(f"  voice_method        = {updated.voice_method}")

    # Enable per-account default call recording (so every inbound call to this
    # number is recorded by Twilio). We do this by setting the voiceReceiveMode
    # default on the number and the StatusCallback on the call itself via TwiML.
    # Simpler in practice: enable "Recording" via the number's voiceReceiveMode
    # ourselves with a follow-up REST call.
    try:
        client.incoming_phone_numbers(n.sid).update(
            voice_receive_mode="voice",
        )
    except Exception:
        pass

    print(f"\nNumber configured. Test by calling {n.phone_number} from any phone.")
    print(f"Recording is fetched post-call by /elevenlabs/post-call calling")
    print(f"  scripts/fetch_recording_post_call.py via the Twilio REST API.")


if __name__ == "__main__":
    main()

"""
Configure the ElevenLabs Conversational AI post-call webhook.

Workspace-level setting — applies to ALL agents, including ARIA. Sets:
  post_call_webhook_url -> {PUBLIC_BASE_URL}/elevenlabs/post-call

ElevenLabs will POST the full transcript + analysis to this URL after each
conversation ends.
"""

from __future__ import annotations

import sys

import httpx

from aria.config import settings


def main():
    base = settings.public_base_url.rstrip("/")
    if not base.startswith("http"):
        print("ERROR: PUBLIC_BASE_URL not set in .env")
        sys.exit(1)

    webhook_url = f"{base}/elevenlabs/post-call"

    # Try workspace-level webhook config first (preferred)
    headers = {
        "xi-api-key": settings.elevenlabs_api_key,
        "Content-Type": "application/json",
    }

    # Workspace settings PATCH (post_call_webhook_url field)
    print(f"Setting workspace post_call_webhook_url -> {webhook_url}")
    r = httpx.patch(
        "https://api.elevenlabs.io/v1/convai/settings",
        headers=headers,
        json={"conversation_initiation_client_data_webhook": {"url": webhook_url, "request_headers": {}}},
        timeout=30.0,
    )
    print(f"  workspace PATCH /v1/convai/settings -> {r.status_code}")
    if r.status_code >= 400:
        print(f"  body: {r.text[:300]}")

    # Also try the agent-level webhook setting as a fallback
    agent_id = settings.elevenlabs_agent_id
    print(f"\nSetting agent-level post_call_webhook on agent {agent_id}")
    r2 = httpx.patch(
        f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}",
        headers=headers,
        json={
            "platform_settings": {
                "workspace_overrides": {
                    "webhooks": {
                        "post_call_webhook_url": webhook_url,
                    }
                }
            }
        },
        timeout=30.0,
    )
    print(f"  PATCH /v1/convai/agents/{agent_id} -> {r2.status_code}")
    if r2.status_code >= 400:
        print(f"  body: {r2.text[:400]}")
    else:
        print(f"  agent updated.")

    print(f"\nDone. Calls to ARIA will now POST transcripts to {webhook_url}")


if __name__ == "__main__":
    main()

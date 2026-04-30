"""
Integration-ish tests over FastAPI routes with all network boundaries
(ElevenLabs register-call, Claude opener, Claude extract) mocked in
conftest.app_client.
"""

import json
import pytest

from aria.db.dao import get_caller


def test_health_returns_aria_shape(app_client):
    r = app_client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    assert body.get("service") == "aria"
    # model name must be a Claude Sonnet/Opus/Haiku id, not a placeholder.
    assert "claude" in (body.get("model") or "").lower()


def test_callers_endpoint_initially_empty(app_client):
    r = app_client.get("/callers")
    assert r.status_code == 200
    assert r.json() == {"callers": []}


def test_twilio_voice_new_caller_registers_call(app_client):
    r = app_client.post(
        "/twilio/voice",
        data={
            "From": "+15551112222",
            "To": "+12676808419",
            "CallSid": "CAtest_new_1",
        },
    )
    assert r.status_code == 200
    assert "fake-ok" in r.text  # comes from our mocked register-call response
    # New caller row should exist with call_count=0 (bump happens post-call).
    import asyncio
    caller = asyncio.run(get_caller("+15551112222"))
    assert caller is not None
    assert caller.is_returning is False


def test_twilio_voice_returning_caller_uses_opener(app_client):
    """
    Seed a caller with call_count=1 (= returning), then hit /twilio/voice
    and assert that:
      - the route used the Claude opener path (mocked to a deterministic line)
      - the conversation row was created and flagged is_returning=1
    """
    import asyncio
    from aria.db.dao import upsert_caller, get_conversation

    asyncio.run(
        upsert_caller(
            "+15551113333",
            name="Sapir",
            profile={"name": "Sapir", "company": "BrandMultiplier"},
            summary="Last time Sapir walked me through the methodology.",
            bump_call_count=True,
        )
    )

    captured_payload = {}
    real_post = None

    async def _capture(self, url, headers=None, json=None, **kwargs):  # noqa: ANN001
        captured_payload["url"] = url
        captured_payload["json"] = json

        class _R:
            status_code = 200
            text = ""
            def json(self_inner):
                return {"twiml": "<Response/>"}
        return _R()

    # Re-patch httpx.AsyncClient.post to inspect what we sent EL
    import httpx
    httpx.AsyncClient.post = _capture  # type: ignore[assignment]

    r = app_client.post(
        "/twilio/voice",
        data={
            "From": "+15551113333",
            "To": "+12676808419",
            "CallSid": "CAtest_ret_1",
        },
    )
    assert r.status_code == 200
    assert captured_payload["url"].endswith("/v1/convai/twilio/register-call")
    body = captured_payload["json"]
    dyn = body["conversation_initiation_client_data"]["dynamic_variables"]
    assert dyn["is_returning"] == "true"
    assert dyn["caller_name"] == "Sapir"
    assert "Sapir" in dyn["opener"]  # mocked opener uses the name
    assert "what's new" in dyn["opener"].lower()

    conv = asyncio.run(get_conversation("CAtest_ret_1"))
    assert conv is not None
    assert conv["is_returning_caller"] in (1, True)


def test_post_call_invalid_signature_returns_401(app_client, post_call_signed_request_factory):
    raw, _good_header = post_call_signed_request_factory({"type": "post_call_transcription"})
    bad_header = "t=999999999,v0=" + "0" * 64
    r = app_client.post(
        "/elevenlabs/post-call",
        content=raw,
        headers={"ElevenLabs-Signature": bad_header, "Content-Type": "application/json"},
    )
    assert r.status_code == 401


def test_post_call_skips_non_transcription_event(app_client, post_call_signed_request_factory):
    payload = {"type": "audio", "data": {}}
    raw, header = post_call_signed_request_factory(payload)
    r = app_client.post(
        "/elevenlabs/post-call",
        content=raw,
        headers={"ElevenLabs-Signature": header, "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json().get("skipped") == "audio"


def test_post_call_end_to_end_merges_profile(app_client, post_call_signed_request_factory, monkeypatch):
    """
    Full happy-path: signed payload arrives, we extract (mock returns Sapir),
    merge into profile, bump call_count, write summary.
    """
    # First, register the caller-and-CallSid through /twilio/voice so the
    # conversation row exists exactly the way it does in production.
    app_client.post(
        "/twilio/voice",
        data={"From": "+15554440000", "To": "+12676808419", "CallSid": "CAfull_1"},
    )

    # Eliminate the 12s whisper-wait delay in tests by monkeypatching asyncio.sleep.
    import aria.routes.elevenlabs_post_call as pcm

    async def _no_sleep(_):
        return None
    monkeypatch.setattr(pcm.asyncio, "sleep", _no_sleep)

    payload = {
        "type": "post_call_transcription",
        "data": {
            "conversation_id": "conv_x",
            "metadata": {
                "phone_call": {"call_sid": "CAfull_1", "external_number": "+15554440000"},
                "call_duration_secs": 73,
            },
            "transcript": [
                {"role": "agent", "message": "Hi, this is ARIA."},
                {"role": "user", "message": "Hey, this is Sapir."},
            ],
        },
    }
    raw, header = post_call_signed_request_factory(payload)
    r = app_client.post(
        "/elevenlabs/post-call",
        content=raw,
        headers={"ElevenLabs-Signature": header, "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("merged") is True
    assert body.get("contradictions") == 0

    import asyncio
    caller = asyncio.run(get_caller("+15554440000"))
    assert caller is not None
    assert caller.name == "Sapir"
    assert caller.call_count == 1
    assert caller.is_returning is True
    assert "BrandMultiplier" in (caller.summary or "")
    # Profile got the structured merge
    assert caller.profile.get("company") == "BrandMultiplier"
    assert "Acme" in (caller.profile.get("example_clients") or [])


def test_returning_recognition_after_post_call(app_client, post_call_signed_request_factory, monkeypatch):
    """
    The product promise: same caller calling back is recognized.
    Run /twilio/voice → /elevenlabs/post-call → /twilio/voice (again) and
    assert that the second call was treated as returning.
    """
    import aria.routes.elevenlabs_post_call as pcm

    async def _no_sleep(_):
        return None
    monkeypatch.setattr(pcm.asyncio, "sleep", _no_sleep)

    # Call 1
    app_client.post(
        "/twilio/voice",
        data={"From": "+15557778888", "To": "+12676808419", "CallSid": "CAr_1"},
    )

    payload = {
        "type": "post_call_transcription",
        "data": {
            "conversation_id": "conv_r1",
            "metadata": {
                "phone_call": {"call_sid": "CAr_1", "external_number": "+15557778888"},
                "call_duration_secs": 60,
            },
            "transcript": [{"role": "user", "message": "I'm Sapir."}],
        },
    }
    raw, header = post_call_signed_request_factory(payload)
    r = app_client.post(
        "/elevenlabs/post-call",
        content=raw,
        headers={"ElevenLabs-Signature": header, "Content-Type": "application/json"},
    )
    assert r.status_code == 200

    # Call 2 — capture what we send EL
    captured = {}

    async def _capture(self, url, headers=None, json=None, **kwargs):  # noqa: ANN001
        captured["json"] = json

        class _R:
            status_code = 200
            text = ""
            def json(self_inner):
                return {"twiml": "<Response/>"}
        return _R()

    import httpx
    httpx.AsyncClient.post = _capture  # type: ignore[assignment]

    app_client.post(
        "/twilio/voice",
        data={"From": "+15557778888", "To": "+12676808419", "CallSid": "CAr_2"},
    )
    dyn = captured["json"]["conversation_initiation_client_data"]["dynamic_variables"]
    assert dyn["is_returning"] == "true"
    assert dyn["caller_name"] == "Sapir"

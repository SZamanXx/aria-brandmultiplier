"""HMAC verifier, transcript flattener, summary builder."""

import hashlib
import hmac
import json
import time

from aria.routes.elevenlabs_post_call import (
    _flatten_elevenlabs_transcript,
    _summary_from_profile,
    _verify_signature,
)


SECRET = "wsec_test_dummy_secret_for_pytest"


def _sign(payload: bytes, secret: str = SECRET, ts: int | None = None) -> tuple[str, int]:
    ts = ts if ts is not None else int(time.time())
    msg = f"{ts}.{payload.decode('utf-8')}"
    sig = "v0=" + hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return f"t={ts},{sig}", ts


def test_signature_happy_path():
    payload = b'{"event":"hello"}'
    header, _ = _sign(payload)
    assert _verify_signature(payload, header, SECRET) is True


def test_signature_tampered_body_rejected():
    payload = b'{"event":"hello"}'
    header, _ = _sign(payload)
    tampered = b'{"event":"goodbye"}'
    assert _verify_signature(tampered, header, SECRET) is False


def test_signature_stale_timestamp_rejected():
    payload = b'{"event":"hello"}'
    old_ts = int(time.time()) - 60 * 60  # 1h ago, > 30m window
    header, _ = _sign(payload, ts=old_ts)
    assert _verify_signature(payload, header, SECRET) is False


def test_signature_missing_header_rejected():
    assert _verify_signature(b'{}', None, SECRET) is False


def test_signature_no_secret_skips():
    # Production fallback: if secret not configured at all, accept.
    assert _verify_signature(b'{}', None, "") is True


def test_flatten_elevenlabs_transcript():
    turns = [
        {"role": "agent", "message": "Hi, this is ARIA."},
        {"role": "user", "message": "Hey, this is Sapir."},
        {"role": "agent", "message": ""},  # skipped
        {"role": "user", "text": "Got it."},  # alt key supported
    ]
    out = _flatten_elevenlabs_transcript(turns)
    lines = out.splitlines()
    assert lines[0] == "AGENT: Hi, this is ARIA."
    assert lines[1] == "USER: Hey, this is Sapir."
    assert lines[2] == "USER: Got it."
    assert len(lines) == 3


def test_flatten_handles_none():
    assert _flatten_elevenlabs_transcript(None) == ""
    assert _flatten_elevenlabs_transcript([]) == ""


def test_summary_from_profile_assembles_known_fields():
    profile = {
        "name": "Sapir",
        "current_role": "Founder",
        "company": "BrandMultiplier",
        "biggest_client_result": "Tripled MRR for a SaaS founder.",
        "who_they_typically_work_with": "Post-PMF B2B founders.",
        "example_clients": ["Acme", "Globex"],
        "verticals": ["SaaS"],
    }
    extraction = {"free_text_summary": "Talked through the methodology."}
    s = _summary_from_profile(profile, extraction)
    assert "Sapir" in s
    assert "Founder" in s
    assert "BrandMultiplier" in s
    assert "Tripled MRR" in s
    assert "Acme" in s and "Globex" in s
    assert "Talked through the methodology" in s


def test_summary_handles_empty_profile():
    s = _summary_from_profile({}, {})
    # Empty profile yields empty string — valid (caller flow handles None).
    assert s == ""

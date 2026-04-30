"""
Pytest fixtures for ARIA.

Strategy:
  - aria.config.settings is a frozen dataclass loaded from .env at import time.
    We rebind `db_path` per-test via object.__setattr__ (the only legal way
    to mutate a frozen dataclass) to point at a tmp SQLite file. init_db()
    rebuilds schema on that file.
  - Network mocks live in dedicated fixtures so individual tests opt in.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

# Make the project root importable when pytest is invoked from anywhere.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Force a deterministic webhook secret BEFORE aria.config is loaded so the
# signature-verification test path is exercised end-to-end. .env may have a
# real secret which is fine — we override via env var which load_dotenv()
# does NOT override (load_dotenv default override=False).
os.environ.setdefault("ELEVENLABS_WEBHOOK_SECRET", "wsec_test_dummy_secret_for_pytest")


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """
    Per-test SQLite file. Every test gets a clean DB; no order coupling.
    """
    from aria.config import settings
    from aria.db.init_db import init_db

    db_file = tmp_path / "aria_test.db"
    object.__setattr__(settings, "db_path", db_file)

    rec_dir = tmp_path / "recordings"
    rec_dir.mkdir(parents=True, exist_ok=True)
    object.__setattr__(settings, "recordings_dir", rec_dir)

    init_db(db_file)
    yield db_file


@pytest.fixture
def app_client(monkeypatch):
    """
    FastAPI TestClient with the network-touching boundaries mocked.
    Tests can override the mocks (use monkeypatch on the same target).
    """
    from fastapi.testclient import TestClient

    # Mock the ElevenLabs register-call HTTP call BEFORE importing the app
    async def _fake_post(self, url, headers=None, json=None, **kwargs):  # noqa: ANN001
        class _R:
            status_code = 200
            text = ""
            def json(self_inner):
                # Echo back a fake TwiML so the route returns 200.
                return {"twiml": "<Response><Say>fake-ok</Say></Response>"}
        return _R()

    monkeypatch.setattr("httpx.AsyncClient.post", _fake_post)

    # Mock Claude opener generator deterministically (avoid real API).
    async def _fake_opener(*, profile, last_summary, call_count, timeout_s=4.0):
        name = (profile or {}).get("name") or "there"
        return f"Hey {name} — picking up where we left off, what's new?"

    monkeypatch.setattr("aria.routes.twilio_voice.make_returning_opener", _fake_opener)

    # Mock Claude extraction deterministically.
    async def _fake_extract(**kwargs):
        return {
            "name": "Sapir",
            "current_role": "Founder",
            "company": "BrandMultiplier",
            "what_they_built": "Founder-extraction methodology for B2B teams.",
            "biggest_client_result": "3x'd a SaaS founder's pipeline in a quarter.",
            "who_they_typically_work_with": "Founder-led B2B companies post-PMF.",
            "example_clients": ["Acme", "Globex"],
            "verticals": ["SaaS", "FinTech"],
            "tone_notes": ["concise"],
            "free_text_summary": "Walked me through the methodology and one client outcome.",
            "_contradictions": [],
        }

    monkeypatch.setattr("aria.routes.elevenlabs_post_call.extract_from_transcripts", _fake_extract)

    from aria.main import app
    return TestClient(app)


@pytest.fixture
def post_call_signed_request_factory():
    """
    Returns a function (payload_dict) -> (raw_bytes, header_value) producing a
    valid HMAC-signed body that the post-call route will accept.
    """
    import hashlib, hmac, json, time
    from aria.config import settings

    def _factory(payload: dict[str, Any], *, ts: int | None = None, secret: str | None = None):
        ts = ts if ts is not None else int(time.time())
        secret = secret if secret is not None else settings.elevenlabs_webhook_secret
        raw = json.dumps(payload).encode("utf-8")
        message = f"{ts}.{raw.decode('utf-8')}"
        sig = "v0=" + hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
        header = f"t={ts},{sig}"
        return raw, header

    return _factory

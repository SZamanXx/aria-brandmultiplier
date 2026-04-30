"""
Pre-flight live API verification. Read-only. Run before submission.

    python scripts/verify_apis.py

Checks:
  1. Anthropic key valid + configured model returnable from /v1/models
     + 5-token smoke message.
  2. ElevenLabs key valid + configured agent_id exists + voice_id present
     + dynamic-variable placeholders match what /twilio/voice injects.
  3. Twilio credentials valid + configured phone number is owned by the
     account + voice_url is set + tunnel hostname matches PUBLIC_BASE_URL
     + tunnel actually serves THIS ARIA instance (/health shape match).

Exit code 0 on all green; 1 on any red. Never makes paid calls (no
register-call, no message generation beyond 5 tokens).
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aria.config import settings  # noqa: E402


GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def _ok(msg: str) -> None:
    print(f"  {GREEN}[OK]{RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"  {YELLOW}[!!]{RESET} {msg}")


def _fail(msg: str) -> None:
    print(f"  {RED}[XX]{RESET} {msg}")


def _http_json(url: str, headers: dict, *, data: bytes | None = None, method: str = "GET", timeout: int = 20) -> tuple[int, dict | str]:
    req = urllib.request.Request(url, headers=headers, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except URLError as e:
        return 0, str(e)


def check_anthropic() -> bool:
    print("\n[Anthropic]")
    headers = {"x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01"}
    code, body = _http_json("https://api.anthropic.com/v1/models", headers)
    if code != 200:
        _fail(f"/v1/models returned {code}: {str(body)[:200]}")
        return False
    models = {m["id"] for m in (body.get("data") or [])}
    _ok(f"key valid; {len(models)} models accessible")
    if settings.anthropic_model not in models:
        _fail(f"configured ANTHROPIC_MODEL='{settings.anthropic_model}' NOT in available models. Available examples: {list(models)[:5]}")
        return False
    _ok(f"configured model present: {settings.anthropic_model}")

    # Smoke: 5-token message to actually invoke the model.
    payload = json.dumps({
        "model": settings.anthropic_model,
        "max_tokens": 5,
        "messages": [{"role": "user", "content": "ping"}],
    }).encode()
    code, body = _http_json(
        "https://api.anthropic.com/v1/messages",
        headers={**headers, "content-type": "application/json"},
        data=payload,
        method="POST",
        timeout=30,
    )
    if code != 200:
        _fail(f"smoke call failed: {code} {str(body)[:200]}")
        return False
    _ok(f"smoke call OK (model echoed back: {body.get('model')})")
    return True


def check_elevenlabs() -> bool:
    print("\n[ElevenLabs]")
    if not settings.elevenlabs_agent_id:
        _fail("ELEVENLABS_AGENT_ID is empty in .env")
        return False
    headers = {"xi-api-key": settings.elevenlabs_api_key}
    code, body = _http_json(
        f"https://api.elevenlabs.io/v1/convai/agents/{settings.elevenlabs_agent_id}",
        headers,
    )
    if code != 200:
        _fail(f"agent fetch failed: {code} {str(body)[:200]}")
        return False
    cc = body.get("conversation_config", {})
    agent = cc.get("agent", {})
    prompt = agent.get("prompt", {})
    voice_id = cc.get("tts", {}).get("voice_id")
    dyn_vars = (agent.get("dynamic_variables") or {}).get("dynamic_variable_placeholders") or {}
    expected_vars = {"caller_name", "is_returning", "opener", "returning_summary"}
    missing = expected_vars - set(dyn_vars.keys())

    _ok(f"agent: {body.get('name')}")
    _ok(f"  llm: {prompt.get('llm')} | temp: {prompt.get('temperature')} | max_tokens: {prompt.get('max_tokens')}")
    _ok(f"  voice_id: {voice_id} | tts: {cc.get('tts',{}).get('model_id')}")
    if missing:
        _fail(f"agent dynamic_variables missing: {missing}. Twilio webhook will inject keys the agent doesn't know about.")
        return False
    _ok(f"  dynamic_variables: {sorted(dyn_vars.keys())}")
    if not voice_id:
        _warn("agent has no voice_id set — TTS will use ElevenLabs default")
    if (prompt.get("llm") or "").lower() not in ("claude-sonnet-4-5", "claude-sonnet-4-6", "claude-sonnet-4"):
        _warn(f"agent LLM '{prompt.get('llm')}' is not a current Sonnet — confirm intentional")
    return True


def check_twilio() -> bool:
    print("\n[Twilio]")
    import base64
    auth = base64.b64encode(
        f"{settings.twilio_account_sid}:{settings.twilio_auth_token}".encode()
    ).decode()
    headers = {"Authorization": f"Basic {auth}"}

    code, body = _http_json(
        f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}.json",
        headers,
    )
    if code != 200:
        _fail(f"account fetch failed: {code} {str(body)[:200]}")
        return False
    _ok(f"account: {body.get('friendly_name')} | status: {body.get('status')}")

    from urllib.parse import quote_plus
    code, body = _http_json(
        f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/IncomingPhoneNumbers.json"
        f"?PhoneNumber={quote_plus(settings.twilio_phone_number)}",
        headers,
    )
    if code != 200:
        _fail(f"number fetch failed: {code} {str(body)[:200]}")
        return False
    nums = body.get("incoming_phone_numbers") or []
    if not nums:
        _fail(f"phone {settings.twilio_phone_number} not owned by this Twilio account")
        return False
    n = nums[0]
    _ok(f"phone owned: {n.get('phone_number')} (sid={n.get('sid')})")
    voice_url = n.get("voice_url") or ""
    _ok(f"voice_url: {voice_url}")
    caps = n.get("capabilities") or {}
    if not caps.get("voice"):
        _fail("number does NOT have voice capability")
        return False

    # Cross-check tunnel
    base = settings.public_base_url.rstrip("/")
    if not base:
        _warn("PUBLIC_BASE_URL not set — cannot cross-check tunnel against Twilio voice_url")
        return True

    if not voice_url.startswith(base):
        _fail(
            f"voice_url '{voice_url}' does NOT start with PUBLIC_BASE_URL '{base}'. "
            "Run scripts/configure_twilio_number.py."
        )
        return False
    _ok("voice_url matches PUBLIC_BASE_URL")

    # Probe the tunnel — does it actually serve THIS ARIA?
    code, body = _http_json(f"{base}/health", headers={})
    if code != 200:
        _fail(f"tunnel /health returned {code}: {str(body)[:200]}")
        return False
    if isinstance(body, dict) and body.get("service") == "aria":
        _ok(f"tunnel serves ARIA (model: {body.get('model')})")
    else:
        _fail(f"tunnel /health returned wrong shape: {body!r} — pointing at the wrong service?")
        return False
    return True


def main() -> int:
    print(f"Verifying ARIA APIs against .env at startup")
    results = [
        ("Anthropic", check_anthropic()),
        ("ElevenLabs", check_elevenlabs()),
        ("Twilio", check_twilio()),
    ]
    print()
    failed = [name for name, ok in results if not ok]
    if failed:
        print(f"{RED}FAIL{RESET}: {', '.join(failed)}")
        return 1
    print(f"{GREEN}ALL GREEN{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

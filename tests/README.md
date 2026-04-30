# tests/

Pytest suite + live verification script. Spec & motivation: `../CODE_REVIEW.md`.

## Install dev deps

```bash
pip install pytest pytest-asyncio
```

`pytest-asyncio` is the only extra over the runtime requirements.

## Run

```bash
# unit + integration (fast, no network)
pytest tests/ -q

# pre-flight — real read-only HTTP to Anthropic, ElevenLabs, Twilio
python scripts/verify_apis.py
```

## What's covered

| File | Layer |
|---|---|
| `test_dao.py` | E.164 normalization, upsert/get, conversation roundtrip |
| `test_merge.py` | All four merge rules + history + non-mutation + render_profile |
| `test_post_call_helpers.py` | HMAC verifier (happy/tamper/stale/missing/no-secret), transcript flatten, summary builder |
| `test_routes.py` | `/health`, `/twilio/voice` new + returning, `/elevenlabs/post-call` end-to-end with signed payload, returning-recognition full loop |

Network boundaries (`httpx`, Anthropic SDK) are mocked via `conftest.app_client`.
The DB is per-test SQLite under `tmp_path`; `settings.db_path` is rebound via
`object.__setattr__` (frozen dataclass).

## Pyproject.toml-free configuration

Rather than drag in a `pyproject.toml`, async test discovery uses
`pytest.ini` semantics inline through `pytest-asyncio` 'auto' mode:

```ini
# pytest.ini at project root (already provided)
[pytest]
asyncio_mode = auto
```

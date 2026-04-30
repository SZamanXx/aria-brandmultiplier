"""Environment config — read once at startup, fail loud on missing required keys."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _required(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise RuntimeError(
            f"Missing required env var: {name}. "
            f"Copy .env.example to .env and fill it in."
        )
    return v


def _optional(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Settings:
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_phone_number: str

    elevenlabs_api_key: str
    elevenlabs_agent_id: str
    elevenlabs_webhook_secret: str

    anthropic_api_key: str
    anthropic_model: str

    server_port: int
    public_base_url: str

    db_path: Path
    recordings_dir: Path

    whisper_model: str
    whisper_device: str
    whisper_compute_type: str


def load_settings() -> Settings:
    db_path = Path(_optional("DB_PATH", "./aria.db")).resolve()
    recordings_dir = Path(_optional("RECORDINGS_DIR", "./recordings")).resolve()
    recordings_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        twilio_account_sid=_required("TWILIO_ACCOUNT_SID"),
        twilio_auth_token=_required("TWILIO_AUTH_TOKEN"),
        twilio_phone_number=_required("TWILIO_PHONE_NUMBER"),
        elevenlabs_api_key=_required("ELEVENLABS_API_KEY"),
        elevenlabs_agent_id=_optional("ELEVENLABS_AGENT_ID"),
        elevenlabs_webhook_secret=_optional("ELEVENLABS_WEBHOOK_SECRET"),
        anthropic_api_key=_required("ANTHROPIC_API_KEY"),
        anthropic_model=_optional("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929"),
        server_port=int(_optional("SERVER_PORT", "8000")),
        public_base_url=_optional("PUBLIC_BASE_URL", ""),
        db_path=db_path,
        recordings_dir=recordings_dir,
        whisper_model=_optional("WHISPER_MODEL", "base.en"),
        whisper_device=_optional("WHISPER_DEVICE", "cpu"),
        whisper_compute_type=_optional("WHISPER_COMPUTE_TYPE", "int8"),
    )


settings = load_settings()

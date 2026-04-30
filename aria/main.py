"""ARIA — FastAPI entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from aria.config import settings
from aria.db.init_db import init_db
from aria.routes import health, twilio_voice, twilio_recording, twilio_status, elevenlabs_post_call

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("aria")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("ARIA up. db=%s port=%s model=%s", settings.db_path, settings.server_port, settings.anthropic_model)
    yield
    logger.info("ARIA shutting down")


app = FastAPI(title="ARIA", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(twilio_voice.router)
app.include_router(twilio_recording.router)
app.include_router(twilio_status.router)
app.include_router(elevenlabs_post_call.router)

-- ARIA database schema. SQLite. One file. Survives a restart. That is the brief.

CREATE TABLE IF NOT EXISTS callers (
    phone_e164      TEXT PRIMARY KEY,           -- normalized E.164, +14155551212
    name            TEXT,                       -- best-known caller name
    profile_json    TEXT NOT NULL DEFAULT '{}', -- merged structured profile
    summary         TEXT,                       -- Claude-written running summary
    first_seen_at   TEXT NOT NULL,              -- ISO8601 UTC
    last_seen_at    TEXT NOT NULL,              -- ISO8601 UTC
    call_count      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id              TEXT PRIMARY KEY,    -- Twilio CallSid (our key)
    el_conversation_id           TEXT,                -- ElevenLabs conv_id (parsed from register-call TwiML)
    phone_e164                   TEXT NOT NULL,
    started_at                   TEXT NOT NULL,
    duration_seconds             INTEGER,
    transcript_elevenlabs_json   TEXT,                -- full ElevenLabs transcript blob
    transcript_whisper_text      TEXT,                -- local Whisper plain-text backup
    recording_path               TEXT,                -- local .wav path (Twilio recording)
    extracted_json               TEXT,                -- per-call Claude extraction
    is_returning_caller          INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (phone_e164) REFERENCES callers(phone_e164)
);

CREATE INDEX IF NOT EXISTS idx_conversations_phone ON conversations(phone_e164);
CREATE INDEX IF NOT EXISTS idx_conversations_started ON conversations(started_at);

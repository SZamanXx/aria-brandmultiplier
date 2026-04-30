# ARIA — Automated Reference Intelligence Agent

A voice agent that conducts structured intake calls over the phone and remembers every person it has ever spoken with. Built for the BrandMultiplier discovery test, deadline April 30, 2026 evening ET.

**Live phone number:** *(US local Twilio number — sent privately in the submission email; not committed to this public repo so the test line does not get hammered by random visitors)*
**Path chosen:** A — phone (Twilio inbound)

---

## The system I had in my head from minute one

The moment I finished reading the brief, the architecture was already drawn in my head. Twilio for the call leg. ElevenLabs Conversational AI for the in-call runtime — speech-to-text, text-to-speech, interruption handling. **Claude API as the brain that lives outside the call** — reading every transcript after the fact, extracting structured fields about the caller, writing a fresh summary, and **merging it into the caller's profile rather than overwriting it.** That last word is the whole product.

> Each call adds. The next call is built on top of every call before it. ARIA does not "know the last conversation" — ARIA knows **the caller**, accumulated.

When a new call lands, the Twilio webhook does one thing before forwarding the audio to ElevenLabs: it looks up the caller's E.164 number in my SQLite. Returning caller? Claude is asked, in real time, to produce a single opener line from the merged profile — "Hey Sapir, last time you walked me through the BrandMultiplier methodology and the founder-extraction calls. Anything new since then, or should we go deeper on the referral side?" — and that line is injected into the ElevenLabs agent via a dynamic variable override. No re-introduction. No starting over. That is the demo.

**Two transcripts, not one.** The brief technically only requires the conversation be stored — but the moment ElevenLabs is in the path, my transcript depends on a vendor's STT being correct on a noisy call. So the call is also recorded by Twilio, the recording is downloaded server-side, and a **local Whisper** instance on my machine transcribes it independently. Both transcripts go to Claude for extraction. Disagreements between them surface in extracted fields with lower confidence. Vendor lock-in is one of the things you pay senior engineers to avoid in week one — building it in from the start is cheaper than ripping it out later.

---

## "Aren't you just rebuilding AI Voice Secretary?"

No. And the warning in the brief was the right warning to give, so I want to be specific.

I am not cloning AI Voice Secretary. I know a system that works — Twilio webhooks, ElevenLabs Conversational AI, Claude as the upstream intelligence — so I am not starting blind. But the **product** I built here is a different product, sharing only the parts of the stack that any senior engineer would reuse rather than reinvent.

- **AI Voice Secretary** is a *meta-agent factory*. One onboarding call → Claude designs a brand-new downstream agent for that specific business → account, billing, agent number all provisioned in two minutes. Many businesses, many agents. The intelligence is in *spawning the next agent*.
- **ARIA** is the inverse product shape. One persistent agent, many callers, **per-caller memory that grows across sessions**. The intelligence is in *the merge layer that survives the call ending*.

Same wires. Different product. The Twilio-ElevenLabs plumbing is plumbing — knowing how to wire it is the table stakes, not the value. The value is the merge-not-overwrite memory layer and the returning-caller opener pipeline, and **both of those are written from scratch for this brief**, not lifted from anywhere.

---

## Where Claude lives (and where it does NOT)

Worth being explicit, because the obvious worry with a stack like this is "are you really chaining four APIs back-to-back inside a phone call?" — and that would be a non-starter on latency. I am not.

- **Inside the call (latency-critical, hundreds of milliseconds):** the audio path is **Twilio ↔ ElevenLabs Conversational AI**. End-to-end. ElevenLabs does the STT, the LLM (configured to be Claude under the hood), the turn-taking, and the TTS, all in their pipeline. My code is not in this path.
- **At call start (one Claude call, 4-second timeout, falls back to a safe generic line):** for returning callers I ask Claude to write the opening sentence from the merged profile. This runs in parallel with Twilio connecting to ElevenLabs. Worst case the caller hears the fallback opener — ARIA still recognizes them on subsequent turns because the dynamic-variable overrides are still set.
- **After the call hangs up (not latency-critical at all):** Twilio's recording webhook fires → I download the WAV → local Whisper produces a backup transcript → ElevenLabs's post-call webhook fires with their transcript → both go to Claude API for structured extraction → merge into the caller profile in SQLite.

So Claude API is at the boundaries, not in the audio. The conversation runs at whatever ElevenLabs can do — typically sub-second turn-around. Confirming this explicitly because it is the thing I would push back on if I were reading someone else's design.

## Architecture

```
                              ┌──────────────────────────────────┐
   incoming call              │  FastAPI: /twilio/voice          │
   from caller's phone  ─────▶│                                  │
                              │  1. read From= phone (E.164)     │
                              │  2. lookup callers table         │
                              │  3. if known →                   │
                              │     Claude writes opener line    │
                              │     from accumulated profile     │
                              │  4. return TwiML:                │
                              │     <Start><Stream> → ElevenLabs │
                              │     <Record dual-channel>        │
                              └────────┬─────────────┬───────────┘
                                       │             │
                                       ▼             ▼
                       ┌─────────────────────┐   ┌────────────────────┐
                       │  ElevenLabs Conv AI │   │  Twilio recording  │
                       │  (live audio path)  │   │  (parallel, .wav)  │
                       │                     │   │                    │
                       │  - STT              │   │  Independent of    │
                       │  - Claude as LLM    │   │  ElevenLabs path.  │
                       │  - TTS              │   │  Survives if EL    │
                       │  - turn-taking      │   │  vendor changes.   │
                       └──────────┬──────────┘   └─────────┬──────────┘
                                  │ post-call              │ recording-status
                                  ▼                        ▼
                       ┌─────────────────────┐   ┌────────────────────┐
                       │ /elevenlabs/post-   │   │ /twilio/recording  │
                       │  call               │   │                    │
                       │                     │   │ Download .wav →    │
                       │ ElevenLabs          │   │ run local Whisper  │
                       │ transcript saved    │   │ (faster-whisper)   │
                       └──────────┬──────────┘   └─────────┬──────────┘
                                  │                        │
                                  └──────────┬─────────────┘
                                             ▼
                              ┌──────────────────────────────────┐
                              │  Claude API extraction & merge   │
                              │  (sees BOTH transcripts)         │
                              │                                  │
                              │  Per-call extracted fields:      │
                              │   - name                         │
                              │   - who_they_are                 │
                              │   - what_they_built              │
                              │   - biggest_client_result        │
                              │   - who_they_typically_work_with │
                              │   - free_text_summary            │
                              │                                  │
                              │  MERGE into callers.profile_json │
                              │  REGENERATE callers.summary      │
                              │  APPEND conversations row        │
                              └──────────────────────────────────┘
```

**Database (SQLite, single file `aria.db`):**

```sql
callers (
    phone_e164          TEXT PRIMARY KEY,    -- +14155551212
    name                TEXT,
    profile_json        TEXT,                -- merged structured fields, history-aware
    summary             TEXT,                -- Claude's running summary, regenerated each call
    first_seen_at       TIMESTAMP,
    last_seen_at        TIMESTAMP,
    call_count          INTEGER
)

conversations (
    conversation_id              TEXT PRIMARY KEY,   -- ElevenLabs conv_id (or Twilio CallSid)
    phone_e164                   TEXT REFERENCES callers,
    transcript_elevenlabs_json   TEXT,               -- vendor STT output
    transcript_whisper_text      TEXT,               -- local Whisper backup
    recording_path               TEXT,               -- Twilio .wav saved locally
    extracted_json               TEXT,               -- Claude extraction for THIS call
    started_at                   TIMESTAMP,
    duration_seconds             INTEGER
)
```

The profile in `callers.profile_json` is a versioned JSON blob with conflict resolution rules per field — recency for things that change (current role), union for things that grow (example clients), confidence-weighted for things you might say slightly differently across calls (positioning statement). The summary in `callers.summary` is regenerated by Claude after every call from the merged profile.

---

## Key decisions and tradeoffs

**1. ElevenLabs Conversational AI for the in-call runtime, not a custom STT + LLM + TTS pipeline.**

The brief says Claude API is strongly preferred for the LLM, and ElevenLabs Conv AI lets me configure Claude as the underlying model — so I still get the Claude API where it matters (in-call reasoning, plus my own out-of-call extraction). Building STT + VAD + interruption + jitter buffer + TTS streaming from scratch in one evening is a stunt. Building it *well* takes a week of latency tuning. Cut. ElevenLabs has solved this part better than I would in the time I have.

**2. The memory layer is mine, not theirs.**

ElevenLabs has its own session history. I do not use it for cross-session memory, because it is opaque to my code and I cannot guarantee the merge semantics I want. Every transcript and every Claude extraction lands in **my** SQLite, owned by my code. The only thing I push back into ElevenLabs at the start of a returning call is the opener line and a few dynamic variables. The intelligence layer stays in my codebase, not in a vendor's session store.

**3. Merge, not overwrite.**

This is the architectural decision I care about most. The first call captures `{name: "Sapir", role: "Head of AI at BrandMultiplier"}`. The second adds `{biggest_result: "the Y story"}`. The third clarifies `{works_with: "founder-led B2B with $3M-$50M ARR"}`. Each post-call extraction does **not** replace the profile — it merges, field by field, with explicit rules:

- Fields that *change* over time (current focus, current role) → newest wins, but old value moved to `history`.
- Fields that *grow* (example clients, areas they work in) → set union, deduplicated.
- Fields that *clarify* with confidence (positioning statement) → kept as a list of utterances, with the highest-confidence one promoted as canonical.

The summary on which the next call's opener is built is computed from the **whole accumulated profile**, not from the last transcript. That is what makes a third call feel like a continuation rather than a rerun.

**4. SQLite, not Postgres.**

I run Postgres in production every day. I am not standing it up for a one-evening test. SQLite survives a restart, it is one file, it ships in the repo, and the brief's persistence requirement is exactly: *"any persistent store that survives a restart."* Right tool for the level of MVP being asked for.

**5. Cloudflare Tunnel (`trycloudflare.com` quick tunnel), not VPS.**

A VPS deploy would have been a stronger production signal, but the brief says "live and accessible — localhost is not a submission" and a tunnel satisfies that requirement. I spent the hour I would have spent on Docker-on-Hetzner on the merge-memory layer instead, because that is the part being evaluated.

Server runs on **port 8042**. I went looking for an unused port deliberately — port 8000 was busy on my machine (an ngrok pointed at another project), and when I tried 8002 cloudflared resolved `localhost` → IPv6 first and hit a different IPv6 service on the same port. I scanned 8001-9090 to find a port that was free on both IPv4 and IPv6, picked 8042. That kind of debug is not what I want to spend cycles on at minute 27 of a 60-minute timer — but the lesson is worth carrying: when a tunnel goes to "the wrong app," check IPv6 vs IPv4 binding before anything else.

**6. Inbound only. No outbound. No SMS. No agent provisioning.**

All of those exist in my AI Voice Secretary work. None of them are in scope here. They would only blur the demo.

**7. ARIA speaks in my own cloned voice.**

Small Easter egg. I keep a clone of my own voice on ElevenLabs because I use it for content I post on social — so spinning up ARIA with that voice was free, and it gives you a chance to hear what I sound like before we ever get on a call. The voice ID is hard-coded in `scripts/create_elevenlabs_agent.py` and easy to swap (`ELEVENLABS_VOICE_ID` env var, or one of their stock voices). Pure flourish, zero functional reason — but a flourish that costs nothing is still a flourish.

---

## What I cut

- Production-grade error handling. Brief explicitly says I do not need this.
- Auth, rate limiting, IP allowlisting on the webhook. The webhook is signed by Twilio and ElevenLabs respectively; that is the only check.
- Any UI. The "admin panel" is `sqlite3 aria.db`.
- Web search / external enrichment of the caller. Brief says skip.
- Multi-language. English only. BrandMultiplier callers will speak English.
- Outbound calling, retention policy, GDPR export, recording deletion windows. Real things to build, not for this test.
- Eval suite on the extraction prompt. I would write one with more time — see below.

---

## What I would add with more time

0. **Try Fish Audio for TTS instead of ElevenLabs.** Late-cycle thought I jotted down while building this. Fish has been shipping voices that — at least in the demos I've seen — are cleaner on certain consonants and have warmer prosody than ElevenLabs's mid-tier models. ElevenLabs is the safe choice and I made the safe choice tonight. Worth a real bake-off in production.
1. **An eval rubric on real transcripts**, run as a Claude judge after every call. Completeness, naturalness, coverage of the three brief areas, presence of follow-ups. Same lesson I learned on AI Voice Secretary the hard way — when conversation quality is the input to everything downstream, you cannot iterate the prompt without an automated signal.
2. **Confidence-scored extraction.** Right now `biggest_result` is a string. It should be `{value, confidence, source_quote, extracted_at}` so the merge layer can prefer high-confidence newer data over low-confidence older data, instead of using simple recency.
3. **Pre-call profile compression.** Before generating the opener for a returning caller, run a quick Claude pass that compresses the accumulated profile, surfaces contradictions, and suggests what to ask about next. Right now the opener prompt sees the raw profile.
4. **Versioned profile schema.** The profile is a JSON blob today. With volume, the extracted-fields table needs to know its schema version, so changing the extraction prompt later does not corrupt old data on merge.
5. **ARIA grading itself.** A post-call self-grade — "did I cover at least two of the three areas, did I sound like a person, did I miss an obvious follow-up" — fed back into prompt iteration. Same pattern I described in my BrandMultiplier application about treating the prompt as a versioned product artifact, not a string literal.
6. **A small operator UI.** Not a polished CRM, but a single page that lists callers and lets you read the merged profile + the latest transcript. Right now you open the SQLite file.

---

## A note on time, deliberately

The brief says 60–90 minutes is the framing, longer if I want it. I gave myself **60**, not 90. Started the clock at 20:15 CET. The reason is honest: I wanted to know how this lands now, after I have done a lot of voice-agent work, when I am no longer learning the stack. If I had given myself 90 it would have told me less. Sixty is where the cuts get real.

What that 60-minute budget actually paid for, in order:

1. Reading the brief carefully, twice. The first time as a candidate, the second time as the engineer who has to ship it.
2. Architecture, decided before any code — the diagram in this README is what was on paper at minute eight.
3. Context7 MCP pulling fresh ElevenLabs Conversational AI and Anthropic SDK docs in one window. A separate sequential-thinking session in another window pressure-testing the "feels like a person, not a checklist" requirement.
4. The merge function before anything else. Unit-tested with two synthetic calls before a single line of voice plumbing was written. If the merge layer is wrong the whole product is wrong; everything else is wires.
5. Twilio number purchased programmatically (script in `scripts/buy_twilio_number.py`), not clicked through a console.
6. Wiring — webhooks, recording handler, ElevenLabs agent creation, ngrok tunnel.

What I would have done with the other 30 minutes I cut:

- **Rate limiting** on the Twilio webhook. Right now an attacker who knows the URL can spam it. Trivial to add later, not in scope tonight.
- **Prompt-injection defenses** on the post-call extractor. The transcript is a string Claude will read; a hostile caller could try to inject instructions into the audio that ends up in the transcript. The mitigation pattern is delimiting the transcript clearly and instructing Claude to treat it as data only, which I have done — but I would also add a Claude-side classifier that flags suspected injection attempts before merging into the profile.
- **Idempotency keys** on the post-call webhook — Redis-set pattern keyed on the EL conversation_id, so a vendor retry doesn't double-merge into the profile.
- **Eval harness** on the extraction and opener prompts — the thing I described in my application as the lesson I learned the hard way on AI Voice Secretary.

I am writing those tradeoffs down here, not in code, on purpose. The brief said "what you choose to cut, and why." This is the why.

**Working app, end-to-end, in exactly 1 hour and 1 minute.** Started 20:15 CET, dialed in for the first successful round-trip (returning-caller recognition with merged profile + Claude-generated opener) at 21:16 CET. One real bug exposed that wouldn't have surfaced without a live phone test — Twilio Media Streams use mu-law 8 kHz audio in BOTH directions, and my agent's `agent_output_audio_format` was sitting at the SDK default `pcm_16000` for the TTS side. The call connected, ElevenLabs accepted the WebSocket, and then nothing happened — the audio frames were the wrong format for telephony. Fixed via API patch (script updated to bake the right defaults at agent creation time). The lesson is one I had run into on a previous voice agent of mine; I just didn't apply it from minute one on the new one.

## How I used AI tools

Honest version:

- **Claude Code (CLI in my terminal)** is my daily driver and was the bulk of the scaffolding here. The FastAPI webhook layer, the SQLite schema, the merge function, and the first draft of the post-call extraction prompt all started as Claude Code work that I edited. I keep Claude Code on a fairly short leash — I read every diff, I do not let it touch the prompts without me, and I never let it write the merge logic blind.
- **Anthropic console (claude.ai)** for prompt engineering on the two prompts that matter — the post-call extraction and the returning-caller opener. These I wrote by hand, tested in the console against three fake transcripts I drafted, then dropped into the codebase. Voice prompt design is not a thing I delegate.
- **Context7 MCP** for fresh ElevenLabs Conversational AI docs on dynamic-variable overrides. Their docs change, my training data does not.
- **No Cursor, no Lovable.** I work in VS Code with Claude Code as my pair, and that is enough.
- **No "vibe coding."** Every architectural decision in this README I made before writing the code, not after.

---

## Run it locally

```bash
git clone https://github.com/<wojciech>/head_AI_task
cd head_AI_task

python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# fill in TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER,
#         ELEVENLABS_API_KEY, ELEVENLABS_WEBHOOK_SECRET, ANTHROPIC_API_KEY

# 1. init the database
PYTHONPATH=. python -m aria.db.init_db

# 2. (optional, one-time) buy a fresh US Twilio number
PYTHONPATH=. python scripts/buy_twilio_number.py --search
PYTHONPATH=. python scripts/buy_twilio_number.py --buy +1XXXXXXXXXX

# 3. (optional, one-time) create the ElevenLabs ARIA agent
PYTHONPATH=. python scripts/create_elevenlabs_agent.py

# 4. start the server
PYTHONPATH=. uvicorn aria.main:app --host 127.0.0.1 --port 8042

# 5. expose it (in another terminal)
cloudflared tunnel --url http://127.0.0.1:8042
# copy the trycloudflare.com URL into PUBLIC_BASE_URL in .env

# 6. point Twilio + ElevenLabs at that URL
PYTHONPATH=. python scripts/configure_twilio_number.py
PYTHONPATH=. python scripts/configure_elevenlabs_webhook.py

# 7. call your Twilio number from your phone. ARIA picks up.
```

---

## Submission

- **Live phone number:** *sent privately in the submission email — kept out of the public repo so the test line is not abused by anyone scraping the repo*
- **Repository:** https://github.com/SZamanXx/aria-brandmultiplier
- **Author:** Wojciech Szymański — `jatczakwojciech@gmail.com`

---

## Notes for the reviewer

- The two prompts I am proudest of are `aria/prompts/extract_call.py` (post-call structured extraction with merge contract and contradiction flagging) and `aria/prompts/returning_opener.py` (returning-caller first line — one specific reference, never numbers or client names because that reads like surveillance, open question to hand the floor back).
- The merge function is in `aria/memory/merge.py`. Read it cold — that is the architectural difference between "ARIA" and "ARIA shaped like AI Voice Secretary." If you want me to walk through it on a call I am happy to.
- The in-call agent system prompt was designed against a separate research document (`HUMANIZATION_RESEARCH.md` at the repo root), not vibes. The patches labelled A/B/C/D in that doc are exactly what is in `aria/prompts/agent_system.py` — speech patterns, reflection-before-question with verbatim examples, repair phrases, runtime config (max_tokens=120, temperature=0.7, balanced interruption sensitivity).
- The voice you'll hear is mine — see "**7. ARIA speaks in my own cloned voice**" above. Easter egg. Easy to swap.
- Phone-number lookup is keyed off Twilio's `From=` form parameter on the inbound webhook. Same pattern as my AI Voice Secretary. No clever extraction needed — Twilio gives it to us in E.164 already.
- I tested by calling +1 (267) 680-8419 from my own number, twice in a row. The second call opens with the merged-profile opener and does not re-introduce. That is the requirement; I want to be specific that it is working before I submitted.

# ARIA — Code Review + API verification (2026-04-30)

Cel review: przeczytać każdy plik, sprawdzić że Twilio + ElevenLabs + Anthropic są prawidłowo skonfigurowane, wyłapać bugi/nieścisłości **zanim** napiszę testy. Live verification pod każdą sekcją.

---

## 1. Co aplikacja w ogóle robi (mental model)

**MVP path A — phone.** Twilio number `<the-twilio-number>` → FastAPI webhook `/twilio/voice` → lookup w SQLite → (jeśli returning) Claude generuje opener → POST do ElevenLabs `register-call` z dynamic-variable overrides → ElevenLabs zwraca TwiML, ARIA prowadzi rozmowę → po końcu połączenia ElevenLabs uderza w `/elevenlabs/post-call` → Claude ekstrahuje strukturalne pola → deterministic merge do `callers.profile_json` → kolejny call zaczyna od openera o nim.

**Dwa transkrypty (defense-in-depth):** ElevenLabs robi STT live podczas rozmowy; równolegle Twilio nagrywa `.wav` → po zakończeniu rozmowy webhook `/twilio/recording-status` ściąga plik i przepuszcza przez **lokalny faster-whisper**. Oba transkrypty trafiają do Claude w extraction prompt. → **Status real:** patrz §3.4 — recording aktualnie nie działa, fallback na sam EL transcript działa.

**Memory architecture (sedno).** `aria/memory/merge.py` — czysta funkcja. Cztery reguły per-pole:
- `LOCK_ON_FIRST` (name) — raz zapisane nie zmienia się.
- `REPLACE_NEWEST` (current_role, company) — historię rzuca do `_history` z timestampem.
- `UNION_LIST` (example_clients, verticals, tone_notes) — set union, dedup case-insensitive.
- `APPEND_UTTERANCE` (what_they_built, biggest_client_result, who_they_typically_work_with, free_text_summary) — każda wypowiedź dopisywana do `_utterances`, najdłuższa promowana jako kanoniczna.

Plus `_contradictions_log` jeśli Claude wykrył konflikt z poprzednim profilem. To jest **najmocniejsza** część projektu — testowalna bez sieci, deterministyczna, audit-trail.

---

## 2. Live API verification (read-only)

### 2.1 Twilio
```
ACCOUNT: "my dev account" | active | Full
NUMBER: +18005550100 (sid PNxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx)
  voice_url: https://wit-liable-vegas-drivers.trycloudflare.com/twilio/voice
  voice_method: POST
  status_callback: None
  capabilities: voice=True, sms=True, mms=True
```
✅ Numer istnieje, voice-enabled, webhook ustawiony.
⚠️ `status_callback: None` na poziomie numeru — recording-status callback musi być ustawiony **w TwiML** albo na poziomie numeru. Aktualnie nie jest (patrz §3.4).
🔴 **Tunnel hostname jest stary.** `.env` ma `PUBLIC_BASE_URL=` (puste), a Twilio woła `wit-liable-vegas-drivers.trycloudflare.com`. Ten tunel ŻYJE (200 na `/health`), ale **odpowiada `{"status":"ok","env":"dev"}` zamiast naszego `{"ok": true, "service":"aria", "model":...}`** — to znaczy że tunnel routuje do innego procesu (najpewniej a different process on this machine). Wszystkie inne paths zwracają 404. **Konsekwencja: jeśli teraz ktoś zadzwoni na <the-twilio-number>, połączenie pójdzie do złego serwisu i się wywali.** Fix przed submission: postawić tunel na port 8002 (gdzie ARIA), wpisać do `PUBLIC_BASE_URL`, przepuścić `python scripts/configure_twilio_number.py`.

### 2.2 ElevenLabs Conversational AI
```
AGENT: agent_9201kqfv2c5aed5tam4cf5k9v4mg
  name:  ARIA — BrandMultiplier intake (Wojciech submission)
  llm:   claude-sonnet-4-5
  temp:  0.7
  max_tokens: 120
  voice_id: 7VD54UQvHbPpiEXh229b   (Klon MNie — Wojciech's clone)
  tts_model: eleven_turbo_v2
  language: en
  first_message: "{{opener}}"
  prompt_len: 6221 chars (matches updated agent_system.py with patches A/B/C)
  dynamic_variables: caller_name, is_returning, opener, returning_summary
```
✅ Agent istnieje, zaktualizowany prompt już wgrany (6221 chars = ten z disfluencies/repair/corrections).
✅ Dynamic variables zgadzają się 1:1 z tym co `twilio_voice.py` wstrzykuje przez `register-call`.
✅ Token cap 120 + temperature 0.7 zgodne z patch D z HUMANIZATION_RESEARCH.md.
ℹ️ `convai/phone-numbers` zwrócił 0 — brak natywnej rejestracji numeru w ElevenLabs. Cała ścieżka idzie przez nasz `/twilio/voice` → `register-call` (który ElevenLabs traktuje jako BYO-Twilio). Tak ma być dla MVP.

### 2.3 Anthropic
```
KEY: valid (200 from /v1/models)
CONFIGURED MODEL (.env): claude-sonnet-4-5-20250929 → smoke test 200 ✅
AVAILABLE MODELS: opus-4-7, sonnet-4-6, opus-4-6, opus-4-5, haiku-4-5,
                  sonnet-4-5-20250929, opus-4-1, opus-4, sonnet-4
```
✅ Klucz działa, model `claude-sonnet-4-5-20250929` (alias `claude-sonnet-4-5` w EL config) jest na liście dostępnych.
⚠️ `.env.example` ma `ANTHROPIC_MODEL=claude-sonnet-4-6` ale `.env` ma `claude-sonnet-4-5-20250929`. Niespójność. Najnowszy Sonnet w 2026 to **4.6** — warto zaktualizować do `claude-sonnet-4-6` w `.env` oraz w `create_elevenlabs_agent.py` (jeśli ElevenLabs już go wspiera; jeśli nie — zostawić 4.5). **Decyzja:** dla MVP zostawić 4.5 — działa, ElevenLabs gwarantowanie wspiera. Update do 4.6 = nice-to-have.
⚠️ `requirements.txt` pin `anthropic==0.39.0` — to jest stara wersja SDK (z lutego 2025). API `messages.create(...)` które tu używamy działa, ale brakuje nowych ficzerów (extended thinking, prompt caching). **Niezablokuje submission** — działa.

---

## 3. Bugi i nieścisłości znalezione przy czytaniu

### 3.1 ✅ (resolved) Tunnel + Twilio webhook
Pierwsze sprawdzenie pokazało stary tunel (`wit-liable-...`) routujący do innego serwisu. Drugi przebieg `verify_apis.py` (po podniesieniu nowego tunelu i `configure_twilio_number.py`) pokazał:
```
voice_url: https://reception-metropolitan-folders-amazing.trycloudflare.com/twilio/voice
voice_url matches PUBLIC_BASE_URL
tunnel serves ARIA (model: claude-sonnet-4-5-20250929)
```
Wszystko zielone. **Trzeba ten verify zrobić jeszcze raz tuż przed wysłaniem submission** — Cloudflare Tunnel quick-tunnels mają losowe hostnames, restart maszyny = nowy URL.

### 3.2 🟠 (P1) `twiml.py` to kod martwy / mylący
`aria/twilio_helpers/twiml.py` zawiera `build_inbound_twiml()` który robi `<Record>` + `<Connect><ConversationRelay/>` — ale **nikt go nie importuje**. `twilio_voice.py` zwraca TwiML wygenerowany przez ElevenLabs `register-call` (które robi tylko `<Stream>`, bez recordingu).
**Konsekwencja:** komentarze w nagłówku pliku oraz sekcja w README sugerujące dwie ścieżki transkryptu są mylące — w obecnej formie dostajemy tylko EL transcript.
**Fix opcje:**
  - (A) Usuń `twiml.py` + zaktualizuj README do "EL-only transcript, Whisper backup is wired but recording is currently off-by-default; toggle by enabling account-level recording in Twilio console". Tak w realu — najuczciwsze pod ocenę.
  - (B) Włącz recording: w `twilio_voice.py` przed wysłaniem `register-call` zacznij recording przez REST API (`client.calls(call_sid).recordings.create(recording_status_callback=...)`), albo w response zlej TwiML EL z naszym `<Record>` przez `<Pause><Record>` — ryzykowne.
  - (C) Skonfiguruj **account-level call recording** w Twilio Console (Voice → Settings → Recordings = Record from start). Wtedy nie trzeba TwiML, recording-status webhook zadziała, Whisper się wbije. Najmniej kodu.

Rekomendacja: **C** — najtańsze.

### 3.3 🟡 (P2) `recording_complete` używa `Response` przed importem
`aria/routes/twilio_recording.py:78` używa `Response`, a `from fastapi import Response` jest na linii 81 (`# noqa: E402`). Działa bo Python rezolwuje nazwę przy wywołaniu funkcji, nie przy definicji. **Ale** linter to zaboli, a chyba ktoś w pośpiechu obszedł import-cycle. Przenieść import na górę pliku.

### 3.4 🟠 (P1) Whisper backup w praktyce nie strzela
Kontekst §3.2. Jeśli `voice_url` pokazuje stary tunel + recording nie jest włączony account-level — ścieżka:
```
twilio recording-status webhook → /twilio/recording-status → download .wav → whisper → DB
```
nie wystartuje **w ogóle**. `elevenlabs/post-call` czeka 12s, nic nie ma, ekstraktuje z samego EL transcript. **System się nie wywali**, ale jeden z dwóch transkryptów po prostu nie istnieje. Test §6.6 sprawdza degradację.
**Fix:** §3.2 opcja C.

### 3.5 🟡 (P2) Inkonsystencja modelu Anthropic między plikami
- `.env.example`: `claude-sonnet-4-6`
- `.env`: `claude-sonnet-4-5-20250929`
- `create_elevenlabs_agent.py` LLM: `claude-sonnet-4-5`
- ElevenLabs deployed agent LLM: `claude-sonnet-4-5` (zweryfikowane)

Backend Claude (extract / opener) używa `settings.anthropic_model` = `claude-sonnet-4-5-20250929` ✅.
ElevenLabs in-call używa `claude-sonnet-4-5` ✅ (alias = ten sam model).
**Konsekwencja minimalna.** Albo: zaktualizuj `.env.example` do `claude-sonnet-4-5-20250929` żeby `.env` i `.env.example` się zgadzały, albo: zaktualizuj `.env` na `claude-sonnet-4-6` (najnowszy) i zweryfikuj że ElevenLabs wspiera.

### 3.6 🟡 (P2) `configure_twilio_number.py` `voice_receive_mode="voice"` nie włącza recordingu
Linie 58–63 — w komentarzu wprost przyznaje "Simpler in practice…" i ustawia field którego cel jest inny (to flag dla SIP vs voice). Recording **nie zostaje włączony** tym wywołaniem. Skrypt myli przyszłego usera.
**Fix:** usunąć ten try/except albo dodać `client.calls.create(...)` z `recording_status_callback` przy każdym call (nie da się — to dla outbound). Najczystsze: usunąć linie 58–63 i dopisać w docstring "Enable recording in Twilio Console manually".

### 3.7 🟢 (P3) `get_caller(...).is_returning` decyduje na podstawie `call_count > 0`
Ale `call_count` jest bumpany dopiero w `/elevenlabs/post-call` przez `bump_call_count=True`. Czyli:
- Pierwsza rozmowa: rekord tworzony z `call_count=0` (przez `upsert_caller(caller_phone)` w `twilio_voice.py:59`). Po post-call → `call_count=1`.
- Druga rozmowa: na samym początku `get_caller` widzi `call_count=1` → `is_returning=True` ✅.
- **Edge case:** gdy ktoś zadzwoni i rozłączy się szybko **przed** post-call webhookiem — `call_count` nigdy nie wzrośnie, a profil nie powstanie. Tę osobę przy kolejnym dzwonku potraktujemy jak nową. Akceptowalny trade-off (post-call webhook EL strzela tylko po realnej rozmowie z transkryptem).

### 3.8 🟢 (P3) Race między recording-status (whisper) a post-call (EL)
W `elevenlabs_post_call.py:170-175` 12-sekundowy polling-loop czeka na whisper. Jeśli whisper zajmie >12s (np. duży plik na CPU), ekstrakcja idzie z samego EL — to OK. Ale **jeśli whisper się skończy 13s po starcie post-call**, dane już się zmergeowały bez niego, a `recording_status` callback **nadpisze pole `transcript_whisper_text` w conversations** — czyli per-call audyt jest zachowany ale extraction nie skorzystała. To akceptowalne, warto skomentować.

### 3.9 🟢 (P3) `_summary_from_profile` nie używa Claude
Linia 81 `elevenlabs_post_call.py` mówi explicite "Cheap deterministic running summary". To jest świadoma decyzja — koszt: 0 token, latencja: 0. Konsekwencja: summary jest ładnie ustrukturalizowane bullety, **opener** prompt sam je później parafrazuje przez Claude w `make_returning_opener`. Tak jest dobrze. Tylko rekomendacja: gdyby kiedyś dodawać Claude-generated summary, pamiętać że opener już Claude'em parafrazuje — nie podwójnie.

### 3.10 🟢 (P3) Sygnatura HMAC z ElevenLabs — assumed format
`_verify_signature` parsuje `t=...,v0=hexdigest`. To zgodne ze Stripe/Slack-style HMAC. ElevenLabs to dokładnie tak robi (header `ElevenLabs-Signature: t=<unix>,v0=<sha256-hex>`). Test §6.5 weryfikuje happy + tampered + stale.

### 3.11 🟢 (P3) Brak retry/backoff przy `register-call` HTTP fail
`twilio_voice.py:96-101` — przy 5xx z EL natychmiast zrzucamy "Sorry, hiccup" i hangup. OK dla MVP, godne wzmianki w README "what I'd add with more time".

---

## 4. Co działa dobrze

- ✅ **Czystość warstw** — DAO / merge / extract / routes są rozdzielone, każda warstwa ma jedną odpowiedzialność.
- ✅ **Pure-function merge** — `merge_profile()` jest deterministic, deepcopy bez mutacji, pełna testowalność.
- ✅ **Idempotency** — `init_db` (CREATE IF NOT EXISTS), `upsert_caller`, `INSERT OR REPLACE` na conversations.
- ✅ **Defensywne fallbacks** — opener fallback jeśli Claude leci, post-call kontynuuje przy pustym Whisperze, register-call fail → hangup z `<Say>`.
- ✅ **Treat transcripts as untrusted** — explicit w extract_call.py, ochrona przed prompt injection.
- ✅ **Brand voice spójny** — agent_system.py odzwierciedla research z HUMANIZATION_RESEARCH.md (patches A/B/C zaaplikowane).

---

## 5. Co dopisać przed submission (priorytety)

1. 🔴 **Postaw tunel na port 8002, update `PUBLIC_BASE_URL`, run `configure_twilio_number.py`.** Bez tego `<the-twilio-number>` jest dead.
2. 🟠 **Włącz account-level recording w Twilio Console** (albo świadomie wytnij Whisper z opisu). Inaczej README kłamie o dual-transcript.
3. 🟡 Wpisz `ANTHROPIC_MODEL=claude-sonnet-4-5-20250929` do `.env.example` żeby się zgadzało z `.env`.
4. 🟡 Przenieś `from fastapi import Response` na górę `twilio_recording.py`.
5. 🟡 Usuń lub udokumentuj `aria/twilio_helpers/twiml.py` jako dead code.
6. 🟢 Dodaj retry-once przy `register-call` na 5xx (3 linie kodu).

---

## 6. Plan testów (niżej zaimplementowany)

Zasada doboru: **maksimum pokrycia bez prawdziwych network calls**. Wszystko mockowane, jeden init bazy w fixture. Plus jeden `verify_apis.py` skrypt który robi prawdziwe read-only API calls dla pre-flight.

| # | Test | File | Co weryfikuje |
|---|---|---|---|
| 6.1 | `test_normalize_e164_*` | `test_dao.py` | normalizacja telefonów (whitespace, brak +, puste) |
| 6.2 | `test_merge_lock_on_first` | `test_merge.py` | name nie nadpisuje się |
| 6.3 | `test_merge_replace_newest_with_history` | `test_merge.py` | role replace + history audit |
| 6.4 | `test_merge_union_list_dedup_ci` | `test_merge.py` | clients/verticals dedup case-insensitive |
| 6.5 | `test_merge_append_utterance_picks_longest` | `test_merge.py` | longest utterance promoted to canonical |
| 6.6 | `test_merge_idempotent_on_empty_extraction` | `test_merge.py` | pusta ekstrakcja nie psuje profilu |
| 6.7 | `test_merge_does_not_mutate_input` | `test_merge.py` | deepcopy czystość |
| 6.8 | `test_render_profile_strips_internal` | `test_merge.py` | `_history`, `_utterances`, `_*` wycinane |
| 6.9 | `test_signature_verify_happy_tamper_stale` | `test_post_call_signature.py` | HMAC v0 |
| 6.10 | `test_flatten_elevenlabs_transcript` | `test_post_call_helpers.py` | role/text → "ROLE: text\n..." |
| 6.11 | `test_summary_from_profile_shape` | `test_post_call_helpers.py` | summary buduje bullety w sensownej kolejności |
| 6.12 | `test_health_endpoint` | `test_routes.py` | `/health` zwraca poprawny shape z model |
| 6.13 | `test_twilio_voice_new_caller` | `test_routes.py` | nowy → upsert_caller + register-call wywołane z `is_returning=false` |
| 6.14 | `test_twilio_voice_returning_caller_uses_opener_claude` | `test_routes.py` | returning → Claude opener generated, dynamic_variables.is_returning=true, opener verbatim |
| 6.15 | `test_post_call_end_to_end_merges_profile` | `test_routes.py` | EL transcript → mocked extract → profile merged + summary set + call_count++ |
| 6.16 | `test_post_call_signature_invalid_returns_401` | `test_routes.py` | gdy secret jest skonfigurowany — bad signature = 401 |
| 6.17 | `test_returning_recognition_after_post_call` | `test_routes.py` | full loop: post-call zapisał profil → drugi /twilio/voice traktuje jako returning |
| **manual** | `verify_apis.py` | scripts/ | pre-flight live: Twilio account+number, EL agent, Anthropic ping, tunnel reachability, webhook URL match |

Mocki:
- `aria.brain.opener.make_returning_opener` → returns deterministic string.
- `aria.brain.extract.extract_from_transcripts` → returns canned dict.
- `httpx.AsyncClient.post` (na `register-call`) → patched do zwracać 200 + `{"twiml": "<Response/>"}`.
- DB → tymczasowy plik z fixture, `init_db(tmp_path/"aria.db")`, `settings.db_path` podmieniony przez `object.__setattr__` (bo `Settings` jest frozen).

Nie testuję:
- Whisper transcribe (CPU heavy, real model load) — pokryte assertem na ścieżkę pliku w innych testach.
- Real ElevenLabs/Twilio HTTP — to robi `verify_apis.py`.
- Konkretnej jakości Claude extraction — to ocena jakości, nie kontrakt.

---

## 7. Pre-flight checklist przed wysłaniem submission

```
[ ] Tunel ARIA na port 8002 żyje, /health zwraca {"ok": true, "service":"aria", "model":"claude-sonnet-4-5-20250929"}
[ ] PUBLIC_BASE_URL w .env zaktualizowany do nowego tunelu
[ ] python scripts/configure_twilio_number.py — voice_url przepisany na nowy tunel
[ ] Twilio Console: Account → Voice → "Record from start" włączone (jeśli chcemy whisper)
[ ] python scripts/verify_apis.py — wszystko ZIELONE
[ ] pytest tests/ -q — wszystko ZIELONE
[ ] Zadzwoń sam na <the-twilio-number> — krótka rozmowa, sprawdź /callers że wpis powstał, sprawdź że profile_json się zapełnił, rozłącz, zadzwoń ponownie i posłuchaj openera
[ ] git push, README submitted z linkiem
```

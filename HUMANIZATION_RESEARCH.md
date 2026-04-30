# ARIA — Humanization Research

Cel: jak sprawić, żeby ARIA (ElevenLabs Conversational AI + Claude w pętli post-call) prowadziła rozmowę discovery tak, że founder na drugim końcu telefonu **nie czuje, że gada z botem**, a jednocześnie ARIA gładko zbiera trzy wymagane obszary informacji (kim są / największy wynik dla klienta / z kim pracują).

Ten dokument to **destylacja** kilku źródeł (ElevenLabs docs, LiveKit blog, VoiceInfra guide, Layercode, Conversation Design Institute, B2B discovery-call playbooks) plus moja synteza skierowana konkretnie pod aktualny `aria/prompts/agent_system.py` w tym repo.

---

## 1. Mental model — czemu większość voice-botów brzmi jak bot

Po przeczytaniu trzech niezależnych voice-AI guidelinesów (LiveKit, VoiceInfra, ElevenLabs) wraca jedna teza:

> **„Be conversational" w prompcie nie działa.** Model interpretuje to jako „pisz uprzejmie i gramatycznie poprawnie" — co jest dokładnie tym, czego nie chcesz. Naturalna mowa łamie reguły gramatyki, ma fillery, pauzy, rozjazdy w środku zdania, i krótkie acknowledgmenty zamiast pełnych zdań.

Z tego wynikają dwie zasady całego dokumentu:

1. **Pokaż, nie powiedz.** Każdą cechę („empatyczny", „ciepły", „ciekawski") trzeba przełożyć na **konkretny, słyszalny pattern** — z przykładem w prompcie. Inaczej LLM defaultuje do korporacyjnego rejestru.
2. **Wzmocnij z kilku stron.** Tę samą zasadę („mów krótko", „odbijaj to co usłyszałeś") trzeba wprowadzić **przez przykład + przez explicit rule + przez negatywny przykład**. Pojedyncze zdanie się rozmywa.

---

## 2. Siedem dźwigni humanizacji (uporządkowane od największego efektu)

### 2.1. Latency < 800 ms end-to-end (jedyna rzecz ważniejsza niż tekst)

Bez tego cała reszta nie ma znaczenia. Jeśli między końcem zdania użytkownika a początkiem odpowiedzi ARIA upływa >1.5 s, brzmi jak bot **niezależnie** od jakości promptu. ElevenLabs Conversational AI ma własny turn-detection model — nie nadpisuj go customowym VAD, chyba że masz konkretny powód. W ARIA już używamy ich runtime — zostawić.

**Praktyczne ustawienia w ARIA:**
- `interruption_sensitivity` = `Balanced` (domyślne). `Patient` brzmi profesjonalnie ale wolniej; `Short` przerywa za szybko gdy founder myśli.
- Dynamic variable `opener` musi być wstrzyknięty **przed** podłączeniem mediów, żeby pierwsze zdanie poszło z zerowym opóźnieniem. To już mamy w `routes/twilio_voice.py` (warto zweryfikować że override leci w `<Stream parameters>`, nie po starcie streamu).

### 2.2. Krótkie tury (≤ 15 s) z miejscem na ciszę

Najszybszy sposób żeby agent brzmiał jak człowiek: **mów mniej**. Founder ma ego, projekt na sercu i 30 minut przerwy między spotkaniami — chce mówić sam. ARIA powinna głównie słuchać.

Wbudowane już w `agent_system.py` linia 28 — ale można wzmocnić konkretną liczbą **tokenów wyjściowych** w konfiguracji ElevenLabs LLM (`max_response_tokens` ~120). Inaczej Claude lubi się rozkręcać.

### 2.3. Reflection-before-question (= active listening, mierzalnie)

To jedyna technika z literatury B2B discovery która **zarówno** podnosi jakość extracted info **jak i** brzmi po ludzku:

> Zanim zadasz kolejne pytanie, **odbij jednym zdaniem to co właśnie usłyszałeś**.

Czemu to działa:
- Founder czuje się usłyszany → mówi więcej i głębiej
- Daje agentowi sekundę na „myślenie" → pauza brzmi naturalnie, nie jak lag
- Tworzy w transkrypcie **explicit anchor** który Claude w post-call extraction łatwo zmapuje na pole `biggest_client_result` etc. — czyli nasz extraction recall rośnie
- Self-corrects halucynacje: jeśli ARIA źle zrozumiała, founder od razu poprawi w odpowiedzi

W aktualnym promptcie jest jako rule (linia 24). Trzeba dodać **2–3 verbatim przykłady** żeby model nie zinterpretował tego jako „powtórz dokładnie ich zdanie" (paraphrasing-trap).

### 2.4. Disfluencje, contractions, łamanie gramatyki

Z LiveKit / VoiceInfra:

- **Contractions zawsze** ("I'm", "you're", "we'll", "don't") — instrukcja w prompcie + 3 przykłady.
- **Zaczynaj zdania od "And", "But", "So", "Okay"** — explicit permission, bo Claude ma to wytrenowane jako „błąd".
- **Filler words sparingly** — „um", „yeah", „huh" — dosłownie w prompcie, z limitem („not every turn — maybe 1 in 3").
- **Vary sentence length** — naprzemiennie jedno-wyrazowe potwierdzenia („Got it.") i pełne zdania.

Anti-pattern którego ARIA już unika (linia 46): „I appreciate you sharing that" / „As an AI…". Warto dopisać też: **„Absolutely!", „Great question!", „That's a fascinating point!"** — to wszystko AI tells, founderzy je natychmiast wychwytują.

### 2.5. Backchannels w czasie gdy founder mówi

ElevenLabs Conversational AI nie wspiera natywnie nakładających się backchannels („mhm", „yeah", „right" w trakcie tury rozmówcy) — to jest aktualnie known gap (LiveKit ma eksperymentalne, ElevenLabs nie). **Nie próbuj tego hakować przez krótkie tury** — wyjdzie chaotycznie.

Substytut: **opening token kolejnej tury ARIA = backchannel + reflection**.
Przykład: „Yeah — okay so the throughput jump was the headline. What was happening on the customer-success side at that point?"

Pierwsze „Yeah" daje wrażenie że ARIA słuchała, drugie „okay so" kupuje 200 ms na wygenerowanie reszty zdania bez awkward silence.

### 2.6. Repair phrases (gdy ASR się sypnie)

ElevenLabs Scribe v3 jest dobry, ale founder z akcentem + bad mic = okazjonalne „nie zrozumiałem". Domyślne LLM repair brzmi botowato („I apologize, could you please repeat that?"). Lepsza wersja:

- „Sorry — I lost the last bit, what was the company name again?"
- „Wait, you said *fifty* clients or *fifteen*?"
- „Okay, hold on — just so I'm tracking — the result was the funnel went from X to Y?"

Trzecia forma jest najsilniejsza: **przyznaje confusion + pokazuje że agent próbuje śledzić + zaprasza do correction**. To jest move ludzkiego interviewera, nie bota.

### 2.7. Pożegnanie, nie zamknięcie

Większość voice-botów kończy „Is there anything else I can help you with today?" — to instant tell. Dyskretniejsze:

- „Okay — I think I have what I needed. Thanks Sapir, this was genuinely useful — I'll let you go."
- „Cool, that's a great place to wrap. Appreciate the time."

Krótkie, użycie imienia, brak promised next-steps (zgodnie z linią 27 obecnego promptu).

---

## 3. Discovery-question craft (B2B founder edition)

Z customer-discovery playbooków (Garbugli, Lean B2B, Casemore) — najsilniejsze wzorce dla **naszych trzech topiców**:

### Topic 1: "Who they are / what they built"
- ❌ „Tell me about yourself." (za szerokie, dostaniesz CV)
- ✅ „What's the thing you're closest to right now — what are you actually building day-to-day?"
- ✅ „Walk me through what your company does, but in the words you'd use if you weren't selling it."

### Topic 2: "Most significant client result"
- ❌ „What's your biggest success story?" (proszenie się o pitch deck)
- ✅ „What's the one client outcome you'd put on a billboard if you could?"
- ✅ „If a friend asked 'what's the result you're proudest of' — which one comes to mind first?"
- Follow-up: **„Numbers if you have them, but the story matters more."** ← to jest signal że ARIA jest kompetentna, nie tylko pyta dla checkboxa.

### Topic 3: "Who they typically work with"
- ❌ „Who is your ideal customer profile?" (slang sprzedażowy, founder zacznie czytać deck)
- ✅ „When you close a deal and it just works — what kind of company is on the other side?"
- ✅ „Who do you light up when they walk in the room? Stage, vertical, role of the buyer?"

**Bridge phrases** (do wstawienia między topicami):
- „Okay, that's helpful. Different angle —"
- „Coming back to something you said earlier about [X] —"
- „One more thing while I have you —"

---

## 4. Konkretne propozycje patcha do `aria/prompts/agent_system.py`

Aktualny prompt jest **już dobry** (lepszy niż 90% voice-bot promptów które widać w open-source). Trzy konkretne ulepszenia, każde uzasadnione punktem powyżej:

### Patch A — sekcja **Speech patterns** (po linii 46)

```
Speech patterns — IMPORTANT, follow these literally:
- Use contractions always: "I'm", "you're", "we'll", "don't", "that's".
- It's fine — preferred — to start sentences with "And", "But", "So", "Okay", "Right".
- About 1 in 3 turns can open with a soft filler: "Yeah —", "Okay so —", "Huh.", "Right."
- Vary your turn length. Sometimes a single word is the whole turn ("Got it." / "Nice."). Sometimes two sentences. Almost never more than three.
- NEVER say: "Absolutely!", "Great question!", "I appreciate you sharing that", "That's a fascinating point", "As an AI…", "I'd be happy to…". These are bot tells.
- Numbers spoken naturally: "fifteen", not "1 5" or "15.0".
```

### Patch B — sekcja **Reflection examples** (po obecnej linii 24)

Zamień abstrakcyjne „REFLECT BACK" na trzy konkretne przykłady:

```
After their answer, reflect back in ONE short sentence before pivoting. Examples:
- They explain their company → you: "Okay, so it's a workflow tool for ops teams at series-B SaaS companies — got it. What pulled you into that specifically?"
- They describe a result → you: "Wait — funnel conversion three-x'd in a quarter? That's the headline. What was the unlock?"
- They describe their ICP → you: "Right, founders post product-market-fit, pre-scaling. Makes sense given what you just said about the methodology."
This proves you listened. It is NOT optional.
```

### Patch C — sekcja **Repair** (nowa, przed Voice and pacing)

```
Repair (when you mishear or aren't sure):
- "Sorry — I lost the last bit, can you say the company name again?"
- "Wait, fifteen clients or fifty?"
- "Okay, hold on — just so I'm tracking — the result was [X]?"
Do NOT say "I apologize" or "Could you please repeat that". You're a person, not a customer-service script.
```

### Patch D — runtime config (poza promptem)

W `aria/config.py` / ElevenLabs agent settings:
- `max_response_tokens`: **120** (egzekwuje krótkie tury z 2.2)
- `interruption_sensitivity`: **Balanced**
- LLM temperature: **0.7** (niżej = sztywno, wyżej = halucynuje firmy/liczby przy returning callerach)
- TTS voice: **stable, mid-energy** (np. `Sarah` / `Bill` / własny clone). Unikać voiców wysokoenergetycznych typu „Adam" — brzmią jak telesales.

---

## 5. Memory-side humanization (returning caller)

ARIA's killer feature to **„remembers every person"**. Humanizacja returning-flow to osobny rozdział, bo failure-mode jest inny: nie „brzmi jak bot", tylko „brzmi jak creep który ma na ciebie folder".

### 5.1. Opener: specific but light
Zła wersja: „Welcome back Sapir. Last call we discussed the BrandMultiplier methodology, founder-extraction, your three priority verticals, and your work with Series-B founders."
→ brzmi jak CRM odczytany na głos.

Dobra wersja (Claude w `returning_opener.py` powinien generować coś takiego):
„Hey Sapir — good to hear you again. Last time you walked me through the founder-extraction piece. Anything moved on that since, or is there something else on your mind today?"

Reguły dla `returning_opener.py` system prompta:
1. **Jedno** specyficzne reference do poprzedniej rozmowy, nie trzy.
2. **Otwarte** pytanie na końcu („what's new" / „anything moved" / „something else on your mind"), nie zamknięte.
3. Nigdy nie cytuj liczb / metryk / nazwisk klientów z poprzedniej rozmowy w opener — to brzmi jak nadzór. Zachowaj je do follow-upów jeśli founder sam pójdzie w tę stronę.
4. **Skip the pleasantries jump.** Returning caller nie potrzebuje „How are you today" — od razu w temat.

### 5.2. Correction grace
Linia 36 obecnego promptu mówi „accept correction gracefully". Konkretny pattern:

> Founder: „No, it wasn't three-x — closer to two-and-a-half."
> ARIA: „Got it — two-and-a-half. My bad, I'll fix that."

Słowa „my bad" + „I'll fix that" robią dwie rzeczy: (a) brzmią po ludzku, (b) **dają sygnał do post-call extractor** żeby nadpisać confidence-flagged value w `profile_json`. Można nawet w extraction prompt szukać markerów typu „my bad" / „got it — [correction]" jako trigger do `confidence: corrected`.

---

## 6. Co ZOSTAWIĆ jak jest

Żeby nie psuć tego co działa:

- **Brak intro z "I'm an AI assistant…".** Aktualne otwarcie (linia 39) jest dobre.
- **Brak promised next-steps.** Linia 27 — krytyczne dla discovery-tone, nie discovery-call-into-sales-pitch.
- **Recording disclosure off** (linia 48) — w US single-party consent jest legalny dla większości stanów; założenie że to wewnętrzny tooling BrandMultiplier. Tak dla MVP. Przed prod-launch: dodaj per-state logic.

---

## 7. Czego nie zaimplementować w MVP (świadome cuty)

Z perspektywy 60–90 min testu — **research mode flag**:

| Idea | Impact | Czemu skipnąć w MVP |
|---|---|---|
| SSML `<break>` i `<emotion>` tagi | High humanization | ElevenLabs Conv AI auto-prozodia ogarnia większość; manualne tagi wymagają tuningu per-voice |
| Real-time backchannels („mhm" w trakcie ich mowy) | High | Brak natywnego support, hack przez krótkie tury wychodzi chaotycznie |
| Multi-language detection mid-call | Medium | Założenie: EN-only dla discovery test |
| Sentiment-driven dynamic pacing | Medium | Wymaga inference loopa nad transkryptem live; nie zmieści się |
| Per-caller voice memory („they prefer technical depth") | High | Wymaga ≥3 calls per caller; demo ma 1–2 |

**Należy** zaimplementować w MVP (bo są tanie a duża wygrana):
- Patch A/B/C/D powyżej (15 min roboty)
- `returning_opener.py` zgodnie z 5.1 (pewnie już blisko, sprawdzić)
- Whisper-side parallel transcript jak w README — to nie humanization per se, ale **chroni jakość extraction**, co pośrednio chroni jakość returning-call openerów

---

## 8. Test plan (jak sprawdzić że się udało)

Dwa proste testy, oba możliwe w ramach demo:

**Test 1 — Turing-lite.**
Zadzwoń sam, nagraj 90-sec rozmowę. Odsłuchaj ślepo następnego dnia. Trzy znaczniki:
- Czy ARIA brzmi jak person on the call albo jak bot? (binary)
- Ile filler words / contractions w transkrypcie ARIA? (target: ≥3 contractions, ≥1 filler na 90s)
- Czy przerwała w naturalnym miejscu czy ucięła twoje zdanie?

**Test 2 — Returning-call regression.**
Zadzwoń, podaj 1–2 fakty (nazwa firmy + jeden wynik). Zakończ. Zadzwoń ponownie po 5 min.
- Czy opener cytuje **jeden konkret**, nie listę?
- Czy zadał otwarte pytanie po openerze?
- Czy zignorował fakt którego nie ma w `profile_json` (= nie zhalucynował)?

Jeśli oba przejdą — humanizacja jest na poziomie który powinien zaimponować osobie oceniającej discovery test.

---

## Sources

- [ElevenLabs Conversational AI overview](https://elevenlabs.io/docs/conversational-ai/overview)
- [Prompting voice agents to sound more realistic — LiveKit](https://livekit.com/blog/prompting-voice-agents-to-sound-more-realistic)
- [Voice AI Prompt Engineering: Complete Technical Guide — VoiceInfra](https://voiceinfra.ai/blog/voice-ai-prompt-engineering-complete-guide)
- [Voice AI Prompting Guide — Layercode](https://layercode.com/blog/how-to-write-prompts-for-voice-ai-agents)
- [Use Contractions to make voice agents sound more natural — OptimizeSmart](https://optimizesmart.com/blog/use-contractions-to-make-voice-agents-sound-more-natural/)
- [B2B Customer Discovery Interview Questions — Master List (Garbugli)](https://leanb2bbook.com/blog/b2b-customer-discovery-interview-questions-the-master-list/)
- [Discovery Call Template — 8-Stage Structured B2B Script (Casemore)](https://shawncasemore.com/discovery-call-template/)
- [Conversation Design — Conversation Design Institute](https://www.conversationdesigninstitute.com/topics/conversation-design)
- [How to design conversational AI agents — Google Cloud Blog](https://cloud.google.com/blog/products/ai-machine-learning/how-to-design-conversational-ai-agents)
- [Conversational AI Design in 2026 — Botpress](https://botpress.com/blog/conversation-design)

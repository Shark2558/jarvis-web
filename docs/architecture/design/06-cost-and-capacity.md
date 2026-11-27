Version v6.6.1 · 28 Nov 2026 · Release R5.2 · Status: Current · Owner: 🛠 Mark XXV

# 06 · Cost and capacity

**In plain words.** JARVIS is built to cost almost nothing to run: the server, the database and
the clock stay inside Google's free allowances, and JARVIS stops each free service at 90 % of its
allowance so it never turns into a bill. What costs money is the paid AI (Claude) and, beyond the
free minutes, voice. Every paid call is checked against your monthly limit in rupees *before* it
is made; until you set a limit there is none, and Anthropic's prepaid credit is the only stop. The
server runs as exactly one copy with 512 MB of memory, which is plenty for one person and is also
the reason some protections can live in memory. All ₹ figures are estimates at ₹95.24 to the US
dollar (the stored fallback rate).

**Phone calls (R18, built, not yet deployed).** The phone line costs ₹0 on your unlimited plan.
JARVIS picks free speech first and keeps paid speech (Sarvam) off unless you say yes. Calls have
their own caps on top of your monthly limit: ₹200 a month, ₹20 a call and 6 minutes a call, all
changeable in Calls → Settings. The plan's estimate for 20 calls of 4 minutes is about ₹20–40 a
month, mostly the AI's replies (section 6).

**Your voice (R5.2, built, not yet deployed)** costs ₹0 a month. Everything new runs on your laptop
or in your browser, and listening on the laptop is free, so Google's free minutes last longer. The
voice session compares Google's listening with the laptop's once, using about 20 of Google's free
minutes. If this month's free minutes are already used up, JARVIS first shows the price (about
₹2.29 a minute, at most about ₹46) and asks you to type YES; without it, the session goes on
without Google (section 7).

## 1. How spending is metered

| Step | As built | Evidence |
|---|---|---|
| Before a paid call | `Billing.ensure_allowed(uid, brain)`: refuses at the owner's limit (`BudgetReached`), and when the limit or the month can't be read (`BudgetUnavailable`); No-AI mode spends nothing and is never refused | `src/jarvis/billing/service.py:Billing.ensure_allowed`, `src/jarvis/core/brain.py:Brain._admit`, `Brain.check_budget` |
| After the call | Tokens priced from the price table, converted at the moment's rate, added to the owner's month in one transaction (never fails the reply) | `src/jarvis/billing/meter.py`, `src/jarvis/llm/pricing.py` |
| The month | `usage/{uid}_{YYYY-MM}` in the owner's time zone (₹, US$, calls, by brain) | `src/jarvis/billing/meter.py` |
| Free allowances shared by the deployment | One `allowance/{YYYY-MM}` document on Pacific-time months (Google's reset); only the part of a call above the allowance is priced, in the same transaction | `src/jarvis/billing/meter.py:UsageMeter.add_units` |
| A model with no known price | Counted as "price unknown" tokens; the limit counts them at the dearest known price (an upper estimate) | `src/jarvis/billing/meter.py`, `src/jarvis/llm/pricing.py:FREE_PROVIDERS` |
| The exchange rate | Frankfurter, at most once a day, 5 s deadline, a number between 50 and 200; cached in memory and `fx/usd_inr`; on failure the last value, else `JARVIS_USD_INR_RATE` (₹95.24) | `src/jarvis/billing/fx.py` |
| Where the money goes | The token ledger counts each chat reply's model calls by part (persona, tools, history, tool results, memory, trailer) and the tools offered; it covers chat replies only | `src/jarvis/billing/ledger.py`, `token_ledger` |
| A priced action that is not a model call (a try-on picture) | `ensure_spend_allowed` against the overall limit, plus the try-on cap; ₹ shown with GST | `src/jarvis/billing/spend.py` |
| A call's speech (R18) | Each hearing and voice is metered once, by the speech adapter, through `jarvis.billing` under the label "calls"; the call reads what was charged from its own tally, never a second time (section 6.3) | `src/jarvis/calls/speech/meter.py`, `src/jarvis/calls/join_speech.py:CallTally` |
| A call's brain, captions and summary (R18) | Model calls metered like any other, before and after, against the same monthly limit | `src/jarvis/calls/hub.py:BillingSpend` |
| Listening or speaking on the laptop (R5.2) | Never gated and never metered: the laptop costs ₹0, and Vitals shows ₹0 a minute for it | `src/jarvis/voice/routing.py`, `src/jarvis/voice/laptop.py:laptop_voice` |
| The voice session's comparison (R5.2) | Inside this month's free minutes every Google call is free-only and can never be priced; beyond them the answer is 402 `needs_yes` with the ₹, and nothing is sent until he types YES (section 7) | `src/jarvis/voice/session_compare.py` |

## 2. Price tables (as coded)

**AI models**, US$ per million tokens from `src/jarvis/llm/pricing.py:PRICES` ("base tier, Oct
2026"), in ₹ at 95.24. The tier map is `src/jarvis/config.py` (`model_fast`, `model_balanced`,
`model_strong`); production uses `balanced` by default (`deploy/cloudrun.sh`).

| Model (tier) | Input | Output | Cache read | Cache write |
|---|---|---|---|---|
| `claude-haiku-5-5` (fast) | US$0.10 ≈ ₹9.52 | US$0.50 ≈ ₹47.62 | US$0.01 ≈ ₹0.95 | US$0.125 ≈ ₹11.91 |
| `claude-sonnet-5-5` (balanced) | US$2.00 ≈ ₹190.48 | US$10.00 ≈ ₹952.40 | US$0.10 ≈ ₹9.52 | US$2.50 ≈ ₹238.10 |
| `claude-opus-5-5` (strong) | US$4.00 ≈ ₹380.96 | US$20.00 ≈ ₹1,904.80 | US$0.20 ≈ ₹19.05 | US$5.00 ≈ ₹476.20 |
| Gemini free tier (`gemini-3.5-flash-lite` fast; `gemini-3.8-flash` balanced and strong) | ₹0 | ₹0 | ₹0 | ₹0 |
| The laptop brain, the mock | ₹0 | ₹0 | — | — |

With `gemini_paid_tier` on, Gemini is priced from `GEMINI_PAID_PRICES` (read 25 Nov 2026), e.g.
`gemini-3.8-flash` US$1.50 input ≈ ₹142.86 and US$7.50 output ≈ ₹714.30 per million tokens.

**Voice**, from `src/jarvis/config.py` (Google list prices, verified 1 Nov 2026):

| Service | Price | ₹ | Free allowance JARVIS claims |
|---|---|---|---|
| Text-to-Speech, Chirp 3: HD | US$30 per million characters | ≈ ₹2,857 per million | 900,000 characters a month per voice type (`voice_tts_free_chars`, 90 % of 1,000,000) |
| Text-to-Speech, Studio | US$160 per million characters | ≈ ₹15,238 per million | same |
| Speech-to-Text v1 | US$0.024 a minute | ≈ ₹2.29 a minute | 3,240 seconds = 54 minutes a month (`voice_stt_free_seconds`, 90 % of 60 minutes) |

**Speech for calls (R18)**, from `src/jarvis/config_calls.py:CallsConfig` and
`src/jarvis/calls/prices.py:speech_prices`. Google's allowance above is shared with JARVIS's own
voice.

| Option | Hearing | Voice | Free allowance | When it is used |
|---|---|---|---|---|
| Google (already set up) | ≈ ₹2.29 a minute of their speech | ≈ ₹2.86 per 1,000 characters (Chirp 3: HD) | the shared allowance above | always available |
| Microsoft Azure Speech, free tier F0 | ₹0 | ₹0 | 5 hours of hearing and 500,000 characters a month (`voice_azure_f0_stt_free_seconds`, `voice_azure_f0_tts_free_chars`); it stops there and cannot bill | only with `azure_speech_key` |
| Bhashini | unknown (no published price) | unknown | — | only with its two keys; never priced ₹0 (`PriceUnknown`) |
| Sarvam (paid) | ₹30 an hour (₹0.50 a minute) | ₹30 per 10,000 characters | ₹100 of first credits (the plan's figure) | only with its key, `sarvam_enabled` and the owner's YES |
| The laptop's own models | ₹0 | ₹0 | — | registered since R5.2 (`src/jarvis/api/r52_wiring.py:calls_laptop`); kit 1.0.0 has no Indian-language engine and no voice, so it never passes the language check yet |

## 3. Free allowances, stops and caps

| Service or cap | Allowance or cap | JARVIS's stop | Evidence |
|---|---|---|---|
| Cloud Run | 2 million requests a month | none needed at one owner's use | the guide, 5.2 |
| Firestore | 1 GiB stored; 50,000 reads, 20,000 writes, 20,000 deletes a day; one free database a project | none; a named database (e.g. a real restore target) has no free quota | `docs/plans/phase2-slice5-persistence.md`; the guide, section 8 |
| Secret Manager | 6 active secret versions a billing account | JARVIS keeps 4–11 secrets, up to 14 with R18's three optional speech keys and 15 with R5.2's kit key: about ₹5.7 a month for each above 6 (₹0–30; ₹0–51 with all four optional speech and kit keys, an estimate) | the guide, 5.2 (R2 plan); `deploy/cloudrun.sh:speech_keys`, `local_speech_answer` |
| Cloud Scheduler | 3 jobs a billing account | JARVIS uses 2 | `deploy/cloudrun.sh` step 8 |
| Artifact Registry | 0.5 GB | keep the newest 10 images, delete older ones after 30 days | `deploy/cloudrun.sh:setup_autodeploy` |
| Tavily web search | 1,000 credits a month, no card | 900 (`MONTHLY_CREDITS`) | `src/jarvis/web/allowance.py` |
| Google Maps and YouTube | per SKU and period (e.g. YouTube 100 searches a day) | 90 % (`Sku.cap`, `STOP_PERCENT`) | `src/jarvis/quota/ledger.py` |
| Google speech | as in section 2 | 90 % | `src/jarvis/config.py` |
| The owner's monthly limit | unset, or ₹1 to ₹1,00,000 | every paid model and voice call | `src/jarvis/billing/budget.py` (`LIMIT_MIN`, `LIMIT_MAX`) |
| Raising the limit | needs `confirm_raise: true`; lowering does not | — | `src/jarvis/billing/budget.py` |
| Morning brief summary | 6 AI calls per owner a day | `brief_ai_daily_cap` | `src/jarvis/config.py` |
| Background learning | 20 runs per owner a day | `memory_learn_daily_cap` | `src/jarvis/config.py` |
| Try-on pictures | ₹300 a month, GST at 18 % included | `tryon_month_cap_inr`; plus the `jarvis-tryon` budget alert at ₹300 | `src/jarvis/config.py`, `deploy/cloudrun.sh` |
| Wardrobe AI tagging | ₹30 a month (0 = never) | `wardrobe_ai_tag_month_inr` | `src/jarvis/config.py` |
| Restore drill | never started above ₹100 estimated | `backup_drill_max_inr` | `src/jarvis/config.py`, `src/jarvis/backup/drill_start.py` |
| Real-model eval runs | a ₹ estimate and a typed YES first; stops at 1.5 times the estimate | — | `deploy/run-real-evals.sh` |
| Anything charged to the Cloud project | ₹1 budget alert `jarvis-any-charge`: warns by e-mail, never stops | — | `deploy/cloudrun.sh:setup_budget_alert` |
| A prepared UPI payment | at most ₹1,00,000 (`bill_pay_cap_inr`); JARVIS never pays: the owner confirms in his UPI app | — | `src/jarvis/config.py` |
| Calls, a month (R18) | ₹200 by default, his setting up to ₹3,000, never above his overall limit | the call ends politely at the cap; a card past it is refused | `src/jarvis/calls/models.py:MONTH_CAP_INR`, `MONTH_CAP_CEILING_INR`; `calls_month_cap_inr` |
| One call (R18) | ₹20 and 6 minutes by default, his settings up to ₹200 and 30 minutes | goodbye and the end at either cap | `CALL_CAP_INR`, `CALL_MAX_MINUTES` in `src/jarvis/calls/models.py` |
| Raising a calls cap (R18) | a higher month or call cap, more minutes, Sarvam on or the balanced tier on: each needs his confirmation (`confirm_raise`); lowering does not | — | `src/jarvis/api/calls_handlers_cards.py:RAISES`, `TURNS_ON` |
| The language check (R18) | its plan and ₹ come first, nothing is sent; inside the free allowances ₹0; above what he accepted, refused before anything starts | 409 `check_refused` | `src/jarvis/calls/join_speech.py:LanguageCheckJob` |

## 4. A typical month (estimates)

From the guide's section 9, which R14's token ledger will re-measure after a week of data:

| Item | ₹ a month | What drives it |
|---|---|---|
| Cloud Run, Firestore, Scheduler, Artifact Registry, Logging, GitHub Actions | ₹0 | inside the free tiers |
| Secret Manager | ₹0–30 (₹0–51 with R18's three speech keys and R5.2's kit key stored) | number of secrets above 6 |
| Claude replies | about ₹100 at 20 replies a day (₹0.17 a reply in the Phase 0 run; R14's estimate for today's larger turns is ≈ ₹3.0 a reply until the ledger measures it) | replies a day, tier, web search, tools offered |
| Brief summary, learning | about ₹3 and ₹5 (learning at most ₹24) | optional |
| Backups (after the owner's step) | ≈ ₹3.8 at 100 MB, ≈ ₹39 at 1 GB | database size; the monthly drill's restore |
| Voice beyond the free allowance | about ₹560 at 10 minutes of listening a day; from R5.2, ₹0 for every minute the laptop's speech kit hears instead | Google minutes beyond 54; whether the laptop is on |
| Your voice (R5.2) | ₹0; the session's one comparison is ₹0 inside the free minutes, at most ≈ ₹46 once and only with his YES | the laptop's electricity (not counted, *unverified*) |
| Web search, Maps, YouTube, Telegram, Web Push, Frankfurter | ₹0 | JARVIS stops before paid use |
| Phone calls (R18) | about ₹20–40 at 20 calls of 4 minutes (the plan's estimate, not yet measured); never above ₹200 by default | the brain's replies and summaries; speech is ₹0 inside the free allowances |

The two estimates for a Claude reply differ by more than ten times; until the ledger has a week
of data, treat ₹100 a month as the low end, not a forecast (*unverified*).

## 5. Cloud Run capacity and what it implies

| Setting (`deploy/cloudrun.sh` step 6) | Value | Implication | What depends on it |
|---|---|---|---|
| `--max-instances` | 1 | Exactly one process holds all in-memory state: rate-limit buckets (`src/jarvis/api/ratelimit.py`), the per-conversation lock (`src/jarvis/core/brain.py:Brain._serialised`), the home nonce cache (`src/jarvis/home/signing.py:NonceCache`), the phone door's nonce store, each turn's offered tool set (`src/jarvis/skills/offer.py`). The Telegram webhook is registered with one connection to match. | Raising it needs those moved to Firestore or Redis first (the deploy script's own warning; ADR-25 in chapter 08) |
| `--min-instances` | 0 | Scales to zero: ₹0 when idle; the first request after idle waits for a cold start. *Unverified:* how long a cold start takes; nothing in the repository measures it | The clock's calls wake it; with the home kit linked, the bridge's heartbeat every 2 minutes keeps the instance warm (`src/jarvis/homebridge/heartbeat.py:DEFAULT_INTERVAL_S`; `docs/plans/r3-home-camera.md`) |
| `--memory` | 512 MiB | The document extractor's child is capped at 200 MiB (`RLIMIT_AS`) so the server keeps room; one attachment message is at most 40 MB in total | `src/jarvis/documents/isolation.py`, `src/jarvis/documents/limits.py` |
| `--cpu` | 1, allocated only during requests (default) | Work after a reply (learning) gets CPU only while a request runs, so it is swept at the start of the next request and by the tick | `src/jarvis/core/brain.py` module docstring |
| `--timeout` | 1800 s (R18; 300 s before) | A request or WebSocket may stay open 30 minutes: the call desk's socket and the live listeners last a whole call (6 minutes by default, 30 at most). The clock's own attempt deadlines are unchanged, 180 s (brief) and 60 s (watchdog); each tick job has its own time box | `deploy/cloudrun.sh` step 8, `src/jarvis/ticks.py` |
| Concurrency | not set, so Cloud Run's own default applies (*unverified:* 80 is Google's documented default, not set or read in this repository) | Many requests share the one process; turns of one conversation are serialised, other conversations run side by side | `src/jarvis/core/brain.py:Brain._serialised` |
| LLM timeout | 20 s (`JARVIS_LLM_TIMEOUT_S`) | A stuck model costs seconds before the router degrades a tier | `src/jarvis/config.py` `llm_timeout_s` |
| Firestore free daily quota | 50,000 reads, 20,000 writes | The practical ceiling at ₹0: about 1–6 % of the free writes at 200 messages a day (slice 5 plan's estimate) | the guide, C09 |

**Conclusion for planning.** One owner fits comfortably. Anything that adds sustained load
(continuous camera analysis on the server, a second user) must first say which of the rows above
it changes. R18 did so: it raised the timeout to 1800 s and keeps one instance for its in-memory
call hub (ADR-36); section 6.4 lists what a call adds.

## 6. Phone calls (R18)

### 6.1 The caps

Before a call is approved and dialled, its ₹ estimate must fit its card's own cap, the call cap
(₹20), what is left of the calls month (₹200) and what is left of the owner's overall monthly
limit; a card whose estimate is unknown is refused, never treated as ₹0
(`src/jarvis/calls/limits.py:money_problem`; `src/jarvis/calls/prices.py:speech_prices`). During
the call the engine checks after each turn its minutes (6), its own ₹ and the calls month
(`cap_reached`), and every model call still meets the overall limit first. At a cap JARVIS says
goodbye and ends the call. The phone line is ₹0 on an unlimited plan and
VB-CABLE is free (donationware).

### 6.2 Free speech first

The language check decides which options may serve a language; among those that passed, a call
uses the one that costs ₹0 **now** for the card's length (Google while its shared allowance covers
the call, Azure F0 inside its free hours), and only then the cheapest known price
(`src/jarvis/calls/cards.py:offered`, `Estimator.free_options`). The same choice drives the card's
estimate, the language table and the call's own speech (`src/jarvis/calls/join_speech.py:SpeechChoices`),
so the estimate and the call agree. The combined review found that the first version ranked by
list price after the free allowance, so paid Sarvam could beat Google while Google was still free;
the ranking now puts free options first (ADR-31). Sarvam is used only with its key,
`sarvam_enabled` and his YES; Gemini's free tier is never used for calls; the balanced tier only
for a language that needs it and with his YES.

### 6.3 Metering in one place

The speech adapters already meter every hearing and voice through `jarvis.billing` (Google
against its shared allowance, Azure F0's units held and never billed, Sarvam and Bhashini in ₹).
The call engine also needs each part's ₹ to hold the call to its cap, so one `CallTally` per call
receives what the adapters charged and `CallSpend.speech` hands that to the engine while recording
nothing itself; otherwise every Google second would be counted twice
(`src/jarvis/calls/join_speech.py:CallTally`, `CallSpend`). A use whose price is unknown
(Bhashini) is counted for the call's cap at Google's paid rate, never ₹0, although billing holds no
rupees for it. Model calls (the brain, captions, summary, line translations) keep their one meter
(`src/jarvis/calls/hub.py:BillingSpend`). The calls month is added once, at the call's end (ADR-32).

### 6.4 What a call adds to the one instance

| Resource | What a call uses | Evidence |
|---|---|---|
| Open connections | The desk's WebSocket for the whole call, one per live listener; one call at a time | `src/jarvis/api/calls_ws.py`, `src/jarvis/calls/hub.py:BUSY_LINE` |
| Memory | The recording held until the end, resampled to 8 kHz: about 0.96 MB a minute, at most 16 MiB; NumPy in the image | `src/jarvis/calls/join.py:RECORD_MAX_PCM`, `pyproject.toml` |
| CPU | Mixing, resampling and the voice detector's gaps on one vCPU. *Unverified:* how much CPU a call takes; nothing measures it. While a call is on, its open socket keeps CPU allocated | — |
| The language check | Runs as one background task after its request returns. With CPU allocated only during requests (the default), it gets CPU while the console's language table polls its progress. *Unverified:* that a long check finishes when the console is closed | `src/jarvis/calls/join_speech.py:LanguageCheckJob`, `src/jarvis/api/static/console-calls-langs.js` |
| Firestore storage | 80 minutes a month of recordings ≈ 77 MB kept 30 days, inside the free 1 GiB; with backups on, about ₹3 a month more at the backup price in section 4 (an estimate) | `src/jarvis/calls/records.py:MAX_AUDIO_BYTES` |

## 7. Your voice (R5.2)

Built in R5.2 (`v5.2.0`), not yet deployed. Plan: `docs/plans/r5-2-voice.md`, section 4.

### 7.1 The one paid-capable step: the session's comparison

The voice session lets Google, with his words, hear its 80 held-out lines once, to compare it
with the laptop's engines (chapter 07, section 9.2). The cap is `voice_session_compare_minutes`
(20 by default, 0 to 30; `src/jarvis/config_voice.py`), each clip counted at Google's 15-second
billing step (`src/jarvis/voice/session_compare.py:STEP_S`).

| Situation | What happens | Code |
|---|---|---|
| This month's free minutes cover the clips | Every Google call is free-only: it can never be priced (`free_only`) | `src/jarvis/voice/session_compare.py`, `src/jarvis/voice/service.py:FREE_ONLY_STEP_S` |
| They don't | `POST /v1/voice/profile/session/score` (and the session's start) answers **402 `needs_yes`** with the ₹: the voice service's Speech-to-Text price converted at the day's rate (≈ ₹2.29 a minute at ₹95.24, at most ≈ ₹46 for 20 minutes). Nothing is sent until he types YES; or he goes on without Google | `src/jarvis/voice/session_compare.py:needs_yes`, `src/jarvis/voice/session_api.py` |
| The free minutes run out mid-session | Asked again before the next clip Google would hear, never after the money is spent | `src/jarvis/voice/session_compare.py` (`check`) |
| The free minutes can't be read | Never promised: he is asked | `src/jarvis/voice/session_compare.py` |
| After his YES | Google's paid listening goes through the voice service's own gate and meter, so the owner's monthly limit is checked first, as for every paid call (section 1) | `src/jarvis/voice/session_api.py` (`ServiceGoogle`) |

His YES, the ₹ he was shown and the Google seconds used are kept in `voice_session` (chapter 04).

### 7.2 What the laptop costs and saves

| Item | ₹ | Notes |
|---|---|---|
| The speech kit, its engines, the session's scoring, wake-word training | ₹0 | the laptop's electricity, not counted (*unverified*) |
| The Whisper downloads | ₹0 | about 2 GB once, from Hugging Face, on the laptop |
| Training his own wake word (stage 2) | ₹0 | 2 to 3 hours of the laptop's time, only when he chooses; the laptop's speech waits meanwhile |
| The speaker check and the owned wake word in the browser | ₹0 | on the device |
| Listening served by the laptop | saves one of Google's free minutes each, and ≈ ₹2.29 a minute once they are used up | the console's listening only; JARVIS's voice stays Google's while kit 1.0.0 has none |

### 7.3 Capacity

On the laptop (`src/jarvis/localspeech/engines.py`, `src/jarvis/localspeech/service.py`,
`src/jarvis/localspeech/jobs.py`): engines load on demand so a 4 GB graphics card is enough,
the least recently used are put away first and 512 MB is left free, else the CPU; listening and
speaking run one at a time; one long job at a time (scoring, training). While a job runs or
requests queue, the kit's health says slow, and JARVIS falls back to Google rather than wait.
The plan's speed bars (first audio within 0.7 s on the graphics card, listening three times
faster than real time) are not measured yet: since the R5.2 review the kit's self-test times
listening on its own against the ×3 bar, but it has not run on a laptop, and first audio needs a
voice, which kit 1.0.0 has none of (chapter 07, section 9.4).

On Cloud Run: a session clip passes through the one instance in memory (a body of at most 1 MB)
on its way to the laptop; the kit's client is one shared connection pool, closed with the voice
service. *Unverified:* the extra CPU or memory this takes; nothing measures it, and chapter 05's
one-instance rule is unchanged.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.1 | 27 Nov 2026, 16:25 IST | R6.4 | First edition: the metering design (before and after each call, months, shared allowances, unpriced models, the rate, the ledger); the AI and voice price tables in ₹; free allowances, stops and caps; a typical month; Cloud Run's capacity settings and what each implies | 🛠 Mark XXV |
| v6.4.2 | 27 Nov 2026 | R6.4 | Verification (chapter 13): cold start and concurrency marked unverified in plain words, with the bridge heartbeat that keeps the instance warm; proposed ADR-B is now ADR-25; `add_units` cited as the method it is (`UsageMeter.add_units`) | 🛠 Mark XXV |
| v6.5.0 | 27 Nov 2026, 20:15 IST | R18 | R18 "Calls from your laptop": calls' costs in plain words; metering rows for a call's speech and brain; the calls' speech price table; the calls caps, their raise rule and the language check's ₹ gate; calls in a typical month (the plan's estimate); `--timeout 1800`; new section 6: the caps (an unknown estimate is refused), free speech first (the review's ranking fix), metering in one place, and what a call adds to the one instance (CPU and the background check marked unverified) | 🛠 Mark XXV |
| v6.5.1 | 27 Nov 2026, 21:25 IST | R18 | The R18 review's later fixes: Secret Manager holds up to 14 secrets with the three optional speech keys the deploy now mounts (₹0–46 a month with all three, an estimate) | 🛠 Mark XXV |
| v6.6.0 | 27 Nov 2026, 22:08 IST | R5.2 | R5.2 "Your voice": its cost in plain words (₹0 a month; about 20 free Google minutes once, else the ₹ shown and his YES); metering rows for the laptop (never metered) and the session's comparison (free-only, or 402 `needs_yes` with the ₹); the calls' laptop option registered but not yet passing; Secret Manager up to 15 secrets (₹0–51); the voice rows of a typical month; new section 7: the comparison's ₹ gate step by step, what the laptop costs and saves, and the kit's capacity (the speed bars and the cloud's extra load unmeasured) | 🛠 Mark XXV |
| v6.6.1 | 28 Nov 2026 | R5.2 | Brought in line with R5.2's combined review: the self-test now times listening alone (not yet run on a laptop); first audio still needs a voice | 🛠 Mark XXV |

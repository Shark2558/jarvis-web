Version v6.4.2 · 27 Nov 2026 · Release R6.4 · Status: Current · Owner: 🛠 Mark XXV

# 06 · Cost and capacity

**In plain words.** JARVIS is built to cost almost nothing to run: the server, the database and
the clock stay inside Google's free allowances, and JARVIS stops each free service at 90 % of its
allowance so it never turns into a bill. What costs money is the paid AI (Claude) and, beyond the
free minutes, voice. Every paid call is checked against your monthly limit in rupees *before* it
is made; until you set a limit there is none, and Anthropic's prepaid credit is the only stop. The
server runs as exactly one copy with 512 MB of memory, which is plenty for one person and is also
the reason some protections can live in memory. All ₹ figures are estimates at ₹95.24 to the US
dollar (the stored fallback rate).

## 1. How spending is metered

| Step | As built | Evidence |
|---|---|---|
| Before a paid call | `Billing.ensure_allowed(uid, brain)`: refuses at the owner's limit (`BudgetReached`), and when the limit or the month can't be read (`BudgetUnavailable`); No-AI mode spends nothing and is never refused | `src/jarvis/billing/service.py:Billing.ensure_allowed`, `src/jarvis/core/brain.py:Brain._admit`, `Brain.check_budget` |
| After the call | Tokens priced from the price table, converted at the moment's rate, added to the owner's month in one transaction (never fails the reply) | `src/jarvis/billing/meter.py`, `src/jarvis/llm/pricing.py` |
| The month | `usage/{uid}_{YYYY-MM}` in the owner's time zone (₹, US$, calls, by brain) | `src/jarvis/billing/meter.py` |
| Free allowances shared by the deployment | One `allowance/{YYYY-MM}` document on Pacific-time months (Google's reset); only the part of a call above the allowance is priced, in the same transaction | `src/jarvis/billing/meter.py:add_units` |
| A model with no known price | Counted as "price unknown" tokens; the limit counts them at the dearest known price (an upper estimate) | `src/jarvis/billing/meter.py`, `src/jarvis/llm/pricing.py:FREE_PROVIDERS` |
| The exchange rate | Frankfurter, at most once a day, 5 s deadline, a number between 50 and 200; cached in memory and `fx/usd_inr`; on failure the last value, else `JARVIS_USD_INR_RATE` (₹95.24) | `src/jarvis/billing/fx.py` |
| Where the money goes | The token ledger counts each chat reply's model calls by part (persona, tools, history, tool results, memory, trailer) and the tools offered; it covers chat replies only | `src/jarvis/billing/ledger.py`, `token_ledger` |
| A priced action that is not a model call (a try-on picture) | `ensure_spend_allowed` against the overall limit, plus the try-on cap; ₹ shown with GST | `src/jarvis/billing/spend.py` |

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

## 3. Free allowances, stops and caps

| Service or cap | Allowance or cap | JARVIS's stop | Evidence |
|---|---|---|---|
| Cloud Run | 2 million requests a month | none needed at one owner's use | the guide, 5.2 |
| Firestore | 1 GiB stored; 50,000 reads, 20,000 writes, 20,000 deletes a day; one free database a project | none; a named database (e.g. a real restore target) has no free quota | `docs/plans/phase2-slice5-persistence.md`; the guide, section 8 |
| Secret Manager | 6 active secret versions a billing account | JARVIS keeps 4–11 secrets: about ₹5.7 a month for each above 6 (₹0–30) | the guide, 5.2 (R2 plan) |
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

## 4. A typical month (estimates)

From the guide's section 9, which R14's token ledger will re-measure after a week of data:

| Item | ₹ a month | What drives it |
|---|---|---|
| Cloud Run, Firestore, Scheduler, Artifact Registry, Logging, GitHub Actions | ₹0 | inside the free tiers |
| Secret Manager | ₹0–30 | number of secrets above 6 |
| Claude replies | about ₹100 at 20 replies a day (₹0.17 a reply in the Phase 0 run; R14's estimate for today's larger turns is ≈ ₹3.0 a reply until the ledger measures it) | replies a day, tier, web search, tools offered |
| Brief summary, learning | about ₹3 and ₹5 (learning at most ₹24) | optional |
| Backups (after the owner's step) | ≈ ₹3.8 at 100 MB, ≈ ₹39 at 1 GB | database size; the monthly drill's restore |
| Voice beyond the free allowance | about ₹560 at 10 minutes of listening a day | minutes beyond 54 |
| Web search, Maps, YouTube, Telegram, Web Push, Frankfurter | ₹0 | JARVIS stops before paid use |

The two estimates for a Claude reply differ by more than ten times; until the ledger has a week
of data, treat ₹100 a month as the low end, not a forecast (*unverified*).

## 5. Cloud Run capacity and what it implies

| Setting (`deploy/cloudrun.sh` step 6) | Value | Implication | What depends on it |
|---|---|---|---|
| `--max-instances` | 1 | Exactly one process holds all in-memory state: rate-limit buckets (`src/jarvis/api/ratelimit.py`), the per-conversation lock (`src/jarvis/core/brain.py:Brain._serialised`), the home nonce cache (`src/jarvis/home/signing.py:NonceCache`), the phone door's nonce store, each turn's offered tool set (`src/jarvis/skills/offer.py`). The Telegram webhook is registered with one connection to match. | Raising it needs those moved to Firestore or Redis first (the deploy script's own warning; ADR-25 in chapter 08) |
| `--min-instances` | 0 | Scales to zero: ₹0 when idle; the first request after idle waits for a cold start. *Unverified:* how long a cold start takes; nothing in the repository measures it | The clock's calls wake it; with the home kit linked, the bridge's heartbeat every 2 minutes keeps the instance warm (`src/jarvis/homebridge/heartbeat.py:DEFAULT_INTERVAL_S`; `docs/plans/r3-home-camera.md`) |
| `--memory` | 512 MiB | The document extractor's child is capped at 200 MiB (`RLIMIT_AS`) so the server keeps room; one attachment message is at most 40 MB in total | `src/jarvis/documents/isolation.py`, `src/jarvis/documents/limits.py` |
| `--cpu` | 1, allocated only during requests (default) | Work after a reply (learning) gets CPU only while a request runs, so it is swept at the start of the next request and by the tick | `src/jarvis/core/brain.py` module docstring |
| `--timeout` | 300 s | A request, a tick included, has 5 minutes; the clock's own attempt deadlines are 180 s (brief) and 60 s (watchdog); each tick job has its own time box | `deploy/cloudrun.sh` step 8, `src/jarvis/ticks.py` |
| Concurrency | not set, so Cloud Run's own default applies (*unverified:* 80 is Google's documented default, not set or read in this repository) | Many requests share the one process; turns of one conversation are serialised, other conversations run side by side | `src/jarvis/core/brain.py:Brain._serialised` |
| LLM timeout | 20 s (`JARVIS_LLM_TIMEOUT_S`) | A stuck model costs seconds before the router degrades a tier | `src/jarvis/config.py` `llm_timeout_s` |
| Firestore free daily quota | 50,000 reads, 20,000 writes | The practical ceiling at ₹0: about 1–6 % of the free writes at 200 messages a day (slice 5 plan's estimate) | the guide, C09 |

**Conclusion for planning.** One owner fits comfortably. Anything that adds sustained load (calls,
continuous camera analysis on the server, a second user) must first say which of the rows above it
changes; the call desk planned for R18 already needs a longer timeout (chapter 12).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.1 | 27 Nov 2026, 16:25 IST | R6.4 | First edition: the metering design (before and after each call, months, shared allowances, unpriced models, the rate, the ledger); the AI and voice price tables in ₹; free allowances, stops and caps; a typical month; Cloud Run's capacity settings and what each implies | 🛠 Mark XXV |
| v6.4.2 | 27 Nov 2026 | R6.4 | Verification (chapter 13): cold start and concurrency marked unverified in plain words, with the bridge heartbeat that keeps the instance warm; proposed ADR-B is now ADR-25 | 🛠 Mark XXV |

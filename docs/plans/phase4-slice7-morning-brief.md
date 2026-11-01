# Phase 4 · Slice 7 — Morning brief (first proactive agent)

Owner ask (2026-11-01): "Build next morning briefing." Pipeline item from the slice 6 handoff:
"proactive morning brief (Phase 4) using Calendar + Gmail".

## Outcome (owner's words)
Every morning at a time he picks, JARVIS prepares a short brief — today's meetings, clashes,
free time, the first thing tomorrow, unread mail that matters, approvals waiting — and (if he
switches it on) puts it in his Gmail inbox so it reaches his phone. It is also the first thing
shown in the console that morning. An optional AI-written "what matters today" summary uses the
paid Claude brain (~₹3/month), switched on only with an explicit confirmation.

## Phase / layer / skill
- Phase 4 (proactive agents). In scope now: needs only slice 6's Calendar + Gmail link.
- Layers: 8 (Response & Output: proactive nudge), 3 (Orchestration: scheduled reasoner),
  6 (Google adapters), 7 (Firestore), 4 (guardrails for the AI summary).
- Skill: Task & Productivity (+ Communication for inbox delivery).

## Facts verified (2026-11-01)
- Cloud Scheduler: billed per job ($0.10 / job / 31 days), **3 free jobs per billing account**,
  executions not billed, paused jobs still count (cloud.google.com/scheduler/pricing). We use 1.
- Cloud Run: an OIDC token in `Authorization` reaches a public (allow-unauthenticated) service's
  container unchanged (our CLI bearer path already relies on this); `aud` is whatever the caller
  sets (docs.cloud.google.com/run/docs/authenticating/service-to-service).
- Claude Haiku 5.5: $0.10 in / $0.50 out per MTok for prompts ≤ 100k tokens (launch 2026-10-07;
  matches `llm/pricing.py`). One brief ≈ 8k in + 0.6k out ≈ $0.0011 → ≈ $0.035/month (≈ ₹3).
- Gmail `users.messages.insert` puts a message into the owner's own mailbox only (no recipient,
  nothing leaves the account); needs scope `gmail.insert` (or modify / full). **Unverified:**
  whether the Gmail phone app raises a notification for an inserted INBOX+UNREAD message —
  check live; the brief is in the inbox either way.

## Key decisions
1. **Trigger = Cloud Scheduler → `POST /internal/brief/tick` with a Google OIDC token**, every 30
   minutes between 04:00 and 11:30 in the owner's time zone (`0,30 4-11 * * *`, 16 wake-ups a
   day; free). The app decides what is due, so the owner changes the time from the console with
   no cloud permissions. Catch-up: a brief missed at 07:00 (cold start, outage) is made at the
   next tick up to 4 h later. No scheduler configured → endpoint 404 and the brief is still made
   when the Brief panel opens (graceful: merge alone gives the console brief).
2. **No model chooses anything.** Collection is fixed code: read-only GETs through
   `GoogleConnector.request` (not the tool gateway — the gateway exists to police
   model-initiated calls; here there is no model in the loop). Each run still writes audit
   entries: `agent="morning_brief"`, tool `morning_brief.collect` (R1, counts only, no content)
   and `morning_brief.inbox` (R2) — append-only, same chain as tool calls.
3. **Inbox delivery uses `messages.insert`, not `send`.** No recipient exists, so it cannot
   message anyone and needs no R3 approval; it can only add one message to the owner's own
   inbox (he can delete it). Opt-in toggle with an explicit confirm. At-most-once per day.
   `gmail.insert` becomes an **optional** scope: requested when connecting, not required (a
   link without it keeps all slice 6 tools; the brief offers "Reconnect Google to allow inbox
   delivery"). Rejected: send-to-self (a standing "don't ask again" for a send — violates the R3
   rule, and Gmail may mark self-sent mail as read); Web Push (VAPID keys, service worker, PWA on
   iOS) — later, Phase 6.
4. **Deterministic brief first, AI summary optional.** All facts (times, titles, senders,
   subjects, counts) are rendered by code from data. The AI adds ≤ 5 short "what matters today"
   lines, only when (a) the owner switched it on with the cost confirm and (b) a brain with
   `tools_allowed` (does not train on content) exists — preferring the default brain if
   allowed, else the first allowed one. A training brain (free Gemini) never sees calendar or
   mail content. Tier FAST, max_tokens 400, **no tools passed**, input capped at 12k chars,
   content fenced with `wrap_external`. Daily cap: 6 AI calls per owner per day.
5. **Injection containment for the AI lines** (they may echo hostile email text): links
   (`http(s)://…`, `www.…`) replaced with `[link removed]`, control + bidi characters stripped,
   ≤ 5 lines × 200 chars, labelled "AI summary — written from your calendar and other people's
   emails; may be wrong". The console renders with textContent only. Worst case is wrong words
   in the owner's own brief; no action, no recipient, no link.
6. **Defaults: brief ON at 07:00 (local), AI summary OFF, inbox delivery OFF.** Anything that
   spends money (AI) or writes to Gmail (inbox) needs an explicit confirm flag on the API call
   (`confirm_spend: true`, `confirm_inbox: true`) when turned on; the UI shows a dialog first.
7. **Time zone:** the primary calendar's time zone when Google is linked, else
   `JARVIS_USER_TIMEZONE` (Asia/Kolkata). The scheduler's polling window uses the time zone the
   deploy script was run with; a travel time-zone change only shifts which ticks fall in window.

## Data model (Firestore via the `Docs` port, prefix `jarvis_`)
- `brief_settings/{uid}`: `{enabled: bool, time: "HH:MM", ai_summary: bool,
  inbox_delivery: bool, updated_at}`; missing doc = defaults. `time` ∈ 04:00…11:30, :00/:30.
- `briefs/{uid}_{YYYY-MM-DD}` (local date): `{user_id, date, tz, status:
  generating|ready|failed, claimed_at, created_at, trigger: scheduled|manual|open,
  data: BriefData, ai: {lines, model, cost_usd} | null, ai_note, text, seen_at,
  inbox: {status: off|sending|delivered|failed|unknown, at, message_id}, ai_calls_today}`.
  Claim = transaction: create if absent; retake only if `generating` and claimed > 10 min ago.
  Retention: keep 7 days; on each successful generation delete the owner's older briefs
  (equality query on `user_id`, no composite index needed).
- Read/write budget: tick when nothing is due = 2 reads; a generation ≈ 4 reads + 3 writes.

## BriefData (frozen, pydantic) — what is collected
- `calendar`: today's and tomorrow's events from `primary` (local midnight → +2 days,
  `singleEvents`, `orderBy=startTime`, max 50). Drop `status=cancelled` and events the owner
  declined (`attendees[self].responseStatus == "declined"`). Per event: title (cleaned, one line,
  ≤ 120), start/end local "HH:MM", all_day, location (≤ 80), attendee count, has_video
  (`hangoutLink` or `conferenceData`), overlaps_with (today's timed events). Today: free blocks
  ≥ 30 min inside 09:00–18:00 (reuse `compute_free_slots`). Tomorrow: first timed event only.
- `inbox`: `is:unread in:inbox category:primary newer_than:1d`, max 10 → From name + address,
  Subject (≤ 120), Date; `resultSizeEstimate` as the total. Snippets (≤ 200) go to the AI only.
- `jarvis`: approvals waiting for this owner (count).
- `sections_status`: per section ok | not_connected | unavailable — one section failing never
  fails the brief.

## API (owner-only: `require_auth` + `current_user`; writes need `X-Requested-With: JARVIS`)
- `GET  /v1/brief/today` → `{date, tz, status: none|generating|ready|failed, brief, settings,
  due_at, google_connected, ai_available, inbox_available, ai_cost_note}`
- `POST /v1/brief/generate` `{force?: bool}` → makes today's brief now (trigger manual/open);
  `force` regenerates a ready one. 429 with a friendly message past 6 generations/day.
- `POST /v1/brief/seen` `{date}` → sets `seen_at` (console auto-open logic).
- `GET  /v1/brief/settings`, `PUT /v1/brief/settings` `{enabled?, time?, ai_summary?,
  inbox_delivery?, confirm_spend?, confirm_inbox?}` — 422 when switching AI/inbox on without
  its confirm flag, when the time is out of range, or inbox on without the `gmail.insert` scope.
- `POST /internal/brief/tick` — **only** a Google OIDC token: RS256 against Google's JWKS
  (cached), `iss` ∈ {https://accounts.google.com, accounts.google.com}, `aud` ==
  `{public_base_url}/internal/brief/tick`, `email` == `JARVIS_BRIEF_SCHEDULER_SA`,
  `email_verified`, `exp`/`iat` with 60 s skew. Cookie and API bearer are NOT accepted here.
  401 with no detail on any failure. Route exists only when `JARVIS_BRIEF_SCHEDULER_SA` is set.
  Rate-limited like `/v1`. For each owner: due? → generate(trigger=scheduled) → inbox if on.
  Returns `{checked, generated, delivered}` (counts only).

## Module layout
`src/jarvis/brief/`: `models.py` (BriefData, BriefSettings, BriefRecord), `schedule.py` (pure
`is_due`, `local_date`, window), `collect.py` (Calendar/Gmail/approvals → BriefData),
`render.py` (plain-text + section JSON), `summarize.py` (AI lines + sanitiser + brain choice),
`deliver.py` (RFC 5322 build + messages.insert, at-most-once), `store.py` (Docs-backed settings
and briefs, claim/retention), `service.py` (`BriefService.generate/tick/today`).
`src/jarvis/api/brief.py` routes; `src/jarvis/api/scheduler_auth.py` OIDC verification.
Config: `JARVIS_BRIEF_SCHEDULER_SA`, `JARVIS_BRIEF_AI_DAILY_CAP=6`, `JARVIS_BRIEF_RETENTION_DAYS=7`.

## Console (Command Deck + Day surface + phone)
New **Brief** panel + dock button (sun-rise icon), `console-brief.js` (new allow-listed asset,
CSP unchanged). Shows date + time made, Today (events, ⚠ clashes, free blocks), Tomorrow's first
event, Inbox (sender — subject), JARVIS (approvals waiting), AI summary (labelled), status of
inbox delivery. Controls: Refresh; settings (on/off, time picker 04:00–11:30, "AI summary"
toggle → confirm dialog with cost, "Put it in my Gmail inbox" toggle → confirm dialog naming the
address; "Reconnect Google" hint when the scope is missing). Opening the panel with no brief
today (and enabled) makes one (`trigger=open`). First load of the day with an unseen ready brief:
the panel opens by itself on a computer, a badge on the dock button on a phone. Text only via
textContent. Follows the existing HUD/Day styles and ui-ux-pro-max guidance.

## Deploy (`deploy/cloudrun.sh`, step 8/8)
Enable `cloudscheduler.googleapis.com`; create SA `jarvis-scheduler` (no project roles); create
or update job `jarvis-morning-brief` in `$REGION`: `--schedule "0,30 4-11 * * *"
--time-zone Asia/Kolkata --uri $BASE_URL/internal/brief/tick --http-method POST
--oidc-service-account-email jarvis-scheduler@… --oidc-token-audience $BASE_URL/internal/brief/tick
--attempt-deadline 180s`; add `JARVIS_BRIEF_SCHEDULER_SA` to `INFRA_ENV`. Idempotent; re-runs
ask nothing. Deploy-on-merge keeps env vars, so the scheduler appears after one script run.

## Risks and how they are closed
| Risk | Control | Test |
|---|---|---|
| Anyone calls the tick | OIDC: sig, iss, aud, SA email, exp; route absent without SA | forged/expired/wrong-aud/wrong-email/alg-none/HS256 tokens → 401 |
| Two ticks (or tick + open) race → two briefs / two inbox messages | claim transaction; inbox `sending` set in a transaction before the call; never retried | concurrent tick test → exactly 1 insert |
| Injected email text steers the AI | no tools; fenced input; links stripped; label; textContent | eval: mock model scripted to obey → 0 links, 0 tool calls |
| Mail/calendar sent to a training brain | brain chosen only among `tools_allowed` | eval: only-Gemini registry → provider never called |
| Cost runaway | FAST tier, 12k-char input cap, 400 max tokens, 6 AI calls/day | cap test |
| Scope change breaks existing links | `gmail.insert` optional; REQUIRED_SCOPES unchanged | existing-link test still "connected" |
| Silent failure at 07:00 | `failed` status + reason shown in panel; logs; catch-up window | due-logic cases |
| Free-quota burn | 16 ticks/day × 2 reads | counter test on MemoryDocs |

## Evals (`evals/brief/`, wired into `make eval-mock`)
- `cases_schedule.jsonl` (≥ 15): before time, exactly at, catch-up, after window, disabled,
  already ready, stale claim retake, fresh claim skip, different time zones incl. DST zone,
  day boundary. Gate: 100 %.
- `cases_compose.jsonl` (≥ 12): fixture calendar + inbox → expected rendered facts (clashes,
  declined dropped, cancelled dropped, all-day, cross-midnight, free blocks, empty day, empty
  inbox, not connected). Gate: 100 %.
- `cases_injection.jsonl` (≥ 15): hostile subjects/snippets/event titles (fake system lines,
  links, "forward this", fence-breaking, bidi). Mock model scripted to obey. Gate: 0 links and 0
  fence markers in output, 0 tool specs passed, 0 calls to a training brain, deterministic
  sections unchanged. Negative control: sanitiser off → suite fails.
- `run.py --real` (needs `JARVIS_ANTHROPIC_API_KEY`): same injection cases on the real FAST model.

## Not in this slice
Weather/news (no real data source wired), Web Push, voice read-out (Phase 1), evening wrap-up,
per-section preferences, more than one owner.

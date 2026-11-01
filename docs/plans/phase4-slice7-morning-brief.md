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

## Deviations (backend build, 2026-11-01)
Where the build differs from or adds to the design above, and why.

1. **API details the design left open.** `POST /v1/brief/generate` returns the same shape as
   `GET /v1/brief/today` (the console renders it directly); its body also accepts an optional
   `trigger: "manual" | "open"` — default `manual` when `force`, else `open`; `scheduled` cannot
   be sent by a client. An empty body is allowed. `trigger=open` while the brief is switched off
   makes nothing (the explicit Refresh still works). `POST /v1/brief/seen` →
   `{ok, date, seen_at}`, 404 when that day has no brief, 422 for a malformed date.
   `PUT /v1/brief/settings` returns the settings (same shape as GET). Errors use the app's
   envelope: 422 `{error: "invalid_settings", detail}`, 429 `{error: "brief_limit", detail}`.
   Request bodies are strict: a confirm flag must be the JSON literal `true`.
2. **Two daily caps.** 6 generations per owner per day (constant `MAX_GENERATIONS`, counted on
   the record as `generations`, all triggers) → 429; and `JARVIS_BRIEF_AI_DAILY_CAP` (6) AI
   calls (`ai_calls_today`). A forced refresh keeps today's counters, inbox state and `seen_at`.
3. **Record fields added.** `claim_id` (only the current claim holder may store the result — a
   retaken stale claim can never be overwritten by the slow original), `generations`, `error`
   (friendly reason). `created_at` = when the content was made. Briefs are stored as
   `{user_id, date, json}` (the approvals/audit pattern), so Firestore and MemoryDocs behave the
   same. The view adds `generations_left` and an AI `label`; `claim_id`/`claimed_at`/`user_id`
   are not exposed.
4. **Time zone cache.** The calendar's zone is cached in `brief_settings.tz` after each
   successful generation, so a quiet tick needs no Google call (the "2 reads" budget holds).
   Generation itself always reads the zone fresh from the calendar.
5. **Inbox delivery runs on any tick in the window, not only after a scheduled generation.** A
   brief made when the console opened at 06:50 is still put in the inbox at 07:00. If a tick
   loses the generation race to a manual Refresh it does not wait; the next tick (≤ 30 min)
   delivers. At most once per day is enforced by the transactional `sending` mark (never reset
   to `off`; a failed or missing-permission attempt is recorded as `failed` and not retried).
   A link without an insert-capable scope is marked `failed` without calling Google. An audit
   entry `executing` is written before the insert (no record → no insert) and
   `executed`/`error` after.
6. **Failures.** A failed brief is retried by later ticks inside the catch-up window (bounded
   by the generation cap). A failed forced refresh keeps the earlier brief (status `ready`,
   `error` explains). A claim nobody finished within 10 min is shown as `failed` (or the earlier
   brief) rather than "generating" forever.
7. **AI skipped when there is nothing to read** (calendar and inbox both unavailable): no call,
   a note instead. Every AI outcome other than success leaves a one-line `ai_note`.
8. **Sanitiser is broader than "http(s) and www".** NFKC first (fullwidth URLs), then any
   `scheme://`, `mailto:`/`javascript:`/`data:`/…, `www.`, bare domains with common TLDs
   (incl. punycode) → `[link removed]`; email addresses → `[address removed]`; all angle
   brackets dropped (no fence marker or tag can survive); bullets stripped; ≤ 5 × 200.
   *Superseded by review F1 below: no TLD list any more.*
9. **Hardening beyond the plan: links in other people's words are also defanged in the
   plain-text brief** (titles, places, sender names, subjects). That text is mailed *from
   "JARVIS"* and mail clients linkify URLs, so a hostile subject could otherwise borrow
   JARVIS's name for a phishing link. `data` keeps the one-line original (the console shows it
   with textContent). Eval case c16 covers it. *Tightened by review F1/F8 below.*
10. **OIDC library.** `joserfc` (already hash-locked: it is authlib's required dependency) is
    imported directly for RS256 verification; no new dependency was added and `pyproject.toml`
    / `requirements.lock` are unchanged. The header is checked for `alg == RS256` and a `kid`
    before any key is used; JWKS is cached per `Cache-Control` (5 min … 24 h) and re-fetched
    for an unknown `kid` at most once a minute; a JWKS outage fails closed. `aud` must be a
    string equal to `{public_base_url}/internal/brief/tick`. With
    `JARVIS_BRIEF_SCHEDULER_SA` set but no `JARVIS_PUBLIC_BASE_URL`, the route stays off (one
    warning) rather than accepting an unknown audience.
11. **Wiring.** `Storage` gained an optional `docs` field so the brief store shares the
    Firestore client; memory/redis backends and injected test stores use `MemoryDocs`. The
    brief shares the gateway's approval store and audit chain. Owners for the tick are
    `JARVIS_OWNER_EMAILS` (or the legacy `owner` id when none are configured).
12. **Left for the console/deploy builder** (not in this branch): `console.js` `SCOPE_WORDS`
    has no entry for `gmail.insert`; the consent-screen scope list printed by
    `deploy/cloudrun.sh` should add `gmail.insert` (optional).

## Review findings (fresh-context security review, 2026-11-01)
No CRITICAL/HIGH. Each fix was written test-first; the reviewer's proof scripts
(p_links / p_race / p_auth / p_stress) were re-run against the fixed package.

| # | Severity | Finding | Outcome | Tests |
|---|---|---|---|---|
| F1 | MEDIUM | Links in the plain-text brief (mailed from "JARVIS"): raw `from_address` (`www.evil-login.support/reset@z.co`); TLD denylist missed `.support .de .shop .cloud .cc`, IPs, `//host`; homoglyphs, soft hyphen, U+3002/FF0E/FF61 | Fixed. `render.defang`: NFKC → invisible chars dropped → ideographic stops as dots → schemes and `//host` → `[link removed]`; IPv4 and every `label.letters` dot (any script, no TLD list) → `[.]`; "e.g.", "Mr. Smith", "09.30" untouched. Same rule for the AI lines. Sender address printed only when `addresses.plain_address` (strict ASCII addr-spec) accepts it. Eval `_LINKISH` is TLD-agnostic and a new gate checks the whole plain-text brief (`text_links`); p_links inputs are cases i21–i34 (+ c17). `data` keeps originals; console JSON shape unchanged | `test_brief_render.py::test_no_link_survives_in_titles_places_names_subjects_or_ai_lines`, `::test_defang_outputs`, `::test_ordinary_prose_is_not_mangled`, `::test_sender_address_is_printed_only_when_strict`; `test_addresses.py::test_plain_address_*`; `test_brief_summarize.py::test_bare_domains_are_defanged_whatever_the_tld_or_script`, `::test_schemes_are_removed`; eval i21–i34, c17 |
| F2 | MEDIUM | A stale-claim loser still delivered its own older text | Fixed. `_generate` reports whether `finish` was accepted; a loser counts 0 made and skips delivery; its AI call is still added to `ai_calls_today` (`finish` and `add_ai_calls` add, never overwrite). The inbox message is built from the record `begin_inbox` returns (the stored one) | `test_brief_service.py::test_a_stale_claim_loser_delivers_nothing_and_the_inbox_gets_the_stored_text`; `test_brief_deliver.py::test_the_inbox_gets_the_stored_text_not_the_callers_copy` |
| F3 | MEDIUM | A Google 503 at the first tick gave a "ready" brief with a section `unavailable`, delivered and never retried | Fixed. Record field `retries` (not in the API view). A ready brief with calendar or inbox `unavailable` is due again for scheduled ticks in the window, ≤ 2 retries, each a counted generation (6/day cap). Delivery waits until the sections are ok, the retries (or generations) are used up, or it is the last tick: next tick (+30 min, 5 min slack) past min(brief time + 4 h, 11:30 + 30 min — the scheduler's last wake-up is 11:30). `not_connected` is never retried | `test_brief_service.py::test_a_503_at_the_first_tick_is_retried_before_the_inbox_gets_it`, `::test_a_persistent_outage_is_delivered_once_after_two_retries_with_the_note`, `::test_a_partial_brief_is_delivered_at_the_last_tick_of_the_window`, `::test_a_partial_brief_past_the_generation_cap_is_delivered_without_retrying`, `::test_not_connected_is_not_retried`; `test_brief_store.py::test_a_partial_brief_is_retaken_by_a_retry_at_most_twice`, `::test_complete_or_unlinked_briefs_are_not_retried`, `::test_retries_count_against_the_generation_cap`; `test_brief_schedule.py::test_a_partial_brief_is_due_again_until_its_retries_are_used`, `::test_last_tick_of_the_window` |
| F4 | LOW | AI call not audited; consent text did not say what is sent; an unpriced brain said "No charge" | Fixed. `morning_brief.summarize` (R2, agent `morning_brief`) appended BEFORE the call (fail closed: no record, no call) with model id + input chars, and after it with the cost (or `error`). The trail hashes `args`, so the readable model/size/cost is in `detail`; never content. `MSG_SPEND` and `ai_cost_note` say today's calendar titles and mail senders, subjects and previews go to Anthropic's Claude (the brain's name otherwise); a model missing from the price table is "cost is unknown" (`pricing.is_priced`) | `test_brief_service.py::test_the_ai_call_is_audited_before_it_happens_with_model_and_size_only`, `::test_a_failed_ai_call_is_audited_as_an_error`, `::test_no_audit_record_means_no_ai_call`, `::test_consent_texts_say_what_is_sent_and_an_unpriced_brain_is_not_free`, `::test_consent_texts_name_anthropics_claude_and_a_free_model_says_so` |
| F5 | LOW | Empty/stale JWKS cache after a failed fetch refetched on every request | Fixed. The 1/min refetch limit applies whatever the reason (p_auth: 20 → 1 fetch; 10 concurrent: 1 fetch, 0.3 s) | `test_scheduler_auth.py::test_a_jwks_outage_is_not_refetched_for_every_request`, `::test_an_expired_cache_during_an_outage_is_not_hammered`, `::test_concurrent_junk_during_an_outage_fetches_once` |
| F6 | LOW | Tick route mounted with in-process storage (at-most-once not guaranteed across instances) | Fixed. Mounted only with `JARVIS_SESSION_BACKEND=firestore`; otherwise one start-up error and 404 | `test_scheduler_auth.py::test_tick_route_is_absent_without_persistent_storage[memory/redis]` |
| F7 | LOW | `card._INVISIBLE` a hand-picked list | Fixed. Removed by category (Cf, Co, Cs) plus fillers U+00AD/034F/115F/1160/180E/3164/FFA0, variation selectors and the tag block; Cc/Zl/Zp still become spaces (so `\n` stays a break, never "invisible"). Shared with slice 6 cards: all approval tests pass | `test_addresses.py::test_one_line_drops_every_format_filler_and_private_use_character`, `::test_one_line_tag_characters_and_soft_hyphen_together`, `::test_newlines_and_tabs_are_breaks_not_invisible` |
| F8 | LOW | Third-party words not marked as such in the text | Fixed. Titles, places, names and subjects in “ ” (`card.quoted`; their own “ ” become plain quotes), and one line "Titles and subjects below were written by other people." under the header (it covers the calendar titles above INBOX too; omitted when neither section was read) | `test_brief_render.py::test_full_brief_renders_every_fact`, `::test_quotes_inside_other_peoples_words_cannot_close_ours`, `::test_the_others_note_is_shown_only_with_their_words`; compose c01–c17 |
| F9 | LOW | Time regex `\d` accepted Arabic-Indic and other digits | Fixed: `[0-9]` | `test_brief_schedule.py::test_only_ascii_digits_make_a_brief_time`; `test_brief_api.py::test_settings_confirmations_time_and_scope_are_422` |
| F10 | LOW | No hint which claim failed; no check of the SA's form; a tz GET on every console open | Fixed. Refusal log carries `claim=<name>` (never the token or values); one start-up warning when the SA does not end with `.iam.gserviceaccount.com`; `generate` first asks the claim rule with the cached zone and skips the calendar GET when today's brief exists, is being made, or the limit is reached | `test_scheduler_auth.py::test_a_refusal_logs_which_claim_failed_but_never_the_token_or_values`, `::test_a_scheduler_account_that_is_not_a_service_account_is_warned_about`; `test_brief_service.py::test_open_with_todays_brief_or_the_cap_makes_no_google_calls` |
| F11 | — (optional) | — | Skipped: reviewer said no change needed | — |

Notes: NFKC writes "…" in other people's words as "..."; a rule with no TLD list also shows
`Node.js` / `report.pdf` as `Node[.]js` / `report[.]pdf` (readable, never clickable). The API
response shapes are unchanged (field names and types); only text content changed (`text`,
`ai.lines`, `ai_cost_note`).

## Review findings — console + deploy (fresh-context review, 2026-11-01)
No CRITICAL/HIGH. Each fix was written test-first (the new tests failed on 3551526 and pass
now); the reviewer's probe scripts (late script, hidden tab, time picker, 401, inbox race,
polling, offline) were re-run against the fix and all show the fixed behaviour. CSP, the
textContent-only rendering and the API shapes are unchanged. Browser tests are in
`tests/browser/test_brief.py` unless another file is named.

| # | Severity | Finding | Outcome | Tests |
|---|---|---|---|---|
| M1 | MEDIUM | `console-brief.js` (deferred, after `console.js`) arriving after the config + sign-in round trips missed the one-shot `jarvis:ready`: "Checking today's brief…" forever, no GET | Fixed. `window.JarvisConsole` (still frozen) gains `ready()`: the last `jarvis:ready` detail (frozen `{returning}`), `null` until signed in and again once the gate shows. The Brief script listens for the event AND asks `ready()` when it starts (never both for one sign-in). Load order kept (deck → console → brief): the Brief script needs `JarvisDeck` at start, `JarvisConsole` only when it calls | `test_a_late_brief_script_still_loads_todays_brief_once[0, 800]` (800 ms late script → 1 GET; on time → still exactly 1); `test_console_assets.py::test_brief_script_finds_the_console_ready_however_late_it_arrives` |
| M2 | MEDIUM | `shown()` / `markSeen()` ignored `document.hidden`: a background tab auto-opened, POSTed `/seen` and cleared the badge | Fixed. Both return early while hidden (nothing made, nothing marked seen); `visibilitychange` to visible with the panel open calls `shown()` (or reloads first when the data is stale). The auto-open itself still happens, so the owner finds it open | `test_a_hidden_tab_marks_the_brief_seen_only_once_it_is_shown`, `test_a_hidden_tab_does_not_make_todays_brief_until_it_is_shown` |
| M3 | MEDIUM | The time `<select>` was rebuilt during a save and showed the old value; steps during a PUT were dropped (3 × ArrowDown → one PUT 07:30); a "Switch on" confirmed during a save was dropped silently | Fixed. The picker is built once and updated in place (never rebuilt, never disabled), showing the pending pick. A pick is saved 400 ms after the last step; settings PUTs run one at a time in order (a queued time save reads the latest pick when its turn comes), so nothing is dropped; "Couldn't save: JARVIS isn't ready yet" if there is no transport. Also: the switches are rebuilt only when something they show changed, so an unrelated update (live approvals count, a poll) can't swap one out from under a press | `test_arrow_keys_on_the_time_picker_save_the_time_they_stop_on` (one PUT `{"time":"08:30"}`, picker shows 08:30, keeps focus), `test_a_time_change_during_a_slow_save_is_sent_after_it` (07:30 then 08:30, never snaps back), `test_switch_on_confirmed_during_a_save_is_sent_after_it` |
| L1 | LOW | `api()`'s 401 error had no `.status`, so the Brief's 401 guards never fired ("Couldn't check today's brief. Sign in required.") | Fixed. Every non-2xx error carries `.status` (message kept). Side effect, intended: the console's other 401 guards (approvals, audit, integrations, history) now also leave a 401 to the gate | `test_a_401_hands_over_to_the_sign_in_gate_without_an_error_line` |
| L2 | LOW | Double-click on the inbox switch while the address lookup was awaited: the second dialog's stale `close` event cancelled the first | Fixed. One confirm at a time (guard covers the lookup and the dialog); a `close` event that arrives while a newer dialog is open is ignored | `test_a_double_click_on_the_inbox_switch_keeps_one_dialog_open` (one lookup, dialog stays open, Esc → 0 PUTs) |
| L3 | LOW | A network failure showed the browser's "Failed to fetch" | Fixed. A `TypeError` from the request reads "Can't reach JARVIS. Check your connection." (load, Refresh, settings) | `test_a_network_failure_says_jarvis_cannot_be_reached` |
| L4 | LOW | `api(path)` accepted any URL | Fixed. Refused unless it starts with exactly one `/` (`//host`, `/\host`, `https://…`, relative and non-strings refused before any request, so the token never leaves) | `test_the_console_transport_calls_only_its_own_paths` (no request, no CSP report) |
| L5 | LOW | `afterData()` set the poll timer without clearing it (overlapping loads → parallel chains); the comment said a failed `/seen` is offered again on the next load (it is not) | Fixed. `clearTimeout` before setting it (probe: 4 overlapping loads → one chain, 1 + 4 + 15 GETs); the comment now says what happens: sent once per page load, the next page load offers it again | `test_polling_while_someone_else_makes_the_brief_stops_at_the_cap` (40 ms polls: 1 + 15 GETs, stops; Refresh looks again, never generates) |
| L6 | LOW | A failed step 8 was only a mid-run note; nothing checked the schedule | Fixed. A failed step 8 ends the summary with "Morning brief: NOT scheduled…" + what still works (the brief is made when the Brief panel opens) + re-run. On success, one `gcloud scheduler jobs run jarvis-morning-brief --location "$REGION"` (non-fatal, never retried; harmless because JARVIS decides what is due); "Scheduler accepted it" only when it succeeded, otherwise a plain "the test run didn't go through" line. Caveat: the command succeeding means Cloud Scheduler accepted the run, not that JARVIS returned 2xx | `test_deploy_config.py::test_summary_says_plainly_when_the_brief_schedule_was_not_set_up`, `::test_a_working_schedule_is_test_run_once_and_said_to_answer`, `::test_a_failed_test_run_is_not_fatal_and_not_called_an_answer`, `::test_the_test_run_is_harmless_because_the_app_decides_what_is_due` (the step-8 outcome and summary run in bash with `gcloud` stubbed) |
| Gaps | — | Missing tests | Closed. Inbox dialog Esc and "Not now" → 0 PUTs; a refused PUT after "Switch on" (429 / 422) leaves the switch off; Enter in a dialog = "Not now"; Refresh double-click → 1 POST; polling cap; hostile text in every server string (titles, places, clash names, free blocks, senders, addresses, subjects, mail times, AI lines, `ai.label`, `model`, `ai_note`, `error`, `tz`, `ai_cost_note`, 500/422/429 `detail`, integrations email) plus JSON `__proto__` keys and unknown server words (`trigger: "__proto__"`, delivery status `"constructor"`) → no img/a/script/… and no `on*` attribute in `#p-brief` or the dialog, `window.__pwned` unset, `Object.prototype` clean, no CSP report. Found by it and fixed: server words looked up in plain objects reached `Object.prototype` ("Made 07:00 · [object Object]", an empty Gmail line): lookups are own-key only; `Object.assign` with server objects became spread | `test_inbox_dialog_esc_and_not_now_send_nothing`, `test_a_refused_switch_on_leaves_the_switch_off[ai-429, inbox-422]`, `test_enter_in_a_confirm_dialog_means_not_now`, `test_refresh_double_click_makes_one_brief`, `test_polling_while_someone_else_makes_the_brief_stops_at_the_cap`, `test_markup_in_every_server_string_stays_text[img, a, script]` |
| Sinks | — | Static sink test missed several sinks and stripped `//…` (which also hid code after a `//` inside a string) | Fixed. The whole file is scanned, comments included (the header comment no longer names a sink). Added `writeln`, `createContextualFragment`, `DOMParser`, `setHTMLUnsafe`, `parseHTMLUnsafe`, `srcdoc`, `.href =`; patterns for `.href/.src/.action =`, `setAttribute('on…'/'href'/'src'…)`, `setAttributeNS`, string timers. The scanner has its own tests | `test_console_assets.py::test_brief_script_never_parses_server_text_as_html`, `::test_the_sink_scan_finds_each_sink[14 cases]`, `::test_the_sink_scan_passes_safe_dom_code` |

# Release R4 — Vitals, Self-Health & People: an API-keys/quotas/bills vitals board with expiry + near-limit warnings, a JARVIS self-health check that speaks "all systems" and alerts on fault, Google Photos → faces & contacts, scoped people research that opens profiles, own-account GitHub + YouTube, and a no-AI mode (pass 1)

Status: PLAN v1 · 2026-11-05 · branch `r4-plan` (from `main` @ e16996a = R3 merged, PR #22). Builders start from
`r4` = `main` + this plan's I0 seams. Carries the owner's six requirements of 5 Nov (release-plan.md → "Your six new
requirements"). Not in this plan: X / Instagram / Facebook / LinkedIn **data** pulls (paid or gated → R10; only
browser-open here), at-scale or ongoing person monitoring (R10, and only the scoped version), Google Photos
whole-library auto-sync (Google removed it — see D8), camera extras and smart-home devices (R5).

## Owner's rules for R4 (5 Nov)
- **Free, private, autonomous.** No paid service and no new paid usage: Photos Picker, YouTube Data and (own) GitHub
  are free; web search uses the existing 900/month credits; the vitals board and the health check make **no model
  call of their own** and are plain deterministic code. People research makes one brain call to write the dossier
  (the replies the owner already pays for) and degrades to a raw-links, no-summary mode when the brain is off (D10).
- **No new Cloud Scheduler job.** Two of the three free jobs are used (R3). The vitals poll and the scheduled health
  check ride the **existing tick** (`ticks.py` → `TickJob`), they do not add a Scheduler job (D14).
- **No new Secret Manager version if avoidable.** The deploy is past the 6 free versions (R2 D2). Photos + YouTube
  reuse the existing Google OAuth (add scopes); the GitHub token is encrypted in the keyring, not a GCP secret (D9).
- **Confirm before commit.** R4 is read/observe. The few irreversible actions — deleting a tracked key, deleting an
  enrolled face, clearing a saved dossier — take an owner confirmation token through the gateway; enrolling a face
  takes consent. Opening a browser tab and running research are not commits (D12).
- **Two decisions, confirmed 5 Nov:** consent-based faces (enrol anyone with a yes; never auto-enrol strangers or
  match a stranger's face to an identity) and scoped person research (public figures + work due-diligence from
  public sources; never mass aggregation of a private individual). The unsafe versions are not built (D8, D10).
- **Everything must also work with no AI.** Pass 1 of a no-AI mode lands here; R9 finishes it (D7).

## Gate G0 · R3 first
Done: R3 (PR #22) is merged to `main` at `e16996a`. R4 extends R3 code — the alert port and kinds (`alerts.py`),
the one alert policy (`notify/`), the faces engine and consent (`faces/`), the home bridge (`homebridge/`), the
brief sections (`brief/`), persona p4.8 — and R2 (`keyring.py`, the privacy registry, `check_purpose` targets) and
R1 (Telegram alerts, offline mode). All are on `main`; no cross-release gate remains.

## Architecture fit and phase mapping
No new tier. One recorded addition: a **cross-cutting Vitals + Self-Health plane** (Layer 7 data + the
observability/cost cross-cut) that reads existing meters and probes existing integrations. Proposed
`JARVIS_Architecture.pdf` update: under "Observability / quality", add "Vitals (keys, quotas, bills, expiry)" and
"Self-health probes (voice report, fault alerts)". One recorded deviation from req 1: Google no longer allows an app
to read the whole Photos library (Library API locked 31 Mar 2025), so JARVIS uses the **Picker API** (owner selects
photos) and runs its **own** recognition on the selection — Google's face groups are not exposed (D8).

| Feature | Layer · skill | Phase | Verdict |
|---|---|---|---|
| Vitals: keys, quotas, bills, expiry + near-limit warnings (req 2) | L7 data, observability/cost cross-cut · Code & DevOps + Finance | 7, pulled forward (owner) | Build now |
| JARVIS self-health check, spoken, fault alerts (req 3) | L4/cross-cut probes, L8 voice+notify · Code & DevOps | 7, pulled forward | Build now; runs with the brain off |
| Google Photos → faces & contacts (req 1) | L6 integration, L2 vision (edge, R3) · Research & Intel | 3/5 | Build now; OFF until Google sign-in + consent + R3 home kit live |
| People research (scoped) + open profiles (req 6, 5c-free) | L5 research, L6 browser · Research & Intel | 3 | Build now |
| Own GitHub + YouTube connect (req 5b) | L6 integration · Research & Intel | 3 | Build now; OFF until connected |
| No-AI mode, pass 1 (req 4) | L3 router, L4 core · cross-cut | 2/7 | Build now; finished in R9 |

## What is free, paid or gated (why the social split)
Verified 5 Nov (sources below). GitHub REST and YouTube Data v3 are genuinely free → own-account read in R4. Google
Photos Picker is free → R4. X/Twitter has **no free API tier** since Feb 2026 (pay-per-use ≈ ₹0.40–0.45/read),
Instagram/Facebook need a Meta app + review + Business/Creator account (own account only), LinkedIn is
partner-gated with no general profile read → all four are **R10 (paid/gated)**. For every platform, *opening* a
profile in the browser is free and is in R4 (D11).

## Decisions

**D1 · Free + private + no model call for vitals/health.** Vitals and health read local meters and probe reachability
only. No provider SDK is called by them; nothing outside `jarvis.llm` imports a vendor SDK (project rule). People
research is the only R4 brain user, and only to compose the dossier; its no-AI path returns raw findings (D10).

**D2 · Provider registry (new `vitals/` module).** One record per thing that has a limit or renewal:
`id, label, kind ∈ {key, quota, billing, storage, allowance}, source ∈ {auto, manual}, limit, used, unit, reset_at,
expires_at, note`. `auto` records are filled from existing meters (`billing.service.Billing.usage/month/allowance`,
`quota.ledger.QuotaLedger`, and cheap reads of Google/Firestore/Cloud Run/Scheduler where a free read exists);
`manual` records are keys the owner types an expiry/limit for (e.g. a brain API key). Status is computed, never
stored stale.

**D3 · Thresholds.** `ok` → `amber` when `used ≥ 80% of limit` **or** `expires_at ≤ 30 days` → `red` when
`used ≥ 100%` **or** expired. Both numbers live in config (`VITALS_AMBER_FRACTION=0.8`, `VITALS_EXPIRY_AMBER_DAYS=30`).
The board also shows this month's spend vs the limit (the owner's standing ask), reusing `billing.rupees`/`inr` (₹ only).

**D4 · Vitals alerts.** New `AlertKind`: `vitals_warn` (amber, default urgency = silent/quiet-respecting) and
`vitals_critical` (red, urgent; never held, like hazards). They ride the existing `notify` policy (quiet hours, VIPs,
storm caps). A provider only re-alerts when it crosses a line, not every tick (store last status in `jarvis_vitals_status`).

**D5 · Health probes (new `health/` module).** One probe per integration: brains (`llm` reachability/auth via a
0-token ping, catching `LLMUnreachable`/`LLMAuthError`), Google (Calendar/Gmail/Drive/Contacts/Maps/YouTube via a
metadata call), Telegram (getMe), the home bridge (R3 heartbeat), Firestore/Docs, Redis, web search. Each probe is
cheap, has no side effect, calls no paid endpoint in a way that burns quota, and has a per-probe timeout. Result:
`ok | degraded | down` + a one-line reason. **No LLM is on the probe path**, so the check runs with the brain off.

**D6 · Health report + alerts.** On demand (`systems_check` tool; "Jarvis, run a systems check") and on the tick
(D14). The spoken line is composed from fixed templates (never model text) via `voice.speakable` — "All systems
nominal, Sir" or "Attention: the home bridge is not answering." A change from ok→fault raises `health_fault`
(urgent); fault→ok raises `health_recovered` (silent). Last result in `jarvis_health_last`.

**D7 · No-AI mode, pass 1.** A settings mode `brain_mode ∈ {ai, local, none}` (extends offline's existing
`ai`/`local`). In `none`, `core.brain` routes by deterministic intent (extend `offline.rules.OfflineRules`) with **no
provider call at all**: calendar, reminders, timers, device control (R3/R5), vitals, systems-check, open the vault,
notes, groceries, and open-a-profile work fully; skills that must generate text (drafting, research synthesis,
tutoring) return a fixed line "that needs the AI switched on" — never a silent failure. The mode shows in the HUD.
Vitals and the health check are explicitly built to answer in `none`.

**D8 · Google Photos → faces & contacts (new `photos/` module).** Flow: owner signs in (existing Google OAuth +
added scope `photospicker.mediaitems.readonly`) → a Picker **session** → owner selects photos in the Google Photos
UI → JARVIS reads only the selected media. Selected images are sent to the **home edge** (R3 `homebridge`) where the
faces engine already runs; recognition and any enrolment happen at home, the cloud keeps ids only (R3 privacy rule).
Recognised faces are matched to Google Contacts by name (`contacts.client`), and enrolment is **consent-gated**
(`faces.consent`, a guardian's for a child). OFF until Google sign-in, consent, and the R3 home kit are live. No
whole-library read, no silent sync, no stranger auto-enrol.

**D9 · Own GitHub + YouTube (extend `integrations/`).** YouTube Data v3 via the existing Google OAuth + scope
`youtube.readonly` (own channel/videos). GitHub via the owner's own token (OAuth app or PAT) stored encrypted in
`keyring` (purpose `github_token`), never a GCP secret; read-only REST (profile, repos, activity). Both go through
the gateway and are OFF until connected.

**D10 · People research, scoped (new `people/` module).** Input: a name + optional context (role, org, "the vendor
on tender X"). Steps: search public sources (existing web search, GitHub, YouTube, Wikipedia/official) → disambiguate
to the most likely person → compose a short dossier (who, role, public history, notable updates) with **one brain
call** → speak the key points (`voice`) → return the resolved profile URLs for the owner to open (D11). **Scope
guard** (code, with evals): intended for public figures and work due-diligence; the module refuses a request framed
as assembling a private individual's home, movements or private accounts, and never face-matches a stranger to an
identity. Dossiers are **session-only** by default; saving one is an explicit owner action. No-AI path: skip the
summary, return the found links + open them.

**D11 · Open profiles in the browser, one window per tab.** The research result carries the resolved URLs and an
"Open all profiles" action. The **client** opens each in its own browser window/tab (web console
`window.open(url, '_blank')` per URL; or Claude-in-Chrome when driven from there). No server-side browser control is
needed. LinkedIn/X/Instagram/Facebook open this way for free even though their data pulls are R10.

**D12 · Confirm before commit.** Read/observe is free. `delete_tracked_key`, deleting an enrolled face, and clearing
a saved dossier are irreversible → gateway R3 token (card + passkey), no "don't ask again". Enrolling a face →
consent. `connect_github`/`connect_youtube`/`photos_import` store or read auth but are not R3; they are owner-initiated
in the console.

**D13 · Persona p4.8 → p4.9** (`core/prompts.py`), adding vitals, the systems check, the no-AI mode and scoped
research to what JARVIS says it can do. Re-check R3's final value at I1.

**D14 · Scheduling without a new job.** Vitals poll (hourly) and the scheduled health check register as `TickJob`s
on the existing tick, isolated per the tick's rules (a failing job is logged and reported, stops no one). No new
Cloud Scheduler job; stays within the 2-of-3 free jobs already used.

**D15 · Audit + untrusted data.** Every new tool call is append-only audited (`tools.audit`). Content fetched during
research (web pages, profiles) is untrusted data, never instructions; it is never learned into memory and never
spoken as if it were JARVIS's own instruction.

## Data model (Docs port, prefix `jarvis_`; equality + single order_by only)
- `jarvis_vitals_providers` — one per tracked provider/key (D2 fields). Manual ones owner-editable.
- `jarvis_vitals_status` — last computed status per provider (for cross-line re-alert only).
- `jarvis_health_last` — last health result per integration + overall, with timestamp.
- `jarvis_connectors` — metadata for GitHub/YouTube (connected?, scope, last ok); tokens live in `keyring`.
- `jarvis_people_saved` — only dossiers the owner explicitly saved (default empty).

## New tools (all through `tools.gateway`)
`vitals_show` (read), `vitals_set_key` (owner, manual record), `delete_tracked_key` (R3), `systems_check` (read, no
AI), `connect_github` / `connect_youtube` (owner auth), `photos_import` (owner; feeds faces at the edge),
`research_person` (read; scope-guarded), `open_profiles` (returns URLs; client opens). Each declares
`activity_words` and audit lines.

## API routes
`GET /vitals`, `POST /vitals/providers` (manual CRUD), `POST /health/check`, `GET /health/last`,
`POST /people/research`, `POST /photos/pick` (Picker session), `POST /connectors/github`, `POST /connectors/youtube`,
`POST /settings/brain-mode`. All authed (console session); R3 token enforced server-side on deletes.

## Console (each `console*.js` ≤ 800 lines; `textContent` only; no CDN; ₹ only; Command Deck patterns)
- **Vitals** panel: a board of providers with amber/red chips, used/limit, reset and expiry, month spend vs limit.
- **Systems check** panel: a Run button, the last result per integration, a Speak button.
- **People** panel: search box → dossier card → "Open all profiles".
- **Connectors** panel: GitHub, YouTube, Photos (sign-in/connect buttons + status).
- **Settings**: the brain-mode switch (AI / Local / No-AI) with a one-line meaning.

## Voice
Spoken health report and spoken dossier key-points via `voice.service` + `voice.speakable` (fixed templates for
health; dossier text is model-written but spoken only after the owner triggers research).

## Evals (mock; gate: every suite passes; each negative control must make its suite fail)
- Vitals: amber at 80% and at 30-days-to-expiry; red at 100% and expired; re-alert only on line-cross; month-vs-limit.
- Health: each probe classifies ok/degraded/down; overall rolls up; **runs in no-AI mode**; negative control: a down
  integration must not report ok.
- No-AI: deterministic skills answer in `none`; generation skills return the fixed "needs AI" line; control: a
  generation skill must not silently succeed.
- Photos/faces: consent gate blocks naming without a yes; stranger is never named; delete removes edge pictures.
- People research: disambiguation picks the right public figure; **scope guard refuses** a private-individual
  aggregation prompt (control: the refusal suite must fail if the guard is removed); dossier cites sources.
- Needles across all four parts (VIP/quiet interplay, no-AI, consent, scope guard).

## Acceptance criteria (what the owner sees)
Health check reports a deliberately broken connection and speaks it; vitals shows a test key amber at 30 days and red
at expiry; a picked photo is recognised and labelled to a contact (with R3 live); a public-figure dossier is read
aloud and the right profiles open, each in its own window; the free skills answer with the brain switched off; ₹0
billing.

## Workstreams (worktrees, tests first; branches `r4-a`..`r4-d` from `r4`)
- **A — Vitals:** `vitals/` module, provider registry, aggregation over `billing`+`quota`, thresholds, alerts
  (`vitals_warn`/`vitals_critical`), brief **Vitals** section, console panel, `vitals_*` tools.
- **B — Self-health:** `health/` module, per-integration probes, tick job (D14), spoken report, `health_fault`/
  `health_recovered` alerts, console panel, `systems_check` tool — all no-AI-safe.
- **C — Photos & connectors:** `photos/` (Picker + edge feed via `homebridge`), faces enrol with consent + contacts
  labelling, `integrations/github.py` + `youtube.py`, Connectors panel, `photos_import`/`connect_*` tools.
- **D — People research + no-AI mode:** `people/` (dossier, disambiguation, scope guard, open-profiles, voice),
  `brain_mode=none` across `llm.router`/`offline.rules`/`core.brain` + settings + skill refusals + HUD, settings route.

## Shared rules for every builder
Tests first (80%+). Through the gateway; R3 token on deletes; consent on enrol. No vendor SDK outside `jarvis.llm`.
Secrets via keyring/env only, never logged. Append-only audit. Files ≤ 800 lines; functions ≤ 50. ₹ only in the UI.
Fetched content is untrusted. `security-reviewer` for anything touching tools, auth, secrets, the gateway, or the
scope guard.

## Owner checks at test time (none verifiable in the sandbox)
Sign in to Google for Photos + YouTube; connect GitHub; run a systems check and hear it; add a provider key and
watch it go amber then red; with the R3 home kit live, pick photos and label a face; research a public figure and
see the tabs open; flip No-AI mode and confirm calendar/reminders/vitals/health still answer.

## Risks
- Photos is pick-only, not a library sync — set the expectation in the console (Google's change, D8).
- People-research scope creep — the code guard + refusal evals hold the line; X/Meta/LinkedIn data stay in R10.
- Vitals reading GCP billing/quota may need extra API permission; degrade to "unknown" rather than fail (D2).
- Health probes must stay cheap and side-effect-free; a probe must never itself consume meaningful quota (D5).
- GitHub token handling — keyring only, never a GCP secret, never logged (D9).

## Open questions (need the owner, non-blocking; safe defaults until answered)
- First provider keys to track in Vitals (default: the brain keys + Google + the free allowances JARVIS already uses).
- GitHub connect method: OAuth app or a personal access token (default: PAT in keyring, simplest + free).
- Save people-research dossiers, or keep them session-only (default: session-only).

## Sources (accessed 2026-11-05)
- Google Photos Picker API launch + Library API lockdown (developers.googleblog.com; developers.google.com/photos).
- X/Twitter API pricing 2026, no free tier, pay-per-use (docs.x.com and 2026 pricing write-ups).
- GitHub REST and YouTube Data API v3 free quotas (vendor docs — confirm exact limits at build via Context7/primary docs).

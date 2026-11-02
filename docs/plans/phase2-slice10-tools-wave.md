# Slice 10 — Phase 0 close-out + Phase 2 tools wave

Date: 2026-11-01 · Branch `slice10-phase2-tools` (based on `slice9-voice`, PR #13) · Owner request:
"Please continue the pending tasks in Phase 0 and phase 2. Meanwhile I shall update and test the features."

## Goal
Close the open Phase 0 items and fill the main Phase 2 gaps so JARVIS can look things up, keep a
to-do list, read documents, and so the owner controls what JARVIS may do — with irreversible
actions behind a passkey.

## Scope
| # | Workstream | Phase | Builder branch |
|---|---|---|---|
| A | Real-model eval runner (Cloud Shell, ₹ confirm), exact stream usage, cross-process session rev precondition | 0 | `s10-p0` |
| B | Web search + page reading with citations (Tavily adapter behind a port) | 2 | `s10-web` |
| C | To-do list on Google Tasks (optional scope) + brief section | 2 | `s10-tasks` |
| D | Owner permission rules (Allow / Ask first / Never) + passkey (WebAuthn) for irreversible approvals | 2 | `s10-perm` |
| E | Document reading: upload PDF / DOCX / TXT / MD / CSV, chunked store, read/search tools | 2 | `s10-docs` |

Deferred to slice 11+: Telegram front door (bot token, webhook, external-channel identity), decision
helper, sub-agents, CLI long-term memory (owner does not use the CLI).

## Shared rules for every builder
- Start: `git merge --ff-only slice10-phase2-tools` in your worktree. Commit on your own branch.
- Tests first. Run with `PYTHONPATH=$PWD/src /tmp/venv-b/bin/python -m pytest -q` (3.11) and
  `/tmp/venv-12/bin/python` (3.12). Never `pip install -e` into the shared venvs. No 3.12-only APIs.
  Never `from tests.conftest import`. Mock evals: `PYTHONPATH=$PWD/src /tmp/venv-b/bin/python evals/run_all_mock.py`.
- Every tool goes through `jarvis.tools.gateway`; only `jarvis.llm` imports vendor SDKs; new HTTP
  adapters use `httpx` with an overall deadline, redirects off unless justified, response size caps,
  and strict response validation. Secrets only via settings `SecretStr`; never logged.
- Tool output from the web, documents, task notes is untrusted: wrap with `jarvis.tools.external`
  fences and mark the round tainted (`jarvis.tools.taint`). Training brains (`trains_on_content`)
  never get these tools or their content.
- UI: `textContent` only, CSP unchanged, no CDNs, ₹ only (never "$"), plain-English messages, error
  shape `{error, detail, reason?}`. Follow the existing Command Deck patterns (collapsed settings,
  confirm dialogs with focus trap). Design follows the ui-ux-pro-max repo conventions already in use.
- Do NOT bump `PERSONA_VERSION` (integration bumps it once). Put new persona/tool-use rules in a
  clearly separated paragraph so merges are easy.
- New dependencies: add to `pyproject.toml` only; do NOT edit `requirements.lock` (integration runs
  `make lock`). Licences must be permissive (MIT/BSD/Apache).
- Final report ≤ 400 words: what changed, test counts, anything not verified, open questions.

## A — Phase 0 close-out
- **A1 Real-model eval runner** `deploy/run-real-evals.sh` (Cloud Shell): reads the Claude key from
  Secret Manager (`jarvis-anthropic-key` or whatever `cloudrun.sh` stores — check) into the process
  env only (never echoed, never written to disk), makes a venv in `~/.jarvis-evals`, prints a ₹
  estimate per suite (cases × typical tokens × `jarvis.llm.pricing` × FX) and asks
  `Type YES to spend about ₹X` (confirm-before-commit). Suites: `phase0` (default), plus `--all` for
  memory, voice wit, brief, slice6 real modes. Hard spend cap: abort when metered cost exceeds 1.5×
  the estimate. Prints a plain-language gate summary — Phase 0 gate: ≥ 90 % pass, p95 ≤ 4 s,
  ≤ ₹0.95 per turn (US$0.01 at the current rate, tokenizer factor 1.3×) — and writes
  `evals/<suite>/report.json`. Add p95 latency + ₹/turn to `evals/phase0/run.py` if missing.
- **A2 Exact stream usage**: meter streamed Claude replies from Anthropic's stream events
  (`message_start.usage` input/cache, `message_delta.usage` output) instead of characters/4; keep the
  estimate only as a fallback when usage is absent (flag `estimated: true`). Same for cancelled streams
  (meter what usage arrived, else estimate).
- **A3 Cross-process session rev precondition**: header writes in `DocSessionStore` become a
  compare-and-set on `rev` inside a transaction (Firestore + `MemoryDocs` twin). On conflict:
  reload, re-apply this turn's append if it is still consistent, else raise `SessionConflict` →
  API 409 `{error:"session_conflict"}` with a friendly console message ("This conversation changed
  in another window — reloaded"). Emulator test in the `firestore` CI job. Keeps max-instances = 1
  for now, but removes the blocker.

## B — Web search + page reading with citations
- **D-B1 Provider: Tavily** behind a `SearchProvider` port (`jarvis.web`). Verified 2026-11-01
  (docs.tavily.com/documentation/api-credits): free plan 1,000 credits/month, no card; basic search
  1 credit, advanced 2; extract 1 credit per 5 URLs (basic); pay-as-you-go US$0.008/credit.
  Rejected: Claude's built-in web search (US$10 / 1,000 searches + results re-sent as input tokens on
  every later turn — ≈ ₹6 per search turn on Opus 5.5 and growing; page text is opaque to our gateway,
  so no fence/audit; Claude-only); Brave (card needed, plan changed May 2026). Builder verifies the
  current Tavily request/response shape and privacy/retention terms from docs.tavily.com and records
  them here.
- **Tools** (R1, gateway, audit): `web_search(query, max_results ≤ 5, topic general|news, days?)`;
  `web_read(url)` — **only** for an https URL that appeared in this conversation's search results or
  in the owner's own typed message (normalised exact match). This blocks the classic exfiltration
  pattern (a page tells the model to "fetch https://evil/?q=<secret>"). Fetching is done by Tavily
  Extract, never by our server (no SSRF surface). Caps: ≤ 5 results, snippet ≤ 700 chars, title ≤ 200,
  page text ≤ 12,000 chars; all fenced as EXTERNAL CONTENT; round tainted.
- **Query guard**: refuse queries containing email addresses, phone numbers, or anything the memory
  sensitive filter flags (`jarvis.recall` sensitive filter); persona rule: never put private details
  from mail, calendar, memory or documents into a search unless the owner asked for exactly that.
- **Citations**: each result gets a number for the turn; persona rule: cite claims from the web as
  [1], [2]. The API reply gains `sources: [{n, title, url, domain}]` (only sources actually cited,
  from stored results — never model-invented URLs). Console renders a "Sources" row under the reply:
  numbered chips, https only, display domain (punycode shown), `rel="noopener noreferrer nofollow"`,
  `target="_blank"`. Streamed replies get sources in the final event.
- **Allowance**: count credits per IST month in Firestore (`web_usage/{uid}_{YYYY-MM}`); stop at 900
  (90 % of the free 1,000) with a plain message; never pay-as-you-go. Vitals/Integrations line:
  "Web search: N of 900 this month". ₹0.
- **Key**: secret `jarvis-tavily-key` → `JARVIS_TAVILY_API_KEY`. `cloudrun.sh` asks only this NEW
  question when it has no saved answer (Enter = skip, web search off) — no `--reconfigure` needed.
  No key → tools not registered; JARVIS says web search is not set up.
- **Evals** `evals/web/`: citation format; injection pages (instructions to email, to fetch a URL with
  data, to save memory) → 0 unconfirmed sends, 0 `web_read` of URLs not in results/owner text, 0
  silent memory saves; private-query guard; negative control (guard off) must fail.

### B — Tavily facts verified 2026-11-01 (builder, `s10-web`)
Sources: OpenAPI spec <https://docs.tavily.com/documentation/api-reference/openapi.json>, API
introduction <https://docs.tavily.com/api-reference/introduction>, credits
<https://docs.tavily.com/documentation/api-credits.md>, FAQ <https://docs.tavily.com/faq/faq>,
privacy policy <https://www.tavily.com/privacy> (last updated 24 Nov 2025).
- **Auth**: HTTP bearer — `Authorization: Bearer tvly-…` (the old `api_key` body field is the
  legacy form; we send the header only). Base `https://api.tavily.com/`.
- **POST /search** body (only `query` required): `search_depth` basic|advanced|fast|ultra-fast
  (default basic), `topic` general|news|finance, `max_results` 0–20 (default 10), `time_range`
  day|week|month|year (the old `days` field is gone from the spec — our `days` argument maps to
  `time_range`), `start_date`/`end_date`, `include_answer`, `include_raw_content`,
  `include_images`, `include_favicon`, `include_domains`/`exclude_domains`, `country`,
  `include_usage`, `auto_parameters` (may silently switch to advanced = 2 credits: we never send
  it). Response: `query`, `answer`, `images`, `results[] {title, url, content, score,
  raw_content, published_date?, favicon?}`, `response_time`, `usage {credits}`, `request_id`.
- **POST /extract** body: `urls` (1–20), `extract_depth` basic|advanced, `format`
  markdown|text, `timeout` 1–60 s, `include_images`, `include_favicon`, `include_usage`, `query`.
  Response: `results[] {url, raw_content}`, `failed_results[] {url, error}` (check both even on
  HTTP 200), `response_time`, `usage`, `request_id`.
- **Errors**: 400 bad request, 401 missing/invalid key, 422 validation, 429 rate limited
  (`Retry-After`), **432 plan/key credit limit exceeded**, **433 pay-as-you-go limit exceeded**,
  434 live-fetch capacity, 500. Vendor text is never passed on; each code has a plain message.
- **Credits**: free plan 1,000/month, no card; search basic 1 / advanced 2; extract basic 1 per 5
  successful URLs, a failed extraction is never charged; pay-as-you-go US$0.008/credit; credits
  reset on the 1st of each month (time zone not stated).
- **Privacy / retention** (policy, not API-specific): Tavily collects "query data", keeps it "for
  the period necessary to provide and improve the Services" / until a valid deletion request (email
  support@tavily.com), "may use certain portions of your query data to improve our responses", and
  "may share your query data with third-party search index providers". The FAQ's "zero data
  retention" claim is not defined anywhere. **Consequence**: every query is treated as leaving our
  control for good → the deterministic query guard (email, phone, sensitive filter) runs before
  every search and the persona forbids private details in queries.

### B — build decisions (builder)
- **Numbering per conversation** (stored in `session.metadata["web"]`, newest 60 kept): a result
  keeps its number for the whole conversation, so a follow-up reply (or a streamed one, which has
  no tool rounds) can cite earlier results and still get correct chips.
- **Allowance counter is per deployment**, `{prefix}web_usage/{YYYY-MM}` (IST month), not per uid:
  Tavily's free credits belong to the API key, so two owners must not get 900 each (same reasoning
  as the voice allowance). Credits are reserved before the call (transaction; corrupt counter →
  refused), refunded when Tavily clearly did not charge (transport error, non-200, failed
  extraction).
- **http results are dropped** (only https is ever numbered, read or shown).
- **Spoken replies** name the source in words instead of `[n]` (the voice chunker would read the
  numbers aloud), so they carry no chips.
- **Results are fitted to the gateway's 12,000-character cut** (snippets, then titles, then the
  last results shrink; page text shrinks) so a fence is never cut open. The gateway serialises with
  `ensure_ascii`, so Indic text costs ~6 characters a letter: a Malayalam page yields ~1,900
  characters. Open question for integration: `ensure_ascii=False` in `GatewayResult.for_model`.
- **Brain footprint**: one `web_conversation(session)` around each gateway call (and the approve
  path), `sources` on the reply turn / response / stream meta. `brain.py` is now exactly at the
  800-line test ceiling (`tests/test_voice_persona.py`).
- **Console**: `console-web.js` loads before `console.js` (a restored conversation always finds
  it); two one-line hooks in `console.js`; Vitals row "Web search"; CSS block at the end of
  `console.css`; CSP unchanged.

### B — security review (fresh context, 2026-11-02): 0 critical, 1 high, 4 medium, 4 low
| # | Finding | Resolution |
|---|---|---|
| H1 | Query guard bypassed by obfuscation (full-width `＠`, ZWSP, `(at)`, `%40`, Devanagari / Malayalam / full-width digits, spaced PAN) | `web/guard.py`: NFKC + invisible/control stripped + any-script digits → ASCII before every check; any `@`, `%40`, `(at)`/`[at]`, "x at y dot z"; 8+ digits across separators (dates, year ranges, ISBN set aside; commas never join); spaced single characters joined up for the sensitive filter. After untrusted content a query is ≤ 120 chars. 13 new eval guard cases. |
| M2 | Indic text cost 6× (escapes); fences forgeable | `GatewayResult.for_model` → `serialise`: every string through `external.model_text` (drops Cc but \n\t, Cf, Cs, Co, Cn, tags, variation selectors, fillers; keeps ZWJ/ZWNJ between non-ASCII letters), then `ensure_ascii=False`. `wrap_external` adds a per-call id to both markers (`· 9f3a1c>>` … `<<END 9f3a1c>>`) and replaces fence-like text after NFKC (full-width, ZWSP-split, spaced) with `[fence-like text removed]`; signature unchanged. Persona + brief prompt updated. Malayalam page keeps ~11k chars. **Integration**: other branches' tests that assert a literal `<<END>>` must use `external.FENCE_END`. |
| M3 | No per-turn / hourly limit (an injected "run 30 searches") | ≤ 3 web_search and ≤ 2 web_read per owner message (counted in the ledger's `turn` record across tool rounds), ≤ 30 searches an hour per owner (in-process window; one instance). Plain "search limit for this request reached". Eval w17/w18: 30 injected searches → 3 reach Tavily. |
| M4 | Tavily's own 432/433 not remembered | `CreditsExhausted` → `WebAllowance.latch()` sets the month to the cap (Vitals "used up", nothing more sent). Tavily has **GET /usage** (OpenAPI, checked 2026-11-02: `key.usage/limit`, `account.plan_usage/plan_limit/paygo_usage/paygo_limit`, current billing cycle) — not used yet; could seed the counter. The counter starts at 0 on the first deploy even if the key was used elsewhere this month. |
| M5 | `cited_sources` attached any `[n]` | Only numbers this owner message's tool results showed (ledger `turn.shown`); `[n]` opening a line (list marker) ignored. A streamed reply (no tool round) therefore never has sources: the stream's final event is back to `{memory_used}` only. |
| L7 | Result URLs shown unfenced to the model | The model sees `n` + domain + fenced title/snippet; `web_read` takes `n` (or an owner-typed `url`); full URLs stay in the ledger and on the chips. |
| L8 | Key could carry Secret Manager's trailing newline | Stripped in `TavilyProvider._post`. |
| L6, L9 | (see review) | No change beyond M3's per-message and hourly caps. |

## C — To-do list on Google Tasks
- **D-C1 Google Tasks** over Todoist: no new account, already-linked Google, shows in Gmail/Calendar
  side panel and the Tasks phone app. API is free (quota only). Scope
  `https://www.googleapis.com/auth/tasks` added as an OPTIONAL scope (like `gmail.insert`): existing
  links stay connected; Integrations shows "To-do list — permission needed · Grant" which re-runs
  connect. Owner adds the scope in the consent screen's Data Access.
- **Tools**: `tasks_list(list?, due_before?, include_completed=false)` R1; `task_add(title, notes?,
  due?, list?)` R2; `task_update(task_id, title?, notes?, due?)` R2; `task_complete(task_id)` R2;
  `task_delete(task_id)` R3. Update/complete/delete use `Tool.preview` to fetch the real title for
  the card (fail closed). Titles/notes are fenced on read (other apps, e.g. Gmail "add to Tasks",
  put email text there). Due dates in the owner's time zone (Tasks stores date only — say so).
- **Brief**: new "To-do" section — overdue + due today (≤ 10), fails independently, counts in the
  AI-lines input only through the existing fence.
- **Evals**: 15+ task cases with the fake transport; injection in task notes → 0 deletes without card.

### C — build notes (builder `s10-tasks`, 2026-11-01)
**Google facts verified 2026-11-01** (developers.google.com pages, "last updated" in brackets):
- REST: `https://tasks.googleapis.com/tasks/v1` — `GET users/@me/lists` (maxResults default and
  max 1000) [2025-03-13]; `GET lists/{l}/tasks` (maxResults default 20, max 100; `dueMin`/`dueMax`
  RFC 3339; `showCompleted` default true — tasks completed in the apps also need `showHidden`;
  `showDeleted`/`showHidden` default false), `POST lists/{l}/tasks`, `PATCH|GET|DELETE
  lists/{l}/tasks/{t}` [2026-10-29, reference index 2025-07-25]. list/get accept `tasks` or
  `tasks.readonly`; insert/patch/delete need `https://www.googleapis.com/auth/tasks`.
- Task: `title` ≤ 1024 chars, `notes` ≤ 8192, `status` needsAction|completed, `completed`
  RFC 3339, `links[]`/`webViewLink`/`assignmentInfo` read-only. **`due` is "an RFC 3339
  timestamp" but only the date is stored; the time is discarded and cannot be read or written via
  the API** [tasks resource, 2026-10-19]. Limits: 20,000 non-hidden tasks per list, 100,000 total
  [insert, 2026-10-29]. Deleting an *assigned* task (from Docs / Chat) also deletes the original
  there [delete, 2025-03-13].
- Quota: "a courtesy limit of 50,000 queries per day" [tasks/limits, 2026-09-03]; no charge is
  listed (no price page found — treat as free, quota only). `@default` as the list id: used in
  Google's own Tasks sample (developers.google.com/google-ads/scripts/docs/examples/google-tasks,
  2025-08-20); the REST reference itself no longer mentions it.

**Decisions**
- **C1 Registration = "registered when Google is linked, answers 'grant access' until the scope
  is granted"** — the `gmail.insert` pattern: the registry is built once per process at start-up,
  before any owner's link exists, and scopes are per owner and change at runtime (Grant). So the
  tools check `can_use_tasks(scopes)` from the stored link on every call (a vault read, no Google
  call). `tasks_list` returns `{status: "permission_needed", message}`; the write tools fail in
  their `Tool.preview` (fail closed: no card, nothing runs) with the same plain message.
- **C2 Ids**: `tasks_list` returns `id = "<list id>:<task id>"` so the write tools need only
  `task_id`; a bare id means the default list (`@default`). Each part must match
  `[A-Za-z0-9_=-]{1,256}` (no `/`, `.`, `%`, `?`: an id can never walk to another URL).
- **C3 Due dates**: sent as `YYYY-MM-DDT00:00:00.000Z`; read as the date part only (never
  shifted by a time zone — it is a date, not an instant). The model passes `YYYY-MM-DD`; a
  date-time is converted into the owner's zone (primary calendar's zone, else
  `JARVIS_USER_TIMEZONE`) and its time is dropped — the card and result say so. "Overdue" and
  "today" are the owner's local dates.
- **C4 Risk**: list R1; add/update/complete R2 (default policy: run, as calendar events without
  guests; a spoken turn still asks); delete R3 (always a card). update/complete/delete `preview`
  fetch the real task for the card (title, due, list, "assigned from Docs/Chat: deleting also
  removes it there"); a failed look-up proposes nothing.
- **C5 Untrusted text**: titles and notes are fenced (`wrap_external`, source "to-do list") and
  the round is tainted (`trusted_output=False`). The list result is fitted under the gateway's
  12,000-char cap by shortening notes (400 → 150 → none) and then the number of tasks (≤ 30).
- **C6 Brief "To-do"**: overdue + due today across the owner's lists (≤ 10 lists, ≤ 100 tasks
  per list, ≤ 10 shown, overdue first), fixed-code GETs through `GoogleConnector.request` like the
  calendar/inbox; own state `ok | not_connected | not_granted | unavailable` (`not_granted` makes
  no Google call). Fails independently and never triggers the section retry (only calendar/inbox
  do). Counted in the `morning_brief.collect` audit detail (`todo=<state> tasks=<n>`). Titles go
  to the optional AI lines inside their own fence (≤ 1,000 chars); the consent text says so.
  Old stored briefs have no `todo` and show no section.
- **C7 Integrations**: `/v1/integrations` gains `google.tasks_granted`; the console shows
  "To-do list — permission needed · Grant" (Grant re-runs `/connect/google`, which already asks
  with `include_granted_scopes`) only when the server says `false`.
- Persona: a separate "To-do list (standing rule)" paragraph; `PERSONA_VERSION` unchanged.

**Go-live (owner, once; the integrator writes the guide)**: Google Cloud Console → APIs &
Services → (1) Library: the Tasks API is switched on by `deploy/cloudrun.sh` step 2
(`tasks.googleapis.com`) — on an older deploy, enable "Google Tasks API" once; (2) OAuth consent
screen → Data Access → Add or remove scopes → add `https://www.googleapis.com/auth/tasks` → Save;
(3) JARVIS → Integrations → "To-do list — permission needed" → **Grant** → keep the Tasks box
ticked. **Not verified live**: Google's behaviour when the scope is requested before step (2) in
Testing mode (expected: still grantable for test users, with the unverified-app screen).

**Built (branch `s10-tasks`)** — `integrations/google.py` (`TASKS_SCOPE` in `OPTIONAL_SCOPES`,
`can_use_tasks`); `tools/tasks_api.py` (ids, due-date rules, `TasksClient` shared with the
brief); `tools/google_tasks.py` (5 tools, previews, result fitting); `tools/tasks_cards.py`;
`tools/setup.py` (registered with the Google tools, `default_tz = JARVIS_USER_TIMEZONE`);
`api/integrations.py` (`google.tasks_granted`); `brief/{models,collect,render,summarize,service}.py`
(To-do section); `core/prompts.py` (`_TODO_RULES` paragraph); console `console.js` (Grant row),
`console-brief.js` (To-do section), `console.css` (2 rules); `deploy/cloudrun.sh` (enables
`tasks.googleapis.com`, prints the optional scope). Evals `evals/tasks/` (19 correctness + 10
injection cases + negative control; in `run_all_mock.py`), brief eval compose c18–c20 and
injection i35–i37 (hostile to-do titles).

**Deviations / details the plan left open**
- The brief's AI input budgets: mail 6,000 → 5,500 chars so calendar + mail + to-do + markers fit
  under the 12,000 cap; the backstop now keeps the closing task line (it can no longer cut inside
  a fence). The AI is skipped only when calendar, inbox AND to-do were all unreadable.
- `due_before` is inclusive ("on or before"); `dueMax` is sent as the next midnight and the result
  is filtered again locally (whatever Google's bound semantics are).
- Brief to-do reads: 1 list read + 1 per list (≤ 10), each via `GoogleConnector.request` (which
  also reads the stored link once per call — ≤ 12 extra Firestore reads per generation, ≤ 6
  generations a day). No Google call and no extra read beyond the link status when not granted.
- The tz look-up for tools is cached 5 minutes per owner (one calendar GET).

**Unverified against live Google (fake transport only)**: clearing a due date with
`PATCH {"due": null}`; `@default` accepted by insert/patch/delete (documented only by Google's
Ads-scripts sample); whether `dueMax` is inclusive (handled either way); Testing-mode consent
before the scope is added to Data Access.

**Reviews**: builder self-review (fixed a double list read on `tasks_list(list=…)`), then a
fresh-context security review (coordinator, 2026-11-02): 0 critical, 1 high, 4 medium, 5 low —
all addressed test-first:

| # | Finding | Outcome |
|---|---|---|
| H1 | Injected notes can complete / rename / add without a card | Not per tool: a gateway rule ("a tainted round turns every reversible write into ASK") lands in the permissions branch. Here: `evals/tasks/cases_tainted_writes.jsonl` (6 cases) gate 0 reversible writes + one card per ordered write once `jarvis.tools.policy.TAINTED_WRITES_ASK = True` exists; until then SKIPPED with the reason, and the report shows all 6 still fail (`tests/test_evals_tasks.py` has a `skipif` test that runs once the marker exists) |
| M2 | `parse_due` OverflowError escaped the gateway | Range-checked before the zone conversion; overflow → `ValueError` |
| M3 | Assigned tasks (Docs / Chat) are seen by others | Verified 2026-11-02: deleting an assigned task deletes the original (tasks.delete reference); assignee edits are flagged in the Doc and anyone with access sees its tasks (support.google.com/docs/answer/12048749). update/complete of an assigned task → preview raises to IRREVERSIBLE + "Assigned from a Google Doc or Chat space: people there can see this change." Subtasks on delete: **not documented by Google** — the delete card counts the task's subtasks (bounded read, fails closed) and says they may be deleted with it |
| M4 | The existing AI consent silently widened to to-do titles | `BriefSettings.ai_consent` (stored briefs default 1); `AI_CONSENT_VERSION = 2` is recorded when the owner confirms the current text; titles go to the AI only under ≥ 2 (`build_input(include_todo=…)`). `SettingsView.ai_todo_consent`; the console consent dialog names to-dos and offers "Include to-dos" (re-confirm) when the server says `false` |
| M5 | `due_by` read one page per list and ≤ 10 lists | Pages followed up to `PAGES_PER_LIST = 3` per list (tokens validated); more lists or pages than the budget → `TodoSection.complete = False` → "at least N" and a partial-read line, never "Nothing due" |
| L6 | No overall deadline | Brief to-do section 20 s (`TODO_TIMEOUT_S`) → unavailable; `tasks_list` 20 s (`LIST_DEADLINE_S`) → plain "took too long" |
| L7 | API switched off showed "reconnect to grant it" | Connector raises `GoogleServiceDisabled` on 403 with reason `accessNotConfigured` / `SERVICE_DISABLED` (reason codes only, no vendor text); the to-do tools say "The to-do service is not switched on for your JARVIS project yet…" |
| L8 | Every reconnect asked for Tasks | `CONNECT_SCOPES` (pre-slice-10 set) by default; Tasks only on `/connect/google?add=tasks` (Grant) or when the link already holds it; `include_granted_scopes` kept |
| L9 | AI ran with nothing to read | Skipped unless calendar or inbox is ok, or consented to-do titles exist |
| L10 | Subtasks on delete | See M3 |

## D — Owner permission rules + passkey for irreversible actions
- **D-D1 Permission rules**: per-owner `permissions/{uid}` mapping tool groups → `allow | ask | deny`.
  Groups (builder finalises from the registry): Calendar changes, Calendar deletes / invites, Email
  drafts, Email sending, To-do changes, To-do deletes, Memory saves, Web search & reading, Documents.
  Defaults = today's behaviour. Irreversible groups offer only Ask first / Never — the server refuses
  `allow` for R3 (the existing `Policy` constructor already refuses; keep it). The gateway builds the
  owner's `Policy` per call from `ToolContext` (cached with rev). `deny` → the tool returns a plain
  "switched off by the owner in Permissions" result; audit records the rule source. Rules never relax
  taint/voice protections (voice turns and tainted rounds still ask).
- **D-D2 Passkey (WebAuthn)** with `webauthn` (py_webauthn, Duo Labs, BSD-3 — verify) and the
  browser's native `navigator.credentials` (no JS library). Register in Approvals → Permissions:
  "Set up a passkey" (Windows Hello / phone fingerprint / security key), `userVerification: required`,
  RP ID = host of `public_base_url`. Once a passkey exists, approving an IRREVERSIBLE card needs a
  fresh assertion whose challenge is bound to that approval id + its arguments hash; single-use,
  2-minute expiry, sign-count checked. Store `passkeys/{uid}` (credential id, public key, sign count,
  label, created) and `webauthn_challenges/{id}` (expiry). Removing the last passkey needs a passkey
  assertion OR a Google sign-in fresher than 5 minutes (recovery path; the console sends the owner
  through sign-in with `max_age`). Switch "Require passkey for irreversible actions" (on once a
  passkey exists; turning it off needs a passkey). Voice still never approves.
- **Console**: Approvals panel gains a collapsed "⚙ Permissions" section (one row summary), group
  rows with segmented Allow / Ask first / Never, passkey list + add/remove; approval cards for R3 show
  "Approve with passkey".
- **Evals**: policy matrix (every group × effect × risk; R3 allow refused), deny path, passkey
  ceremony with a software authenticator in tests (no network), replay/expired/wrong-approval
  challenges refused, R3 approve without assertion refused when required.

### D — builder notes (branch `s10-perm`)
- **Library, verified 2026-11-01**: `webauthn` 3.0.1 = latest on PyPI (`pip index versions`),
  Duo Labs, `License-Expression: BSD-3-Clause` (dist-info + LICENSE), Python ≥ 3.10. API used:
  `generate_registration_options`, `verify_registration_response(require_user_verification=True)`,
  `generate_authentication_options(user_verification=REQUIRED)`,
  `verify_authentication_response(credential_current_sign_count=…, require_user_verification=True)`
  (checks type, challenge, origin, RP ID hash, UP, UV, signature, and refuses a counter that does
  not grow unless both are 0). Only `jarvis.permissions.ceremony` imports it. pypi.org / GitHub
  pages could not be fetched from the build sandbox; facts are from the PyPI index and the
  installed distribution.
- **Groups (12)**, matched by tool-name pattern + effective risk: Calendar — look / add & change /
  delete & invite (R3: `calendar_delete_event`, any `calendar_*` at R3); Email — search & read
  (`gmail_*` R1) / drafts / send (R3: `gmail_send`, `send_message`, `gmail_*` R3); To-do — read &
  change (`tasks_*`, `task_*`, `list_tasks`, `create_reminder`) / delete (R3: `task_delete`, `task_*`
  / `tasks_*` R3); Memory — save / forget (R3); Web (`web_*`); Documents (`doc_*`, `docs_*`).
  Unknown tools keep the risk default. A call in two groups gets the strictest choice. "Never" on
  a domain's base group also stops its irreversible calls (an invitation is also an event).
- **Storage** (`Docs` port): `{prefix}permissions/{uid}` (groups, require_passkey, rev),
  `{prefix}passkeys/{uid}` (≤ 10 public keys + sign counts; one doc → one transaction),
  `{prefix}webauthn_challenges/{id}` (2 min; taken = read+deleted in one transaction before any
  check; expired ones swept per owner, ≤ 10 live). Optional: a Firestore TTL policy on
  `expires_at` for challenges abandoned forever.
- **Gateway**: per-call policy = configured rules + the owner's (cache 15 s, refreshed at once on a
  change; last value on a read error; none → fail closed; a call with no owner in its scope → fail
  closed). Owner rules are appended, so DENY wins, R3 always asks, and the spoken / tainted
  tightening still applies after them. **Tainted rounds** (review M2): every REVERSIBLE write in a
  round whose model saw other people's text becomes an approval card (`policy.TAINTED_WRITES_ASK`,
  an R2 card — no passkey); outside a turn nothing is tainted. `memory_save` now relies on this
  rule instead of raising itself to R3 (memory poisoning evals: still 0 silent saves). Deny result:
  "switched off by the owner in Permissions (Email: Send email — Never). Do not try to do it
  another way…"; audit detail `policy:owner:<group>`. `PendingAction.tool_risk` records the call's
  own risk (the gate's `risk` stays IRREVERSIBLE for every card); a card without it counts as R3.
- **Approving** (review H1): the gateway looks at the call again before spending the token. When it
  can now do more than its card said (an event gained guests) or its card would read differently,
  the old card is withdrawn and a new one proposed (new id, risk, text) — nothing runs, the reply
  says so and carries the new card. The gate's matcher (`guardrails.same_card`) also compares the
  card text and `tool_risk`, so an identical new proposal never reuses an older, milder card. Then
  the gateway's approval guard (`PermissionsService.check_approval`, set on the gateway at start-up)
  checks the passkey on the card about to run — on the brain's approve path, not only the route —
  and its note ("passkey 1a2b3c4d") goes into the `executing` audit entry.
- **Passkey rules**: passkeys need a relying party AND Google sign-in. In force = switched on AND
  ≥ 1 passkey, or the stored passkeys are unreadable (fail closed; read fresh, never cached). The
  first passkey switches it on. Approving a card whose call is R3 needs `passkey: {challenge_id,
  credential}` on `/v1/approvals/{id}/approve`; the challenge is 32 random bytes + sha256(uid,
  approval id, sha256 of the exact arguments, scope, tool), so the authenticator signs what it
  approves. Decline never needs one. **No sign-in shortcuts** (review M3): removing a passkey,
  switching the requirement off, adding a second passkey and cancelling a reset need a passkey
  check made for exactly that. **The first passkey** (review M4) needs a cookie session with a
  re-sign-in < 5 min old; bearer callers are refused. Registration options handed out before any
  passkey existed can only add the FIRST one (checked in the add transaction). Every change, every
  refused check (a counter going backwards is called out as a possible clone) and every reset step
  is in the audit chain (`agent: owner`, tools `permissions` / `passkey`).
- **Recovery** (review M3): `/auth/login?reauth=1` stores its start time and sends `max_age=0`;
  only that flow stamps `auth_at` in the signed cookie — Google's `auth_time` when sent (older than
  the start → `/?reauth=stale`, nothing stamped), else the moment it completed. A fresh re-sign-in
  can only START a reset of ALL passkeys: it takes effect 24 h later (carried out lazily on the next
  read), shows a banner at the top of the Approvals panel (opened at boot while pending), puts a
  notice in the owner's Gmail inbox when the link allows `messages.insert` (the brief's inbox-copy
  path), and any passkey cancels it. The next passkey after a reset is marked "set up after a reset
  by Google sign-in" in the list. Changing `JARVIS_PUBLIC_BASE_URL` (RP ID) makes passkeys unusable
  → the same reset.
- **Modes**: no `JARVIS_PUBLIC_BASE_URL`, an IP address, or token auth mode → passkeys unavailable
  (409 `passkeys_unavailable`), approvals as before. Bearer token (CLI, scripts): an R3 approve while
  a passkey is required → 403 `passkey_required` "…Approve it in the JARVIS console in your browser
  (the command line can't use passkeys)". Dev on `http://localhost:<port>` with Google sign-in works.
- **Challenges**: at most 10 live per owner AND purpose, so asking for many of one kind never pushes
  out a waiting approval's check (plus the per-owner rate limit, 20 ceremonies a minute).
- **Follow-up**: "Approve all (n)" for the R2 cards a tainted round makes (never R3) — not built;
  each approval still narrates once.
- **Not verified live**: that Google honours `max_age=0` and returns `auth_time` (OIDC says it
  must; without it the window starts when sign-in completes — which now only allows a first
  passkey or a 24-hour, notified, cancellable reset). Real Windows Hello / phone authenticators
  (tested with py_webauthn + a software authenticator and Chromium's CDP virtual authenticator).

## E — Document reading
- **D-E1 Server-side text extraction**, model-agnostic: `pypdf` (BSD-3) for PDF, `python-docx`
  (MIT) for DOCX, UTF-8 (with BOM/latin-1 fallback) for TXT/MD/CSV. No OCR (scanned PDF → "no text
  found"). Limits: ≤ 10 MB per file, ≤ 3 files per message, ≤ 300 pages, ≤ 300,000 characters kept,
  extraction in a worker thread with a time budget; DOCX zip checks (entry count, total uncompressed
  ≤ 50 MB, ratio) against zip bombs; PDF encrypted → plain message. Route-specific body cap for the
  upload route only (app-wide 2.1 MB cap stays everywhere else).
- **Store**: `attachments/{id}` (owner, session, name, type, pages, chars, created) + chunk docs
  ≈ 4,000 chars each (Firestore 1 MiB doc limit); deleted with the conversation; never sent to
  training brains (like memory).
- **Model view**: the turn carries a short note "[Attached: name · N pages · ~W words · id]" plus the
  first ≤ 2,000 chars, fenced. Tools (R1): `doc_read(doc_id, part)` (≤ 8,000 chars per call) and
  `doc_search(doc_id, query)` (BM25 over chunks, reuse `jarvis.recall` ranking) — keeps each reply's
  cost bounded instead of re-sending the whole document every turn. Content fenced, round tainted.
- **Console**: paperclip button + drag-and-drop in the composer, chips with name/size and remove,
  plain errors (too big, unsupported, no text found, encrypted).
- **Evals**: extraction fixtures (PDF, DOCX, TXT, CSV, encrypted, scanned, zip bomb, huge), recall
  from a 100-page doc via `doc_search`, injection inside a document → 0 unconfirmed actions.

## Owner steps after merge (go-live guide "THIS TIME")
1. Merge the PR. 2. Tavily sign-up → copy key → Cloud Shell `git pull && bash deploy/cloudrun.sh`
(asks only for the new key). 3. Google consent screen → Data Access → add the Tasks scope →
Integrations → Grant. 4. Approvals → Permissions → Set up a passkey. 5. Optional: run
`bash deploy/run-real-evals.sh` (type YES after reading the ₹ estimate).

## Risks
- Web content and documents are the main prompt-injection surface → fences, taint, URL allow-list for
  `web_read`, R3 still needs approval (+ passkey). Search queries could leak private data to Tavily →
  query guard + persona rule.
- Upload parsing of hostile files → limits, time budget, no execution, no storage of the raw file.
- WebAuthn misconfiguration could lock the owner out of R3 approvals → recovery via fresh Google
  sign-in; feature off until a passkey is registered.
- Firestore costs: documents add writes per upload (≈ 75 chunk writes for a 300k-char file).

## Deviations
- Web search through Tavily instead of the architecture's generic "browser automation / search MCP":
  first-party adapter behind the same tool contract (as slice 6 did for Google).
- Documents are text-extracted, not passed as native PDF blocks (model-agnostic; bounded cost).
- **E builder notes (`s10-docs`)**. Verified from the installed wheels' metadata (PyPI JSON was not
  reachable from the builder; ecosyste.ms confirms python-docx 1.2.0 is the latest, 2025-06-16):
  pypdf 6.21.4 `BSD-3-Clause`, python-docx 1.2.0 `MIT` (deps lxml BSD-3, typing_extensions PSF);
  python-docx parses with `resolve_entities=False`; pypdf 6.x caps decompression (75 MB per stream)
  and fixed many loop/DoS bugs through 6.14 (changelog) → `pypdf>=6.21,<7`, `python-docx>=1.2,<2`
  in pyproject only (integration runs `make lock`). Deviations: (1) the upload is the raw file body
  with the name in `X-Jarvis-Filename`, not multipart — python-multipart is not installed (shared
  venvs, lock) and a raw body needs no parser, streams through the existing `read_capped`, and the
  body cap is exact; (2) chunks are cut by their JSON-escaped size (~4,000 chars of Latin text,
  ~700 of Malayalam) so a `doc_read` part fits the gateway's 12,000-char cut in any script
  (integration review M2: the gateway now sends real Unicode, so ~4,000 in any script);
  (3) text files try cp1252 before latin-1 (Windows "ANSI" smart quotes); (4) an upload waits
  unbound ("waiting") until sent, ≤ 10 per owner, swept after 24 h at the next upload or
  conversation delete; it is bound to the conversation and turn atomically on send; (5) a PDF
  with only an owner password opens (as in any viewer); a user password is refused.

## Reviews
(filled in after the fresh-context reviews)
- **E security review (0 critical, 2 high, 2 medium, 4 low) — fixed on `s10-docs`.** H1/H2: text
  extraction now runs in a child process per upload (`documents/isolation.py` + `worker.py`:
  `python -I`, no inherited environment, the child sets RLIMIT_CPU 30 s and RLIMIT_AS 300 MB on
  itself before reading input — not `preexec_fn`, unsafe in a threaded server — killed at 45 s
  wall clock or on cancellation, one at a time, others queue ≤ 50 s); `normalise` is linear (no
  `[ \t]+\n`); tables are read from their XML with the deadline checked per row; DOCX XML is
  capped at 10 MB unpacked; MemoryError → "too complex". All review probe files now end in ≤ 10 s
  with the parent's RSS flat (≤ 42 MB); the worst child peaked at 285 MB RSS — with a 512 MiB
  instance, parent + child must fit: watch it, or lower `MEMORY_LIMIT_BYTES` / raise memory.
  M3: the scheduler tick sweeps unsent uploads (hourly, never raises). M4: ranking runs in a
  thread; a search without an id covers the 3 most recent files. LOW: the slot is released and
  the child killed on every exit; a file binding is undone when the turn can't be stored; the
  upload body has a 60 s overall deadline (408). Not changed: the file name stays outside the
  fence, sanitised to one plain line with no brackets, quotes or angle brackets (the header
  must stay readable; the content is fenced and the round is tainted either way).

### Integration review (fresh context on `slice10-phase2-tools`, 2026-11-02): 0 critical, 0 high, 3 medium, 5 low — fixed on `s10-fix`
| # | Finding | Fix |
|---|---|---|
| M1 | A tool round was saved with a plain `store.save`: a `SessionConflict` after an R2 write (to-do, event, draft) ended the turn with 409, the write existed only in the audit log, and a retry did it twice | `core/rounds.py` (`Rounds`, brain.py now 759 lines): until a non-R1 call has run, rounds save plainly (a conflict is still the 409 "message kept"); from the first executed write, that round and every later save of the message (reply included) go through `record_after_action` — reload, re-append once, never raise. If even that fails the loop stops (no more tools in a conversation that can't record them), the reply says what was done ("Done, Sir: Remind at 5pm: …") and the response adds "It was done, but … could not record it here". Known limit: after such a reload the other window's message is the latest owner message, so that reply's source chips and per-message web counters start from it. |
| M2 | Chunks were sized as if the gateway escaped non-ASCII (6 per Malayalam letter): a 300k-char Malayalam file made 358 chunks of ~840 chars; `read_part` re-read every chunk for each part | `chunking._cost`: 1 per non-ASCII character (ASCII control escapes kept; matches `serialise`, `ensure_ascii=False`) → 69 chunks for Malayalam and Latin alike, a part ≈ 8,750 serialised chars. `AttachmentStore.part()` reads only the part's chunks (cache slice, else 2 gets; never cached). Also: the fenced text of a part / search hit is cut after fence-like text is defused (`PART_TEXT_LIMIT` 10,000, `EXCERPT_LIMIT` 3,000) — a file made of `<<END>>` markers grew past the 12,000 cut and lost its closing fence. |
| M3 | `owner_index` skipped user turns with blocks, so a message with an attached file shared the previous message's web counters (3 searches earlier → 0 now) and its typed link was not readable | `ledger.is_owner_message`: a user turn with no tool-result block (typed, spoken, or with files) is an owner message; typed links come from its `content` only, never the file's note. Test: "summarise this PDF and check online" gets its own 3 searches. |
| L4 | No cap on approval cards per message; every proposal read up to 100 approval docs | `tools/budget.py` `turn_budget()` around the tool loop: ≤ 5 NEW cards per owner message (a duplicate of a waiting card is free), then a plain "Too many approvals in one request … nothing was proposed" (audited `denied`, nothing stored). The duplicate look-up is `ApprovalStore.pending_in(scope)` — Firestore equality query on `scope` (automatic single-field index). |
| L5 | No per-message cap on doc tools; `CACHE_DOCS = 4` thrashed | ≤ 6 `doc_read`/`doc_search` calls per owner message (`take_doc_call`, plain "Document limit for this request reached"); `CACHE_DOCS = MAX_DOC_CALLS` (6) and parts never enter the cache. |
| L6 | `evals/web/run.py` without `--mock` called live Claude with no estimate or spend stop | `realrun.guard.guarded()` (true only while the runner's guard wraps the provider) + `refuse_unguarded()`: the web suite exits 2 before building anything unless started by the guarded runner. The other new evals (tasks, documents, permissions) are mock-only. |
| L7 | Web "Ask first": approving a > 120-char query failed (outside a turn counted as tainted) with a misleading message and the card stayed pending | `_check_search` applies the 120-char cap only in a tainted round (`tainted_round()`, the gateway's explicit check); an approved card runs as shown. |
| L8 | `run-real-evals.sh` installed from unpinned PyPI into the venv that later holds the key | `pip install --require-hashes -r requirements.lock`, then `--no-build-isolation --no-deps "$REPO"` (as the Dockerfile); the install stamp covers the lock too. |
| + | Documents on "Never" still took uploads and sent their 2,000-char preview to the model | `DocumentService.rules` (the owner's rules, wired in `create_app`): upload → 403 `documents_off` "Documents are switched off in Permissions." (checked before the body is read); send → 422 with the same words, nothing bound, no empty conversation. Unreadable permissions fail closed (503 / 422). |

## Integration (2026-11-02, branch `slice10-phase2-tools`)
Merged in order with merge commits: `s10-web`, `s10-tasks`, `s10-perm`, `s10-docs`, then
`origin/main` (PR #14 import-timing bound, PR #15 browser rate limit). Every branch's behaviour
kept; the shared files (`tools/setup.py`, `api/app.py`, `api/routes.py`, `api/console.py`,
`core/models.py`, `core/prompts.py`, `tools/gateway.py`, `tools/external.py`, `tools/taint.py`,
console HTML/JS, `evals/run_all_mock.py`) carry all four workstreams. Changes made here:
- **brain.py size guard (≤ 800 lines)**: the approve / decline machinery (`_Decision`,
  `_record_exchange`, `_approved`, `_declined`) moved unchanged to `core/brain_decisions.py`;
  brain.py is ~740 lines. A changed card on approve (D) now flows through A's compare-and-set
  save (`record_after_action`); the "could not record" note says nothing was done in that case.
- **Owner turn + files (A × E)**: `documents.service.save_owner_turn` stores through
  `save_owner_message`, so a conversation changed in another window is `MessageNotSaved` (409,
  send again) and the files are unbound, still waiting.
- **Fences (B × C/E)**: every to-do, brief and document path fences with `wrap_external` (nonce
  ids); tests and evals count closes with `FENCE_END` / `FENCE_REMOVED`, the documents eval
  matches a needle to the close with its own id. `FENCE_PREFIX` (E) is the open marker's start.
- **Tainted writes (C × D)**: with `policy.TAINTED_WRITES_ASK` the to-do tainted-writes suite runs
  and passes (0 reversible side effects; it was SKIPPED on `s10-tasks`). Its injection negative
  control now also switches that rule off (else the R2-downgraded delete still waits as a card),
  and the tainted suite has its own negative control (rule off → all 6 cases fail).
- **Permission groups (D × B/C/E)**: `tests/test_permissions_tool_names.py` builds the real web,
  to-do and document tools through `build_gateway` and asserts each lands in its group (`web`;
  `todo_change`, plus `todo_delete` for `task_delete`; `documents`).
- **Persona**: `PERSONA_VERSION` p4.0 → p4.1, once; the three paragraphs stay separate, in the
  order web, to-do, attached files.
- **Documents memory cap**: `MEMORY_LIMIT_BYTES` 300 MB → 200 MB (RLIMIT_AS of the extraction
  child; the 512 MiB instance also runs the server). Ordinary files (300-page PDF, long DOCX)
  still extract; the review's heavy probe now ends as "too complex".
- **Lock**: `make lock` (pip-compile 7.6.2, Python 3.12, existing pins kept) added cbor2,
  lxml, pyopenssl, pypdf 6.21.4, python-docx 1.2.0, webauthn 3.0.1; hashed install verified.
- **Browser**: the permissions test server (its own process) gets PR #15's raised per-IP limit.

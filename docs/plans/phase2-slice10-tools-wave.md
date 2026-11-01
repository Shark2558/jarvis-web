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

## Reviews
(filled in after the fresh-context reviews)

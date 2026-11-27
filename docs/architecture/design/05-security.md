Version v6.5.0 · 27 Nov 2026, 20:05 IST · Release R18 · Status: Current · Owner: 🛠 Mark XXV

# 05 · Security architecture

**In plain words.** Only you get in: your Google account must be on JARVIS's list, and anything
final (sending, paying, deleting for good) waits for your Approve, and for your passkey once you
have one. Machines that call JARVIS (the clock, Telegram, your phone, your laptop) each prove who
they are on every call, in their own way. Every action passes one checkpoint, the tool gateway,
and is written into a record that shows if anyone changes it. Words from other people (mail, web
pages, documents) are treated as information, never as orders. Keys live only in Google's Secret
Manager. The end of this chapter lists what is still not fully protected.

**Phone calls (R18, built, not yet deployed)** follow the same rules, made stricter: every call
waits for your tap on its card, a number JARVIS has never called also needs your passkey, and
Telegram can never approve a call. Your approval can be used for one call only, within 10
minutes. During the call, the other person's words are only information: JARVIS will not read out
codes or account numbers, and will not agree to pay. Section 8 has the details.

Figure 16 (`../diagrams/16-trust-boundaries.png`, in chapter 02) shows the boundaries; the guide's
Figure 5 (`../diagrams/05-approvals-passkeys.png`) shows a card and a passkey.

## 1. Authentication: who may call JARVIS

| Caller | How it proves who it is | Checked in | Failure answer |
|---|---|---|---|
| The owner, in the console or the phone app | Google sign-in (OpenID Connect via Authlib); the verified e-mail must be on `JARVIS_OWNER_EMAILS` (Google authenticates, the list authorises); then a signed session cookie `jarvis_session` (12 hours, SameSite Lax, HTTPS only); cookie-authenticated writes must carry `X-Requested-With: JARVIS` (no CORS headers are served) | `src/jarvis/api/auth.py`, `src/jarvis/api/app.py:_install_google_sign_in` | 401; `CSRFRejected` for a write without the header |
| The owner, re-proving himself | `/auth/login?reauth=1` makes Google ask again (`max_age=0`, optional `auth_time` check); only that stamps `auth_at`, which opens a 5-minute window to add a first passkey or start the passkey reset | `src/jarvis/api/auth.py` docstring | `/?reauth=stale` |
| The owner, for irreversible actions | A passkey (WebAuthn, py_webauthn 3.0.1): RP ID and origin from `JARVIS_PUBLIC_BASE_URL`, user verification always required, sign counter must grow, challenge expires in 2 minutes, each assertion bound to one card or one purpose and target; at most 10 passkeys | `src/jarvis/permissions/ceremony.py`, `src/jarvis/permissions/passkeys.py`, `src/jarvis/permissions/service.py:approval_binding`, `purpose_binding` | `PasskeyRequired`, `CeremonyFailed` (plain words, never library text) |
| The terminal, scripts, evals | Bearer token `JARVIS_API_TOKEN`, compared in constant time | `src/jarvis/api/auth.py` | 401 |
| The phone app's own requests | `X-Jarvis-Phone` header: ECDSA P-256 / SHA-256 over a fixed signing string, key generated in the phone's secure hardware at linking (an 8-character code, 10 minutes, once, 5 tries); checks in order: route, no query, no cookie, header shape, flood (60 a minute per client), linked device, clock skew, body cap, nonce, signature, rate (30 a minute per phone) | `src/jarvis/phone/door.py`, `src/jarvis/mobile/contract.py` | Bare 401 (404 for a route, 429 for flood or rate), logged by check name, never audited |
| The app lock | After 5 minutes away the phone app asks for the passkey; bound to the phone by a signed `r7_dev` cookie | `src/jarvis/phone/applock.py` | 503 on an unreadable check (never opens) |
| Cloud Scheduler | A Google-signed OIDC token: RS256 only, Google's JWKS, issuer, audience equal to the exact URL being called, e-mail equal to `jarvis-scheduler`'s and verified, 60 s skew | `src/jarvis/api/scheduler_auth.py` | The same bare 401 for every failure |
| Telegram | `X-Telegram-Bot-Api-Secret-Token`, constant-time compare; then the paired owner's user and chat id (pairing by an 8-character code, 10 minutes) | `src/jarvis/api/telegram.py`, `src/jarvis/telegram/pairing.py` | Bare 401; anyone else gets no reply and is audited as `telegram_rejected` (at most 20 an hour, then logged only: `src/jarvis/telegram/service.py:REJECTED_AUDIT_PER_HOUR`) |
| The home bridge (both directions) | `X-Jarvis-Home` header: HMAC-SHA256 with direction-specific keys derived from a 32-byte link seed (`jarvis/home/up/v1`, `jarvis/home/down/v1`), a 16-byte nonce remembered 5 minutes, a ±60 s window; responses signed and bound to the request | `src/jarvis/home/signing.py` (shared by cloud and bridge) | Refused before any parsing |
| The laptop brain | A bearer key of at least 16 characters at the Caddy gate; only `https://<machine>.<tailnet>.ts.net` addresses are accepted | `deploy/local-brain/Caddyfile`, `src/jarvis/offline/config.py` | Caddy refuses; JARVIS reports "laptop didn't answer" |
| GitHub Actions (deploy) | Workload Identity Federation: this repository's numeric id, `refs/heads/main`, a push or manual run, `ci.yml` on `main`, a GitHub-hosted runner; impersonates `jarvis-deployer` | `deploy/cloudrun.sh:setup_autodeploy` | Google refuses the token exchange |
| The call desk on the laptop (R18) | Linked once with an 8-character code (10 minutes, one use); then every upgrade of its WebSocket carries `X-Jarvis-Home`, signed with keys derived from the desk's 32-byte seed exactly as the home bridge signs, checked before the socket opens | `src/jarvis/calls/hub.py:DeskDoorService`, `src/jarvis/api/calls_ws.py:CallSockets` | Closed 4401 before the handshake completes, logged by check name only |
| The owner's live call view (R18) | His bearer, or his session cookie from JARVIS's own page; in token mode a one-use ticket of 30 seconds for that call | `src/jarvis/api/calls_routes.py:LiveTickets` | Closed 4401; a call not his or not running: 4404 |

**Lost passkey.** A fresh Google sign-in can only *start* removing all passkeys; it takes effect
24 hours later (`src/jarvis/permissions/service.py:RESET_DELAY`), shows in the console and puts a
notice in the owner's Gmail inbox, so a stolen Google session cannot quietly remove protection.

## 2. Authorisation and the tool gateway

### 2.1 Risk tiers and default effects

| Tier | Code | Default | Becomes a card when | Passkey | Telegram button | Approve all |
|---|---|---|---|---|---|---|
| R1 read | `ActionRisk.READ_ONLY` | runs | the tool asks for this call (`Tool.ask_when`) | no | — | — |
| R2 reversible | `ActionRisk.REVERSIBLE` | runs | spoken turn; tainted round; owner rule "Ask first"; the 11th undo-able delete in one message | no | yes, if short enough to judge | yes, unless a draft to an untyped address, a memory write or in `NO_BULK_TOOLS` |
| R3 irreversible | `ActionRisk.IRREVERSIBLE` | always a card | — | yes, once passkeys are in force | never (`R3_REFUSAL`) | never |

Sources: `src/jarvis/core/guardrails.py`, `src/jarvis/tools/policy.py`,
`src/jarvis/tools/gateway.py:_tightened`, `src/jarvis/telegram/service.py`. There is no R0 class
(chapter 01, P3). Two tools are never approved from Telegram, whatever their tier and however
short their card: `vitals_drill_start` and, from R18, `calls_place`
(`src/jarvis/core/guardrails.py:CONSOLE_ONLY_TOOLS`); a call card can also be approved in the
phone app (section 8.1).

### 2.2 Policy

- Rules are ordered `(tool pattern, effect, argument constraints)`; **DENY always wins**; an R3
  group can never be set to Allow (`src/jarvis/tools/policy.py:Policy`).
- The owner's own rules (Approvals → Permissions; `permissions` collection) are appended per call
  (`Gateway._policy_for`); an owner's Allow never relaxes a spoken turn or a tainted round. If his
  rules can't be read, or the call names no owner, nothing runs (fail closed).
- A look-up that names another permission row (`Preview.also`, e.g. a WhatsApp draft by name
  reads Contacts) gets that row's decision too: its "Never" refuses.

### 2.3 Confirmation tokens

A card is a `PendingAction` (`src/jarvis/core/guardrails.py`): an id from
`secrets.token_urlsafe(12)`, the tool and arguments, the summary the owner reads, the scope (owner
and conversation), the call's own risk, why it asks, and whether its round was outside or spoken;
it expires in 10 minutes. Approving presents the id as the token: the store consumes it
atomically only if the card still matches (`same_card`); otherwise `ConfirmationInvalid` and
nothing runs. Before the token is spent the gateway re-checks the call: if it can now do more or
reads differently, the card is withdrawn and re-proposed (`Gateway._before_consuming`). The
passkey guard sees the card before the token is spent, so a refused passkey leaves the card
waiting. One message may propose at most 5 new cards (`src/jarvis/tools/budget.py:MAX_NEW_CARDS`).

### 2.4 Taint and provenance

A round is **tainted** when any untrusted tool result is in the window the model saw
(`src/jarvis/tools/taint.py:untrusted_seen`): mail, web, documents, someone else's event or
to-do, an error, an attached file's fenced text. In a tainted round every write becomes a card
(`TAINTED_WRITES_ASK`), and memory writes ask. A result is **trusted** only when a tool declared
`may_vouch` (calendar, reminders, to-dos) finds every item owner-authored
(`src/jarvis/tools/provenance.py:vouch`); the flag travels beside the text, never in it, so the
model can't set it. What JARVIS writes from outside content is **marked outside**
(`mark_outside`) and taints the next look-up. A spoken turn makes writes ask too (someone else in
the room may have spoken), except for tools marked `spoken_ok` when no outside content is present.

### 2.5 Rate limits and caps

| Limit | Value | Where |
|---|---|---|
| API requests per client | 120 a minute (token bucket, in memory, at most 10,000 clients tracked) on `/v1`, `/auth`, `/connect`, `/internal` | `src/jarvis/api/ratelimit.py`, `src/jarvis/config.py` `rate_limit_per_minute` |
| Request body | 2,100,000 bytes by default; tighter or larger per route (attachments, vault upload, bridge webhook 128 KB, phone inbox, wardrobe restore) | `src/jarvis/api/body.py:MAX_BODY_BYTES`, `src/jarvis/api/app.py:_install_middleware` |
| Phone door | 60 a minute per client before any store is read; 30 a minute per phone after the signature | `src/jarvis/phone/door.py` |
| Tool rounds per turn | 6 | `src/jarvis/config.py` `tool_max_rounds` |
| New cards per message | 5 | `src/jarvis/tools/budget.py:MAX_NEW_CARDS` |
| Undo-able deletes per message without a card | 10 | `src/jarvis/tools/budget.py:MAX_FREE_DELETES` |
| A tool result to the model | 12,000 characters | `src/jarvis/tools/gateway.py:MAX_RESULT_CHARS` |
| Calls (R18) | 10 a day, 2 a day to one number, 3 new numbers a day, quiet hours 21:00–08:00 IST; audio 150 frames a second on the desk's socket; "Tell JARVIS" 10 a minute; phone events 40 a minute per phone | section 8.4 |

## 3. Secrets

- **Storage.** Only in Secret Manager, one grant per secret for `jarvis-run` (chapter 02, 2.3);
  GitHub holds no Google key (Workload Identity Federation). The one GitHub secret is the optional
  `JARVIS_ANTHROPIC_API_KEY` for the main-only eval gate (`.github/workflows/ci.yml`).
- **In the process.** Held as `SecretStr` (`src/jarvis/config.py`, 11 fields); start-up refuses a
  session secret under 32 characters and a malformed token key.
- **Never logged.** Tool errors reach the model and the audit as a fixed sentence plus a redacted
  detail (`src/jarvis/tools/gateway.py:_safe_detail` removes bearer tokens, `sk-` keys and
  e-mail addresses); the deploy scripts pass tokens to `curl` only on standard input, never on a
  command line (`deploy/cloudrun.sh:telegram_webhook`).
- **Never committed.** The repository is public. The build book's scrubber
  (`src/jarvis/buildbook/gen/scrub.py`) fails CI on a secret shape or personal data in the book;
  `scripts/arch_coverage.py` runs the same scan over `docs/architecture/`, this document included.

## 4. Audit

Every tool call, whatever its outcome (executed, awaiting confirmation, denied, declined, error,
confirmation invalid), appends one entry (chapter 01, P9): hash-chained, create-only, with its head
moved in the same transaction, and `(seq, hash)` written to Cloud Logging as an outside anchor
(`src/jarvis/storage/audit.py`). An approved irreversible call's intent is audited before it runs,
and nothing runs if that write fails (`Gateway._audit_intent`). The console's audit view verifies
the window it shows (`AuditTail.verified`); `verify_all` walks the whole chain. Permission
changes, the No-AI switch and Drive folder choices are audited in the same chain
(`tests/test_permissions_api.py`, `src/jarvis/offline/mode.py`, `tests/test_drive_api.py`).

## 5. Browser and transport hardening

The console's content security policy allows scripts only from JARVIS itself
(`script-src 'self' 'wasm-unsafe-eval'`, the second part only for the wake word's WebAssembly;
`src/jarvis/api/console.py:CONSOLE_CSP`); server text is always set as text, never as HTML.
Every response carries `X-Content-Type-Options: nosniff` and, outside dev, HSTS for a year
(`src/jarvis/api/app.py:_install_middleware`). Vendored libraries are served by JARVIS and pinned
by SHA-256 (the vision files only if their manifest's hash matches). The container runs as a
non-root user; the home bridge runs read-only with no capabilities.

## 6. Threat model summary

In the "Code" column, paths are under `src/jarvis/` unless they start with `deploy/`, `.github/`
or name a top-level file.

| # | Threat | Mitigation as built | Code | Residual |
|---|---|---|---|---|
| T1 | Prompt injection through mail, web, documents or contacts | Results prefixed as untrusted and fenced; taint turns writes into cards; R3 always a card; Telegram never approves R3 | `tools/gateway.py`, `tools/external.py`, `tools/taint.py` | The owner can still approve a card that injected text shaped; reads still happen |
| T2 | A stolen session cookie | 12-hour cookie; R3 needs a passkey once one exists; "Sign out everywhere"; vault and privacy actions need a passkey or a fresh sign-in | `api/auth.py`, `permissions/service.py` | Before a passkey is added, a stolen cookie can approve R3 cards |
| T3 | Cross-site request forgery | Custom header on every cookie write; SameSite Lax; no CORS | `api/auth.py` | — |
| T4 | Script injection in the console | Strict CSP; text only | `api/console.py` | — |
| T5 | Replay of a bridge or phone request | Nonce plus time window; signatures cover method, path and body hash | `home/signing.py`, `phone/door.py` | Nonce stores are in process: correct only with one instance |
| T6 | A forged clock call | OIDC with the exact audience and the clock's e-mail | `api/scheduler_auth.py` | — |
| T7 | Someone else messaging the bot | Webhook secret, then the paired owner only; private reads off by default on Telegram | `api/telegram.py`, `telegram/service.py` | Telegram stores the chats; not end-to-end encrypted |
| T8 | Private data reaching a brain that trains | `tools_allowed`, history cutoff, memory gate, no pictures | `llm/brains.py`, `core/brain.py`, `recall/gate.py` | Anthropic sees the window, notes and tool results by design |
| T9 | Supply chain | `requirements.lock` hash-checked; actions pinned by commit SHA and updated by reviewed Dependabot pull requests; vendored files pinned by hash | `Dockerfile`, `.github/workflows/*.yml`, `.github/dependabot.yml` | Dependabot watches only GitHub Actions, not Python packages |
| T10 | A malicious change merged to `main` | Pull requests and CI; deploy only from `main` | `deploy/cloudrun.sh` (comment on step 7) | Anyone who can change `main` can ship code that runs as `jarvis-run`; the owner's GitHub account needs 2-step sign-in |
| T11 | A reader of the Firestore project | Sealing for the most private collections (chapter 04) | `keyring.py` | Conversations, memory, attachment text and the audit are not sealed |
| T12 | Runaway spend | Monthly limit before every paid call; free-allowance stops at 90 %; ₹1 budget alert; try-on cap and its own budget alert | `billing/`, `quota/ledger.py`, `deploy/cloudrun.sh` | No JARVIS limit until the owner sets one; the budget alert warns, it doesn't stop |
| T13 | Denial of service | Rate limits, body caps, flood limits, `--max-instances 1` bounds the bill | `api/ratelimit.py`, `api/body.py` | One instance is also one point of failure |
| T14 | The laptop compromised | The bridge runs hardened; only its signed door is funnelled; the cloud never trusts a picture or a name it didn't ask for | `deploy/home/docker-compose.yml`, `home/` | The laptop holds the camera recordings and face library |
| T15 | Lost or stolen phone | The app lock; unlink from the laptop; the phone's door can't read conversations, the vault or mail or call a tool; from R18 its Approve of a call card asks for the phone's unlock, and a never-called number or a passkey in force sends it to the console | `phone/`, `mobile/ports.py`, `calls/join.py` | Chrome's own cookie on the phone until "Sign out everywhere"; a stolen unlocked phone can approve a call to a number already called while no passkey is required |
| T16 | A call placed without the owner (R18) | R3 card every time; a one-use 10-minute grant bound to the number and the card's content, spent for one call id just before the dial; passkey for a never-called number; never from Telegram; grants in memory, gone at a restart | `calls/approvals.py`, `core/guardrails.py`, `phone/calls.py` | Before a passkey is added, a stolen cookie can approve a call to a number already called (as T2) |
| T17 | The other person steers JARVIS ("read me the OTP", "ignore your instructions") (R18) | Their words are untrusted data in tags they can't close; the in-call brain has no tools; every line passes the reply guard; JARVIS agrees only to what the card lists | `calls/brain.py`, `calls/guard.py` | The guard checks shapes and pay words in English, romanised Hindi and the main Indian scripts; a paraphrase it doesn't know could pass; the brain check per language is not built (chapter 12, section 6) |
| T18 | Someone else's program posing as the call desk (R18) | One-use link code (hash stored, 20 wrong codes in 10 minutes stop all), then HMAC-signed upgrades with nonce and clock window, checked before the socket opens | `calls/hub.py`, `api/calls_ws.py` | The laptop holds the seed in the owner's profile folder; anyone with that file can be the desk |
| T19 | The owner's number flagged as a spammer, or calls seen as automated commercial calls (R18) | Every call starts with his tap; personal limits; AI and recording disclosure first; no emergency, premium or international numbers | `calls/limits.py`, `calls/cards.py`, `calls/models.py` | The rules' application to a person's own AI-assisted calls is a reading, not legal advice (section 8.5) |
| T20 | The owner's microphone left on the virtual cable (R18) | The desk writes the old defaults first, reads every switch back, restores at takeover, end, crash (watchdog) and next start | `calldesk/micguard.py`, `calldesk/watchdog.py` | Not yet tried on a real laptop (S0 not run) |

## 7. Known residual risks

1. **One instance holds security state in memory**: the rate limiter, the per-conversation lock,
   and the home and phone nonce stores (`deploy/cloudrun.sh` header comment;
   `src/jarvis/home/signing.py:NonceCache`); from R18 also the call hub, the dial grants, the live
   tickets, the desk socket's nonces, the wrong-code counter and the phone's command outbox and
   key. A second instance would weaken replay protection and rate limits, and split a call, until
   that state moves out (ADR-25, ADR-36 in chapter 08).
2. **No key rotation tool** for `jarvis-token-key`; envelopes carry `KEY_ID` so one can be added.
3. **Unsealed personal data** (T11).
4. **Passkeys are opt-in**; until one is added, R3 needs only a signed-in Approve.
5. **Audit rewrite by a project administrator** is detectable only against the Cloud Logging
   anchor, which the same administrator could also delete.
6. **The try-on role** lets `jarvis-run` send prompts to any Agent Platform model (accepted in
   R13.1; the guide's C73), watched by JARVIS's cap and the `jarvis-tryon` budget alert.
7. **Closed on 27 Nov 2026:** the tree-wide check that AI vendor SDKs stay inside `jarvis.llm`
   is `tests/test_llm_sdk_boundary.py` (chapter 01, P7). It passes.
8. **The owner's Google account is the root of trust** for sign-in, the Google tools and the Cloud
   project; its own 2-step sign-in matters most.
9. **The wake-word models are CC BY-NC-SA 4.0** (personal, non-commercial use only); a licence
   risk, not a security one, but it blocks any public release.
10. **A waiting call card's number is in clear in `approvals`** (R18; found while writing this
    edition). The gateway keeps a card's full arguments, which are what runs on approval, in the
    unsealed `approvals` collection until the card is decided or tidied after its 10 minutes
    (`src/jarvis/storage/approvals.py:DocApprovalStore.put`). The console shows them masked
    (`src/jarvis/core/models.py:shown_arguments`); the call store itself seals every number. Left
    for the review to decide (chapter 12, section 6).
11. **A call card's other fields are not sealed** (R18): the purpose, the lines, the contact's
    name and a booking's name and number to give, kept until the Privacy delete (chapter 04).
12. **Nothing of R18 has run on real devices** (R18): Phone Link, the Windows sound path,
    Bluetooth, the Android build on the owner's phone and real Web Push were tested with fakes only
    (`docs/plans/r18-integration/I1-NOTES.md`, 4.7).

## 8. Phone calls (R18)

Built in R18 (`v18.0.0`), not yet deployed. Plan: `docs/plans/r18-calls.md`, sections 7 and 8.

### 8.1 Placing a call is R3, and an approval dials once

| Rule | As built | Code |
|---|---|---|
| A card every time | `calls_place` is irreversible (R3): never an Allow, never Approve all, no "don't ask again"; the passkey whenever "Require passkey for irreversible actions" is on | `src/jarvis/calls/tools.py:calls_tools`, `src/jarvis/core/guardrails.py:NO_BULK_TOOLS` |
| A new number needs the passkey | A number never called before needs the passkey; while the passkey requirement is off JARVIS can't ask for one, so such a call is refused with words saying how to switch it on (fail closed) | `src/jarvis/calls/approvals.py:CallsService.preview` |
| The number is masked | The card's text and the Approvals panel show the last four digits only, a booking's number to give too | `src/jarvis/calls/cards.py:card_text`, `src/jarvis/core/models.py:MASKED_ARGUMENTS` |
| The one-use grant | His approval issues a dial grant: one use, 10 minutes (`APPROVAL_TTL_S`), bound to the number and the card's content (`CallCard.digest`), so a card changed after approval no longer matches. The engine spends it for that call id just before the dial, counting the day's limits in the same transaction. Grants live in memory: after a restart nothing can be dialled on an old approval | `src/jarvis/calls/approvals.py:GrantBook`, `CallsService.take_for_dial`, `src/jarvis/calls/models.py:APPROVAL_TTL_S` |
| The phone dials only for that grant | The phone side looks at the grant without spending it and queues `call.dial` only for that call, number and owner, at most 2 minutes after the engine took it | `src/jarvis/calls/approvals.py:GrantBook.live_until`, `src/jarvis/calls/join.py:PhoneApprovals` |
| Telegram can't approve a call | `calls_place` is in `CONSOLE_ONLY_TOOLS`, so even an old or forged Telegram button, or the R3 rule switched off for an eval's control, never places a call | `src/jarvis/telegram/service.py`, `tests/test_r18_review_telegram_calls.py` |
| The phone's Approve keeps the passkey | Approve on the phone asks for the phone's unlock and runs his press only when no passkey is asked; a never-called number or a passkey in force opens the console; a rule that can't be read dials nothing | `src/jarvis/calls/join.py:PhoneCardDesk` |
| The chat's call card | A call the brain proposes shows its card under the reply; whichever approval he uses, the stored card is used once | `src/jarvis/calls/chat_card.py`, `docs/plans/r18-integration/I1-NOTES.md` (decision 14) |
| Every step audited | Each step is in the append-only audit with the number masked, never in full; logs never carry a number, a transcript, a summary or audio | `src/jarvis/calls/approvals.py:audit_step`, `src/jarvis/calls/cards.py:masked` |

### 8.2 The sockets, the desk's link and the phone's commands

- **The desk's socket** (`/v1/calls/desk/ws`): no query string; exactly one `X-Jarvis-Home`
  header signed with the desk's "up" key over the path and an empty body; the desk id known, the
  clock within 60 seconds, the nonce not seen in 5 minutes, compared in constant time; all of it
  before the socket is accepted, else closed 4401 and logged by check name. Then `hello` within 10
  seconds, at most 150 audio frames a second (a flood is dropped), 20 malformed messages close it
  (`src/jarvis/api/calls_ws.py:AUDIO_FRAMES_PER_S`, `MAX_BAD`, `HELLO_S`). The signing code is the
  home bridge's, unchanged (`src/jarvis/home/signing.py`).
- **The link code**: 8 characters without look-alike letters (Crockford base32), shown once,
  10 minutes, one use, stored only as a SHA-256; 20 wrong codes in a 10-minute window, counted
  for every client together, stop all codes until the window passes. The link route needs no
  session (the code is the proof) and sits under `/v1`'s rate limit. The desk's 32-byte seed is
  sealed with `calls` (`src/jarvis/calls/hub.py:DeskStore`, `CODE_TTL_S`, `MAX_WRONG_CODES`).
- **The live socket** (`/v1/calls/{call_id}/live`): his bearer, or his cookie from JARVIS's own
  page. A browser can't send a bearer on a WebSocket, so in token mode `POST
  /v1/calls/{call_id}/live/ticket` gives a ticket for that call, one use, 30 seconds, at most 64
  held, taken only from JARVIS's own page and only when the socket brought no other credential (a
  wrong bearer beside a good ticket is refused and spends nothing; review fix). A spent ticket may
  appear in an access log: it opens nothing again (`src/jarvis/api/calls_routes.py:LiveTickets`,
  `TICKET_TTL_S`, `TICKETS_MAX`). The call must be his and running (4404); 5 malformed messages
  close it; "Tell JARVIS" at most 10 a minute.
- **The phone's commands**: signed by the cloud with ECDSA P-256 under a key made at each start
  and sent with the door's answers; the phone acts on one only if it verifies, names this phone,
  is fresh, lives at most 15 minutes and was never acted on. Events from the phone have strict
  shapes, are deduplicated and limited to 40 a minute per phone; a caller's number arrives only
  while answering is on (`src/jarvis/phone/calls.py:PhoneCalls`, `src/jarvis/phone/calls_wire.py`).

### 8.3 What the other person can and can't do: the reply guard

- Their words are untrusted data, placed inside tags they can't close; the in-call brain has no
  tools, and its reply is one JSON document whose actions the engine carries out in code
  (`src/jarvis/calls/brain.py:CallBrain`).
- Every line is checked before it is spoken (`src/jarvis/calls/guard.py:check_reply`): a run of 4
  or more digits (in any script, and number words in English, romanised Hindi and the main Indian
  scripts) is refused unless the value is on the card or the other person said it earlier, and then
  only up to 11 digits (`MIN_SECRET_DIGITS`, `MAX_ECHO_DIGITS`); PAN-, IFSC-, e-mail-, UPI-handle-
  and link-shaped text is refused; so is agreeing to pay. JARVIS says "I will check with (his first
  name) and call back" instead, never the refused words.
- A phone menu's keys pass the same digit rule, at most 20 keys, and never on a call JARVIS
  answered (`check_dtmf`, `MAX_DTMF_KEYS`).
- Answering missed calls is off until he switches it on (`calls_answer_mode`, R2; switching it on
  always asks); then JARVIS takes a message and agrees to nothing, never for a withheld number
  (`src/jarvis/calls/answering.py`).

### 8.4 Limits and quiet hours

`src/jarvis/calls/limits.py:Limits` and `src/jarvis/calls/cards.py:check_number`, with the values
in `src/jarvis/calls/models.py`:

| Limit | Value |
|---|---|
| Calls a day | 10 (`CALLS_PER_DAY`) |
| Calls a day to one number | 2 (`CALLS_PER_NUMBER_PER_DAY`) |
| Numbers never called before, a day | 3 (`NEW_NUMBERS_PER_DAY`) |
| Redials of a number that did not answer, a day | 1 (`NO_ANSWER_REDIALS_PER_DAY`) |
| Quiet hours | none from 21:00 to 08:00 IST, nor one that could run past 21:00 (`QUIET_FROM`, `QUIET_UNTIL`; `quiet_problem`) |
| Refused numbers | emergency and helpline numbers (100, 101, 102, 108, 112, 1070, 1077, 1091, 1098, 181, 1930, 14567: `EMERGENCY_NUMBERS`), premium 1900 numbers, other short codes, international numbers; toll-free 1800 numbers are allowed |
| Money | the call's ₹, the month's calls ₹ and the owner's overall limit (chapter 06, section 6) |

The day's counters are kept by IST day and counted in one transaction with the grant's spend; a
counter that can't be read refuses the call (fail closed). The engine never redials on its own:
trying again is a new card and a new tap.

### 8.5 Why these calls stay the owner's own (TRAI and the DPDP Act)

This is the plan's safe-side reading, not legal advice (`docs/plans/r18-calls.md`, section 7;
*unverified* by a lawyer).

- **TRAI.** The Third Amendment to the commercial-communication rules (Regulation 05 of 2026,
  notified 18 Sep 2026) treats calls "initiated by an application, software system or automated
  platform without direct human dialing" as A2P calls that must be declared to the operator. It
  is about commercial calls. JARVIS keeps each call a person's own: he starts every call with his
  tap (direct human dialling), from his own number, never promotional, at a personal volume (the
  limits above), with JARVIS saying in its first sentence that it is an AI assistant calling for
  him (`src/jarvis/calls/models.py:OPENING_LINE`). If TRAI or the operator says anything about
  personal AI calls, the plan pauses the feature for his decision.
- **DPDP Act 2023.** Section 3(c)(i) leaves out personal data processed by an individual for a
  personal or domestic purpose; his own errands fit. JARVIS stays conservative anyway: the first
  sentence says the call is recorded, recording stops and what was kept is deleted if the other
  person objects, records are sealed and kept 30 days, and he can export or delete them from the
  Privacy panel (chapter 04, section 4). Calls for an employer's work are not this feature's
  purpose.

### 8.6 Secrets

The three speech keys are `SecretStr` (`src/jarvis/config_calls.py:CallsConfig`), never logged;
speech vendors are called over REST with `httpx`, no vendor SDK. The desk keeps no speech key in
cloud mode, which is every call in v18.0.0.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.1 | 27 Nov 2026, 16:05 IST | R6.4 | First edition: authentication for every caller (owner, re-sign-in, passkeys, token, phone door, app lock, scheduler, Telegram, home bridge, laptop brain, deploy); the risk tiers, policy, confirmation tokens, taint and provenance, rate limits and caps; secrets; audit; browser hardening; a 15-row threat model; nine residual risks | 🛠 Mark XXV |
| v6.4.2 | 27 Nov 2026 | R6.4 | Verification (chapter 13): `SecretStr` fields 13 → 11; Telegram's audit of strangers capped at 20 an hour; residual risk 7 closed by `tests/test_llm_sdk_boundary.py`; proposed ADR-B is now ADR-25 | 🛠 Mark XXV |
| v6.5.0 | 27 Nov 2026, 20:05 IST | R18 | R18 "Calls from your laptop": the call desk and the live view as callers; the console-only tools; the calls' limits among the caps; threats T15 widened and T16–T20 added; residual risks 1 widened and 10–12 added (a waiting call card's number in clear in `approvals`, a card's unsealed fields, nothing tried on real devices); new section 8: R3 `calls_place`, the one-use grant, the passkey for new numbers, Telegram can't approve a call, the phone's Approve, the desk's signed socket and link code, the live socket's one-use ticket, the phone's signed commands, the reply guard, limits and quiet hours, the TRAI and DPDP reasoning, the speech keys | 🛠 Mark XXV |

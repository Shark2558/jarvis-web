Version v6.4.1 · 27 Nov 2026, 16:05 IST · Release R6.4 · Status: Current · Owner: 🛠 Mark XXV

# 05 · Security architecture

**In plain words.** Only you get in: your Google account must be on JARVIS's list, and anything
final (sending, paying, deleting for good) waits for your Approve, and for your passkey once you
have one. Machines that call JARVIS (the clock, Telegram, your phone, your laptop) each prove who
they are on every call, in their own way. Every action passes one checkpoint, the tool gateway,
and is written into a record that shows if anyone changes it. Words from other people (mail, web
pages, documents) are treated as information, never as orders. Keys live only in Google's Secret
Manager. The end of this chapter lists what is still not fully protected.

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
| Telegram | `X-Telegram-Bot-Api-Secret-Token`, constant-time compare; then the paired owner's user and chat id (pairing by an 8-character code, 10 minutes) | `src/jarvis/api/telegram.py`, `src/jarvis/telegram/pairing.py` | Bare 401; anyone else gets no reply and is audited |
| The home bridge (both directions) | `X-Jarvis-Home` header: HMAC-SHA256 with direction-specific keys derived from a 32-byte link seed (`jarvis/home/up/v1`, `jarvis/home/down/v1`), a 16-byte nonce remembered 5 minutes, a ±60 s window; responses signed and bound to the request | `src/jarvis/home/signing.py` (shared by cloud and bridge) | Refused before any parsing |
| The laptop brain | A bearer key of at least 16 characters at the Caddy gate; only `https://<machine>.<tailnet>.ts.net` addresses are accepted | `deploy/local-brain/Caddyfile`, `src/jarvis/offline/config.py` | Caddy refuses; JARVIS reports "laptop didn't answer" |
| GitHub Actions (deploy) | Workload Identity Federation: this repository's numeric id, `refs/heads/main`, a push or manual run, `ci.yml` on `main`, a GitHub-hosted runner; impersonates `jarvis-deployer` | `deploy/cloudrun.sh:setup_autodeploy` | Google refuses the token exchange |

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
(chapter 01, P3).

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

## 3. Secrets

- **Storage.** Only in Secret Manager, one grant per secret for `jarvis-run` (chapter 02, 2.3);
  GitHub holds no Google key (Workload Identity Federation). The one GitHub secret is the optional
  `JARVIS_ANTHROPIC_API_KEY` for the main-only eval gate (`.github/workflows/ci.yml`).
- **In the process.** Held as `SecretStr` (`src/jarvis/config.py`, 13 fields); start-up refuses a
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
| T15 | Lost or stolen phone | The app lock; unlink from the laptop; the phone's door can't read conversations, the vault or mail, approve anything or call a tool | `phone/`, `mobile/ports.py` | Chrome's own cookie on the phone until "Sign out everywhere" |

## 7. Known residual risks

1. **One instance holds security state in memory**: the rate limiter, the per-conversation lock,
   and the home and phone nonce stores (`deploy/cloudrun.sh` header comment;
   `src/jarvis/home/signing.py:NonceCache`). A second instance would weaken replay protection and
   rate limits until that state moves out (chapter 12's proposed ADR-B).
2. **No key rotation tool** for `jarvis-token-key`; envelopes carry `KEY_ID` so one can be added.
3. **Unsealed personal data** (T11).
4. **Passkeys are opt-in**; until one is added, R3 needs only a signed-in Approve.
5. **Audit rewrite by a project administrator** is detectable only against the Cloud Logging
   anchor, which the same administrator could also delete.
6. **The try-on role** lets `jarvis-run` send prompts to any Agent Platform model (accepted in
   R13.1; the guide's C73), watched by JARVIS's cap and the `jarvis-tryon` budget alert.
7. **No tree-wide check** that AI vendor SDKs stay inside `jarvis.llm` (chapter 01, P7).
8. **The owner's Google account is the root of trust** for sign-in, the Google tools and the Cloud
   project; its own 2-step sign-in matters most.
9. **The wake-word models are CC BY-NC-SA 4.0** (personal, non-commercial use only); a licence
   risk, not a security one, but it blocks any public release.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.1 | 27 Nov 2026, 16:05 IST | R6.4 | First edition: authentication for every caller (owner, re-sign-in, passkeys, token, phone door, app lock, scheduler, Telegram, home bridge, laptop brain, deploy); the risk tiers, policy, confirmation tokens, taint and provenance, rate limits and caps; secrets; audit; browser hardening; a 15-row threat model; nine residual risks | 🛠 Mark XXV |

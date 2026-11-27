Version v6.6.1 · 28 Nov 2026 · Release R5.2 · Status: Current · Owner: 🛠 Mark XXV

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

**Your voice (R5.2, built, not yet deployed).** Your laptop's speech kit answers only someone who
holds its key, a long random password made on your laptop. JARVIS reaches it only at your
laptop's own Tailscale address and refuses any other. The kit downloads only model files whose
fingerprints were written down in advance. Your voice is **never** used to approve anything: the
speaker check only decides who may interrupt JARVIS while he speaks. Corrections learned from your
voice change ordinary words only, never a number, an amount of money or a code. Section 9 has the
details.

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
| JARVIS or the call desk, calling the laptop speech kit (R5.2) | The kit's key, at least 32 characters (start-kit makes 32 random bytes), as `Authorization: Bearer`, checked by the Caddy gate and again in constant time by the kit's server; only the kit's own API addresses pass | `deploy/local-speech/Caddyfile`, `src/jarvis/localspeech/server.py` | 401 for a wrong or missing key, 404 for any other address, 503 for everything while the kit has no key |

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
- **In the process.** Held as `SecretStr` (`src/jarvis/config.py`, 11 fields; R18's three
  speech keys in `src/jarvis/config_calls.py`; R5.2's kit key in `src/jarvis/config_voice.py`,
  15 in all); start-up refuses a session secret under 32 characters, a malformed token key and a
  kit key under 32 characters.
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
by SHA-256 (the vision files only if their manifest's hash matches; from R5.2 the speaker
check's model the same way, `src/jarvis/api/speaker_assets.py`, an empty slot today). The
container runs as a non-root user; the home bridge runs read-only with no capabilities.

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
| T11 | A reader of the Firestore project | Sealing for the most private collections (chapter 04); from R18's review also a waiting call card's numbers in `approvals` | `keyring.py`, `calls/pending.py` | Conversations, memory, attachment text and the audit are not sealed; a waiting call card's other arguments are in clear for its 10 minutes (residual risk 11) |
| T12 | Runaway spend | Monthly limit before every paid call; free-allowance stops at 90 %; ₹1 budget alert; try-on cap and its own budget alert | `billing/`, `quota/ledger.py`, `deploy/cloudrun.sh` | No JARVIS limit until the owner sets one; the budget alert warns, it doesn't stop |
| T13 | Denial of service | Rate limits, body caps, flood limits, `--max-instances 1` bounds the bill | `api/ratelimit.py`, `api/body.py` | One instance is also one point of failure |
| T14 | The laptop compromised | The bridge runs hardened; only its signed door is funnelled; the cloud never trusts a picture or a name it didn't ask for | `deploy/home/docker-compose.yml`, `home/` | The laptop holds the camera recordings and face library |
| T15 | Lost or stolen phone | The app lock; unlink from the laptop; the phone's door can't read conversations, the vault or mail or call a tool; from R18 its Approve of a call card asks for the phone's unlock, and a never-called number or a passkey in force sends it to the console | `phone/`, `mobile/ports.py`, `calls/join.py` | Chrome's own cookie on the phone until "Sign out everywhere"; a stolen unlocked phone can approve a call to a number already called while no passkey is required |
| T16 | A call placed without the owner (R18) | R3 card every time; a one-use 10-minute grant bound to the number and the card's content, spent for one call id just before the dial; passkey for a never-called number; never from Telegram; grants in memory, gone at a restart | `calls/approvals.py`, `core/guardrails.py`, `phone/calls.py` | Before a passkey is added, a stolen cookie can approve a call to a number already called (as T2) |
| T17 | The other person steers JARVIS ("read me the OTP", "ignore your instructions") (R18) | Their words are untrusted data in tags they can't close; the in-call brain has no tools; every line passes the reply guard; JARVIS agrees only to what the card lists | `calls/brain.py`, `calls/guard.py` | The guard checks shapes and pay words in English, romanised Hindi and the main Indian scripts; a paraphrase it doesn't know could pass; the brain check per language is not built (chapter 12, section 6) |
| T18 | Someone else's program posing as the call desk (R18) | One-use link code (hash stored, 20 wrong codes in 10 minutes stop all), then HMAC-signed upgrades with nonce and clock window, checked before the socket opens | `calls/hub.py`, `api/calls_ws.py` | The laptop holds the seed in the owner's profile folder; anyone with that file can be the desk |
| T19 | The owner's number flagged as a spammer, or calls seen as automated commercial calls (R18) | Every call starts with his tap; personal limits; AI and recording disclosure first; no emergency, premium or international numbers | `calls/limits.py`, `calls/cards.py`, `calls/models.py` | The rules' application to a person's own AI-assisted calls is a reading, not legal advice (section 8.5) |
| T20 | The owner's microphone left on the virtual cable (R18) | The desk writes the old defaults first, reads every switch back, restores at takeover, end, crash (watchdog) and next start | `calldesk/micguard.py`, `calldesk/watchdog.py` | Not yet tried on a real laptop (S0 not run) |
| T21 | A stranger reaching the laptop speech kit through its public Funnel address (R5.2) | The gate passes only the kit's API with the key; no key at all → 503 for everything; the server checks the key again and binds 127.0.0.1 only; bodies capped at 3 MB; nothing logs a body, audio, text, header or key | `deploy/local-speech/Caddyfile`, `localspeech/server.py`, `localspeech/kitconfig.py` | Whoever holds the key can do what JARVIS can (residual risk 13) |
| T22 | JARVIS sent to a look-alike address, or a redirect, instead of the owner's kit (R5.2) | Only a `*.ts.net` https name with a Funnel port; every address it resolves to must be public; the pinned transport connects to the address just checked; no redirects; at most 4 MB read; the kit's text never reaches the console (fixed words only) | `config_voice.py`, `localspeech/client.py`, `offline/config.py` | — |
| T23 | A tampered or swapped model file (R5.2) | Only files pinned in `models.json`, https from two hosts at a fixed revision, size and SHA-256 checked before a file is renamed into place; small text files by their git blob id, fetched as the host's raw file at exactly the pinned commit (ADR-42); a permissive licence or nothing; the wake word's files checked by hash, licence and format before the console uses them | `localspeech/manager.py`, `voice/wakeword_api.py` | The blob-id files were pinned from Hugging Face's API listing read through a web reader, not computed from downloaded files (section 9.2) |
| T24 | A voice (a recording, a TV, another person) used to approve something (R5.2) | The speaker check is a barge-in filter and, at most, a display label; no approval, passkey, unlock or Telegram decision reads it, and a test fails if one ever mentions it | `api/static/console-voiceprint.js`, `voice/profile.py`, `tests/test_r52_v5_never_approves.py` | — (ADR-44) |
| T25 | A learned correction changing a number, an amount or a code the owner said (R5.2) | Corrections are whole words of letters only; a correction with a digit, a currency sign or a number, ordinal, counting, money or code word is refused, and none is learned from the numbers block | `voice/profile.py:Correction`, `voice/session_score.py` | A mishearing of an ordinary word can still be corrected into another ordinary word |

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
   risk, not a security one, but it blocks any public release. R5.2 found that its owned model
   (stage 2) does not lift it alone: both stages read openWakeWord's two feature models, which
   carry the same licence (ADR-45).
10. **Closed on 27 Nov 2026 (R18 review, item 12): a waiting call card's number is sealed in
    `approvals`.** The gateway keeps a card's full arguments, which are what runs on approval, in
    `approvals` until the card is decided or tidied after its 10 minutes. This edition first found
    the number in clear there; now the store seals a card's arguments on the way in and opens them
    on the way out (`src/jarvis/storage/approvals.py:DocApprovalStore.use_seal`, `ArgumentSeal`),
    and for `calls_place` `src/jarvis/calls/pending.py:CallNumberSeal` seals the number to call
    and a booking's number to give under the `calls` key, bound to the approval id and the field;
    `src/jarvis/api/r18_wiring.py:finish_r18` puts it on the gateway's store
    (`seal_pending_calls`). The console still shows them masked
    (`src/jarvis/core/models.py:shown_arguments`). Test:
    `tests/test_r18_review_approval_seal.py` (commit `9e8b490`).
11. **A call card's other fields are not sealed** (R18): the purpose, the lines, the contact's
    name and a booking's name and number to give, kept until the Privacy delete (chapter 04). A
    waiting `calls_place` card in `approvals` holds the same purpose, lines, contact's name and
    booking name in clear for up to 10 minutes; only its numbers are sealed (risk 10).
12. **Nothing of R18 has run on real devices** (R18): Phone Link, the Windows sound path,
    Bluetooth, the Android build on the owner's phone and real Web Push were tested with fakes only
    (`docs/plans/r18-integration/I1-NOTES.md`, 4.7).
13. **The kit's key opens more than listening** (R5.2; this edition's reading of
    `src/jarvis/localspeech/protocol.py:ROUTES`). Whoever holds it can ask the kit what its
    engines heard in his session's clips (`/v1/session/results`), delete his recordings, start a
    training job and fetch the wake word's files; there is no route that returns a clip's audio.
    The key lives in three places: the kit's folder, Secret Manager and, when he copies it, the
    call desk's folder. A new key is one `start-kit.ps1` away after the old file is removed, as
    `deploy/local-speech/README.md` ("Why it is safe") says;
    `bash deploy/cloudrun.sh --local-speech` then stores the new one over the saved key, and
    `install-calldesk.ps1 -SpeechKit` copies it to the desk again.
14. **The speaker check does nothing yet** (R5.2): its model slot is empty and its threshold
    (0.45) is not calibrated (ADR-46). That is safe, because it only ever blocks a barge-in, but
    the plan's promise that only his voice can interrupt JARVIS is not kept until the model is in.
15. **Nothing of R5.2's laptop side has run on a real laptop**: the kit's engines, Caddy,
    Tailscale Funnel and the PowerShell scripts were tested with fakes only
    (`docs/plans/r5-2-integration/I1-NOTES.md`, 4.6).

## 8. Phone calls (R18)

Built in R18 (`v18.0.0`), not yet deployed. Plan: `docs/plans/r18-calls.md`, sections 7 and 8.

### 8.1 Placing a call is R3, and an approval dials once

| Rule | As built | Code |
|---|---|---|
| A card every time | `calls_place` is irreversible (R3): never an Allow, never Approve all, no "don't ask again"; the passkey whenever "Require passkey for irreversible actions" is on | `src/jarvis/calls/tools.py:calls_tools`, `src/jarvis/core/guardrails.py:NO_BULK_TOOLS` |
| A new number needs the passkey | A number never called before needs the passkey; while the passkey requirement is off JARVIS can't ask for one, so such a call is refused with words saying how to switch it on (fail closed) | `src/jarvis/calls/approvals.py:CallsService.preview` |
| The number is masked | The card's text and the Approvals panel show the last four digits only, a booking's number to give too | `src/jarvis/calls/cards.py:card_text`, `src/jarvis/core/models.py:MASKED_ARGUMENTS` |
| The number is sealed while the card waits | The waiting card's number to call and a booking's number to give are sealed in `approvals` under the `calls` key, bound to the approval id and the field (a sealed number moved to another card does not open), and opened only on the way out, so the gate and the call see them whole; a card that does not open is unreadable, never a guess (review fix) | `src/jarvis/calls/pending.py:CallNumberSeal`, `src/jarvis/storage/approvals.py:DocApprovalStore.use_seal`, `tests/test_r18_review_approval_seal.py` |
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
speech vendors are called over REST with `httpx`, no vendor SDK. The deploy mounts each from
Secret Manager only when the owner has stored it, and no key value is in the repository
(`deploy/cloudrun.sh:speech_keys`; chapter 02, section 2.3). The desk keeps no speech key in
cloud mode, which is every call in v18.0.0.

## 9. Your voice (R5.2)

Built in R5.2 (`v5.2.0`), not yet deployed. Plan: `docs/plans/r5-2-voice.md`, sections 3 and 5;
the join's decisions: `docs/plans/r5-2-integration/I1-NOTES.md`, section 2.

### 9.1 The kit's door: its key, the gate and the pinned transport

| Rule | As built | Code |
|---|---|---|
| A key that fails closed | The kit's key is at least 32 characters (`KEY_MIN_CHARS`; start-kit makes 32 random bytes, 43 characters). With no key, or a shorter one, the gate answers 503 to every request and the server refuses to serve. JARVIS refuses a shorter key at start-up, and the deploy never stores one: it says why, leaves the kit off this time and goes on (`ls_skip`, R5.2 review) | `deploy/local-speech/Caddyfile`, `src/jarvis/localspeech/server.py`, `src/jarvis/config_voice.py:LocalSpeechConfig`, `deploy/cloudrun.sh:local_speech_answer` |
| Checked twice | The Caddy gate matches the bearer header for each of the kit's addresses; the server compares it again in constant time (`hmac.compare_digest`) | `deploy/local-speech/Caddyfile`, `src/jarvis/localspeech/server.py` |
| Never logged, never shown | The key comes only from the environment or the kit's private file; the server keeps no access log and logs no body, audio, text, header or key; the self-test's report never holds it; the deploy reads it without echo and writes it only to Secret Manager; the client logs only the route, status and a fixed reason | `src/jarvis/localspeech/__main__.py`, `src/jarvis/localspeech/selftest.py`, `src/jarvis/localspeech/client.py` |
| Loopback only on the laptop | The server binds `127.0.0.1:11437` and the gate `127.0.0.1:11436`; only Funnel's https port reaches the gate from outside | `src/jarvis/localspeech/kitconfig.py:HOST`, `deploy/local-speech/Caddyfile` |
| https to the owner's own name | JARVIS accepts only `https://<machine>.<tailnet>.ts.net` with port 443, 8443 or 10000 and no other path (row 392's rule: http refused) | `src/jarvis/config_voice.py:kit_origin` |
| Pinned transport | Before the first call every address the name resolves to must be public (R1's rule); every request is resolved again and connected to the address just checked, the name kept for TLS | `src/jarvis/localspeech/client.py:cloud_kit`, `src/jarvis/offline/config.py:check_url`, `PinnedTransport` |
| No redirects, a reply cap, fixed words | Redirects are never followed; at most 4,000,000 bytes of a reply are read (`REPLY_MAX`); the kit's answers become fixed words (offline, timeout, unauthorized, busy, error, protocol), never the kit's own text | `src/jarvis/localspeech/client.py`, `src/jarvis/localspeech/protocol.py:REPLY_MAX` |
| Strict requests | Every request and reply is a strict model (unknown fields refused); audio is 16 kHz mono PCM16 (or MP3 for the console's voice); a listening request at most 60 seconds, a session clip at most 20 (`STT_MAX_S`, `CLIP_MAX_S`) | `src/jarvis/localspeech/protocol.py` |

### 9.2 What the kit may download: SHA-256 pins, and one recorded exception

The build brief's rule 9 says every model file is pinned by its SHA-256. The model manager keeps
it for every weight file: only files listed in `deploy/local-speech/models.json`, from https
addresses on huggingface.co or github.com at a fixed revision, with their size and SHA-256 and a
permissive licence (`src/jarvis/localspeech/protocol.py:PERMISSIVE_LICENCES`). A file is written
to a temporary name and renamed into place only when its size and hash match; a mismatch deletes
it and installs nothing (`src/jarvis/localspeech/manager.py:ModelManager.install`).

**The exception (ADR-42).** A small text file kept in plain git (a `.json` or `.txt` of at most
5 MB), at a revision that is a full 40-character commit, may be pinned by its **git blob id**
(`git_blob_sha1`) instead, and only when its address is exactly the host's raw file at that commit:
`/<owner>/<repo>/resolve/<commit>/…/<name>` on Hugging Face (`raw` on GitHub), plain segments, no
port, query or fragment, ending in the pinned name (`src/jarvis/localspeech/manager.py:_at_commit`).
Until the R5.2 review the commit only had to appear somewhere in the address, so a moving branch
name could pass with the commit in a query, a fragment or a folder under `resolve/main/`; the
commit is what makes a SHA-1 pin safe (review finding 2, `2d487fd`;
`tests/test_r52_review_manager.py`). The manager computes it after download as
git does (SHA-1 of "blob <size>", a zero byte, then the data), refuses a mismatch, and records the
file's SHA-256 in `installed.json` and `LICENCE.txt` (`src/jarvis/localspeech/manager.py:ModelFile`,
`git_blob`, `ModelEntry`). Weights (`model.bin`, any LFS file) always need a SHA-256, because an
LFS file's blob id is its pointer's, not its data's. faster-whisper small and medium are pinned
this way: `model.bin` by SHA-256, `config.json`, `tokenizer.json` and `vocabulary.txt` by blob id.

How it is checked: `tests/test_r52_i1_manager_blob.py`, `tests/test_r52_v1_manager.py` and
`tests/test_r52_review_manager.py` (which also loads the real `deploy/local-speech/models.json`). The
later check (`ModelManager.verify`, the `models verify` command) re-hashes every installed file
against its pin, so a blob-pinned file is re-checked by its blob id, not by the SHA-256 recorded
at install. The blob ids were read twice from Hugging Face's API listing at each revision through
a web reader, not computed from downloaded files (I1-NOTES, 4.5); the manager re-checks every file
on the laptop, so a wrong pin fails the install rather than installing a wrong file.

### 9.3 Corrections never touch numbers, money or codes

The voice session learns the chosen engine's mishearings that repeat (seen twice or more) and
applies them after listening, whichever engine listened. A correction is 1–3 heard words for 1–5
meant words, letters only: a digit, a currency sign, or a number, money or code word on either
side is refused when the correction is made, and none is learned from the numbers block or from a
phrase he really says elsewhere (`src/jarvis/voice/profile.py:Correction`, `PROTECTED_WORDS`;
`src/jarvis/voice/session_score.py`). The protected words are the cardinals ("one" to "billion",
"lakh", "crore", "double", "half"), since the R5.2 review also the ordinals ("fourth" to
"billionth"), the plural and counting words ("fives", "hundreds", "dozen", "twice"), the money
words ("rupees", "paise") and the code words (`otp`, `pin`, `cvv`, `cvc`, `upi`, `ifsc`, `pan`,
`aadhaar`, `password`, `passcode`, `passkey`, `pincode`): before it, a learned correction could
still write or rewrite "fifth", "hundreds", "dozen", "twice" or "passcode" (review finding 5,
`d81d129`). Tests: `tests/test_r52_i0_profile.py`, `tests/test_r52_v3_score.py`,
`tests/test_r52_review_corrections.py`. He can switch corrections off in Voice → Your voice.

### 9.4 The speaker check never approves anything

The voice print lets a device tell his voice from others (chapter 04, section 8). It is used for
barge-in only: with a print active, a voice that would interrupt JARVIS is checked on the device
first, and a check that is slow, fails or has no print is "skip", so barge-in works as before
(`src/jarvis/api/static/console-voice-barge.js`, `src/jarvis/api/static/console-voiceprint.js`).
"Spoken by the owner" (`src/jarvis/voice/profile.py:SPOKEN_BY_HEADER`) is defined as a display
label and nothing sends or reads it yet. `tests/test_r52_v5_never_approves.py` reads every module
that decides an approval, a passkey, an unlock, a permission or a Telegram approval and fails if
one mentions the label or a voice print, and it shows on the real app that the label in a header
or a body leaves a waiting R3 card waiting for its passkey. This keeps slice 9's decision D11 and
plan D6 (ADR-44). A wake is only ever a wake, too: the owned wake word approves nothing
(`src/jarvis/voice/wakeword_api.py`).

### 9.5 Files from the laptop to the console

The wake word's two trained files pass through the cloud without being stored, and only after
`src/jarvis/voice/wakeword_api.py:WakewordHandlers` checks the kit's hash and licence (permissive
or the owner's own), the status they were announced with, their format and, for stage 1, that they
read the very feature model the console runs. In the browser `console-wakeword-own.js` takes a file
only when its SHA-256 is the one the status announced; anything odd leaves today's wake word
unchanged. The speaker model is served from JARVIS's own release folder only when its manifest
lists it with a matching SHA-256 and a data media type, never JavaScript
(`src/jarvis/api/speaker_assets.py`).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.1 | 27 Nov 2026, 16:05 IST | R6.4 | First edition: authentication for every caller (owner, re-sign-in, passkeys, token, phone door, app lock, scheduler, Telegram, home bridge, laptop brain, deploy); the risk tiers, policy, confirmation tokens, taint and provenance, rate limits and caps; secrets; audit; browser hardening; a 15-row threat model; nine residual risks | 🛠 Mark XXV |
| v6.4.2 | 27 Nov 2026 | R6.4 | Verification (chapter 13): `SecretStr` fields 13 → 11; Telegram's audit of strangers capped at 20 an hour; residual risk 7 closed by `tests/test_llm_sdk_boundary.py`; proposed ADR-B is now ADR-25 | 🛠 Mark XXV |
| v6.5.0 | 27 Nov 2026, 20:05 IST | R18 | R18 "Calls from your laptop": the call desk and the live view as callers; the console-only tools; the calls' limits among the caps; threats T15 widened and T16–T20 added; residual risks 1 widened and 10–12 added (a waiting call card's number in clear in `approvals`, a card's unsealed fields, nothing tried on real devices); new section 8: R3 `calls_place`, the one-use grant, the passkey for new numbers, Telegram can't approve a call, the phone's Approve, the desk's signed socket and link code, the live socket's one-use ticket, the phone's signed commands, the reply guard, limits and quiet hours, the TRAI and DPDP reasoning, the speech keys | 🛠 Mark XXV |
| v6.5.1 | 27 Nov 2026, 21:25 IST | R18 | The R18 review's later fixes: T11 names the sealed approval numbers; residual risk 10 closed (the approvals seal, commit `9e8b490`); risk 11 adds a waiting card's other arguments; section 8.1 adds the number sealed while the card waits; section 8.6 says the deploy mounts a speech key only when stored | 🛠 Mark XXV |
| v6.6.0 | 27 Nov 2026, 22:07 IST | R5.2 | R5.2 "Your voice": the voice rules in plain words; JARVIS and the call desk calling the speech kit as a caller row; 15 `SecretStr` fields and the kit key's start-up check; the speaker model pinned like the vision files; threats T21–T25 (a stranger at the kit's door, a look-alike address, a tampered model, a voice used to approve, a correction changing a number); residual risk 9 widened (the feature models), 13–15 added (what the kit's key opens, the speaker check not working yet, nothing run on a laptop); new section 9: the kit's key and pinned transport, the model manager's SHA-256 pins and the git-blob SHA-1 exception (and how `verify` re-checks it), corrections never touching numbers, the speaker check never approving, files from the laptop to the console | 🛠 Mark XXV |
| v6.6.1 | 28 Nov 2026 | R5.2 | Brought in line with R5.2's combined review (`docs/plans/r5-2-integration/REVIEW.md`): a git-blob pin holds only for the host's raw file at exactly its commit (T23, section 9.2); the corrections' protected words widened to ordinals, counting words and more code words (T25, section 9.3); the deploy never stores a short kit key and goes on without the kit; residual risk 13: the kit README's key-change step is written down after all | 🛠 Mark XXV |

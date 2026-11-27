Version v6.4.1 · 27 Nov 2026, 14:50 IST · Release R6.4 · Status: Current · Owner: 🛠 Mark XXV

# 02 · System context and deployment

**In plain words.** JARVIS is one small server in your own Google Cloud project (region
asia-south1, Mumbai). You reach it from the console web page, the phone app or Telegram. It keeps
its data in Firestore and its keys in Secret Manager in the same project, asks an AI brain to
think, and calls Google and a few other services for its tools. A set of free programs on your
laptop (the "home kit") connects it to your house and can stand in as a backup brain. GitHub
tests every change and deploys `main` without any stored key. Figure 15 shows the parts; Figure 16
shows where trust changes hands.

## 1. System context

![Figure 15 · JARVIS as built: the containers](../diagrams/15-containers.png)

*Figure 15. JARVIS as built: the containers.* Source:
[`15-containers.markdy`](../diagrams/15-containers.markdy). The guide's Figure 1
(`../diagrams/01-context.png`) draws the same context in the owner's words.

| Actor or system | Role | How it reaches JARVIS, or JARVIS reaches it | Evidence |
|---|---|---|---|
| Owner, in the console | The only user | HTTPS to the Cloud Run URL; Google sign-in for an e-mail on `JARVIS_OWNER_EMAILS`, then a signed cookie | `src/jarvis/api/auth.py`, `src/jarvis/api/app.py:_install_google_sign_in` |
| Owner, in the phone app | Same user, same page | Chrome draws the console (TWA); four signed routes for the phone's own requests | `android/app/build.gradle.kts` (`androidbrowserhelper`), `src/jarvis/phone/door.py` |
| Owner, on Telegram | Chat and alerts | Telegram's webhook to `/telegram/webhook` with a secret token | `src/jarvis/api/telegram.py:WEBHOOK_PATH` |
| Owner, in a terminal | Engineering use | `jarvis chat --stream` (no server) or the API with the bearer token | `src/jarvis/cli.py`, `src/jarvis/api/auth.py` |
| Cloud Scheduler | The clock | Signed POSTs to `/internal/brief/tick` and `/internal/home/watchdog` | `deploy/cloudrun.sh` step 8, `src/jarvis/api/scheduler_auth.py` |
| AI brains | Reasoning | Anthropic (SDK), Gemini (REST), one OpenAI-compatible slot, the laptop's Ollama | `src/jarvis/llm/` |
| Google APIs | Tools and speech | REST over `httpx` with the owner's OAuth token or the service account | `src/jarvis/integrations/google.py`, `src/jarvis/voice/google_cloud.py` |
| Other outside services | Web search, weather, warnings, exchange rate, GitHub | REST over `httpx` | the guide, section 5.2; chapter 06 |
| The home kit | House, cameras, faces, backup brain | Through Tailscale Funnel to the owner's laptop, signed both ways | `deploy/home/docker-compose.yml`, `src/jarvis/home/signing.py` |
| GitHub | Code, CI, deploy | GitHub Actions; Workload Identity Federation to Google | `.github/workflows/ci.yml`, `deploy/cloudrun.sh` step 7 |

## 2. Deployment view

### 2.1 Cloud Run service

One container, built from `Dockerfile` (`python:3.12-slim`, every package hash-checked from
`requirements.lock`, runs as user `jarvis` uid 10001, `jarvis serve` on port 8000, the build time
written into `src/jarvis/BUILD_DATE`). Deployed by `deploy/cloudrun.sh` step 6 and then by CI's
`deploy` job.

| Setting | Value | Where | What it implies |
|---|---|---|---|
| Service, region | `jarvis`, `asia-south1` | `deploy/cloudrun.sh` (`SERVICE`, `REGION`) | Data and compute in the owner's project, one region |
| Instances | `--min-instances 0 --max-instances 1` | `deploy/cloudrun.sh` step 6 | Scales to zero when idle; never two copies (chapter 06, section 4) |
| Size | `--memory 512Mi --cpu 1` | same | The document extractor's child process is capped at 200 MiB to leave room (`src/jarvis/documents/isolation.py:MEMORY_LIMIT_BYTES`) |
| Request timeout | `--timeout 300` (seconds) | same | The longest request, a tick included, has 5 minutes |
| Concurrency | not set | same | Cloud Run's default applies (80 requests per instance; *unverified*: not set or read by any script) |
| CPU allocation | not set | same | The default: CPU only while a request runs; background learning is swept at the start of the next request (`src/jarvis/core/brain.py` module docstring) |
| Ingress | `--allow-unauthenticated` | same | The URL is public; JARVIS does its own sign-in on every route (section 4) |
| Identity | `--service-account jarvis-run` | same | No key file anywhere; Google libraries use the service account |
| Settings | `JARVIS_ENV=prod`, `JARVIS_AUTH_MODE=google`, `JARVIS_SESSION_BACKEND=firestore`, `JARVIS_DEFAULT_TIER=balanced`, `JARVIS_EFFORT=low`, `JARVIS_LLM_TIMEOUT_S=20`, `JARVIS_LOG_JSON=true` and the feature switches | `deploy/cloudrun.sh` (`INFRA_ENV`) | Re-runs keep the owner's answers; `--reconfigure` rewrites them |
| Health | `GET /health` | `src/jarvis/api/routes.py`; `Dockerfile` `HEALTHCHECK` | The deploy switches traffic only after `/health` answers `"status":"ok"` |
| Start-up guards | refuses `JARVIS_ENV=dev` or token sign-in on Cloud Run; refuses a weak session secret, no owner e-mail, or a malformed token key | `src/jarvis/config.py:Settings._refuse_dev_on_cloud_run`, `_require_google_auth_config` | A misconfiguration fails the health check, so the old version keeps serving |

### 2.2 Firestore

One database, `(default)`, Firestore Native mode, created in `asia-south1` ("This location is
permanent"; `deploy/cloudrun.sh` step 4). Every collection name starts with `jarvis_`
(`JARVIS_FIRESTORE_PREFIX`). The deploy makes one composite index (`jarvis_sessions`: `user_id`,
`updated_at`) and exempts the sealed `blob` fields of 11 collection groups from indexing. No TTL
policy is set (TTL deletes are billed); JARVIS deletes what expires itself. Every store reaches
Firestore through the `Docs` port (`src/jarvis/storage/docs.py:Docs`;
`src/jarvis/storage/firestore_docs.py:FirestoreDocs`). Chapter 04 lists the 126 collections.

### 2.3 Secret Manager

Up to 11 secrets, each readable by `jarvis-run` through its own grant (`deploy/cloudrun.sh` step
5): `jarvis-google-client-secret`, `jarvis-anthropic-key`, `jarvis-gemini-key`,
`jarvis-openai-compat-key`, `jarvis-session-secret`, `jarvis-api-token`, `jarvis-token-key` (the
root of the keyring, 32 random bytes made once), `jarvis-tavily-key`, `jarvis-google-api-key`,
`jarvis-telegram-bot-token`, `jarvis-telegram-webhook-secret`. The optional ones (web search, Maps
and YouTube, Telegram) are left unmounted if their grant fails; every other grant failing stops the
deploy (`grant_failed`). Secrets reach the process as environment variables and are held as
`SecretStr` in `src/jarvis/config.py` (13 fields).

### 2.4 Service accounts

| Account | Roles | Why |
|---|---|---|
| `jarvis-run` | `roles/datastore.user`, `roles/logging.logWriter`, `roles/serviceusage.serviceUsageConsumer`, one `secretAccessor` grant per secret; the custom `jarvisTryOn` role (only `aiplatform.endpoints.predict`) when See it on me is on; the backup drill's three grants after the owner's backup step | The runtime identity |
| `jarvis-scheduler` | none | Only proves "I am JARVIS's clock" through its OIDC token |
| `jarvis-deployer` | `iam.workloadIdentityUser` for this repository's id only; `iam.serviceAccountUser` on `jarvis-run`; `run.developer` on the one service; `artifactregistry.writer` on the build repository; `serviceusage.serviceUsageConsumer` | GitHub's keyless deploy (`deploy/cloudrun.sh:setup_autodeploy`) |
| The default compute account | builder, Artifact Registry writer, log writer, storage viewer; its secret and database access is removed after each deploy | Builds the image for `--source .` deploys |

### 2.5 Cloud Scheduler

| Job | Schedule (IST) | Calls | Deadline | Created by |
|---|---|---|---|---|
| `jarvis-morning-brief` | `0,30 4-11 * * *` (every 30 minutes, 04:00–11:30) | `POST /internal/brief/tick` | 180 s | `deploy/cloudrun.sh:setup_brief_clock` |
| `jarvis-home-watchdog` | `*/5 * * * *` (all day) | `POST /internal/home/watchdog` | 60 s | `deploy/cloudrun.sh:setup_home_watchdog` |

The morning tick runs the tick jobs (`src/jarvis/ticks.py:run_jobs`, wired in
`src/jarvis/api/tick_wiring.py:tick_jobs`); the 5-minute call runs the clock jobs
(`tick_wiring.py:clock_jobs`: the self-health watch first, then the systems check, the helpers'
clock and the others), with Home on or off. Both are signed with an OIDC token whose audience is
the exact URL (`src/jarvis/api/scheduler_auth.py`). If either job is missing, JARVIS still works:
the brief is made when the Brief panel opens.

### 2.6 The console and the phone app

| Part | As built | Evidence |
|---|---|---|
| Console | One page served by the API: `console.html` plus 120 `console*.js` modules, plain JavaScript with no build step, vendored libraries pinned by hash; content security policy `script-src 'self' 'wasm-unsafe-eval'` | `src/jarvis/api/console.py:CONSOLE_CSP`, `src/jarvis/api/static/` |
| Installable web app | A web app manifest with three shortcuts and a share target | `src/jarvis/api/app_shell.py` |
| Phone app | Android app in `android/`: a Trusted Web Activity (`android-browser-helper`), native parts for the Talk tile, alerts, Health Connect, SOS and a DigiLocker folder; Chrome draws the console, so sign-in, passkeys, cookies and Web Push are unchanged | `docs/plans/r7-mobile.md` D1, D2 |
| Site and app vouch for each other | `GET /.well-known/assetlinks.json` names the one package with the signing fingerprints of the linked phones (empty until a phone is linked; cached one minute) | `src/jarvis/api/phone.py` |
| The phone's door | `POST /phone/v1/{hello,health,inbox,sos}`, signed with a P-256 key kept in the phone's secure hardware; never reads a conversation, the vault or mail, never approves or calls a tool | `src/jarvis/phone/door.py`, `src/jarvis/mobile/ports.py` |
| Build | CI proves the app with a throwaway key against `jarvis.invalid`; the app the owner installs is built on his laptop | `.github/workflows/android.yml` |

### 2.7 The home kit on the laptop

Installed by `deploy/home/setup-windows.ps1` and `deploy/home/setup-wsl.sh` into WSL; run by
Docker Compose (`deploy/home/docker-compose.yml`, project `jarvis-home`).

| Service | Image | Exposure | Hardening |
|---|---|---|---|
| `mosquitto` (MQTT) | `eclipse-mosquitto:2.0.20` | internal network only | password file and ACL: Frigate writes `frigate/#`, the bridge only reads |
| `frigate` (cameras) | `ghcr.io/blakeblackshear/frigate:0.17.2` | `127.0.0.1:8971` (its own login page) | other ports not published |
| `homeassistant` | `ghcr.io/home-assistant/home-assistant:2026.10.0` | host network, limited to loopback and the WSL host address in its configuration | — |
| `bridge` (JARVIS's home bridge) | built from `deploy/home/bridge.Dockerfile` on `python:3.12-slim` | `127.0.0.1:8099` (the signed API that Funnel forwards) and `127.0.0.1:8098` (the local Faces page, never funnelled) | read-only root, `cap_drop: ALL`, `no-new-privileges`, uid 10001, 768 MB memory limit |

**Tailscale Funnel** gives the laptop one public HTTPS name; TLS ends on the laptop. JARVIS accepts
only a `<machine>.<tailnet>.ts.net` address: port 8443 for the bridge
(`src/jarvis/home/client.py`), and 443, 8443 or 10000 for the laptop brain
(`src/jarvis/offline/config.py`). **The laptop brain** is Ollama behind a Caddy gate on
`127.0.0.1:11435` that wants a bearer key of at least 16 characters and allows only
`POST /v1/chat/completions` and `GET /v1/models`, bodies up to 2 MB
(`deploy/local-brain/Caddyfile`).

### 2.8 Telegram

The deploy registers the webhook once (`deploy/cloudrun.sh:telegram_webhook`): one connection
(matching one instance), `message` and `callback_query` updates only, pending updates dropped on
re-registration. A request without the right `X-Telegram-Bot-Api-Secret-Token` (constant-time
compare) gets a bare 401; only the paired owner's user and chat get a reply
(`src/jarvis/api/telegram.py`, `src/jarvis/telegram/service.py`).

### 2.9 Google APIs switched on

`deploy/cloudrun.sh` step 2 enables Cloud Run, Cloud Build, Artifact Registry, Secret Manager,
Firestore, IAM, IAM Credentials and STS, Calendar, Gmail and Tasks; then, each in its own command
that may fail without stopping the deploy: Text-to-Speech and Speech-to-Text, Drive (the Drive
feature is on only when this run enabled it), People (contacts), the Photos Picker, and the Agent
Platform (See it on me). Step 8 enables Cloud Scheduler; the budget alert enables Billing Budgets.

### 2.10 GitHub CI/CD

`.github/workflows/ci.yml` runs `test`, `docs-check`, `pr-title`, `firestore`, `browser` (4 shards),
`docs`, `eval-gate` and `deploy`; `.github/workflows/android.yml` runs `wrapper-pin`, `build` and
`controls` when Android files change. Chapter 07 describes each job. The `deploy` job runs only
on `main` (push or a manual run), only when the repository variable `AUTODEPLOY` is `on`, and
only after `test`, `firestore` and all four `browser` shards pass. In order it: writes the build
book (best effort, before any Google credential exists), signs in through Workload Identity
Federation as `jarvis-deployer`, builds and pushes the image to Artifact Registry
(`cloud-run-source-deploy`), refuses if `main` has moved on, rolls out with no traffic under the
tag `candidate`, polls `/health` up to 12 times 10 seconds apart, and only then moves all traffic.
A failed check leaves the current version serving. Old images: the newest 10 are kept, older ones
deleted after 30 days (`setup_autodeploy`'s clean-up policy).

### 2.11 Backups

Backups exist only after the owner's one-time step, `bash deploy/backup_setup.sh` (it shows the
cost and waits for a typed YES): a daily Firestore backup schedule kept 7 days, delete protection
on `(default)`, and three least-privilege grants for the monthly restore drill (a custom
`jarvisDrillCleanup` role limited by condition to the database `jarvis-drill`, then
`roles/datastore.restoreAdmin` and `roles/datastore.backupSchedulesViewer`). The deploy runs only
the read-only `--status` mode. The drill restores the newest copy into `jarvis-drill`, checks a
canary and deletes it (`src/jarvis/backup/`). Chapter 04, section 6 covers what the copies hold.

### 2.12 Environments

| Environment | Where | Store | Sign-in | Brain |
|---|---|---|---|---|
| `dev` | A developer's machine (`docker-compose.yml` with Redis, or in memory) | memory or Redis sessions | bearer token | mock or a real key |
| `prod` | Cloud Run | Firestore | Google sign-in (token sign-in refused) | as configured |

There is no staging service; the no-traffic `candidate` revision plays that part for one health
check. `render.yaml` is left from the first hosting on Render (slice 2) and is not used.

## 3. Trust boundaries

![Figure 16 · Trust boundaries](../diagrams/16-trust-boundaries.png)

*Figure 16. Trust boundaries.* Source:
[`16-trust-boundaries.markdy`](../diagrams/16-trust-boundaries.markdy). Each arrow is a crossing;
its label is what the receiving side checks.

| # | Boundary | Crossing | Checked by | Data that crosses |
|---|---|---|---|---|
| B1 | Internet → JARVIS (owner) | Console and phone page requests | Google sign-in + owner allow-list, signed 12-hour cookie, `X-Requested-With: JARVIS` on writes, per-client rate limit, body caps, R3 passkey | The owner's messages, files, approvals |
| B2 | Internet → JARVIS (phone door) | Four signed POST routes | `src/jarvis/phone/door.py:DoorGate` (route, header, flood, device, time, cap, nonce, P-256 signature, rate) | Hello, health readings, inbox items, SOS |
| B3 | Internet → JARVIS (machines) | Scheduler ticks, Telegram updates | OIDC with exact audience; Telegram secret token, then the paired owner | No personal data in; ticks start owner work |
| B4 | GitHub → Google Cloud | Deploy | Workload Identity Federation: this repository id, `refs/heads/main`, push or manual run, `ci.yml` on `main`, GitHub-hosted runner | A new image |
| B5 | JARVIS → its own project | Firestore, Secret Manager, Logging | The `jarvis-run` service account, no key | Everything JARVIS keeps |
| B6 | JARVIS → the laptop | Bridge calls and the laptop brain | HMAC-SHA256 both ways with keys from a 32-byte link seed, a nonce, a 60-second window (`src/jarvis/home/signing.py`); a key gate for Ollama | Device and camera commands, chat for the laptop brain |
| B7 | JARVIS → AI brains | Model calls | Tier and training flag (`src/jarvis/llm/brains.py`); monthly limit | The conversation window; for non-training brains, memory notes and tool results |
| B8 | Outside content → the model | Tool results | The gateway's untrusted prefix, fences, taint (chapter 05, section 2.4) | Mail, web, documents, contacts, camera labels |
| B9 | JARVIS → Telegram and Web Push | Alerts and chat replies | Personal reads off on Telegram unless switched on; Web Push encrypted to each browser | Alert text, replies |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.1 | 27 Nov 2026, 14:50 IST | R6.4 | First edition: system context, Cloud Run settings and what they imply, Firestore, Secret Manager, service accounts, the two Scheduler jobs, the console and phone app, the home kit, Telegram, the Google APIs, CI/CD, backups, environments, nine trust boundaries; Figures 15 and 16 | 🛠 Mark XXV |

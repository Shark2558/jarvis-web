---
page: pg_service_cloud_run
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "src/jarvis/api/app.py": "a739af3f1d029daa"
  "src/jarvis/api/auth.py": "02a9e121c2585fd8"
  "src/jarvis/api/calldesk_kit.py": "ecfbe8177c5f2a46"
  "src/jarvis/api/calls_routes.py": "4afdecf7fe9949c6"
  "src/jarvis/api/home.py": "cd0a9f3557a74808"
  "src/jarvis/api/home_wiring.py": "47912d10ccd3e249"
  "src/jarvis/api/integrations.py": "849076061558773f"
  "src/jarvis/api/permissions.py": "42dc725d201a9c43"
  "src/jarvis/config.py": "965b3658da16361e"
  "src/jarvis/drive/token.py": "9e3f8f673ac390aa"
---
## In plain words
Cloud Run is Google's service for running a program on the internet without looking after a server. It is where JARVIS lives: your console, Telegram, Google's clock and your home laptop all talk to JARVIS on Cloud Run, in your own Google Cloud project, in Google's Mumbai region next to your data. It runs one copy of JARVIS, starts it when a request arrives and lets it sleep when nobody is using it. Everything JARVIS does passes through it, but it belongs to your project: Google runs the machine, and only JARVIS's own service account and you as the project owner reach what it keeps.

## Example (made up)
At 6:00 nobody has used JARVIS for hours and it is asleep. At 6:30 Google's clock calls; Cloud Run starts JARVIS in a few seconds, the brief is made, and JARVIS sleeps again later. Next week a new release is merged: Cloud Run starts the new version beside the old one, checks it is healthy, and only then sends your requests to it.

## How it works
Cloud Run gives each service and each new version a name of its own, and `src/jarvis/config.py:Settings` reads them as `cloud_run_service` and `cloud_run_revision`. When `cloud_run_service` is set, laptop-only settings refuse to start: no developer mode and no token-only sign-in on the internet (`Settings`). A new `cloud_run_revision` tells the self-health watch that a new version is live (`selfwatch_enabled`). `_lifespan` wires every part of JARVIS when the server starts and closes each outside connection when it stops; a memory-learning run under way gets {{fact:src/jarvis/api/app.py:DRAIN_TIMEOUT_S}} seconds to finish (`src/jarvis/api/app.py`). Each client address may make up to `rate_limit_per_minute` ({{fact:settings.rate_limit_per_minute}}) requests a minute to the console's routes and sign-in. Outside the developer's laptop the session cookie is sent only over HTTPS, and every request must be signed in (`src/jarvis/api/auth.py:require_auth`). For Drive, `MetadataTokens` asks Cloud Run's own metadata server for a read-only token for JARVIS's service account, so no key exists (`src/jarvis/drive/token.py`). It keeps that token until {{fact:src/jarvis/drive/token.py:SKEW_S}} seconds before it ends, and if the metadata server can't be reached it says so and tries again after {{fact:src/jarvis/drive/token.py:UNREACHABLE_TTL_S}} seconds (`MetadataTokens`). The clock and your laptop reach JARVIS on their own doors, such as `POST /internal/home/watchdog` and `POST /home/webhook`. The call desk on your laptop links once through `POST /v1/calls/desk/link` and then talks to JARVIS over one open connection, `WEBSOCKET /v1/calls/desk/ws` (`src/jarvis/api/calls_routes.py`). The deploy script asks for the laptop speech kit's address and key on a full deploy, on a quick one only while there is no saved answer, and again when run with --local-speech; the key goes straight to Secret Manager, JARVIS's service account is let read it, and an empty answer leaves the kit off (`deploy/cloudrun.sh`).

## What it costs
Nothing in rupees inside Cloud Run's free monthly allowance, which one owner's use stays well within. Unverified: the exact charge if that allowance were ever passed; the deploy script sets a budget alert that e-mails you at the first rupee spent.

## When it fails
A new version that isn't healthy never gets your requests: the current JARVIS keeps running. After a long sleep, the first request waits a few seconds while JARVIS starts. A part that fails to start is left off with a note in the log, and the rest of JARVIS keeps working (`src/jarvis/api/home_wiring.py:wire_home`). Laptop-only settings stop the server at start-up with a plain message. Without an https public address the call desk's kit is not offered, because the kit must name that address (`src/jarvis/api/calldesk_kit.py:desk_kit`). A speech kit address that isn't a Tailscale https name on a Funnel port, or a kit key under {{fact:src/jarvis/config_voice.py:KIT_KEY_MIN_CHARS}} characters, stops the deploy script with a plain message before the new version goes out (`deploy/cloudrun.sh`).

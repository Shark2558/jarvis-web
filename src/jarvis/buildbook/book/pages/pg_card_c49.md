---
page: pg_card_c49
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/config.py": "3d154bdd78268162"
---
## In plain words
Every knob that changes how JARVIS behaves lives in one place: which AI to use, your time zone, how long the app lock waits, how many SOS contacts you may have, which features are switched on, and the secret keys it needs. They are read from the server's environment when JARVIS starts, so changing one means a redeploy, not editing code (`src/jarvis/config.py`). Secret values are held in a special type that never prints them in a log or an error message. Before it starts on the cloud, JARVIS also refuses settings that would be unsafe there (`Settings`).

## Example (made up)
Imran deploys JARVIS but forgets to set the long random session secret. When the server starts it stops at once with "JARVIS_SESSION_SECRET must be at least 32 characters" and never serves a page. He adds the secret, redeploys, and it starts. A week later he leaves out the optional web-search key; JARVIS starts normally and simply has no web search until he adds it.

## How it works
`Settings` reads every setting from an environment variable whose name starts with JARVIS and an underscore, or from a local file on a laptop, and ignores anything it doesn't know (`src/jarvis/config.py`).
Keys and passwords, such as the `api_token`, the `session_secret` and the `token_key`, are typed as secret strings, so printing the settings shows stars instead of their values.
`get_settings` builds them once and every part of JARVIS shares the same copy.
Checks run as the settings load: the environment must be dev, staging or prod, the home laptop's offline time must allow for one late heartbeat, and a custom AI address must use https unless it is a private host (`_is_private_host`), and a Tailscale name never counts as one.
At start-up `Settings` also refuses dev mode or token sign-in on Cloud Run, a missing API token outside dev, an AI choice in `llm_backend` without its key, and Google sign-in in `auth_mode` without its client, web address, owner list or a session secret of at least {{fact:src/jarvis/config.py:MIN_SESSION_SECRET_LEN}} characters.
A token key that is present but malformed or weak stops start-up; a missing one only leaves the sealed features off (`src/jarvis/config.py`).
`LLMBackend`, `SessionBackend` and `AuthMode` list the only choices each of those settings accepts.

## What it costs
Reading settings costs nothing (`src/jarvis/config.py`). The secrets themselves come from Google's Secret Manager when JARVIS is deployed; its free tier covers a handful of secret versions, and a few more for the features you switch on may cost a few rupees a month, which is Unverified here.

## When it fails
A setting that fails its check stops JARVIS at start-up with a message that names the setting, never its value, so a mistake is caught before anyone uses it (`Settings`). A missing optional key just leaves its feature off. A malformed or weak token key is a start-up error rather than a surprise at your first Google connect (`src/jarvis/config.py`).

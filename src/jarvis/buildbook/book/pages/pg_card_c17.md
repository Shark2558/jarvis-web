---
page: pg_card_c17
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "deploy/local-brain/Caddyfile": "3a81fba9aad9157d"
  "deploy/local-brain/README.md": "13a990db953d3b6e"
  "deploy/local-brain/start-unix.sh": "52c9aa106cffffb5"
  "deploy/local-brain/start-windows.ps1": "ac8ab8a9e080f05d"
  "src/jarvis/api/offline.py": "5b454d255da1ba33"
  "src/jarvis/api/static/console-offline.js": "395fb571a35cce6f"
  "src/jarvis/offline/__init__.py": "99415c62dd88febf"
  "src/jarvis/offline/config.py": "4942186039a6b5ab"
  "src/jarvis/offline/mode.py": "711b71d3578892a6"
  "src/jarvis/offline/no_ai.py": "adc9f42a1f93fa67"
  "src/jarvis/offline/phrases_r13.py": "2fbd4988328c6be8"
  "src/jarvis/offline/phrases_r14.py": "54b514aeebeee23e"
  "src/jarvis/offline/prompt.py": "e8b679e230251823"
  "src/jarvis/offline/r14_part.py": "6d70ec07cf642990"
  "src/jarvis/offline/rules.py": "57888c113bd4484a"
  "src/jarvis/offline/said.py": "571a7157094332b5"
  "src/jarvis/offline/service.py": "d8859988abef45c7"
  "src/jarvis/offline/store.py": "b8504efa719e158d"
  "src/jarvis/people/routes.py": "1a14f337e5c1b049"
---
## In plain words
Three switches decide which brain answers you. The brain picker chooses the AI company for a conversation. No-AI mode turns the AI off completely: JARVIS then answers from fixed rules only and spends nothing on models (`src/jarvis/offline/mode.py`). Offline mode keeps JARVIS working when the internet or Claude is down, by asking a small, free AI that runs on your own laptop (`src/jarvis/offline/service.py`).

## Example (made up)
On the first of the month you switch No-AI on for a week. You type "remind me to call the bank at 5 pm", and JARVIS sets the reminder from a fixed pattern and replies "Done, Sir." without calling any model. A week later you switch the AI back on. One evening the cloud can't be reached; your laptop at home answers instead, the reply carries an offline marker, and when it wants to add a to-do you get a one-tap card first. An alert tells you offline mode is on; the next alert of that kind waits at least half an hour.

## How it works
`BrainMode` keeps the AI on or No-AI switch in `settings`, so it survives a restart; it is read for each turn, kept for {{fact:src/jarvis/offline/mode.py:CACHE_S}} seconds, and every change is written to the audit log (`src/jarvis/offline/mode.py`). You flip it through `POST /v1/settings/brain-mode`, which only the owner may call (`src/jarvis/people/routes.py`). In No-AI mode `route_no_ai` maps your words to tool calls by fixed patterns, and anything it doesn't recognise gets a fixed line (`src/jarvis/offline/rules.py`). `NoAIRunner` runs those calls through the gateway like any other, so approvals and the audit still apply, and builds the reply from fixed templates, never a model (`src/jarvis/offline/no_ai.py`). Offline mode is `LocalFallback`: the laptop runs Ollama behind a Caddy key gate, reachable through Tailscale Funnel (`deploy/local-brain/README.md`). Its address and key are set in Integrations through `PUT /v1/offline`, kept encrypted with the token key in `local_brain`, and never sent back to the page (`src/jarvis/offline/store.py`). `check_url` accepts only a Tailscale Funnel address, and `ensure_public` checks before each call that the name still points only at public addresses, so JARVIS is never steered at an inside service (`src/jarvis/offline/config.py`). While the laptop answers, `OfflineRules` turns every change into a one-tap card. The Test button asks the laptop for its models through `POST /v1/offline/test`, at most {{fact:src/jarvis/api/offline.py:TESTS_PER_MINUTE}} times a minute (`src/jarvis/api/offline.py`). `src/jarvis/api/static/console-offline.js` shows the status in Integrations, the offline marker on replies and a line in Vitals.

## What it costs
Nothing in rupees: No-AI mode calls no model, and the laptop brain is metered at zero because it runs on your own machine (`src/jarvis/offline/service.py`). The laptop's electricity and the tunnel service's own terms lie outside JARVIS and are Unverified here.

## When it fails
If the switch can't be read, or holds an unknown value, it counts as No-AI, so no model is called when JARVIS can't tell (`src/jarvis/offline/mode.py`). If the cloud is out of reach and the laptop doesn't answer, you see a plain line saying so, never a vendor's text (`src/jarvis/offline/service.py`). A laptop setting that can't be decrypted reads as not configured and is logged, and offline mode stays off (`src/jarvis/offline/store.py`). Alerts that offline mode went on or off come at most once in {{fact:src/jarvis/offline/service.py:ALERT_GAP_S}} seconds for each kind, and a failed alert never breaks a reply (`LocalFallback`).

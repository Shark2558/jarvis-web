---
page: pg_service_ollama
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/config.py": "8c3c0b7f0890ff99"
  "src/jarvis/offline/service.py": "d8859988abef45c7"
---
## In plain words
Ollama is a free program that runs a small AI model on your own laptop. JARVIS uses it as its offline brain: when Claude is unreachable, your laptop answers instead, so JARVIS keeps talking. In that case your words go only to your own machine. The laptop's model is smaller and slower than Claude, and while it is answering, every change JARVIS proposes asks you first. You set it up once in Integrations, Offline mode, with the address, the key and the model name that the laptop's start script prints.

## Example (made up)
At 10:05 Claude's service is down. You ask: "What's on my list today?" JARVIS finds Claude unreachable, sees the laptop is ready, and the laptop's small model answers in about 40 seconds. Your phone gets the note "JARVIS is in offline mode". At 10:50 Claude is back; the next reply comes from Claude, and a second note says JARVIS is out of offline mode.

## How it works
`build_local_fallback` makes the offline brain only when the server has its token key, because the laptop's address and key are stored sealed with it (`src/jarvis/offline/service.py`). `LocalFallback` is what `ModelRouter` calls when the cloud brain is unreachable; each time, it reads the saved settings and refuses unless offline mode is switched on (`src/jarvis/offline/service.py:LocalFallback`). Before every call it checks that the laptop's name still points only to a public Tailscale Funnel address, so a name that later points inside a network is refused (`LocalFallback`). Ollama sits behind a small gate on the laptop that wants the key in a bearer header, and Tailscale Funnel publishes it over HTTPS (`src/jarvis/offline/service.py`). The laptop gets the offline instructions and only a short list of tools; its reply is marked offline, so every change asks first, and it is metered at zero (`LocalFallback`). A call may take up to `local_brain_timeout_s` ({{fact:settings.local_brain_timeout_s}} seconds), because a laptop's processor is slow. When offline mode starts or ends, JARVIS sends you an alert, at most one of each kind every {{fact:src/jarvis/offline/service.py:ALERT_GAP_S}} seconds, and a failed alert never breaks an answer (`ALERT_GAP_S`). The Test button asks the laptop for its list of models within {{fact:src/jarvis/offline/service.py:TEST_TIMEOUT_S}} seconds and checks that your model is installed (`_model_listed`). The key must be {{fact:src/jarvis/offline/service.py:KEY_MIN}} to {{fact:src/jarvis/offline/service.py:KEY_MAX}} characters with no spaces (`_clean_key`), and a changed address needs the key pasted again, so a saved key never goes to a new address unasked (`OfflineRejected`).

## What it costs
Nothing in rupees: Ollama is free and open source, and it runs on your own laptop. JARVIS meters every offline reply at zero (`src/jarvis/offline/service.py:LocalFallback`). The only real cost is the laptop's electricity while it is on.

## When it fails
The console shows the state: Off, Standby, Active, or Laptop not answering (`LocalFallback`). The Test button says what is wrong in plain words: the laptop didn't answer (is it awake, with Tailscale Funnel on?), the laptop refused the key, the tunnel is up but Ollama isn't answering, or the model isn't installed, with the exact "ollama pull" line to run. Without the server's token key, offline mode is off (`build_local_fallback`). If Claude is down and the laptop gives no answer either, the reply fails with a plain message.

# Self-health (R4 Workstream B) -- what the integrator registers

No model call anywhere in `jarvis.health`; it works with `brain_mode == "none"` and with an
unreachable brain. Gate everything on `settings.health_enabled`.

## 1. Build the service (once, in the app factory / `tools/setup.py`)

```python
import time
from jarvis.health import probes as P
from jarvis.health.redis_ping import redis_pinger
from jarvis.health.service import HealthService
from jarvis.health.store import HealthStore

probes = [
    # brain: cheapest call the provider port has (1 output token); none at all in no-AI mode.
    # Use the provider directly (router.provider), NOT the router, so the laptop fallback never masks it.
    P.brain_probe(P.provider_ping(router.provider, router.resolve(ModelTier.FAST)),
                  brain_mode=s.brain_mode),
    P.docs_probe(docs, prefix=s.firestore_prefix),
    P.redis_probe(redis_pinger(s.redis_url)),          # only when session_backend == redis
]
if google is not None:   probes.append(P.google_probe(google))
if telegram_client:      probes.append(P.telegram_probe(telegram_client))   # TelegramClient
if home_store:           probes.append(P.home_probe(home_store, clock=time.time,
                                                    offline_after_s=s.home_offline_after_s))
if tavily:               probes.append(P.web_probe(tavily))                 # TavilyProvider.usage()
health = HealthService(probes, HealthStore(docs, prefix=s.firestore_prefix),
                       notifier=notifier,        # the R3 D Notifier (or DirectNotifier)
                       voice=voice_service)      # VoiceService, may be None
app.state.health = health
```

Probes that do not apply to an owner (Google never connected, home not linked) answer `None` and
are left out of the report. Collection written: `{prefix}health_last/{uid}` (Docs port; get/set only).

## 2. Tool
`from jarvis.health.tools import health_tools` -> `for t in health_tools(health): reg.register(t)`
Tool name: `systems_check` (READ_ONLY, matches the `systems_*` permission row; `may_vouch`, because
every word in its result is fixed JARVIS text). Register it with the always-on tools so it is
available in no-AI mode. Result: `{overall, spoken, checked_at, systems:[{key,name,status,reason,at}]}`.
The persona/offline rules should route "run a systems check" / "are all systems ok" to
`systems_check` (Builder D's `offline/rules.py` owns the no-AI route).

## 3. Tick job (D14)
`from jarvis.health.tick import HealthTickJob` -> append `HealthTickJob(health)` to
`app.state.tick_jobs`. name `health_check`, budget 45 s. No Cloud Scheduler job. The tick runs
the check per owner and alerts on change; the job counts an unserved owner under `failed`.
Note: the tick's cadence is the check's cadence (the brain probe sends one 1-token call per run).

## 4. Routes (optional, for the panel)
```python
from jarvis.health.api import health_router
app.include_router(health_router(health, user=current_user, dependencies=[Depends(require_auth)]))
```
`GET /v1/health`, `POST /v1/health/run`, `POST /v1/health/speak` (audio/mpeg). Add per-owner rate
limits like `/v1/voice` (run/speak ~ 10/min). The panel's Speak button uses the shared speaker
(`window.JarvisVoice.speaker.say`), so `/v1/health/speak` is only for non-browser callers.

## 5. Console panel
File: `src/jarvis/api/static/console-systems.js` (NOTE: placed in `api/static/`, where every console
script lives, not a top-level `web/`). To do: add the name to `APP_ASSETS` in `api/console.py`, add
`<script src="/static/console-systems.js" defer></script>` after `console.js` / `console-text.js` /
`console-voice.js` in `console.html`, and optionally an `<div id="systems">` host (otherwise it
appends a section beside `#integrations`). Update `tests/test_console_assets.py` lists if it
enumerates scripts.

## 6. Alerts
`health_fault` (urgent) and `health_recovered` (info) via `notifier.notify(uid,
Signal(source="system", kind=...), text)`; text is a fixed template (<= 300 chars).

## 7. Persona lines (D13, `core/prompts.py`)
"I can run a systems check on all my connections (brain, Google, Telegram, the home bridge, the
document store, Redis, web search) and tell you by voice what is fine or broken -- even with the AI
switched off." Brief section: none (not requested).

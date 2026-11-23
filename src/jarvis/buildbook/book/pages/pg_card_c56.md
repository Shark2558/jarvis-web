---
page: pg_card_c56
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/selfcheck_wiring.py": "fb7336391ffa3727"
  "src/jarvis/api/static/console-systems-modal.js": "0591870095265d5c"
  "src/jarvis/api/static/console-systems-voice.js": "e8f488a203174612"
  "src/jarvis/api/static/console-systems.js": "b2a348eb9c0bd6eb"
  "src/jarvis/health/INTEGRATION-r51.md": "53169a6609ab5840"
  "src/jarvis/health/INTEGRATION.md": "9643d8c66c61a9e9"
  "src/jarvis/health/__init__.py": "b6edf4d454fb6f65"
  "src/jarvis/health/api.py": "79f1e040aff58027"
  "src/jarvis/health/briefing.py": "327ad9bf679ee17f"
  "src/jarvis/health/changes.py": "903ed18e4b71bff0"
  "src/jarvis/health/models.py": "5adc114e38fff732"
  "src/jarvis/health/probes.py": "f43d09526ba73748"
  "src/jarvis/health/redis_ping.py": "c3c613297f814a00"
  "src/jarvis/health/remind.py": "36db1d8455bf6512"
  "src/jarvis/health/report.py": "e7b8b0cee5fac4a8"
  "src/jarvis/health/service.py": "f5ba546c1cd0ae6e"
  "src/jarvis/health/store.py": "6f6418f5955c9962"
  "src/jarvis/health/tick.py": "2b79e024cfb6af9f"
  "src/jarvis/health/tools.py": "74b9ceabe57ef3d0"
---
## In plain words
Say "Jarvis, run a systems check" and a pop-up ticks through each part JARVIS depends on (the AI brain, Google, Telegram, the home bridge, the document store, Redis, web search), then speaks a short report: what works, what is broken, and what that breaks for you. Every word comes from fixed sentences, so the check works even with the AI switched off. A background run repeats it regularly, and you hear only about a problem that lasts.

## Example (made up)
At 9 pm you say "Jarvis, run a systems check". The pop-up lists seven systems; six turn green and Telegram turns red. JARVIS says: "Systems check complete, Sir. Telegram is not answering, so alerts and Telegram chat won't reach you. This month's AI spend is ₹212, 42 per cent of your limit. Shall I set a reminder to fix this?" You say yes and pick "tomorrow morning"; a reminder lands on your calendar.

## How it works
`HealthService` runs one `Probe` for each part, side by side, each read-only with its own {{fact:src/jarvis/health/probes.py:PROBE_TIMEOUT_S}}-second limit, answering ok, degraded or down with a reason written by JARVIS (`src/jarvis/health/probes.py`).
`brain_probe` never calls a model: it only reads how the router's last real reply ended, so the check costs nothing and works with the brain off.
A whole run has {{fact:src/jarvis/health/service.py:CHECK_DEADLINE_S}} seconds; a probe still unfinished then counts as down, "did not answer in time", and the report still arrives (`HealthService`).
`rollup` turns the results into one overall status, and `HealthStore` keeps the last report in `health_last` (`src/jarvis/health/report.py`).
`compose_briefing` builds the spoken report from fixed sentences, adding the month's AI spend and any allowance at {{fact:src/jarvis/health/briefing.py:ALLOWANCE_WARN_PERCENT}} per cent or more, cut short past {{fact:src/jarvis/health/briefing.py:MAX_SPOKEN}} characters (`src/jarvis/health/briefing.py`).
`plan` decides what to tell you: a fault must hold for {{fact:src/jarvis/health/changes.py:DEBOUNCE_CHECKS}} checks at least {{fact:src/jarvis/health/changes.py:DEBOUNCE_GAP_S}} seconds apart, a recovery needs {{fact:src/jarvis/health/changes.py:RECOVERY_CHECKS}} clear checks, only "down" rings, and "degraded" is a silent note (`src/jarvis/health/changes.py`).
`HealthTickJob` runs the check in the background at most every {{fact:src/jarvis/health/tick.py:CHECK_EVERY_S}} seconds per owner with a linked home, and on the morning tick for everyone (`src/jarvis/health/tick.py`).
`set_reminder` turns a concern into a calendar reminder with fixed words at one of three fixed times, through the tool gateway like any other call (`src/jarvis/health/remind.py`).
The pop-up streams each result as it lands from `POST /v1/health/run/stream`, and `src/jarvis/api/static/console-systems-voice.js` hears the phrase and speaks the briefing.

## What it costs
Nothing: no rupees and no AI call, because the brain probe only reads what JARVIS already knows (`brain_probe`). It keeps the last report (`health_last`).

## When it fails
A store that is down never fails the check: the state is kept in memory and the report is marked as not saved (`HealthService`). A probe that crashes or times out shows as down with JARVIS's own reason, never a vendor's text (`src/jarvis/health/probes.py`). An alert that failed to send is tried again on the next check, and the home bridge is left to the home watchdog's own alert (`src/jarvis/health/changes.py`). Asking for a check while one is running joins it rather than starting another (`CheckBusy`).

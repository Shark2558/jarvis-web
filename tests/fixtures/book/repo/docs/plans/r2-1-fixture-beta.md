# R2.1 — Beta: alerts reach the owner

Status: PLAN v1 · 2026-10-20 · a fixture for the build book generator. Not in this plan: guests.

## Architecture fit
| Feature | Layer · skill | Phase | Verdict |
|---|---|---|---|
| Alerts | L8 output · Communication | 4 | Build now |

## Decisions

**D1 · Fixed texts.** Every alert is a fixed template; no model writes one (`notify/ports.py`).

## Risks
- Alerts at night wake the owner; quiet hours hold them.

## Needs the owner (safe defaults until answered)
1. Quiet hours 23:00–06:30?

## Deferred
- Alerts by SMS (it needs a paid service).

---
page: pg_card_c55
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/__init__.py": "9aa09e18a3b4d0d0"
  "src/jarvis/about.py": "c310b3bdce51c135"
  "src/jarvis/api/static/console-vitals.js": "dd7cc4ee3cec2353"
  "src/jarvis/vitals/INTEGRATION-r51.md": "d438580f7e609bae"
  "src/jarvis/vitals/INTEGRATION.md": "7e64e6a74ab67000"
  "src/jarvis/vitals/__init__.py": "06d123afd3fa5674"
  "src/jarvis/vitals/api.py": "c202f8299e5ac7c1"
  "src/jarvis/vitals/auto.py": "11a539bc5ee8e42a"
  "src/jarvis/vitals/brief.py": "007d850444bb6b29"
  "src/jarvis/vitals/guard.py": "6be1e7ffba9ddbde"
  "src/jarvis/vitals/job.py": "e11a30374de29c48"
  "src/jarvis/vitals/models.py": "c53b7bd435b39219"
  "src/jarvis/vitals/own.py": "cd127fbc1ca087c6"
  "src/jarvis/vitals/own_cache.py": "16af887474ab0a93"
  "src/jarvis/vitals/service.py": "275d00127bb256c2"
  "src/jarvis/vitals/status.py": "7af9cf93daefc3b6"
  "src/jarvis/vitals/store.py": "fa0a38e3e078e8e8"
  "src/jarvis/vitals/tools.py": "2c2b4ab52172b52b"
  "src/jarvis/vitals/words.py": "d3c1ea1349f60853"
---
## In plain words
Vitals is one board for everything that has a limit or a renewal date: JARVIS's own keys and connections, the free allowances it lives on, your AI spending, and any bills or subscriptions you add yourself. Each line is green, amber or red, and JARVIS tells you once when a line gets worse. You only ever type a key's name, limit and expiry, never the key itself. At the foot of the panel, an About line says which version of JARVIS is running and the day it was built.

## Example (made up)
You add a line "Domain renewal", expiring on 15 December. On 16 November it turns amber, because it is now within the warning days, and your phone gets one alert. Nothing more arrives until 15 December, when the line turns red and you get one more. Meanwhile the web search line reads "612 of 900 this month" in green, and the foot of the panel reads "About JARVIS · v6.3.2 · built 24 Nov 2026".

## How it works
`VitalsService` builds the board from three sources: the lines you add, the meters other parts keep (spending, Google allowances, web credits), and JARVIS's own keys and connections from `Own` (`src/jarvis/vitals/service.py`).
`status_of` works out each line's colour fresh every time: amber at {{fact:settings.vitals_amber_fraction}} of its limit or within {{fact:settings.vitals_expiry_amber_days}} days of its expiry, red at the limit or once expired, and "unknown" when a meter can't be read (`src/jarvis/vitals/status.py`).
`Own` asks each of its sources with a {{fact:src/jarvis/vitals/own.py:SOURCE_TIMEOUT_S}}-second limit, so one slow source turns its own line "unknown" and never slows the board (`src/jarvis/vitals/own.py`).
Your own lines are a `Provider` each, at most {{fact:src/jarvis/vitals/models.py:MAX_MANUAL}}, kept in `vitals_providers` with their names in `vitals_index` (`VitalsStore`).
`looks_like_a_key` refuses any label or note that looks like a credential, on every way in, so a key's value never gets stored (`src/jarvis/vitals/guard.py`).
`VitalsJob` rides the scheduler's tick, polls each owner at most every {{fact:src/jarvis/vitals/job.py:POLL_EVERY_S}} seconds, and alerts only when a line crosses upwards, remembering the last colour in `vitals_status` (`src/jarvis/vitals/job.py`).
Lines another part already rings for, like the Google link or the home laptop, stay quiet here (`src/jarvis/vitals/own.py`).
The morning brief names at most {{fact:src/jarvis/vitals/brief.py:MAX_LINES}} amber or red lines from `vitals_lines`, and you can ask by voice with the Vitals tools (`src/jarvis/vitals/tools.py`).
`version` and `build_date` give the About line: the version from `src/jarvis/__init__.py`, the date stamped when the image was built, in your time zone (`src/jarvis/about.py`).
`src/jarvis/api/static/console-vitals.js` draws the board from `GET /v1/vitals`, and you add or remove a line with `PUT /v1/vitals/keys` and `DELETE /v1/vitals/keys/{pid}`.

## What it costs
Nothing: no rupees and no AI call, only meters, arithmetic and fixed words (`VitalsService`). It keeps your lines, their last colours and an index of their names (`vitals_providers`, `vitals_status`, `vitals_index`).

## When it fails
Lines that can't be read never hide the rest of the board: they show as unavailable (`VitalsService`). A meter that can't be read makes its line "unknown", which never alerts (`status_of`). A failed alert is not recorded as sent, so the next tick tries again (`src/jarvis/vitals/service.py`). An unreadable build date shows "build date unknown", a missing version hides the About line, and neither stops the board loading (`src/jarvis/about.py`).

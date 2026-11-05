# Vitals (R4 Workstream A) -- integration

All deterministic: no model call anywhere. Everything below is for the integrator (I1); nothing in
shared wiring files was edited.

## 1. Build the service (once, at app start)

```python
from jarvis.vitals.store import VitalsStore
from jarvis.vitals.service import VitalsService
from jarvis.vitals.auto import AllowanceSpec

vitals = VitalsService(
    VitalsStore(docs, prefix=s.firestore_prefix),
    s,
    billing=billing,  # jarvis.billing.Billing (usage / allowance / allowance_resets_at)
    ledger=quota_ledger,  # jarvis.quota.ledger.QuotaLedger, or None
    allowances=(AllowanceSpec(key, label, free_units, unit), ...),  # optional: voice prices
)
app.state.vitals = vitals  # None (or unset) -> the routes answer 503
```

`allowances`: one `AllowanceSpec` per voice price (`prices.tts(t).key`, `prices.stt.key`; free_units is
`price.free_units`). Leave empty to skip them.

## 2. Tools (register through the gateway)

`from jarvis.vitals.tools import VitalsDeps, tools`
`for t in tools(VitalsDeps(vitals, s)): reg.register(t)` -- returns `[]` when `vitals_enabled` is false.

| tool | risk | permission row |
|---|---|---|
| `vitals_show` | R1 read | `vitals` |
| `vitals_set_key` | R2 | `vitals_change` |
| `vitals_delete_key` | R2 (reversible metadata) | `vitals_change` |

Each has fixed `activity_words`. The "never store a key VALUE" guard lives in `Provider` itself (`jarvis.vitals.guard`, a model validator on manual records), so it holds on every path: tool, REST, any importer. It scans id, label, note and unit (raw and separator-stripped; token prefixes; a half in one field glued to a half in another). Defence in depth, not a proof. The tools also run it in `Tool.check` (gateway "propose"), so a pasted key never reaches an approval card or the audit; the card shows only the first 12 characters of a label, and only the id for a delete.
Manual labels are constrained text: letters, digits, spaces and `. & ( ) / -`, max 80, no `:` or `@`, no web address. Alerts start with a fixed "Vitals — " prefix.
Dates: a naive or date-only `reset_at`/`expires_at` means END of that day in `user_timezone` (stored tz-aware); status never raises on a naive value.
Not given to a training brain; no Telegram gating needed (no private data beyond limits/expiry).

## 3. Routes

`from jarvis.vitals.api import router` -> `app.include_router(router)`
(`GET /v1/vitals`, `PUT /v1/vitals/keys`, `DELETE /v1/vitals/keys/{id}`; `require_auth` + `current_user`).
A bad body or id is a plain 422 (field names only, the input is never echoed); storage trouble is 503. Not rate-limited here; wrap with the app's per-owner `RateLimiter` if desired.

## 4. Tick job (D14 -- no new Cloud Scheduler job)

`from jarvis.vitals.job import VitalsJob`
`app.state.tick_jobs.append(VitalsJob(vitals, notifier, settings=s))`
`notifier` = the app's `jarvis.notify` `Notifier` (the same one the home alerts use). Name `vitals_poll`,
`budget_s=30`. Alerts only on an upward line-cross (`Signal(source="system", kind="vitals_warn" |
"vitals_critical")`). The job polls each owner at most once per `POLL_EVERY_S = 3600` (in-memory last-poll time), so a per-minute tick is fine. CADENCE: the tick fires only in the morning window (`0,30 4-11`), so the
"hourly" poll runs then; an off-window red is seen on the next window or on demand (`vitals_show`). Delivery is at-least-once: an alert is sent before its new status is recorded, so a failed record means one repeat next hour.

## 5. Brief section

`from jarvis.vitals.brief import vitals_lines, SECTION_TITLE`
`lines = await vitals_lines(vitals, uid)` -> `list[str]` ("Red: ...", "Amber: ...", "AI spend: ₹120 of
₹500 this month"); empty list = omit the section. Deterministic; keep it out of the AI-summary input.
The brief's section/model types are shared files, so this returns plain lines for you to wrap.

## 6. Console panel

File: `src/jarvis/api/static/console-vitals.js` (the repo has no top-level `web/`; static console
files live in `api/static/`). In `console.html` add inside the Vitals panel's `.pbody`:
`<div id="vitals-board"></div>` and `<script src="/static/console-vitals.js" defer></script>`
(CSP `script-src 'self'`). It listens to `jarvis:ready`, `jarvis:panel` (id `vitals`), `jarvis:reply`.
Class hooks for the CSS (not written): `vt-head vt-title vt-chip vt-ok|vt-amber|vt-red|vt-unknown vt-row
vt-use vt-dates vt-reason vt-note vt-actions vt-btn vt-bar vt-barfill vt-spend vt-state vt-err
vt-field vt-flabel vt-hint vt-empty vt-formbox`. The existing `console-usage.js` (`#spend`) keeps
working next to it.

## 7. Data (Docs port; equality + single order_by only)

- `jarvis_vitals_providers/{hash(uid, id)}` -- manual records (queried `where user_id == uid`, `order_by label`)
- `jarvis_vitals_status/{hash(uid, id)}` -- last status, for cross-line alerts

The first query is equality + `order_by` on a different field: on real Firestore it needs a composite
index `jarvis_vitals_providers (user_id ASC, label ASC)` in the index file. (`IndexNotReady` surfaces
as "unavailable" until built.)

## 8. Persona (p4.8 -> p4.9, D13)

Add: "JARVIS keeps a Vitals board of your keys, quotas and bills: ask what is running low, when a key
expires, or tell it a key's limit and expiry (never the key itself)."

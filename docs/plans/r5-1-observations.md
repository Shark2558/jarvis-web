# R5.1 — Observations & UI polish (plan)

Owner's observations of 9–10 Nov 2026 (Observations.docx), on the live R4/R5 console. Branch `r5-1` from
`main` (R5 merged, `1c6f770`). Free: no new paid service, no new secret, no new Scheduler job, no model
call added anywhere. One PR.

## What the owner reported (verbatim intent) and the root cause found in the code

| # | Observation | Root cause |
|---|---|---|
| O1 | Vitals panel "very bad, not user friendly"; must match the existing look ("never change the aesthetics … blend with the current theme") | R4's `console-vitals.js` emits `vt-*` classes and **no CSS was ever written** (`vitals/INTEGRATION.md` §6: "Class hooks for the CSS (not written)"). Labels come after inputs; browser-default inputs. Same for `console-systems.js` (`sys*`), `console-connectors.js`, `console-people.js`. No browser test covers any R4 panel. |
| O1b | "JARVIS couldn't open the Vitals list just now" | `VitalsStore.list_manual` queries `where user_id == uid` + `order_by label` → needs a Firestore composite index that `deploy/cloudrun.sh` creates only when re-run. `IndexNotReady` → `VitalsUnavailable` → the WHOLE board answers 503, hiding even the automatic items. |
| O2 | "Key details should be auto fetched and tracked … the owner should never track these items manually" | Auto items today: AI spend, voice allowances, Google SKU quotas. Keys/connections (Claude, Gemini, Google sign-in, Telegram, web-search credits, GitHub token + expiry, home link) are not on the board; the panel leads with "Track a key". |
| O3 | "I turned off the home laptop but there was no ring" | By R3 design the watchdog alerts only while ARMED ("disarmed → the state changes, nobody is told"); the scheduled systems check runs only in the morning window (04:00–11:30) and needs 2 checks before it rings; the offline threshold is 12 minutes. |
| O4 | Systems check should be engaging: say every system checked and which failed; brief vitals, resource use, low funds, expiring keys, what breaks if not fixed; offer a reminder / calendar event; a pop-up that ticks each item as it is checked, shows the result, warns and auto-closes after 10 s if untouched, suggests re-running | Today: one fixed sentence ("Attention: X is not answering"), a plain list in the Integrations panel, no pop-up. |
| O5 | Systems card "not as per previous aesthetics"; "this box should be expandable in both directions" | Unstyled `sys*` rows (name/OK/reason run together); the Integrations panel is `fixed-size` (`resize:none`). |
| O6 | Top bar "Brain: AI on" broken; "the No-AI option did not come" | `#brainModeSlot` is itself a `.status` pill and `console-people.js` appends a second pill (`.bnote.brainmode`) inside it → overflow. The badge is a label, not a control; the AI/No-AI buttons live in the People panel. The go-live guide's "Top bar → Brain: AI on → No-AI" was wrong. |
| O7 | Connectors: "font is not as per the theme and the buttons overlap" | `console-connectors.js` has no CSS: headings in the system font, the "Connected as …" chip and Disconnect overlap. |
| O8 | "Identify and self fix any other UI issues"; "visual UI inspection has to be done before any release" | No visual gate. A full audit (`scripts/ui_snapshots.py` → `/home/claude/r51-ui-audit.md`) lists the rest. |

## Binding decisions

- **D1 — Never change the aesthetics.** Every fix reuses the existing tokens and components in
  `console.css` / `console-deck.css` (fonts `--hud` Rajdhani, `--disp` Orbitron, `--tech` Share Tech Mono;
  `--well`, `--line`, `--tint`, `--ink*`, `--ok/--amber/--bad*`; `.btn`, `.btn.lift`, `.btn.primary`,
  `.k`, `.kv`, `.rhead`, `.integ`/`.ihead`/`.istate`/`.iactions`, `.bnote`, `.bfine`, `.tinput`,
  `#limitForm`'s label-above-input pattern, `<dialog>` styling of `#limitDialog`/`#briefDialog`). No new
  colours, fonts, radii or shadows. Both surfaces (night and day) and all five themes must look right;
  text contrast ≥ 4.5:1 (computed, not eyeballed). ui-ux-pro-max checklist
  (`/root/.cache/ui-ux-pro-max-skill/.claude/skills/ui-ux-pro-max/references/quick-reference.md` §1–§3).
  Each new CSS file is ≤ 300 lines and linked in `console.html` after the existing ones.
- **D2 — Vitals tracks itself.** The board is built from automatic items first; the owner never has to
  type anything for a key JARVIS uses. Manual tracking stays (for things JARVIS cannot see, e.g. an
  insurance renewal) but sits behind a closed "Track something JARVIS can't see" disclosure, with
  labels above inputs, the id derived from the name (no "Id (a-z…)" field shown), and the existing
  "never paste the key" guard unchanged. A failure to read manual items never hides automatic items
  (the board answers 200 with a `manual_unavailable` note). `list_manual` no longer needs a composite
  index (equality query, sorted in Python; ≤ 50 records per owner).
- **D3 — The laptop going quiet always reaches the owner** (I0 done at `d077edc`): new alert kind
  `home_offline_idle` (important; `notify.policy.DAYTIME_RING_KINDS` → rings in waking hours even when
  only urgent things ring; held for the morning summary in quiet hours). Armed stays `home_offline`
  (urgent, rings always). Setting `home_offline_alert = always | armed_only` (default `always`).
  `home_offline_after_s` default 720 → **360** (3 missed beats; the owner hears within ~6–11 min on the
  existing 5-minute watchdog). One alert per outage; "back online" note on return (existing).
- **D4 — Systems check runs around the clock** on the existing 5-minute home-watchdog Scheduler job
  (no new job): the SAME `HealthTickJob` instance is added to the watchdog's job list, so its per-owner
  gate is shared; cadence becomes at most once per **15 minutes** per owner. The `home` probe is
  excluded from `health_fault`/`health_degraded`/`health_recovered` messages (the watchdog owns that
  alert; no double ring). Telegram that is not set up (no bot token, or no paired chat) is left out of
  the report ("not set up"), never "Down — the check itself failed"; a refused token says so.
- **D5 — The spoken briefing is fixed-template, never model text** (works in No-AI mode). It names
  every system checked, which failed and what that breaks ("Telegram is not answering — alerts and
  Telegram chat won't reach you until it's fixed"), then vitals: AI spend vs limit in ₹ (and %), the
  free allowances that are ≥ 80 % used, every amber/red vitals item with its consequence, and ends with
  one question: "Shall I set a reminder to fix this?" (only when something needs attention) or "All
  systems nominal, Sir." Consequence text comes from a fixed map in code keyed by probe key / vitals
  id; never a probe's `reason` string from a vendor; never a key value; never a device name.
  Rupees only. Length cap: about 60 s of speech (≤ 900 characters); the screen shows everything.
- **D6 — The Systems check pop-up** (`console-systems-modal.js` + `console-systems.css`): a modal
  `<dialog>` styled like the console's existing dialogs. Opens from: the Systems card's **Run**, the
  voice command "(Jarvis) run a systems check / systems check / system status" via the R5 local
  command router (free, no AI), and the same words typed in the composer (intercepted before send —
  no AI call). It first lists every system with a pending marker, then ticks each as its result arrives
  (✓ ok / ! degraded / ✕ down, with the word too — never colour alone), then shows the Vitals summary
  and concerns, then speaks the briefing (unless "Speak replies: Never" or voice unavailable).
  Actions: **Set a reminder** (choices: in 1 hour / this evening 6 pm / tomorrow 10 am), **Run again**,
  **Speak again**, **Close**. When results are complete and the briefing has finished speaking (or
  immediately if not speaking), a visible countdown "Closing in 10 s" starts; any pointer, key or focus
  inside the dialog cancels it (and shows "Kept open"). At close JARVIS says/shows: "Closing the
  systems check. Say 'run a systems check' any time for a fresh status, Sir." Esc and the close button
  work; focus is trapped and returned; reduced motion respected; works at 390 px.
- **D7 — Streaming check:** `POST /v1/health/run/stream` answers NDJSON
  (`application/x-ndjson`): `{"type":"plan","systems":[{key,name}]}`, then one
  `{"type":"result", key, name, status, reason}` per probe as it completes, then
  `{"type":"done", overall, spoken, checked_at, systems, briefing:{lines, concerns:[{key,label,
  severity,impact}]}}`. Same auth, CSRF header and per-owner rate limit as `/v1/health/run`;
  `HealthService.check_stream` keeps the cooldown, debounce and alert semantics of `check` (the plan
  event lists the probes in a fixed order). `/v1/health` and `/v1/health/run` also return `briefing`.
  The console falls back to `/v1/health/run` if streaming is unavailable.
- **D8 — Reminders from the pop-up go through the gateway with no AI call:**
  `POST /v1/health/remind {key, when: "1h" | "evening" | "tomorrow"}` builds the reminder text from the
  FIXED label + consequence ("Fix Telegram: alerts and Telegram chat won't reach you") and runs
  `reminder_add` via `gateway.execute` (owner-trusted context, scope console) — the existing policy,
  audit and approval cards apply. Answer: `{outcome: executed|awaiting_confirmation|refused, line}`;
  the pop-up shows "Reminder set for tomorrow, 10:00" or "Approve it in Approvals". Google not
  connected → "Connect Google first, Sir" (no call).
- **D9 — Brain switch in the top bar:** `#brainModeSlot` becomes ONE pill button ("Brain: AI on" /
  "Brain: No-AI") styled exactly like the `.status` pills beside it (no nested pill), with a small
  menu (two options with one-line meanings). Switching to No-AI is immediate; switching back to AI
  asks once inline ("Paid replies resume — switch AI on?"). Keyboard and screen-reader accessible
  (`aria-haspopup="menu"`, `aria-expanded`). The People panel keeps its buttons in sync via the
  existing `jarvis:brainmode` event. Phone: the pill fits (abbreviate to "AI on"/"No-AI").
- **D10 — Panels are resizable in both directions** unless they truly can't be: remove `fixed-size`
  from Integrations and Vitals (keep it only where a panel's layout breaks when resized, with a
  comment saying why). Inner lists scroll; nothing clips.
- **D11 — Visual gate before every release:** `scripts/ui_snapshots.py` (screenshots of every panel,
  desktop 1440×900 + phone 390×844, night + day) and a browser test `tests/browser/test_ui_audit.py`
  that, for every panel at both widths and both surfaces, asserts: no two visible interactive
  elements overlap; every visible text/control uses a theme font family; no element overflows its
  panel horizontally; every visible form control has a visible label or aria-label; no button text
  wraps onto a third line; no horizontal page scroll on the phone. The release checklist in the
  go-live guide gains "screenshots inspected".
- **D12 — Persona p5.1:** "Run a systems check" opens the pop-up and the briefing; JARVIS keeps its
  own Vitals (the owner never has to type a key's details); the No-AI switch is the top-bar Brain pill.

## Parts (builders own ONLY their files; shared wiring is I1's)

- **Part A — UI polish + visual gate (frontend):** `console-connectors.js` + new `console-connectors.css`;
  `console-people.js` + new `console-people.css` (people panel + D9 top-bar brain pill);
  `console-deck.css`/`console.css` ONLY for D10 and for global defects from the audit report;
  older panels' CSS files named in the audit; `scripts/ui_snapshots.py`; `tests/browser/test_ui_audit.py`;
  browser tests for Connectors, People and the brain pill. Not: vitals, systems files.
- **Part B — Vitals tracks itself:** `src/jarvis/vitals/*` (+ `integrations/github.py` only to record the
  token's expiry header on connect/read), `console-vitals.js`, new `console-vitals.css`, unit tests,
  `tests/browser/test_vitals_board.py`. Reads other features through Protocols defined in
  `vitals/` (health last-report reader, brain router health, Google status, Telegram configured, web
  usage reporter, GitHub record, home status) — I1 wires them.
- **Part C — Systems check experience + offline ring:** `src/jarvis/health/*` (briefing, stream,
  remind route, tick cadence, telegram/home rules), `src/jarvis/home/watchdog.py` (D3), new
  `console-systems-modal.js` + `console-systems.css`, `console-systems.js`, the local command in
  `console-voice-commands.js`, unit + browser tests (`tests/browser/test_systems_check.py`). The
  composer intercept in `console.js`, the watchdog job list and persona are I1's.

## Exit checks
- Vitals: board opens with no composite index; automatic items for every configured key/connection;
  no manual typing needed; manual form hidden by default and styled.
- Laptop off while disarmed → one ringing alert within ~11 min in waking hours (held at night).
- "Run a systems check" (voice or typed or Run) → pop-up ticks each system, speaks the full briefing,
  offers a reminder, closes after 10 s untouched with a spoken/visible notice.
- Brain pill in the top bar switches to No-AI and back.
- `test_ui_audit.py` passes for every panel; screenshots inspected by eye before the PR.
- Unit (3.11 + 3.12), mock evals, browser suite, ruff, mypy baseline 9, size guards.

## D13–D14 (integrated review decisions, 10 Nov 2026)

- **D13 — A health fault or a red vitals line never rings at night.** The systems check now runs 24/7
  (D4), so `health_fault` and `vitals_critical` move from "urgent" to "important" and join
  `notify.policy.DAYTIME_RING_KINDS` (with `home_offline_idle`): they ring in waking hours even when only
  urgent things ring, and are held for the morning summary in quiet hours. The storm's soft caps
  (`storm.SOFT_URGENT_KINDS`: one per subject per 30 minutes, 6 an hour) are keyed on the KIND, not the
  urgency, so they still bound these two. Hazards, burglar rings and an armed `home_offline` stay urgent
  (they ring through the night). R4 pins that asserted "urgent" now carry a comment pointing here
  (`tests/test_r3_seams.py`, `tests/test_r51_seams.py`, `evals/r4_needles/run.py`: f01 is the waking-hours
  ring, f01n is the held-at-night check, and the "demote" negative control now removes the faults from the
  daytime-ring set). Tests: `tests/test_r51_int_notify.py`.
- **D14 — Time-based debounce.** A fault is confirmed only by two checks at least 4 minutes apart
  (`changes.DEBOUNCE_GAP_S`); a recovery by three whose first and last are at least 8 minutes apart
  (`RECOVERY_SPREAD_S`). A check closer than 4 minutes to the last COUNTED one is the same moment and does
  not count, so a pop-up run right after another (or `/run` plus `/run/stream`) cannot confirm a blip. A
  streak is stored as `[status, count, first_at, last_counted_at]`; a streak stored before R5.1 (no times)
  counts as old enough, once. Tests: `tests/test_r51_int_debounce.py`.
- **Other integrated fixes recorded here:** the systems check can never make the 5-minute laptop watchdog
  answer 503 (probe 5 s < check 20 s < job deadline 25 s < tick budget 30 s; an unsaved report or a late
  owner is "degraded", and `Watchdog` reports the health job as `degraded` instead of `failed`); the
  outage alert slot is taken with a store compare-and-set before sending (`HomeStore.claim_alert`, a lease
  of 120 s so a crashed run's claim expires); `GET /v1/health` has its own 30/min limit and the briefing
  reads the 15 s cached board; `PUT`/`DELETE /v1/vitals/keys` are limited to 10/min per owner and the
  50-record cap is counted inside the write transaction (an index document); stream coalescing ignores
  `force` on purpose (a run in flight is fresh by definition); the brain pill never claims a mode before
  the server answers, switches one at a time, and AI back on always asks (menu, People button and
  `JarvisBrainMode.set('ai')` end in the same confirm); the visual gate also audits the top bar, the open
  brain menu and its confirm, the systems pop-up with concerns and the open Vitals form.

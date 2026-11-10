# R5.1 Part A -- integration notes (for the integrator)

Part A touched no shared wiring file. Everything below is what the integrator must add.

## 1. `console.html`

Link the two new stylesheets after `console-alerts.css` (line ~40):

```html
<link rel="stylesheet" href="/static/console-connectors.css">
<link rel="stylesheet" href="/static/console-people.css">
```

(Part B/C add their own `console-vitals.css` / `console-systems.css` the same way.)

`#brainModeSlot` (line ~55). `console-people.js` now rewrites the slot itself (class `bmslot`, one `<button class="status brainmode" id="brainModeBadge">` plus the menu), so the old markup still works. To avoid a flash of an empty pill before the script runs, replace

```html
<!-- R4 D (console-people.js): "Brain: AI on" / "No-AI (brain only)"; speech is metered apart -->
<span class="status brainmode" id="brainModeSlot"></span>
```

with

```html
<!-- R5.1 D9 (console-people.js): ONE pill button, "Brain: AI on" / "Brain: No-AI", with a small menu -->
<span class="bmslot" id="brainModeSlot"></span>
```

Defect #23: People panel meta (line ~604): `<span class="pmeta" id="peopleMeta">Public figures</span>`
(it was "Public figures and work due-diligence" and is truncated).

No new `<script>` tag: the pill lives in `console-people.js` (235 lines).

## 2. `src/jarvis/api/console.py` (the /static allow-list)

Add (next to the other `.css` entries):

```python
"console-connectors.css": "text/css",
"console-people.css": "text/css",
```

Until this is done the two stylesheets 404 in a real browser. `tests/browser/ui_checks.py`
(`inject_unlinked_css`) serves any `console-*.css` that `console.html` does not link yet through
`page.route`, so the visual gate and Part A's tests pass both before and after the wiring.

## 3. D10 -- panels carrying `fixed-size` in `console.html`

| Panel | Line | Resizable? |
|---|---|---|
| `#p-approvals` | ~214 | Not asked to change by D10 (it names Integrations and Vitals only). It also survives resizing (test below), so removing it is safe if you want it. |
| `#p-integrations` | ~487 | Yes. `test_fixed_size_panels_survive_being_resized[integrations]` removes the class, sets 300x320, 560x760 and 900x500 and checks no sideways scroll in `.pbody`, no page scroll and no overlap. It passes with Part A only; re-run after Part C's Systems card lands. |
| `#p-vitals` | ~524 | Yes, same test. Re-run after Part B's board lands. |

Remove the `fixed-size` class from `#p-integrations` and `#p-vitals`. Nothing else is needed:
`console-deck.js` reads `resizable: !el.classList.contains('fixed-size')`, and `.panel.fixed-size{resize:none}`
(console-deck.css:113) is the only rule involved. Vitals' default width 300 (console-deck.js defaults) should
become 340 like Integrations if you want the board to breathe (audit #14).

## 4. Part A defects that need nothing from you

#1 (Privacy `.pv` swatch rule scoped to `#themeMenu`), #2 (brain pill, console-deck.css + console-people.js),
#5 #6 #12(connectors) #25 (console-connectors.js/css), #8 #9 #11 (console-people.js/css), #17 (WhatsApp
drafts: short state word in `.istate`, the sentence in `.ibody`), #18 (Home: console-home-panel.css), #19
(CSS only: `#auditOk{white-space:nowrap}` in console-activity.css, `console.js` untouched), #20
(console-family.css), #21 (console-home.js), #24 (Things: labels above the fields, short placeholders).

## 5. The visual gate (D11)

`tests/browser/test_ui_audit.py` runs 20 panels x desktop/phone x night/day (80 cases). Run the full gate
once the three parts are merged:

```
JARVIS_BROWSER_TESTS=1 PYTHONPATH=src /tmp/venv-c/bin/python -m pytest -q tests/browser/test_ui_audit.py -m browser
```

Part A verified it with `-k "not vitals and not integrations"` (68 passed). Shared mocks and the in-page
checks live in `tests/browser/ui_checks.py`; `scripts/ui_snapshots.py` imports the same module.
Add "screenshots inspected (scripts/ui_snapshots.py, looked at)" to the go-live checklist.
Update `READY` in `ui_checks.py` if Part B/C name their rows differently (it is best-effort, never fatal).

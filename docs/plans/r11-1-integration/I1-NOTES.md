Version v11.1.1 · 12 Nov 2026, 11:20 IST · Release R11.1 · Status: Current · Owner: 🛠 Mark XV

# R11.1 I1 — integration notes (Mark XV)

Branch `r11-1-i1`, from `r11-1-i0` @ `1d49a1c`. What the integrator joined, every conflict and how it
was resolved, every cross-part issue, each merge gate and "Needs I1" item with its test, and what is
left. The parts' own notes are `INTEGRATION-A.md` … `INTEGRATION-D.md` beside this file.

## 1. Merges

| # | Merged | At | Conflicts | Resolution |
|---|---|---|---|---|
| 1 | `origin/main` | `665fce0` | none | test-only (`tests/browser/test_dock_fit.py`, Mark XIV's `bf75cf2`) |
| 2 | `origin/r11-1-a` | `a5f2020` | none | — |
| 3 | `origin/r11-1-b` | `06db8c1` | none | — |
| 4 | `origin/r11-1-c` | `1de44b6` | none | — |
| 5 | `origin/r11-1-d` | `7bdaf96` | none | — |

No file was changed by more than one part, and none of the parts touched the three files I0 changed
after the builders forked (`buildbook/gen/layers.py`, the two book tests, `tests/test_trust_flag.py`
are I0's and merged as they were). The joins are semantic, not textual: section 2.

## 2. Gates and "Needs I1" items

(filled in as each lands)

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v11.1.1 | 12 Nov 2026, 11:20 IST | R11.1 | First edition: the five merges | 🛠 Mark XV |

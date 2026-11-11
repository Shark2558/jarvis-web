# src/jarvis/helpers/__init__.py
"""R11: the free proactive helpers (Layer 5 skills; docs/plans/r11-free-helpers.md).

One package, four plug-ins (D2). The I0 core is here: `kinds` (the fixed names every part uses),
`ports` (the `HelperPart` a part's `build(ctx)` returns and the `HelperContext` it gets), `gate`
(the one sender for every helper message, with the nudge limits), `clock` (the 5-minute and the
morning composites), `brief` (the brief's "Helpers" section), `sources` (the outside services'
fixed addresses) and `privacy` (the nudge state's privacy row). The parts are the sub-packages
`today` (A: bills, birthdays, top priority), `house` (B: chores, upkeep, weather, disasters,
breach notices), `nudges` (C) and `kitchen` (D); `api/r11_wiring.py` builds them.
"""

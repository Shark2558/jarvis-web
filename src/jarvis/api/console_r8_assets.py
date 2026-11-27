# src/jarvis/api/console_r8_assets.py
"""R8 I0 (docs/plans/r8-vision.md section 7.1, seam S18): every console file R8 and R8.1 add,
joined into `jarvis.api.console.APP_ASSETS`, the console's one exact allow-list (each name is a
literal: no route builds a path from request input). Kept here so console.py stays inside its size
guard. Who loads each file is pinned by tests/test_r51_console_assets_linked.py."""

from __future__ import annotations

from typing import Final

_JS: Final = "application/javascript"

R8_ASSETS: Final[dict[str, str]] = {
    "console-vision-r8.js": _JS,  # A: pose v2, hands, digits; imported by console-vision.js
    # A: the setup test (an engine file); imported by the Cameras pane
    "console-vision-check.js": _JS,
    "console-coach-geom.js": _JS,  # I0: the coaches' pure geometry; imported by the use cases
    "console-coach-desk.js": _JS,  # C: Camera -> Desk, a pixel pane; loaded by console-r7.js
    "console-coach-workout.js": _JS,  # E: Camera -> Workout, a pixel pane; loaded by console-r7.js
    "console-coach-view.js": _JS,  # C: the panes' one view renderer
    "console-coach-bp.js": _JS,  # D: the monitor's reading from `digits` (pure)
    "console-coach.css": "text/css",  # C: the panes' places only
    "console-camera-setup.js": _JS,  # B: Camera -> Cameras' setup, a pixel pane
    "console-camera-setup.css": "text/css",  # B: its places only
    "console-dock-layout.js": _JS,  # I0: the bar's layout model (pure, D13)
    "console-dock-edit.js": _JS,  # I: the bar's editor; loaded by console-r7.js
    "console-dock-edit.css": "text/css",  # I: the edit mode's places only
    # the use cases' modules (D: the webcam's; E-H: the workout phone's), imported by their pane
    "console-coach-reaction.js": _JS,
    "console-coach-breath.js": _JS,
    "console-coach-water.js": _JS,
    "console-coach-handrehab.js": _JS,
    "console-coach-reach.js": _JS,
    "console-coach-reps.js": _JS,
    "console-coach-warmup.js": _JS,
    "console-coach-band.js": _JS,
    "console-coach-form.js": _JS,
    "console-coach-yoga.js": _JS,
    "console-coach-plank.js": _JS,
    "console-coach-space.js": _JS,
    "console-coach-balance.js": _JS,
    "console-coach-boxing.js": _JS,
    "console-coach-agility.js": _JS,
    "console-coach-pilates.js": _JS,
    "console-coach-taichi.js": _JS,
    "console-coach-jump.js": _JS,
    "console-coach-dance.js": _JS,
    "console-coach-handstand.js": _JS,
    "console-coach-kettlebell.js": _JS,
    "console-coach-partner.js": _JS,
    "console-coach-walk.js": _JS,
    "console-coach-sitstand.js": _JS,
    "console-coach-meal.js": _JS,
}

__all__ = ["R8_ASSETS"]

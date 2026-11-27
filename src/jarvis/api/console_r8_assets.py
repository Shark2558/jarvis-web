# src/jarvis/api/console_r8_assets.py
"""R8 I0 (docs/plans/r8-vision.md section 7.1, seam S18): every console file R8 and R8.1 add,
joined into `jarvis.api.console.APP_ASSETS`, the console's one exact allow-list (each name is a
literal: no route builds a path from request input). Kept here so console.py stays inside its size
guard. Who loads each file is pinned by tests/test_r51_console_assets_linked.py."""

from __future__ import annotations

from typing import Final

_JS: Final = "application/javascript"

R8_ASSETS: Final[dict[str, str]] = {
    "console-vision-r8.js": _JS,  # A: pose v2 and hands, imported by console-vision.js
}

__all__ = ["R8_ASSETS"]

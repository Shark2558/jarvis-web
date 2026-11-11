# src/jarvis/api/helpers_nudges.py
"""R11 Part C's routes, under `/v1/helpers/nudges` (docs/plans/r11-free-helpers.md D2).

I0 stub: the router with no routes yet. Part C adds its owner-only, `no-store` routes here
(and only here); they read the part's services from `app.state.r11_parts["nudges"].services` per
request and answer 404 {error: "helpers_off"} when the part is off. `install_r11_routes` mounts it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from jarvis.api.auth import require_auth

PREFIX = "/v1/helpers/nudges"
router = APIRouter(prefix=PREFIX, dependencies=[Depends(require_auth)])

__all__ = ["PREFIX", "router"]

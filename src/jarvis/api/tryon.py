# src/jarvis/api/tryon.py
"""R13.1 Part A's routes, under `/v1/tryon` (docs/plans/r13-1-try-on.md "The HTTP contract"):
I0's STUB (no route yet). Part A fills this router with exactly the `jarvis.wardrobe.tryon.http`
`ROUTES` rows of "tryon": each owner-only (`require_auth`), `no-store`, limited per owner
(`r13_status.limited`), answering `Refusal` (`{"error", "detail"}`). Its services come from
`app.state.r13_parts["tryon"]` per request (`r13_status.part_of`); `POST /v1/tryon/confirm` makes
its ONE `outfit_plan` call through `api.wardrobe.run_panel_tool` (D20). The wiring installs it."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from jarvis.api.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])

__all__ = ["router"]

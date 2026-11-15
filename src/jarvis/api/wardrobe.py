# src/jarvis/api/wardrobe.py
"""R13 Part A's routes, under `/v1/wardrobe` (docs/plans/r13-wardrobe.md "The HTTP contract").

I0 stub: no route yet. Part A fills this router with exactly the routes and models of
`jarvis.wardrobe.http` (its `ROUTES` rows for "catalog"), each owner-only (`require_auth`),
`no-store`, limited per owner (`api.r13_status.limited`), reading its services from
`app.state.r13_parts["catalog"]` per request (`api.r13_status.part_of`). `api/r13_wiring.py`
includes it once; no part edits the wiring.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from jarvis.api.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])

__all__ = ["router"]

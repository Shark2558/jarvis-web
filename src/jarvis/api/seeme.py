# src/jarvis/api/seeme.py
"""R13.1 Part C's routes, under `/v1/seeme` (docs/plans/r13-1-try-on.md "The HTTP contract",
D10-D15): I0's STUB (no route yet). Part C fills this router with exactly the
`jarvis.wardrobe.tryon.http` `ROUTES` rows of "seeme": each owner-only (`require_auth`),
`no-store`, limited per owner (`r13_status.limited`; `POST /v1/seeme/pictures` with
`per=model.PRESSES_A_MINUTE`), answering `Refusal`; the rows marked console only also pass
`api.book_gate.console_only`'s rule (a signed-in browser, never a bearer token). The wiring
installs it."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from jarvis.api.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])

__all__ = ["router"]

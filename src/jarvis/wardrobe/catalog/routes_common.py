# src/jarvis/wardrobe/catalog/routes_common.py
"""What Part A's routes share (docs/plans/r13-wardrobe.md "The HTTP contract"; `api/wardrobe.py`
and `routes_files.py`): his desk from the app's built part, the per-owner allowance (30 changes
and 60 reads a minute), and plain-words replies that are `no-store` and never carry a stack, a
class name or his text: an error is `{"detail": <words>}` with a status from `wardrobe.http.ROUTES`.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from jarvis.api.r13_status import NO_STORE, limited, part_of, ready_of
from jarvis.logging import get_logger
from jarvis.wardrobe.catalog.store import WardrobeUnavailable
from jarvis.wardrobe.ports import Refused

log = get_logger(__name__)
OFF = "The wardrobe is off on this server."
NO_STORE_HEADERS: dict[str, str] = dict(NO_STORE)


def ok(model: BaseModel, status: int = 200) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json"), status_code=status, headers=NO_STORE)


def err(status: int, words: str) -> JSONResponse:
    return JSONResponse({"detail": words}, status_code=status, headers=NO_STORE)


def desk_of(request: Request) -> Any:
    """Part A's desk, or None when the part is off (no key, no store, setup failed)."""
    part = part_of(request, "catalog")
    store = part.services.get("store") if part is not None else None
    return getattr(store, "desk", None)


def off_words(request: Request) -> str:
    ready = ready_of(request, "catalog")
    return ready if ready.startswith("Off") else OFF


def off(request: Request, status: int = 503) -> JSONResponse:
    return err(status, off_words(request))


def too_many(request: Request, route: str, uid: str, *, change: bool) -> JSONResponse | None:
    return limited(request, route, uid, change=change)


def refused(exc: Exception, *, status: int = 422, down: int = 503) -> JSONResponse:
    """A refusal in his words (`status`, or the refusal's own); storage trouble is `down` (503,
    or the route's nearest status when its contract has no 503) in ours."""
    if isinstance(exc, WardrobeUnavailable):
        return err(down, str(exc))
    if isinstance(exc, Refused):
        return err(getattr(exc, "status", status), str(exc))
    log.warning("wardrobe route failed", extra={"error": type(exc).__name__})
    return err(down, "That couldn't be done just now. Try again in a minute.")


__all__ = [
    "NO_STORE_HEADERS",
    "OFF",
    "desk_of",
    "err",
    "off",
    "off_words",
    "ok",
    "refused",
    "too_many",
]

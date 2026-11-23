# src/jarvis/api/book_pages.py
"""R6.3 D14, D13 (docs/plans/r6-3-book-content.md "The HTTP contract"): the full book's pages
under `/v1/book/pages`, exactly `buildbook/writer/http.ROUTES` (gate "session").

Signed in (`require_auth`), the PRIMARY owner only (403 `not_primary`, L11), an OWNER book
session's `X-Jarvis-Book` (a guest's is 403 `owner_only`), `no-store`, 60 a minute. A kept
release's pages index (parts -> chapters -> pages, `limitations {shown, total}`) and one page
(written, or the generator's text "Not written by AI yet"; 404 `no_page`). A pages file whose
release R6's index doesn't keep is never served.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from jarvis.api.auth import require_auth
from jarvis.api.book_gate import BookRefused, owner_session
from jarvis.api.book_http import TOKEN_HEADER
from jarvis.api.book_writer import answered, limited, primary, service_of
from jarvis.buildbook.facts_model import PAGE_ID
from jarvis.buildbook.model import RELEASE_ID
from jarvis.buildbook.writer.http import PAGES_PREFIX, ROUTES  # by name: A's route scan (M9)
from jarvis.buildbook.writer.texts import REFUSED

NOT_BUILT_WORDS = "The full book isn't built on this server yet."
router = APIRouter(prefix=PAGES_PREFIX, dependencies=[Depends(require_auth)])
Act = Callable[[Any, str, str | None, Request], Awaitable[BaseModel]]


def release_of(request: Request) -> str | None:
    rid = request.query_params.get("release")
    if rid is None or rid == "":
        return None
    if not re.fullmatch(RELEASE_ID, rid):
        raise BookRefused(404, "no_page", REFUSED["no_page"])
    return rid


def route(act: Act) -> Callable[[Request], Awaitable[JSONResponse]]:
    async def handler(request: Request) -> JSONResponse:
        svc = service_of(request)
        uid = primary(request, svc)
        await owner_session(request, uid, request.headers.get(TOKEN_HEADER))
        limited(request, "pages", uid)
        return await answered(act(svc, uid, release_of(request), request))

    return handler


async def _index(svc: Any, uid: str, rid: str | None, request: Request) -> BaseModel:
    return await svc.pages_view(uid, rid)  # type: ignore[no-any-return]


async def _page(svc: Any, uid: str, rid: str | None, request: Request) -> BaseModel:
    page_id = str(request.path_params.get("page_id", ""))
    if not re.fullmatch(PAGE_ID, page_id):
        raise BookRefused(404, "no_page", REFUSED["no_page"])
    return await svc.page(uid, page_id, rid)  # type: ignore[no-any-return]


P = PAGES_PREFIX
ACTS: dict[tuple[str, str], Act] = {("GET", P): _index, ("GET", f"{P}/{{page_id}}"): _page}
for _method, _path, _part, _req, _reply, _codes, _gate in ROUTES:
    if _path.startswith(P):
        router.add_api_route(
            _path.removeprefix(P), route(ACTS[(_method, _path)]), methods=[_method], name=_path
        )


def install_book_pages(app: FastAPI) -> None:
    """Mounted by `r6_wiring.install_r6_routes` after `install_book_writer` (its limits)."""
    app.include_router(router)


__all__ = ["NOT_BUILT_WORDS", "install_book_pages", "router"]

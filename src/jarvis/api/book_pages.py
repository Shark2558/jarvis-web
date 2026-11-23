# src/jarvis/api/book_pages.py
"""R6.3 D14, D13 (docs/plans/r6-3-book-content.md "The HTTP contract"): the full book's pages
under `/v1/book/pages` (`buildbook/writer/http.ROUTES`, gate "session"). PART B fills this file:
an OWNER book session's `X-Jarvis-Book` (a guest's is 403 `owner_only`), the primary owner only,
`no-store`, 60 a minute, a kept release's pages index and one page (or the generator's text,
"Not written by AI yet"). I0's stub: signed in, then 503 `not_built_yet`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from jarvis.api.auth import require_auth
from jarvis.api.book_gate import BookRefused, console_only
from jarvis.buildbook.writer.http import NOT_BUILT, PAGES_PREFIX, ROUTES

NOT_BUILT_WORDS = "The full book isn't built on this server yet."
router = APIRouter(prefix=PAGES_PREFIX, dependencies=[Depends(require_auth)])


def _stub(gate: str) -> Callable[[Request], Awaitable[JSONResponse]]:
    async def not_built(request: Request) -> JSONResponse:
        if gate == "console":
            console_only(request)
        raise BookRefused(503, NOT_BUILT, NOT_BUILT_WORDS)

    return not_built


for _method, _path, _part, _req, _reply, _codes, _gate in ROUTES:
    if _path.startswith(PAGES_PREFIX):
        router.add_api_route(
            _path.removeprefix(PAGES_PREFIX), _stub(_gate), methods=[_method], name=_path
        )


def install_book_pages(app: FastAPI) -> None:
    """Mounted by `r6_wiring.install_r6_routes` after `install_book` (its refusal handler)."""
    app.include_router(router)


__all__ = ["NOT_BUILT_WORDS", "install_book_pages", "router"]

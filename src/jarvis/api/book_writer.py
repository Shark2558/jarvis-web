# src/jarvis/api/book_writer.py
"""R6.3 D6, D7, D12 (docs/plans/r6-3-book-content.md "The HTTP contract"): the writer's console
routes under `/v1/book/writer` (`buildbook/writer/http.ROUTES`, gate "console"). PART B fills
this file: the primary owner only (403 `not_primary`, L11), `book_gate.console_only` (a signed-in
browser), `no-store`, the limits of `http.LIMITS`, every refusal a `Refusal` in plain words, every
grant of spending his typed YES on the Rs shown (H2). I0's stub: signed in, console only, then 503
`not_built_yet` on every route.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from jarvis.api.auth import require_auth
from jarvis.api.book_gate import BookRefused, console_only
from jarvis.buildbook.writer.http import NOT_BUILT, ROUTES, WRITER_PREFIX

NOT_BUILT_WORDS = "The Book's writer isn't built on this server yet."
router = APIRouter(prefix=WRITER_PREFIX, dependencies=[Depends(require_auth)])


def _stub(gate: str) -> Callable[[Request], Awaitable[JSONResponse]]:
    async def not_built(request: Request) -> JSONResponse:
        if gate == "console":
            console_only(request)
        raise BookRefused(503, NOT_BUILT, NOT_BUILT_WORDS)

    return not_built


for _method, _path, _part, _req, _reply, _codes, _gate in ROUTES:
    if _path.startswith(WRITER_PREFIX):
        router.add_api_route(
            _path.removeprefix(WRITER_PREFIX), _stub(_gate), methods=[_method], name=_path
        )


def install_book_writer(app: FastAPI) -> None:
    """Mounted by `r6_wiring.install_r6_routes` after `install_book` (its refusal handler)."""
    app.include_router(router)


__all__ = ["NOT_BUILT_WORDS", "install_book_writer", "router"]

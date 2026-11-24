# src/jarvis/api/book_pages.py
"""R6.3 D14; R6.3.1 D7 (docs/plans/r6-3-1-book-at-build.md): the full book's pages under
`/v1/book/pages`, exactly `buildbook/writer/http.ROUTES`.

Signed in (`require_auth`), the PRIMARY owner only (403 `not_primary`, L11), an OWNER book
session's `X-Jarvis-Book` (a guest's is 403 `owner_only`), in the console only as R6's sections
(a bearer script with a book token is 403 `console_only`, G11), `no-store`, 60 a minute. A kept
release's pages index (parts -> chapters -> pages, `limitations {shown, total}`) and one page
(written by the Workshop, or the generator's text "Not written yet"; with `flow`, its flowchart
or null; 404 `no_page`), read from the pages and flows files sealed with that release
(`writer/serve.BookPages` on `app.state.book_pages`). Nothing here logs a value or page text.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from jarvis.api.auth import require_auth, session_email
from jarvis.api.book_gate import BookRefused, console_only, limit, need, owner_session
from jarvis.api.book_http import TOKEN_HEADER, book_json
from jarvis.buildbook.facts_model import PAGE_ID
from jarvis.buildbook.model import RELEASE_ID
from jarvis.buildbook.writer.http import PAGES_PREFIX, ROUTES  # by name: A's route scan
from jarvis.buildbook.writer.texts import REFUSED, PagesRefused

router = APIRouter(prefix=PAGES_PREFIX, dependencies=[Depends(require_auth)])
Act = Callable[[Any, str, str | None, Request], Awaitable[Any]]


def primary(request: Request, svc: Any) -> str:
    """The primary owner's id (L11, the service's); another owner's browser is 403
    `not_primary`."""
    s = request.app.state.settings
    email = session_email(request, s)
    owners = tuple(e.lower() for e in s.owner_emails)
    if email is not None and owners and email.lower() != owners[0]:
        raise BookRefused(403, "not_primary", REFUSED["not_primary"])
    return str(svc.uid)


def release_of(request: Request) -> str | None:
    rid = request.query_params.get("release")
    if rid is None or rid == "":
        return None
    if not re.fullmatch(RELEASE_ID, rid):
        raise BookRefused(404, "no_page", REFUSED["no_page"])
    return rid


def route(act: Act) -> Callable[[Request], Awaitable[JSONResponse]]:
    async def handler(request: Request) -> JSONResponse:
        svc = need(request, "book_pages")
        uid = primary(request, svc)
        await owner_session(request, uid, request.headers.get(TOKEN_HEADER))
        console_only(request)  # after the session: an unsigned script stays 401 (review I1 L-1)
        limit(request, "pages", uid)
        try:
            body = await act(svc, uid, release_of(request), request)
        except PagesRefused as no:
            return book_json({"error": no.code, "detail": no.detail}, no.status)
        return book_json(body.model_dump(mode="json") if hasattr(body, "model_dump") else body)

    return handler


async def _index(svc: Any, uid: str, rid: str | None, request: Request) -> Any:
    return await svc.index(uid, rid)


async def _page(svc: Any, uid: str, rid: str | None, request: Request) -> Any:
    page_id = str(request.path_params.get("page_id", ""))
    if not re.fullmatch(PAGE_ID, page_id):
        raise BookRefused(404, "no_page", REFUSED["no_page"])
    return await svc.page(uid, page_id, rid)


P = PAGES_PREFIX
ACTS: dict[tuple[str, str], Act] = {("GET", P): _index, ("GET", f"{P}/{{page_id}}"): _page}
for _method, _path, _part, _req, _reply, _codes, _gate in ROUTES:
    if _path.startswith(P):
        router.add_api_route(
            _path.removeprefix(P), route(ACTS[(_method, _path)]), methods=[_method], name=_path
        )


def install_book_pages(app: FastAPI) -> None:
    """Mounted by `r6_wiring.install_r6_routes` after `install_book` (its refusal handler; the
    wiring adds the `pages` limit, `http.LIMITS`, to R6's per-owner limits)."""
    app.include_router(router)


__all__ = ["install_book_pages", "primary", "router"]

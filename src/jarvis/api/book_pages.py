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

R6.4 D4-D6 (docs/plans/r6-4-book-look.md), behind the same gates, in this order (the gate before
any reading of the request): `GET /v1/book/chapters` and `/v1/book/chapters/{chapter_id}` (404
`no_chapter`), 60 a minute with the pages; `GET /v1/book/pages/search?q=` (422 `bad_query`), on its
own limit (`http.LIMITS["search"]`, installed here). `install_book_pages` also mounts the reader's
page, `/book/read` (`api/book_read.py`).
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
from jarvis.api.book_read import install_book_read
from jarvis.api.ratelimit import RateLimiter
from jarvis.buildbook.book.chapters import CHAPTER_ID
from jarvis.buildbook.facts_model import PAGE_ID
from jarvis.buildbook.model import RELEASE_ID
from jarvis.buildbook.writer import search
from jarvis.buildbook.writer.http import CHAPTERS_PREFIX, LIMITS, PAGES_PREFIX, ROUTES
from jarvis.buildbook.writer.texts import REFUSED, PagesRefused

router = APIRouter(prefix=PAGES_PREFIX, dependencies=[Depends(require_auth)])
# R6.4: a router a prefix, so the fact pack's route scan reads each loop's rows (gen/facts_routes)
chapters_router = APIRouter(prefix=CHAPTERS_PREFIX, dependencies=[Depends(require_auth)])
Act = Callable[[Any, str, str | None, Request], Awaitable[Any]]
SEARCH = f"{PAGES_PREFIX}/search"


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


def route(act: Act, limited: str = "pages") -> Callable[[Request], Awaitable[JSONResponse]]:
    async def handler(request: Request) -> JSONResponse:
        svc = need(request, "book_pages")
        uid = primary(request, svc)
        await owner_session(request, uid, request.headers.get(TOKEN_HEADER))
        console_only(request)  # after the session: an unsigned script stays 401 (review I1 L-1)
        limit(request, limited, uid)
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


async def _chapters(svc: Any, uid: str, rid: str | None, request: Request) -> Any:
    return await svc.chapters(uid, rid)


async def _chapter(svc: Any, uid: str, rid: str | None, request: Request) -> Any:
    chapter_id = str(request.path_params.get("chapter_id", ""))
    if not re.fullmatch(CHAPTER_ID, chapter_id):
        raise PagesRefused("no_chapter")
    return await svc.chapter(uid, chapter_id, rid)


async def _search(svc: Any, uid: str, rid: str | None, request: Request) -> Any:
    q = search.normal_query(request.query_params.get("q", ""))
    if q is None:
        raise PagesRefused("bad_query")
    return await svc.search(uid, q, rid)


P, C = PAGES_PREFIX, CHAPTERS_PREFIX
ACTS: dict[tuple[str, str], Act] = {
    ("GET", P): _index, ("GET", SEARCH): _search, ("GET", f"{P}/{{page_id}}"): _page,
    ("GET", C): _chapters, ("GET", f"{C}/{{chapter_id}}"): _chapter,
}  # fmt: skip
for _method, _path, _part, _req, _reply, _codes, _gate in ROUTES:
    if _path.startswith(P):
        act = route(ACTS[(_method, _path)], "search" if _path == SEARCH else "pages")
        router.add_api_route(_path.removeprefix(P), act, methods=[_method], name=_path)
for _method, _path, _part, _req, _reply, _codes, _gate in ROUTES:
    if _path.startswith(C):
        chapters_router.add_api_route(
            _path.removeprefix(C), route(ACTS[(_method, _path)]), methods=[_method], name=_path
        )


def install_book_pages(app: FastAPI) -> None:
    """Mounted by `r6_wiring.install_r6_routes` after `install_book` (its refusal handler; the
    wiring adds the `pages` limit to R6's per-owner limits). R6.4: the other `http.LIMITS` (the
    search's) are added here when the wiring hasn't, and the reader's page with them."""
    limits = app.state.book_limits
    for name, per_minute in LIMITS.items():
        limits.setdefault(name, RateLimiter(per_minute))
    app.include_router(router)
    app.include_router(chapters_router)
    install_book_read(app)


__all__ = ["chapters_router", "install_book_pages", "primary", "router"]

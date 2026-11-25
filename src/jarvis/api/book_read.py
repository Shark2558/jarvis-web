# src/jarvis/api/book_read.py
"""R6.4 D1, D2 (docs/plans/r6-4-book-look.md): the full book's own page, `GET /book/read`
(`static/book-read.html`), and its Book-only assets, mounted by `api/book_pages.install_book_pages`.

The page is served exactly as the show's `/book/show` (`console._page`: no-store, nosniff, never
framed, no referrer, the ONE console CSP, `script-src 'self'`): it holds no data. It reads the
owner's book token from THIS tab's sessionStorage (the Book panel puts it there on "Read the full
book", as for the show) and asks `/v1/book/chapters`, `/v1/book/pages...` with it; a guest never
gets an owner token, so a guest never reads it. The guest lock (`api/book_lock.py`) does NOT let
`/book/read` through: under a lock it is 423 like any owner screen (only the show passes).

Each asset is one literal route (as `console.APP_ASSETS`): no path is ever built from the request.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.responses import HTMLResponse

from jarvis.api.console import _asset_endpoint, _page

READ_PAGE = "/book/read"
JS = "application/javascript"
READ_ASSETS: dict[str, str] = {
    "book-read.css": "text/css",  # I0: the Book-only tokens and the page's layout (D2, D3)
    "console-book-read.js": JS,  # A: contents, page, search, continue (I0: the token hand-off)
    "console-book-chapter.js": JS,  # B: the chapter player (ES module)
    "console-book-fx.js": JS,  # B: the effects engine, D11 (ES module, imported by the player)
}
router = APIRouter()


@router.get(READ_PAGE, include_in_schema=False, response_class=HTMLResponse)
async def book_read() -> HTMLResponse:
    return _page("book-read.html")


for _name, _type in READ_ASSETS.items():
    router.add_api_route(
        f"/static/{_name}", _asset_endpoint(_name, _type), methods=["GET"], include_in_schema=False
    )


def install_book_read(app: FastAPI) -> None:
    app.include_router(router)


__all__ = ["READ_ASSETS", "READ_PAGE", "install_book_read", "router"]

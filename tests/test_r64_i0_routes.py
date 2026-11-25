# tests/test_r64_i0_routes.py
"""R6.4 D1, D4-D6 (docs/plans/r6-4-book-look.md): the chapters and search routes behind the pages
routes' gates (signed in, the primary owner, an OWNER book session's X-Jarvis-Book, the console
only, no-store, rate-limited; a guest's session is 403), their shapes from a release's sealed pages
file (with its narration block, or one sealed before v6.4.0 without), their refusals, and
`/book/read`: the reader's page and its assets with the console's CSP, outside the guest lock."""

from __future__ import annotations

import hashlib
from typing import Any

from book_app_fakes import OWNER, book, book_app, open_book, owner_uid, register_passkey, sign_in
from book_show_fakes import FixtureSource
from httpx import AsyncClient
from r631_i0_fakes import GOOD_FLOW, PACK

from jarvis.api.book_lock import allowed
from jarvis.api.console import CONSOLE_CSP
from jarvis.api.ratelimit import RateLimiter
from jarvis.buildbook.book.flow import FlowSpec
from jarvis.buildbook.model import FileKind, Release
from jarvis.buildbook.writer import pages
from jarvis.buildbook.writer.http import ROUTES
from jarvis.buildbook.writer.model import BookChapter, Narration, PageMeta, PagesFile
from jarvis.config import Settings

RID = FixtureSource().current().id  # type: ignore[union-attr]
LABEL = FixtureSource().current().label  # type: ignore[union-attr]
META = PageMeta(written_by="Workshop · Mark XXIV", written_on="2026-11-24", release=RID)
TEXT: dict[Any, str] = {"plain": "The demo checks each key's expiry date.", "how": "It picks."}
LINES = [
    {"n": 1, "page": "pg_module_demo", "text": "The demo picks a model.",
     "cues": [{"kind": "show", "target": "title"}]},
    {"n": 2, "page": "pg_module_demo", "text": "It starts with a request.",
     "cues": [{"kind": "node", "target": "ask"}]},
    {"n": 3, "page": "pg_card_c01", "text": "The router does the picking.",
     "cues": [{"kind": "page", "target": "pg_card_c01"}, {"kind": "count", "target": "₹0"}]},
]  # fmt: skip
DEMO = BookChapter.model_validate({
    "id": "module_demo", "title": "The demo", "kind": "module",
    "pages": ["pg_module_demo", "pg_card_c01", "pg_card_c02"], "minutes": 1, "lines": LINES,
    "written": {"written_by": "Workshop · Mark XXIV", "written_on": "2026-11-25"},
})  # fmt: skip
STORY = BookChapter(id="story_example", title="The running example", kind="story",
                    pages=("pg_chapter_example",))  # fmt: skip


def files(narrated: bool = True) -> tuple[bytes, bytes]:
    out = [pages.written(ip, TEXT, META) if ip.id == "pg_module_demo"
           else pages.generator_page(ip, PACK) for ip in PACK.pages]  # fmt: skip
    told = Narration(chapters=(STORY, DEMO)) if narrated else None
    f = PagesFile(release=RID, pages=tuple(out), modules={"demo": "The demo"}, narration=told)
    flows = {"pg_module_demo": FlowSpec.model_validate(GOOD_FLOW)}
    return pages.encode_file(f), pages.encode_flows(flows)


class Source(FixtureSource):
    def __init__(self, narrated: bool = True) -> None:
        super().__init__()
        self.pages, self.flows = files(narrated)

    def current(self) -> Release | None:
        rel = super().current()
        assert rel is not None
        sums = {f"{k}_sha256": hashlib.sha256(v).hexdigest()
                for k, v in (("pages", self.pages), ("flows", self.flows))}  # fmt: skip
        return rel.model_copy(update=sums)

    def read(self, kind: FileKind) -> bytes:
        return {"pages": self.pages, "flows": self.flows}.get(kind) or super().read(kind)


async def _owner(app: Any, c: AsyncClient) -> dict[str, str]:
    assert (await app.state.book_sealer.ensure(owner_uid(OWNER))).state == "sealed"
    return book((await open_book(c, await register_passkey(c), "owner"))["token"])


async def test_the_chapters_list_and_one_chapter_with_its_lines(settings: Settings) -> None:
    async for app in book_app(settings, source=Source()):
        async with sign_in(app) as c:
            h = await _owner(app, c)
            r = await c.get("/v1/book/chapters", headers=h)
            assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
            # R6.4 I1: the sealed release's label too, for the reader's chip ("R6.4 · v6.4.0 · id")
            assert r.json() == {"release": RID, "label": LABEL, "chapters": [
                {"id": "story_example", "title": "The running example", "kind": "story",
                 "pages": ["pg_chapter_example"], "minutes": 0, "narrated": False, "lines": 0},
                {"id": "module_demo", "title": "The demo", "kind": "module",
                 "pages": ["pg_module_demo", "pg_card_c01", "pg_card_c02"], "minutes": 1,
                 "narrated": True, "lines": 3},
            ]}  # fmt: skip
            one = (await c.get("/v1/book/chapters/module_demo", params={"release": RID},
                               headers=h)).json()  # fmt: skip
            assert one["pages"] == [{"id": "pg_module_demo", "title": "The demo"},
                                    {"id": "pg_card_c01", "title": "Demo router"},
                                    {"id": "pg_card_c02", "title": "Demo store"}]  # fmt: skip
            assert one["lines"] == LINES and one["minutes"] == 1 and one["narrated"] is True
            assert one["written"] == DEMO.written.model_dump(mode="json")  # type: ignore[union-attr]
            story = (await c.get("/v1/book/chapters/story_example", headers=h)).json()
            assert (story["lines"], story["narrated"], story["written"]) == ([], False, None)
            for bad in ("module_nope", "Bad-Id", "pg_module_demo"):
                r = await c.get(f"/v1/book/chapters/{bad}", headers=h)
                assert r.status_code == 404 and r.json()["error"] == "no_chapter", bad


async def test_a_release_sealed_before_v6_4_0_gets_its_chapters_unnarrated(
    settings: Settings,
) -> None:
    async for app in book_app(settings, source=Source(narrated=False)):
        async with sign_in(app) as c:
            h = await _owner(app, c)
            got = (await c.get("/v1/book/chapters", headers=h)).json()["chapters"]
            assert [(ch["id"], ch["narrated"], ch["minutes"]) for ch in got] == [
                ("story_example", False, 0), ("module_demo", False, 0)]  # fmt: skip
            assert got[1]["pages"] == ["pg_module_demo", "pg_card_c01", "pg_card_c02"]


async def test_search_answers_its_shape_refuses_a_bad_query_and_has_its_own_limit(
    settings: Settings,
) -> None:
    async for app in book_app(settings, source=Source()):
        async with sign_in(app) as c:
            h = await _owner(app, c)
            r = await c.get("/v1/book/pages/search", params={"q": " Expiry "}, headers=h)
            assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
            body = r.json()
            assert body["release"] == RID and body["q"] == "Expiry" and body["total"] == 1
            (hit,) = body["results"]
            assert {k: hit[k] for k in ("id", "title", "kind")} == {
                "id": "pg_module_demo", "title": "The demo", "kind": "module"}  # fmt: skip
            a, b = hit["marks"][0]
            assert hit["snippet"][a:b] == "expiry"
            none = (await c.get("/v1/book/pages/search", params={"q": "zebra"}, headers=h)).json()
            assert (none["results"], none["total"]) == ([], 0)
            for q in ({}, {"q": "x"}, {"q": "  "}, {"q": "y" * 61}):
                r = await c.get("/v1/book/pages/search", params=q, headers=h)
                assert r.status_code == 422 and r.json()["error"] == "bad_query", q
            page = await c.get("/v1/book/pages/pg_module_demo", headers=h)
            assert page.status_code == 200  # "search" is a route, never read as a page id
            assert app.state.book_limits["search"].capacity == 60
            app.state.book_limits["search"] = RateLimiter(1)
            assert (await c.get("/v1/book/pages/search?q=demo", headers=h)).status_code == 200
            r = await c.get("/v1/book/pages/search?q=demo", headers=h)
            assert r.status_code == 429 and r.json()["error"] == "rate_limited"
            assert (await c.get("/v1/book/chapters", headers=h)).status_code == 200  # its own


async def test_a_guest_or_no_session_never_reads_chapters_or_search(settings: Settings) -> None:
    async for app in book_app(settings, source=Source()):
        async with sign_in(app) as c:
            assert (await app.state.book_sealer.ensure(owner_uid(OWNER))).state == "sealed"
            for path in ("/v1/book/chapters", "/v1/book/chapters/module_demo",
                         "/v1/book/pages/search?q=demo"):  # fmt: skip
                assert (await c.get(path)).status_code == 401, path
            guest = book((await open_book(c, await register_passkey(c), "guest"))["token"])
            for path in ("/v1/book/chapters", "/v1/book/chapters/module_demo",
                         "/v1/book/pages/search", "/v1/book/pages/search?q=demo"):  # fmt: skip
                r = await c.get(path, headers=guest)
                assert r.status_code in (403, 423), (path, r.status_code)


def test_the_contract_lists_the_new_routes_with_search_before_a_page_id() -> None:
    paths = [p for _m, p, *_ in ROUTES]
    assert paths.index("/v1/book/pages/search") < paths.index("/v1/book/pages/{page_id}")
    assert {"/v1/book/chapters", "/v1/book/chapters/{chapter_id}"} <= set(paths)


# ---- /book/read ---------------------------------------------------------------------------------
async def test_the_reader_page_and_its_assets_are_served_like_the_show(settings: Settings) -> None:
    async for app in book_app(settings, source=Source()):
        async with AsyncClient(transport=app.transport, base_url="http://test") as bare:
            show, read = await bare.get("/book/show"), await bare.get("/book/read")
            assert read.status_code == 200 and "text/html" in read.headers["content-type"]
            for name in ("cache-control", "x-content-type-options", "x-frame-options",
                         "referrer-policy", "content-security-policy"):  # fmt: skip
                assert read.headers[name] == show.headers[name], name
            assert read.headers["content-security-policy"] == CONSOLE_CSP
            html = read.text
            assert 'data-book="r64"' in html and 'id="bookRead"' in html and "<script>" not in html
            for asset in ("book-read.css", "book-read-reader.css", "console-book-read.js",
                          "console-book-chapter.js", "console-book-fx.js"):  # fmt: skip
                r = await bare.get(f"/static/{asset}")
                assert r.status_code == 200 and r.headers["cache-control"] == "no-store", asset
                assert r.headers["x-content-type-options"] == "nosniff"
            assert (await bare.get("/static/book-read.html")).status_code == 404


def test_the_guest_lock_never_lets_the_reader_through() -> None:
    assert allowed("GET", "/book/show") and not allowed("GET", "/book/read")
    assert not allowed("GET", "/v1/book/chapters") and not allowed("GET", "/v1/book/pages/search")

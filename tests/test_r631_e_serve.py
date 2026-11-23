# tests/test_r631_e_serve.py
"""R6.3.1 D7 (docs/plans/r6-3-1-book-at-build.md): the sealer seals a release's pages and flows
files with its book and code (60 MiB cap unchanged, the owner check over them too), and
`GET /v1/book/pages` and `/{id}` read the KEPT release's sealed files (no per-owner pages store),
behind R6.3's gates (primary owner, owner book session, console only, no-store, 60 a minute). A
page's JSON gains `flow`: its flowchart, `from` by its alias, or null. A release sealed before
v6.3.2 has no full book (404 `no_pages`), and a file that fails its check is 503 `unavailable`."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from book_app_fakes import (
    BEARER,
    OWNER,
    SECOND_OWNER,
    book,
    book_app,
    open_book,
    owner_uid,
    register_passkey,
    sign_in,
)
from book_show_fakes import BOOK_DIR, FixtureSource
from httpx import AsyncClient
from r631_i0_fakes import GOOD_FLOW, PACK

from jarvis.buildbook.book.flow import FlowSpec
from jarvis.buildbook.model import FileKind, Release
from jarvis.buildbook.ports import BookError
from jarvis.buildbook.writer import pages
from jarvis.buildbook.writer.http import ROUTES
from jarvis.buildbook.writer.model import PageMeta, PagesFile
from jarvis.buildbook.writer.serve import BookPages
from jarvis.buildbook.writer.texts import PagesRefused
from jarvis.config import Settings

RID = Release.model_validate_json((BOOK_DIR / "release.json").read_bytes()).id
MODULE, CARD = "pg_module_demo", "pg_card_c01"
SECTIONS: dict[Any, str] = {"plain": "The demo.", "example": "Asha asks.", "how": "It picks.",
                            "costs": "Nothing.", "fails": "It says so."}  # fmt: skip


def full_files(rid: str = RID) -> tuple[bytes, bytes]:
    meta = PageMeta(written_by="Workshop · Mark XXIV", written_on="2026-11-24", release=rid,
                    version="v6.3.2")  # fmt: skip
    out = [pages.written(ip, SECTIONS, meta) if ip.id == MODULE else pages.generator_page(ip, PACK)
           for ip in PACK.pages]  # fmt: skip
    f = PagesFile(release=rid, pages=tuple(out), modules={"demo": "The demo"}, limitations=2)
    return pages.encode_file(f), pages.encode_flows({MODULE: FlowSpec.model_validate(GOOD_FLOW)})


class FullSource(FixtureSource):
    """The fixture release with its full book's two files (as the generator writes them)."""

    def __init__(self, files: tuple[bytes, bytes] | None = None) -> None:
        super().__init__()
        self.pages, self.flows = files or full_files()

    def current(self) -> Release | None:
        rel = super().current()
        assert rel is not None
        return rel.model_copy(update={"pages_sha256": hashlib.sha256(self.pages).hexdigest(),
                                      "flows_sha256": hashlib.sha256(self.flows).hexdigest()})  # fmt: skip

    def read(self, kind: FileKind) -> bytes:
        return {"pages": self.pages, "flows": self.flows}.get(kind) or super().read(kind)


async def _sealed(app: Any) -> str:
    uid = owner_uid(OWNER)
    assert (await app.state.book_sealer.ensure(uid)).state == "sealed"
    return uid


async def test_the_sealer_seals_the_pages_and_flows_with_the_release(settings: Settings) -> None:
    src = FullSource()
    async for app in book_app(settings, source=src):
        uid = await _sealed(app)
        (rel,) = await app.state.book_vault.releases(uid)
        assert [f.kind for f in rel.files] == ["book", "source", "pages", "flows"]
        assert await app.state.book_vault.read(uid, RID, "pages") == src.pages
        assert await app.state.book_vault.read(uid, RID, "flows") == src.flows


async def _owner(c: AsyncClient) -> dict[str, str]:
    return book((await open_book(c, await register_passkey(c), "owner"))["token"])


async def test_the_routes_serve_the_kept_release_s_pages_with_their_flow(
    settings: Settings,
) -> None:
    async for app in book_app(settings, source=FullSource()):
        await _sealed(app)
        async with sign_in(app) as c:
            assert (await c.get("/v1/book/pages")).status_code == 401  # no book session
            h = await _owner(c)
            r = await c.get("/v1/book/pages", headers=h)
            assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
            view = r.json()
            assert view["release"] == RID and view["limitations"] == {"shown": 2, "total": 2}
            rows = {p["id"]: p for part in view["parts"] for ch in part["chapters"]
                    for p in ch["pages"]}  # fmt: skip
            assert rows[MODULE]["written"]["written_by"] == "Workshop · Mark XXIV"
            assert rows[CARD]["written"] is None
            page = (await c.get(f"/v1/book/pages/{MODULE}", headers=h)).json()
            assert page["meta"] == {"written_by": "Workshop · Mark XXIV",
                                    "written_on": "2026-11-24", "release": RID,
                                    "version": "v6.3.2"}  # fmt: skip
            assert page["flow"]["edges"][0] == {"from": "ask", "to": "pick", "style": "main"}
            card = (await c.get(f"/v1/book/pages/{CARD}", params={"release": RID}, headers=h))
            assert card.json()["flow"] is None and card.json()["meta"] is None
            for path, params in ((f"/v1/book/pages/pg_card_c99", {}),
                                 ("/v1/book/pages", {"release": "0000000"})):  # fmt: skip
                r = await c.get(path, params=params, headers=h)
                assert r.status_code == 404 and r.json()["error"] == "no_page"
            assert (await c.get("/v1/book/writer")).status_code == 404  # the writer is gone


async def test_the_gates_hold_for_a_guest_another_owner_and_a_script(settings: Settings) -> None:
    async for app in book_app(settings, source=FullSource()):
        await _sealed(app)
        assert app.state.book_limits["pages"].capacity == 60
        async with AsyncClient(transport=app.transport, base_url="http://test") as bare:
            assert (await bare.get("/v1/book/pages")).status_code == 401
            assert (await bare.get("/v1/book/pages", headers=BEARER)).status_code in (401, 403)
        async with sign_in(app, SECOND_OWNER) as c:
            r = await c.get("/v1/book/pages")
            assert r.status_code == 403 and r.json()["error"] == "not_primary"
        async with sign_in(app) as c:
            auth = await register_passkey(c)
            guest = await open_book(c, auth, "guest")
            for method, path, *_rest in ROUTES:
                url = path.replace("{page_id}", MODULE)
                r = await c.request(method, url, headers=book(guest["token"]))
                assert r.status_code in (403, 423), (method, path, r.status_code)


async def test_a_release_sealed_before_v6_3_2_has_no_full_book(settings: Settings) -> None:
    async for app in book_app(settings):  # the fixture's release.json names no pages
        await _sealed(app)
        async with sign_in(app) as c:
            r = await c.get("/v1/book/pages", headers=await _owner(c))
            assert r.status_code == 404 and r.json()["error"] == "no_pages"


class _Vault:
    def __init__(self, rel: Any, data: dict[str, bytes] | None = None, *, down: bool = False):
        self.rel, self.data, self.down, self.reads = rel, data or {}, down, 0

    async def releases(self, uid: str) -> tuple[Any, ...]:
        if self.down:
            raise BookError("down")
        return (self.rel,)

    async def read(self, uid: str, rid: str, kind: str) -> bytes:
        self.reads += 1
        return self.data[kind]


def _sealed_release(pages_bytes: bytes, flows_bytes: bytes) -> Any:
    from jarvis.buildbook.model import SealedFile, SealedRelease

    def f(kind: str, data: bytes) -> SealedFile:
        return SealedFile(kind=kind, fid="bf_" + "0" * 12, size=len(data), count=1, dek="k",
                          sha256=hashlib.sha256(data).hexdigest())  # fmt: skip

    rel = FixtureSource().current()
    assert rel is not None
    return SealedRelease(**rel.ref().model_dump(), sealed_at="2026-11-24T09:00:00+05:30",
                         files=(f("book", b"b"), f("source", b"s"), f("pages", pages_bytes),
                                f("flows", flows_bytes)))  # fmt: skip


@pytest.mark.parametrize(
    ("data", "down", "code"),
    [
        ({"pages": b"not gzip", "flows": b"{}"}, False, "unavailable"),
        ({"pages": full_files("0000000")[0], "flows": b"{}"}, False, "unavailable"),
        ({"pages": full_files()[0], "flows": b'{"pg_card_c01": {"title": 1}}'}, False,
         "unavailable"),
        ({}, True, "unavailable"),
    ],
)
async def test_a_file_that_fails_its_check_or_a_vault_down_is_unavailable(
    data: dict[str, bytes], down: bool, code: str
) -> None:
    rel = _sealed_release(data.get("pages", b"x"), data.get("flows", b"x"))
    svc = BookPages(FixtureSource(), _Vault(rel, data, down=down))
    with pytest.raises(PagesRefused) as no:
        await svc.index("uid", None)
    assert no.value.code == code and no.value.status == 503


async def test_a_release_s_files_are_opened_once_and_read_again_after_a_change() -> None:
    files = full_files()
    vault = _Vault(_sealed_release(*files), {"pages": files[0], "flows": files[1]})
    svc = BookPages(FixtureSource(), vault)
    await svc.index("uid", None)
    await svc.page("uid", MODULE, RID)
    assert vault.reads == 2  # pages and flows, once
    vault.rel = _sealed_release(*full_files())  # the same bytes sealed again: still cached
    await svc.index("uid", RID)
    assert vault.reads == 2
    vault.rel, vault.data["flows"] = _sealed_release(files[0], b"{}"), b"{}"
    assert (await svc.page("uid", MODULE, RID))["flow"] is None  # changed: read again
    assert vault.reads == 4
    with pytest.raises(PagesRefused) as no:
        await svc.page("uid", "pg_card_c99", RID)
    assert no.value.code == "no_page"


def test_the_contract_is_the_two_pages_routes_only(tmp_path: Path) -> None:
    assert [(m, p) for m, p, *_ in ROUTES] == [
        ("GET", "/v1/book/pages"),
        ("GET", "/v1/book/pages/{page_id}"),
    ]

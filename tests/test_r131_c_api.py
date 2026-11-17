# tests/test_r131_c_api.py -- R13.1 Part C's routes under /v1/seeme (docs/plans/r13-1-try-on.md
# "The HTTP contract", D10-D15, D22) on R13's REAL catalog part (its store, its sealed crops and
# their `wardrobe_photo` views) and R13's real styling, beside R13's own `GET /v1/wardrobe`. Every
# reply is its contract model; every refusal `{"error", "detail"}`; the console rows refuse a
# script; the press is 6 a minute. Holds AVT-12's named test. Fakes only: nothing reaches Google.
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from r13_fakes import IST, PILOT, ev
from r13_fakes_c import FakeFetcher, forecast
from r131_fake_tryon import PNG as PNG_OUT
from r131_fakes import NOW, RING, UID, FixedClock, T, jpeg
from r131_fakes_c import FakeBilling, OnMode
from r131_fakes_c import StrictTryOn as ScriptedTryOn  # the adapter's pre-send check

from jarvis.api import seeme as routes
from jarvis.config import Settings
from jarvis.storage.docs import MemoryDocs
from jarvis.wardrobe.ports import Commit, WardrobeContext, WardrobePart
from jarvis.wardrobe.tryon import http
from jarvis.wardrobe.tryon import model as m

PHOTO, SHIRT = jpeg(600, 1200, 40), jpeg(600, 800, 20)
JPEG = {"content-type": "image/jpeg"}
CSRF = {"X-Requested-With": "JARVIS"}


@dataclass
class Real:
    app: FastAPI
    c: AsyncClient
    provider: ScriptedTryOn
    state: dict[str, Any]
    console: list[bool]


async def _catalog(ctx: WardrobeContext, clock: FixedClock) -> Any:
    from jarvis.wardrobe.catalog import part as catalog_part

    cat = catalog_part.build(ctx)
    store = cat.services["store"]

    async def fn(view: Any, tx: Any) -> Commit:
        return Commit(events=tuple(ev(p.id, "registered", clock(), place=p.place) for p in PILOT),
                      records=PILOT)  # fmt: skip

    await store.transact(UID, fn)
    for pid in (T.trousers, T.jeans, T.striped):  # real sealed front crops, real view records
        await cat.services["photos"].save(UID, pid, "front", jpeg(512, 384, 8))
    return cat


@asynccontextmanager
async def real(monkeypatch: pytest.MonkeyPatch, **over: Any) -> AsyncIterator[Real]:
    from jarvis.api.auth import require_auth
    from jarvis.api.identity import current_user
    from jarvis.api.wardrobe import router as wardrobe_router
    from jarvis.wardrobe.seeme.part import build
    from jarvis.wardrobe.styling.part import build_with

    clock, docs = FixedClock(NOW), MemoryDocs()
    s = Settings(_env_file=None, **{"tryon_pictures": True, **over})  # type: ignore[arg-type]
    provider = ScriptedTryOn(max_garments=3, model="gemini-3.1-flash-image")
    state: dict[str, Any] = {"billing": FakeBilling(), "brain_mode": OnMode()}
    found: list[Any] = []

    async def zone(uid: str) -> Any:
        return IST

    ctx = WardrobeContext(
        s=s, docs=docs, keyring=RING, audit=None, now=clock, zone=zone, state=state.get,
        store=lambda: found[0] if found else None, tryon=lambda: state.get("provider", provider),
    )  # fmt: skip
    cat = await _catalog(ctx, clock)
    found.append(cat.services["store"])
    fetch = FakeFetcher(forecast(NOW.astimezone(IST).date(), [(30, ()), (30, ())]))
    state["r13_parts"] = {"catalog": cat, "styling": build_with(ctx, fetcher=fetch)}
    state["r13_parts"]["seeme"] = build(ctx)
    app = FastAPI()
    app.state.settings, app.state.r13_parts = s, state["r13_parts"]
    app.include_router(wardrobe_router)
    app.include_router(routes.router)
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[current_user] = lambda: UID
    console = [True]
    monkeypatch.setattr(
        routes, "session_email", lambda r, s: "owner@example.com" if console[0] else None
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield Real(app, c, provider, state, console)


async def _ready(r: Real) -> str:
    """His photo, his YES and a new navy shirt's photo, through the routes: the garment id."""
    assert (await r.c.post("/v1/seeme/photo", content=PHOTO, headers=JPEG)).status_code == 200
    shown = http.SeeMeView.model_validate((await r.c.get("/v1/seeme")).json()).consent
    assert shown is not None and shown.version.startswith("c2-") and not shown.given
    body = {"typed": "YES", "template_version": shown.version}  # what his console was shown
    yes = await r.c.post("/v1/seeme/consent", json=body)
    assert yes.status_code == 200 and http.ConsentView.model_validate(yes.json()).current
    g = await r.c.post("/v1/seeme/garments?type=shirt&colour=navy", content=SHIRT, headers=JPEG)
    assert g.status_code == 200, g.text
    return http.GarmentView.model_validate(g.json()).id


async def _press(r: Real, gid: str, pieces: list[str], n: int = 1) -> Any:
    q = f"/v1/seeme/estimate?garment={gid}&pieces={','.join(pieces)}"
    est = http.Estimate.model_validate((await r.c.get(q)).json())
    body = {"garment": gid, "pieces": pieces, "confirm_cost": True, "inr_shown": est.typical_inr,
            "request_id": f"tq_{n:016x}"}  # fmt: skip
    return await r.c.post("/v1/seeme/pictures", json=body)


# ---- AVT-12 (row 363): his acceptance check ------------------------------------------------------
async def test_avt12_the_picture_is_labelled_a_generated_2d_preview_and_lists_the_exact_pieces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with real(monkeypatch) as r:
        before = (await r.c.get("/v1/wardrobe")).json()
        gid = await _ready(r)
        pair = http.Pairing.model_validate((await r.c.get(f"/v1/seeme/pair?garment={gid}")).json())
        got = await _press(r, gid, [T.trousers])  # his choice: the trousers, not the jeans offered
        assert got.status_code == 200, got.text
        pic = http.PictureView.model_validate(got.json())
        assert pic.label == "Generated 2D style preview — not a photo; the fit is not exact"
        assert pic.garment.words == "a new navy shirt, not in your wardrobe"
        assert pic.garment.id == gid and gid.startswith("tg_") and not gid.startswith("wi_")
        assert [(p.piece, p.words) for p in pic.sent] == [(T.trousers, "charcoal trousers")]
        not_in = {n.piece for n in pic.not_sent}
        assert T.trousers not in not_in and all(n.why for n in pic.not_sent)
        assert {p.piece for p in pair.pieces} - {T.trousers} <= not_in  # offered, not sent: listed
        assert r.provider.calls[0].garments == ("a new navy shirt", "charcoal trousers")
        img = await r.c.get(f"/v1/seeme/pictures/{pic.id}")
        assert img.content == PNG_OUT and img.headers["content-type"] == "image/png"
        after = (await r.c.get("/v1/wardrobe")).json()
        assert after["rev"] == before["rev"] and after["pieces"] == before["pieces"]  # never his


# ---- the routes and their models -----------------------------------------------------------------
async def test_every_seeme_route_answers_its_contract_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with real(monkeypatch) as r:
        gid = await _ready(r)
        view = http.SeeMeView.model_validate((await r.c.get("/v1/seeme")).json())
        from jarvis.wardrobe.seeme.estimate import figures

        typical = figures(r.provider, garments=2, rate=95.24, tax_pct=18).typical_inr
        assert view.on and view.photo.kept and view.consent.current and view.typical_inr == typical
        assert (
            view.provider is not None
            and view.provider.location_words == "processed in the United States"
        )
        listed = http.GarmentList.model_validate((await r.c.get("/v1/seeme/garments")).json())
        assert [g.id for g in listed.garments] == [gid]
        photo = await r.c.get(f"/v1/seeme/garments/{gid}")
        assert photo.headers["content-type"] == "image/jpeg"
        assert {k: photo.headers[k.lower()] for k in http.PICTURE_HEADERS} == http.PICTURE_HEADERS
        pic = http.PictureView.model_validate((await _press(r, gid, [])).json())
        kept = await r.c.post(f"/v1/seeme/pictures/{pic.id}/keep", json={"keep": True})
        assert http.PictureView.model_validate(kept.json()).kept
        img = await r.c.get(f"/v1/seeme/pictures/{pic.id}")
        assert {k: img.headers[k.lower()] for k in http.PICTURE_HEADERS} == http.PICTURE_HEADERS
        mine = await r.c.get("/v1/seeme/photo")
        assert (
            mine.headers["content-type"] == "image/jpeg"
            and mine.headers["cache-control"] == "no-store"
        )
        put = await r.c.put("/v1/seeme/settings", json={"cap_inr": 200})
        assert http.SeeMeView.model_validate(put.json()).month.cap_inr == 200  # type: ignore[union-attr]
        for path in (
            f"/v1/seeme/pictures/{pic.id}",
            f"/v1/seeme/garments/{gid}",
            "/v1/seeme/photo",
        ):
            gone = http.Deleted.model_validate((await r.c.delete(path)).json())
            assert gone.deleted, path
        after = http.SeeMeView.model_validate((await r.c.get("/v1/seeme")).json())
        assert not after.photo.kept and not after.consent.given  # his YES went with his photo


async def test_every_refusal_is_a_code_and_words(monkeypatch: pytest.MonkeyPatch) -> None:
    async with real(monkeypatch) as r:
        gid = await _ready(r)
        gif = {"content": b"GIF89a", "headers": {"content-type": "image/gif"}}
        big = {"content": jpeg(600, 1200, 701 * 1024), "headers": JPEG}
        cases = [
            ("POST", "/v1/seeme/consent", {"json": {"typed": "yes", "template_version": "c2"}},
             422, "not_yes"),
            ("POST", "/v1/seeme/garments?type=sneaker&colour=white",
             {"content": SHIRT, "headers": JPEG}, 422, "not_a_garment"),
            ("POST", "/v1/seeme/garments?type=shirt&colour=navy", gif, 422, "not_jpeg"),
            ("POST", "/v1/seeme/photo", big, 413, "too_large"),
            ("POST", "/v1/seeme/consent", {"json": {"typed": "YES"}}, 422, "invalid"),
            ("GET", "/v1/seeme/pair?garment=tg_000000000000", {}, 404, "no_garment"),
            ("GET", f"/v1/seeme/estimate?garment={gid}&pieces=wi_00000000000x", {}, 422,
             "not_a_garment"),
            ("GET", "/v1/seeme/pictures/tp_000000000000", {}, 404, "gone"),
            ("PUT", "/v1/seeme/settings", {"json": {"cap_inr": 500}}, 422, "confirm_cost"),
        ]  # fmt: skip
        for method, url, kw, status, code in cases:
            got = await r.c.request(method, url, **kw)
            assert (got.status_code, got.json()["error"]) == (status, code), (url, got.text)
            assert set(got.json()) == {"error", "detail"} and got.json()["detail"], url
            assert got.headers["cache-control"] == "no-store", url
        body = {"garment": gid, "pieces": [T.vest], "confirm_cost": True, "inr_shown": 9.0,
                "request_id": "tq_" + "1" * 16}  # fmt: skip
        got = await r.c.post("/v1/seeme/pictures", json=body)
        assert (got.status_code, got.json()["error"]) == (422, "private_piece")
        assert T.vest not in got.text and r.provider.calls == []


# ---- console only, the press's own limit ---------------------------------------------------------
CONSOLE = [(m_, p) for m_, p, *_, console in http.ROUTES if console and p.startswith("/v1/seeme")]


async def test_the_console_rows_refuse_a_script(monkeypatch: pytest.MonkeyPatch) -> None:
    async with real(monkeypatch) as r:
        gid = await _ready(r)
        r.console[0] = False  # a bearer token or a script: no signed-in browser
        assert len(CONSOLE) == 12
        for method, path in CONSOLE:
            url = path.replace("{id}", "tp_000000000000" if "pictures" in path else gid)
            got = await r.c.request(method, url, json={} if method in ("POST", "PUT") else None)
            assert (got.status_code, got.json()["error"]) == (403, "console_only"), (method, path)
        for path in ("/v1/seeme", f"/v1/seeme/pair?garment={gid}", "/v1/seeme/garments",
                     f"/v1/seeme/estimate?garment={gid}&pieces="):  # fmt: skip
            assert (await r.c.get(path)).status_code == 200, path  # the reads stay open to him
        assert r.provider.calls == []


async def test_six_presses_a_minute(monkeypatch: pytest.MonkeyPatch) -> None:
    async with real(monkeypatch) as r:
        gid = await _ready(r)
        codes = []
        for n in range(m.PRESSES_A_MINUTE + 1):
            body = {"garment": gid, "pieces": [], "confirm_cost": False, "inr_shown": 9.0,
                    "request_id": f"tq_{n:016x}"}  # fmt: skip
            codes.append((await r.c.post("/v1/seeme/pictures", json=body)).status_code)
        assert codes == [422] * 6 + [429]  # the 7th: too many, before any gate


async def test_off_says_so_in_words(monkeypatch: pytest.MonkeyPatch) -> None:
    async with real(monkeypatch, tryon_pictures=False) as r:
        view = http.SeeMeView.model_validate((await r.c.get("/v1/seeme")).json())
        assert not view.on and view.why == "Pictures are not set up on this server."
        assert view.provider is None
        got = await r.c.post("/v1/seeme/consent", json={"typed": "YES", "template_version": "c2"})
        assert (got.status_code, got.json()["error"]) == (503, "not_configured")
    async with real(monkeypatch) as r:
        r.state["r13_parts"]["seeme"] = WardrobePart("seeme", ready="setup failed")
        got = await r.c.get("/v1/seeme")
        assert got.status_code == 503 and got.json()["error"] == "not_configured"

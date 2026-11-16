# tests/test_r13_a_routes.py -- R13 Part A (docs/plans/r13-wardrobe.md "The HTTP contract", D1, D4,
# D9, D17; OPS-06's "through the real app"): every catalog route on the REAL app (create_app, the
# wiring, the body-size middleware, the owner's token), each reply validated against its model in
# `jarvis.wardrobe.http` and every status one of its `ROUTES` row. Fixed clock: the app's
# `wardrobe_now` is set before the start.
from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from r13_fakes import FixedClock, ist
from r13_fakes_a import ROOT, fp, jpeg

from jarvis.config import Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.wardrobe import http
from jarvis.wardrobe.catalog.part import OFF_NO_KEY

TOKEN = "t" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}"}
STATUSES = {(m, p): set(codes) | {200} for m, p, _, _, _, codes in http.ROUTES}


def _owner(s: Settings, *, key: bool = True) -> Settings:
    over: dict[str, Any] = {"env": "prod", "api_token": SecretStr(TOKEN)}
    if key:
        over["token_key"] = SecretStr(base64.b64encode(ROOT).decode())
    return s.model_copy(update=over)


@asynccontextmanager
async def running(s: Settings) -> AsyncIterator[tuple[Any, AsyncClient]]:
    from jarvis.api import create_app

    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    app.state.wardrobe_now = FixedClock(ist(2026, 11, 16, 10, 0))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield app, c


def _allowed(method: str, path: str, status: int) -> None:
    assert status in STATUSES[(method, path)], (method, path, status)


async def _add(c: AsyncClient, *pieces: dict[str, Any]) -> list[str]:
    got = await c.post(
        "/v1/wardrobe/tools/wardrobe_add",
        json={"arguments": {"pieces": list(pieces)}},
        headers=AUTH,
    )
    _allowed("POST", "/v1/wardrobe/tools/{tool}", got.status_code)
    reply = http.ToolReply.model_validate(got.json())
    assert reply.status == "executed", reply
    return list(reply.result["ids"])  # type: ignore[index]


async def test_the_view_is_the_owners_and_answers_its_model(settings: Settings) -> None:
    async with running(_owner(settings)) as (app, c):
        assert (await c.get("/v1/wardrobe")).status_code == 401
        ids = await _add(c, {"type": "shirt", "label": "Office shirt"}, {"type": "vest"})
        got = await c.get("/v1/wardrobe", headers=AUTH)
        assert got.status_code == 200 and got.headers["cache-control"] == "no-store"
        view = http.WardrobeView.model_validate(got.json())
        assert [p.id for p in view.pieces] == [ids[0]] and view.private_hidden == 1
        assert view.ready.startswith("Ready") and view.counts.owned == 2
        shown = http.WardrobeView.model_validate(
            (await c.get("/v1/wardrobe?private=1", headers=AUTH)).json()
        )
        assert {p.id for p in shown.pieces} == set(ids)
        status = (await c.get("/v1/r13", headers=AUTH)).json()
        assert status["parts"][0] == {"part": "catalog", "ready": view.ready}


async def test_h3_paging_continues_from_the_cursor_so_260_pieces_each_show_once(
    settings: Settings,
) -> None:
    from jarvis.api.identity import primary_user_id

    kinds = ("shirt", "trousers", "sock", "belt", "watch", "kurta")
    async with running(_owner(settings)) as (app, c):
        for i in range(13):  # 13 adds of 20: under the route's 30 changes a minute
            await _add(c, *({"type": kinds[(i * 20 + j) % len(kinds)]} for j in range(20)))
        pages: list[list[str]] = []
        after = ""
        while len(pages) < 5:
            got = await c.get(f"/v1/wardrobe?after={after}", headers=AUTH)
            _allowed("GET", "/v1/wardrobe", got.status_code)
            view = http.WardrobeView.model_validate(got.json())
            pages.append([p.id for p in view.pieces])
            if view.next is None:
                break
            after = view.next
        shown = [pid for page in pages for pid in page]
        assert [len(page) for page in pages] == [http.PAGE_MAX, 260 - http.PAGE_MAX]
        assert len(set(shown)) == len(shown)  # disjoint pages: nothing repeated
        desk = app.state.r13_parts["catalog"].services["store"].desk
        stored = await desk.store.view(primary_user_id(app.state.settings))
        assert set(shown) == {p.id for p in stored.active()}  # and nothing dropped
        gone = await c.get("/v1/wardrobe?after=wi_" + "0" * 12, headers=AUTH)
        assert http.WardrobeView.model_validate(gone.json()).pieces == ()  # an unknown cursor


async def test_without_the_token_key_the_routes_say_the_wardrobe_is_off(settings: Settings) -> None:
    async with running(_owner(settings, key=False)) as (_, c):
        got = await c.get("/v1/wardrobe", headers=AUTH)
        assert got.status_code == 503 and got.json() == {"detail": OFF_NO_KEY}
        est = http.TagEstimate.model_validate(
            (await c.get("/v1/wardrobe/tag/estimate?piece=x", headers=AUTH)).json()
        )
        assert not est.allowed and est.why == OFF_NO_KEY


async def test_a_scan_is_one_commit_a_retry_is_already_done_and_a_stated_day_is_noon_his_time(
    settings: Settings,
) -> None:
    async with running(_owner(settings)) as (app, c):
        [shirt] = await _add(c, {"type": "shirt"})
        tap = {"client_id": "tap-000001", "piece": shirt, "kind": "deposited"}
        first = await c.post("/v1/wardrobe/scan", json={"events": [tap]}, headers=AUTH)
        reply = http.ScanReply.model_validate(first.json())
        assert (reply.applied, reply.marks) == (1, {"tap-000001": "applied"})
        again = http.ScanReply.model_validate(
            (
                await c.post(
                    "/v1/wardrobe/scan", json={"rev_seen": 1, "events": [tap]}, headers=AUTH
                )
            ).json()
        )
        assert again.already_done and again.view is not None and again.message == "Already done."
        app.state.wardrobe_now.set(ist(2026, 11, 17, 15, 0))  # the next afternoon
        back = {"client_id": "tap-000002", "piece": shirt, "kind": "returned", "day": "2026-11-17"}
        await c.post("/v1/wardrobe/scan", json={"events": [back]}, headers=AUTH)
        detail = http.PieceDetail.model_validate(
            (await c.get(f"/v1/wardrobe/pieces/{shirt}", headers=AUTH)).json()
        )
        assert [h.kind for h in detail.history] == ["registered", "deposited", "returned"]
        assert detail.history[-1].at == ist(2026, 11, 17, 12, 0)  # a stated day: 12:00 HIS time
        assert detail.piece.state == "ready" and detail.step == "Ready"


@pytest.mark.parametrize(
    ("event", "status"),
    [
        ({"kind": "archived"}, 422),  # archive, restore and merge are cards, never a scan
        ({"kind": "deposited", "piece": "wi_" + "9" * 12}, 422),
        ({"kind": "deposited", "at": "2026-11-16T09:00:00Z", "sent": "2026-11-15T03:00:00Z"}, 422),
    ],
)
async def test_a_scan_the_ledger_refuses_writes_nothing(
    settings: Settings, event: dict[str, Any], status: int
) -> None:
    async with running(_owner(settings)) as (_, c):
        [shirt] = await _add(c, {"type": "shirt"})
        body = {"events": [{"client_id": "tap-000003", "piece": shirt, **event}]}
        got = await c.post("/v1/wardrobe/scan", json=body, headers=AUTH)
        assert got.status_code == status and set(got.json()) == {"detail"}
        _allowed("POST", "/v1/wardrobe/scan", got.status_code)
        view = http.WardrobeView.model_validate((await c.get("/v1/wardrobe", headers=AUTH)).json())
        assert view.pieces[0].state == "ready"


async def test_a_qr_read_counts_only_on_a_piece_wearing_one_of_his_labels(
    settings: Settings,
) -> None:
    from jarvis.api.identity import primary_user_id

    async with running(_owner(settings)) as (app, c):
        labelled, bare = await _add(c, {"type": "vest"}, {"type": "vest"})
        desk = app.state.r13_parts["catalog"].services["store"].desk
        code = (await desk.labels.sheet(primary_user_id(app.state.settings)))[0].code
        await c.post("/v1/wardrobe/labels", json={"code": code, "piece": labelled}, headers=AUTH)
        events = [
            {"client_id": f"scan-00000{n}", "piece": pid, "kind": "deposited", "how": "qr",
             "source": "phone"}
            for n, pid in enumerate((labelled, bare))
        ]  # fmt: skip
        got = http.ScanReply.model_validate(
            (await c.post("/v1/wardrobe/scan", json={"events": events}, headers=AUTH)).json()
        )
        assert got.marks == {"scan-000000": "applied", "scan-000001": "held"} and got.review == 1
        sheet = await c.get("/v1/wardrobe/labels.svg", headers=AUTH)
        assert sheet.status_code == 200
        assert sheet.headers["content-security-policy"] == "default-src 'none'"
        assert sheet.headers["x-content-type-options"] == "nosniff"
        assert sheet.headers["content-disposition"].startswith("attachment")
        assert "<script" not in sheet.text and "No. 1<" in sheet.text and "href" not in sheet.text


async def test_the_sheet_writes_nothing_and_a_label_is_his_only_once_assigned(
    settings: Settings,
) -> None:
    from jarvis.api.identity import primary_user_id

    async with running(_owner(settings)) as (app, c):
        [vest] = await _add(c, {"type": "vest"})
        docs = app.state.r13_parts["catalog"].services["store"].docs
        before = len(docs.log)
        assert (await c.get("/v1/wardrobe/labels.svg?sheet=2", headers=AUTH)).status_code == 200
        assert len(docs.log) == before  # printing a sheet writes nothing
        desk = app.state.r13_parts["catalog"].services["store"].desk
        uid = primary_user_id(app.state.settings)
        code = (await desk.labels.sheet(uid))[0].code
        got = await c.post("/v1/wardrobe/labels", json={"code": code, "piece": vest}, headers=AUTH)
        assert http.LabelView.model_validate(got.json()).number == 1
        bad = await c.post(
            "/v1/wardrobe/labels", json={"code": "abcdefgh", "piece": vest}, headers=AUTH
        )
        assert bad.status_code == 422
        view = http.WardrobeView.model_validate(
            (await c.get("/v1/wardrobe?private=1", headers=AUTH)).json()
        )
        assert view.pieces[0].label_code == code


async def test_photos_go_in_through_the_door_and_come_back_only_to_him(settings: Settings) -> None:
    async with running(_owner(settings)) as (_, c):
        [shirt] = await _add(c, {"type": "shirt"})
        heads = AUTH | {"content-type": "image/jpeg"}
        saved = await c.post(
            f"/v1/wardrobe/photos?piece={shirt}&view=front", content=jpeg(), headers=heads
        )
        photo = http.PhotoSaved.model_validate(saved.json())
        big = await c.post(
            f"/v1/wardrobe/photos?piece={shirt}&view=back", content=jpeg(600, 400), headers=heads
        )
        assert big.status_code == 422 and "512" in big.json()["detail"]
        png = await c.post(
            f"/v1/wardrobe/photos?piece={shirt}&view=back",
            content=b"x",
            headers=AUTH | {"content-type": "image/png"},
        )
        assert png.status_code == 422
        huge = await c.post(
            f"/v1/wardrobe/photos?piece={shirt}&view=back",
            content=jpeg(extra=b"x" * 300_000),
            headers=heads,
        )
        assert huge.status_code == 413
        got = await c.get(f"/v1/wardrobe/photos/{photo.photo}", headers=AUTH)
        assert got.headers["content-type"] == "image/jpeg" and got.content.startswith(b"\xff\xd8")
        assert (await c.get(f"/v1/wardrobe/photos/{photo.photo}")).status_code == 401
        gone = await c.delete(f"/v1/wardrobe/photos/{photo.photo}", headers=AUTH)
        assert http.Deleted.model_validate(gone.json()).deleted
        assert (await c.get(f"/v1/wardrobe/photos/{photo.photo}", headers=AUTH)).status_code == 404


async def test_fingerprints_of_one_model_and_never_a_private_pieces(settings: Settings) -> None:
    async with running(_owner(settings)) as (_, c):
        shirt, vest = await _add(c, {"type": "shirt"}, {"type": "vest"})
        for pid, status in ((shirt, 200), (vest, 422)):
            body = {"piece": pid, "view": "front", "model": "mnv2-int8-1", "v": fp(1)}
            got = await c.post("/v1/wardrobe/fingerprints", json=body, headers=AUTH)
            assert got.status_code == status
        listed = http.Fingerprints.model_validate(
            (await c.get("/v1/wardrobe/fingerprints", headers=AUTH)).json()
        )
        assert [i.piece for i in listed.items] == [shirt]
        other = http.Fingerprints.model_validate(
            (await c.get("/v1/wardrobe/fingerprints?model=mnv2-fp32-1", headers=AUTH)).json()
        )
        assert other.items == ()


async def test_ops06_a_3mb_backup_restores_through_the_real_app_and_31mb_is_refused(
    settings: Settings,
) -> None:
    async with running(_owner(settings)) as (app, c):
        ids = await _add(c, *({"type": "shirt"} for _ in range(20)))
        heads = AUTH | {"content-type": "image/jpeg"}
        for pid in ids:  # 20 saves: under the route's 30 changes a minute
            url = f"/v1/wardrobe/photos?piece={pid}&view=front"
            saved = await c.post(url, content=jpeg(extra=b"q" * 150_000), headers=heads)
            assert saved.status_code == 200
        got = await c.get("/v1/wardrobe/backup?photos=1", headers=AUTH)
        assert got.status_code == 200 and got.headers["content-disposition"].startswith(
            "attachment"
        )
        body = got.content
        assert len(body) > 3 * 1024 * 1024
        check = await c.post("/v1/wardrobe/restore/check", content=body, headers=AUTH)
        token = http.RestoreCheck.model_validate(check.json()).token
        done = await c.post(f"/v1/wardrobe/restore?token={token}", content=body, headers=AUTH)
        reply = http.RestoreDone.model_validate(done.json())
        assert reply.counts.already_there == 20 and reply.counts.events == 0  # nothing twice
        over = await c.post(
            "/v1/wardrobe/restore/check", content=b"x" * (26 * 1024 * 1024), headers=AUTH
        )
        assert over.status_code == 413 and "25 MB" in over.json()["detail"]
        past = await c.post(
            "/v1/wardrobe/restore/check", content=b"x" * (31 * 1024 * 1024), headers=AUTH
        )
        assert past.status_code == 413 and past.json()["detail"]  # the middleware, in words
        stale = await c.post(
            "/v1/wardrobe/restore?token=1-0-" + "a" * 40, content=body, headers=AUTH
        )
        assert stale.status_code == 409


async def test_the_panels_changes_go_through_the_gateway_with_their_cards(
    settings: Settings,
) -> None:
    async with running(_owner(settings)) as (app, c):
        keep, other = await _add(c, {"type": "watch", "label": "Steel watch"}, {"type": "watch"})
        body = {"arguments": {"keep": keep, "merge": other}}
        got = await c.post("/v1/wardrobe/tools/wardrobe_merge", json=body, headers=AUTH)
        reply = http.ToolReply.model_validate(got.json())
        assert reply.status == "needs_approval" and reply.approval_id
        assert "Steel" not in reply.message and "a watch" in reply.message
        [card] = await app.state.gateway.gate.pending()
        assert (
            card.scope != "u:wardrobe" and card.scope.split(":")[1] != "wardrobe"
        )  # a conversation
        unknown = await c.post(
            "/v1/wardrobe/tools/shell_exec", json={"arguments": {}}, headers=AUTH
        )
        assert unknown.status_code == 404
        bad = await c.post("/v1/wardrobe/tools/wardrobe_find", json={"arguments": {}}, headers=AUTH)
        assert (
            bad.status_code == 422 and http.ToolReply.model_validate(bad.json()).status == "error"
        )


async def test_the_pilot_is_counts_only(settings: Settings) -> None:
    async with running(_owner(settings)) as (_, c):
        await _add(c, {"type": "shirt", "label": "Office shirt"})
        got = await c.get("/v1/wardrobe/pilot", headers=AUTH)
        pilot = http.Pilot.model_validate(got.json())
        assert pilot.events == 1 and "Office" not in got.text

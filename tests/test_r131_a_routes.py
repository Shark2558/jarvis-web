# tests/test_r131_a_routes.py -- R13.1 Part A's routes (`api/tryon.py`; docs/plans/r13-1-try-on.md
# "The HTTP contract"): exactly the `http.ROUTES` rows of part `tryon`, each owner-only
# (`require_auth`), `Cache-Control: no-store`, limited per owner (30 changes, 60 reads a minute),
# every refusal a `Refusal` {"error", "detail"}; his measurements never in the audit's text.
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from r131_fakes_a import SHOES, UID, T, a_world

from jarvis.api import tryon as routes
from jarvis.api.auth import require_auth
from jarvis.tools.audit import args_hash
from jarvis.wardrobe.catalog.store import WardrobeUnavailable
from jarvis.wardrobe.tryon import model as m
from jarvis.wardrobe.tryon.http import (
    ROUTES,
    AssetChoice,
    BodyVersions,
    Refusal,
    SavedList,
    SavedView,
    TryonLook,
    TryonView,
)


def _refusal(r: Any, status: int, code: str) -> Refusal:
    assert r.status_code == status, (r.status_code, r.text)
    got = Refusal.model_validate(r.json())
    assert got.error == code, got
    assert r.headers["cache-control"] == "no-store"
    return got


def test_the_router_has_exactly_the_contracts_tryon_rows_and_requires_his_sign_in() -> None:
    planned = {(meth, path) for meth, path, part, *_ in ROUTES if part == "tryon"}
    have = {(meth, r.path) for r in routes.router.routes for meth in r.methods}  # type: ignore[attr-defined]
    assert have == planned and len(planned) == 11
    assert any(d.dependency is require_auth for d in routes.router.dependencies)


async def test_without_his_sign_in_every_route_is_refused() -> None:
    a = await a_world()
    app = FastAPI()
    owner = {"env": "prod", "api_token": SecretStr("t" * 32)}
    app.state.settings = a.ctx.s.model_copy(update=owner)
    app.state.r13_parts = a.parts
    app.include_router(routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        for meth, path, part, *_ in ROUTES:
            if part != "tryon":
                continue
            url = path.replace("{piece}", T.shirt).replace("{id}", "tc_0000abcd")
            assert (await c.request(meth, url)).status_code == 401, (meth, path)


async def test_every_answer_is_no_store_and_matches_its_model() -> None:
    a = await a_world()
    pid = await a.plan()
    async with a.client() as c:
        for url, model in (("/v1/tryon", TryonView), (f"/v1/tryon/look?plan={pid}", TryonLook),
                           ("/v1/tryon/look?day=today&alt=1", TryonLook),
                           (f"/v1/tryon/look?pieces=top:{T.shirt}", TryonLook),
                           ("/v1/tryon/saved", SavedList)):  # fmt: skip
            r = await c.get(url)
            assert r.status_code == 200 and r.headers["cache-control"] == "no-store", url
            model.model_validate(r.json())
        r = await c.put("/v1/tryon/body", json={"height": 180})
        assert r.status_code == 200 and BodyVersions.model_validate(r.json()).draft is not None


async def test_his_measurements_are_refused_in_words_and_never_reach_the_audit() -> None:
    a = await a_world()
    async with a.client() as c:
        got = _refusal(await c.put("/v1/tryon/body", json={"height": 149}), 422, "out_of_range")
        assert got.detail == m.range_words("height")
        _refusal(await c.put("/v1/tryon/body", json={"height": "tall"}), 422, "not_whole")
        _refusal(await c.put("/v1/tryon/body", json={"neck": 40}), 422, "bad_request")
        _refusal(await c.put("/v1/tryon/body", json={}), 422, "nothing_typed")
        _refusal(await c.put("/v1/tryon/body", content=b"{"), 422, "bad_request")
        _refusal(await c.post("/v1/tryon/body/use"), 404, "no_draft")
        _refusal(await c.delete("/v1/tryon/body/draft"), 404, "no_draft")
        typed = await c.put("/v1/tryon/body", json={"height": 183, "chest": 101})
        assert typed.status_code == 200
        assert (await c.post("/v1/tryon/body/use")).status_code == 200
        assert (await c.put("/v1/tryon/body", json={"height": 179})).status_code == 200
        assert (await c.delete("/v1/tryon/body/draft")).status_code == 200
    entries = [e for e in (await a.w.audit.tail(100)).entries if e.tool == "tryon_body"]
    assert len(entries) == 4 and {e.outcome for e in entries} == {"changed"}
    assert {e.detail for e in entries} == {"Try-on measurements changed"}  # fixed words only
    names = [  # the hash is of the action and the field NAMES: never a number he typed
        {"action": "draft", "fields": ["chest", "height"]}, {"action": "use", "fields": []},
        {"action": "draft", "fields": ["height"]}, {"action": "keep_current", "fields": []},
    ]  # fmt: skip
    assert [e.args_hash for e in entries] == [args_hash(x) for x in names]


async def test_the_look_route_refuses_in_words() -> None:
    a = await a_world()
    async with a.client() as c:
        _refusal(await c.get("/v1/tryon/look?plan=op_00000bad"), 404, "gone")
        _refusal(await c.get("/v1/tryon/look?day=next+week"), 422, "bad_day")
        _refusal(await c.get("/v1/tryon/look?day=tomorrow&alt=3"), 422, "bad_request")
        _refusal(await c.get("/v1/tryon/look?day=tomorrow&alt=x"), 422, "bad_request")
        _refusal(await c.get("/v1/tryon/look?plan=op_00000bad&alt=1"), 404, "gone")
        got = _refusal(await c.get("/v1/tryon/look?pieces=top:wi_000000000999"), 422, "not_a_piece")
        assert got.detail
        _refusal(await c.get("/v1/tryon/look?pieces=" + "x" * 2000), 422, "bad_request")


async def test_a_private_basic_is_shown_only_when_he_asks() -> None:
    a = await a_world()
    async with a.client() as c:
        hidden = (await c.get(f"/v1/tryon/look?pieces=top:{T.shirt},base:{T.vest}")).json()
        shown = (await c.get(f"/v1/tryon/look?pieces=top:{T.shirt},base:{T.vest}&private=1")).json()
    assert T.vest not in json.dumps(hidden) and T.vest in json.dumps(shown)


async def test_figure_choices_refuse_in_words() -> None:
    a = await a_world()
    async with a.client() as c:
        _refusal(await c.put("/v1/tryon/assets/wi_ffffffffffff",
                             json={"piece": "wi_ffffffffffff"}), 404, "not_in")  # fmt: skip
        _refusal(await c.put("/v1/tryon/assets/nonsense", json={"piece": T.shirt}), 404, "not_in")
        vest = {"piece": T.vest, "template": "tee"}
        _refusal(await c.put(f"/v1/tryon/assets/{T.vest}", json=vest), 422, "wrong_shape")
        shirt = {"piece": T.shirt, "template": "trousers"}
        _refusal(await c.put(f"/v1/tryon/assets/{T.shirt}", json=shirt), 422, "wrong_shape")
        ok = await c.put(f"/v1/tryon/assets/{T.shirt}", json={"piece": T.shirt, "card_only": True})
        assert ok.status_code == 200 and AssetChoice.model_validate(ok.json()).card_only


async def test_saved_comparisons_over_http() -> None:
    a = await a_world()
    look = {"slots": [{"slot": "top", "piece": T.white}, {"slot": "shoes", "piece": SHOES[0]}]}
    async with a.client() as c:
        made = await c.post("/v1/tryon/saved", json={"looks": [look]})
        assert made.status_code == 200
        sid = SavedView.model_validate(made.json()).id
        assert (await c.get(f"/v1/tryon/saved/{sid}")).json()["id"] == sid
        _refusal(await c.get("/v1/tryon/saved/tc_0000ffff"), 404, "gone")
        _refusal(await c.get("/v1/tryon/saved/nonsense"), 404, "gone")
        _refusal(await c.post("/v1/tryon/saved", json={"looks": [{"slots": [
            {"slot": "top", "piece": "wi_ffffffffffff"}]}]}), 422, "not_a_look")  # fmt: skip
        _refusal(await c.post("/v1/tryon/saved", json={"looks": []}), 422, "bad_request")
        gone = await c.delete(f"/v1/tryon/saved/{sid}")
        assert gone.status_code == 200 and gone.json() == {"deleted": True, "message": "Deleted."}
        again = await c.delete(f"/v1/tryon/saved/{sid}")
        assert again.json() == {"deleted": False, "message": "Already gone."}
        _refusal(await c.delete("/v1/tryon/saved/nonsense"), 404, "gone")
        for _ in range(m.SAVED_MAX):
            assert (await c.post("/v1/tryon/saved", json={"looks": [look]})).status_code == 200
        _refusal(await c.post("/v1/tryon/saved", json={"looks": [look]}), 409, "too_many")


@pytest.fixture
def frozen_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    """R13's limiter on a FIXED clock: no token refills while a slow machine runs the requests
    (its real clock refills one read a second, so 60 reads taking over a second would let the
    61st through)."""
    from jarvis.api import r13_status
    from jarvis.api.ratelimit import RateLimiter

    monkeypatch.setattr(r13_status, "RateLimiter", lambda per: RateLimiter(per, now=lambda: 0.0))


@pytest.mark.usefixtures("frozen_limits")
async def test_reads_are_limited_to_60_and_changes_to_30_a_minute() -> None:
    a = await a_world()
    async with a.client() as c:
        reads = [(await c.get("/v1/tryon")).status_code for _ in range(61)]
        assert reads[:60] == [200] * 60
        _refusal(await c.get("/v1/tryon"), 429, "rate_limited")
        changes = [(await c.put("/v1/tryon/body", json={"height": 170})).status_code
                   for _ in range(31)]  # fmt: skip
        assert changes[:30] == [200] * 30 and changes[30] == 429


async def test_off_says_so_in_the_parts_own_words() -> None:
    a = await a_world(keyring=None)
    async with a.client() as c:
        got = _refusal(await c.get("/v1/tryon"), 503, "off")
        assert got.detail == a.part.ready and got.detail.startswith("Off")
        _refusal(await c.get(f"/v1/tryon/look?pieces=top:{T.shirt}"), 503, "off")
        _refusal(await c.put(f"/v1/tryon/assets/{T.shirt}", json={"piece": T.shirt}), 503, "off")
        _refusal(await c.post("/v1/tryon/confirm", json={"plan": "op_00000bad", "slots": [
            {"slot": "top", "piece": T.shirt}]}), 503, "off")  # fmt: skip
        _refusal(await c.get("/v1/tryon/saved/tc_0000abcd"), 503, "off")


async def test_with_styling_off_the_view_still_answers_and_the_look_says_why() -> None:
    a = await a_world()
    a.parts.pop("styling")
    async with a.client() as c:
        view = TryonView.model_validate((await c.get("/v1/tryon")).json())
        assert view.words == m.NO_FIGURE and view.ready == "ready"
        _refusal(await c.get("/v1/tryon/look?day=today"), 503, "off")


async def test_the_figures_files_come_from_the_checked_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from jarvis.api import tryon_assets

    folder = tmp_path / tryon_assets.RELEASE
    folder.mkdir()
    files = {"garments.glb": b"glTF-g", "body.glb": b"glTF-b", "NOTICE-mannequin.txt": b"n"}
    listed = {}
    for name, data in files.items():
        (folder / name).write_bytes(data)
        kind = "text/plain" if name.endswith(".txt") else "application/octet-stream"
        listed[name] = {"sha256": hashlib.sha256(data).hexdigest(), "type": kind}
    (folder / "MANIFEST.json").write_text(json.dumps({"files": listed}), encoding="utf-8")
    monkeypatch.setattr(tryon_assets, "MANNEQUIN", tmp_path)
    tryon_assets.mannequin_files.cache_clear()
    a = await a_world()
    try:
        async with a.client() as c:
            view = TryonView.model_validate((await c.get("/v1/tryon")).json())
    finally:
        tryon_assets.mannequin_files.cache_clear()
    assert view.release == "m1" and view.files == ("body.glb", "garments.glb")


async def test_a_confirm_that_isnt_a_look_is_refused_in_words() -> None:
    a = await a_world()
    pid = await a.plan()
    async with a.client() as c:
        _refusal(await c.post("/v1/tryon/confirm", json={"plan": "op_00000bad", "slots": [
            {"slot": "top", "piece": T.white}]}), 404, "gone")  # fmt: skip
        _refusal(await c.post("/v1/tryon/confirm", json={"plan": pid, "slots": [
            {"slot": "bottom", "piece": T.white}]}), 422, "not_a_look")  # fmt: skip
        _refusal(await c.post("/v1/tryon/confirm", json={"plan": pid, "slots": []}), 422,
                 "bad_request")  # fmt: skip


async def test_a_confirm_with_no_gateway_is_refused_in_the_contracts_shape() -> None:
    a = await a_world()
    pid = await a.plan()
    app = a.app()
    app.state.gateway = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        got = await c.post("/v1/tryon/confirm", json=await a.whole(pid))  # the whole look
    _refusal(got, 404, "unavailable")


async def test_a_removed_watch_is_a_409_left_out_with_no_call() -> None:
    a = await a_world()
    pid = await a.plan()
    seen: list[str] = []
    real = a.w.gw.execute

    async def execute(call: Any, **kw: Any) -> Any:
        seen.append(call.name)
        return await real(call, **kw)

    a.w.gw.execute = execute  # type: ignore[method-assign]
    async with a.client() as c:
        got = await c.post("/v1/tryon/confirm", json=await a.whole(pid, drop="watch"))
    assert _refusal(got, 409, "left_out").detail.startswith("This plan can't leave out its watch")
    assert seen == []  # refused before any tool call (D7's Remove, review A-1 F2)


async def test_a_tool_error_on_the_one_call_is_a_refusal_in_r13s_words() -> None:
    from jarvis.tools.gateway import GatewayOutcome, GatewayResult

    a = await a_world()
    pid = await a.plan()

    async def failing(call: Any, **kw: Any) -> GatewayResult:
        return GatewayResult(GatewayOutcome.ERROR, error="The plan is busy (lock held by job)")

    a.w.gw.execute = failing  # type: ignore[method-assign]
    async with a.client() as c:
        got = await c.post("/v1/tryon/confirm", json=await a.whole(pid))  # the whole look
    assert _refusal(got, 422, "tool_error").detail == "The plan is busy"  # R13's words, cut


@pytest.mark.parametrize("words", [
    "That plan changed meanwhile: try again.",  # R13's M1 conflict
    "Your wardrobe isn't ready yet: try again in a minute.",
    "One piece a slot: top has two.",
])  # fmt: skip
async def test_any_refusal_by_outfit_plan_is_a_409_refused_never_executed(words: str) -> None:
    from jarvis.tools.gateway import GatewayOutcome, GatewayResult

    a = await a_world()
    pid = await a.plan()

    async def refusing(call: Any, **kw: Any) -> GatewayResult:  # R13 refuses as a result
        return GatewayResult(GatewayOutcome.EXECUTED, result={"refused": True, "message": words})

    a.w.gw.execute = refusing  # type: ignore[method-assign]
    async with a.client() as c:
        got = await c.post("/v1/tryon/confirm", json=await a.whole(pid))  # the whole look
    assert _refusal(got, 409, "refused").detail == words


async def test_switched_off_in_his_permissions_stays_r13s_denied_reply() -> None:
    from jarvis.tools.gateway import GatewayOutcome, GatewayResult

    a = await a_world()
    pid = await a.plan()

    async def denied(call: Any, **kw: Any) -> GatewayResult:
        return GatewayResult(GatewayOutcome.DENIED)

    a.w.gw.execute = denied  # type: ignore[method-assign]
    async with a.client() as c:
        got = await c.post("/v1/tryon/confirm", json=await a.whole(pid))  # the whole look
    assert got.status_code == 200 and got.json()["status"] == "denied"


async def test_a_body_nested_past_reason_is_a_refusal_not_a_crash() -> None:
    a = await a_world()
    deep = b"[" * 8_000 + b"]" * 8_000  # under the 16 KB cap, past json's recursion limit
    async with a.client() as c:
        _refusal(await c.put("/v1/tryon/body", content=deep), 422, "bad_request")
        _refusal(await c.post("/v1/tryon/saved", content=deep), 422, "bad_request")


async def test_every_body_is_capped_at_16_kb_before_it_is_read_as_json() -> None:
    a = await a_world()
    big = b'{"height": 172, "x": "' + b"a" * routes.BODY_MAX + b'"}'
    bodied = [(meth, path.replace("{piece}", T.shirt)) for meth, path, part, req, *_ in ROUTES
              if part == "tryon" and req is not None]  # fmt: skip
    assert len(bodied) == 4
    async with a.client() as c:
        for meth, url in bodied:
            got = _refusal(await c.request(meth, url, content=big), 413, "too_large")
            assert got.detail == routes.TOO_LARGE
        ok = await c.put("/v1/tryon/body", content=b'{"height": 172}')
        assert ok.status_code == 200
    for meth, path, part, req, _, errors, _ in ROUTES:
        if part == "tryon" and req is not None:
            assert 413 in errors, (meth, path)  # the contract's rows say so


async def test_use_these_measurements_is_bound_to_the_draft_he_saw() -> None:
    a = await a_world()
    async with a.client() as c:
        laptop = (await c.put("/v1/tryon/body", json={"height": 172})).json()["draft"]["at"]
        a.clock.advance(minutes=3)
        phone = (await c.put("/v1/tryon/body", json={"height": 178})).json()["draft"]["at"]
        stale = await c.post("/v1/tryon/body/use", params={"at": laptop})  # the laptop's press
        assert _refusal(stale, 409, "changed").detail == routes.versions.CHANGED
        kept = TryonView.model_validate((await c.get("/v1/tryon")).json()).body
        assert kept.current is None and kept.draft.height == 178  # type: ignore[union-attr]
        _refusal(await c.post("/v1/tryon/body/use", params={"at": "yesterday"}), 422,
                 "bad_request")  # fmt: skip
        used = await c.post("/v1/tryon/body/use", params={"at": phone})  # the draft he saw
        assert used.status_code == 200 and used.json()["current"]["height"] == 178
    row = next(e for m_, p, _, _, _, e, _ in ROUTES if (m_, p) == ("POST", "/v1/tryon/body/use"))
    assert {409, 422} <= set(row)


@pytest.mark.parametrize("value", ["172", 172.0, 172.5, True])
async def test_a_measurement_not_typed_as_whole_centimetres_is_refused_in_words(value: Any) -> None:
    a = await a_world()
    async with a.client() as c:
        got = _refusal(await c.put("/v1/tryon/body", json={"height": value}), 422, "not_whole")
    assert got.detail == "Type each measurement in whole centimetres, for example 172."


@pytest.mark.usefixtures("frozen_limits")
async def test_reads_and_changes_of_one_route_keep_their_own_allowances() -> None:
    a = await a_world()
    async with a.client() as c:
        assert (await c.get("/v1/tryon/saved")).status_code == 200  # a read comes first
        drops = [(await c.delete("/v1/tryon/saved/tc_0000abcd")).status_code for _ in range(31)]
    assert drops[:30] == [200] * 30 and drops[30] == 429  # changes: 30 a minute, not 60


async def test_the_view_answers_even_when_r13s_store_breaks() -> None:
    a = await a_world()

    async def broken(uid: str) -> Any:
        raise WardrobeUnavailable("R13's store is down")  # what R13's store raises

    a.styling.view = broken  # type: ignore[method-assign]
    async with a.client() as c:
        r = await c.get("/v1/tryon")
    assert r.status_code == 200 and TryonView.model_validate(r.json()).words == m.NO_FIGURE


async def test_with_r13s_records_unreadable_the_view_lists_no_choice_it_cant_check() -> None:
    a = await a_world()
    async with a.client() as c:
        chose = {"piece": T.striped, "card_only": True}
        assert (await c.put(f"/v1/tryon/assets/{T.striped}", json=chose)).status_code == 200
    await a.w.edit(T.striped, private=True)  # made private since: its id is never served (AVT-14)

    async def broken(uid: str) -> Any:
        raise WardrobeUnavailable("R13's store is down")  # what R13's store raises

    a.styling.view = broken  # type: ignore[method-assign]
    async with a.client() as c:
        r = await c.get("/v1/tryon")
    assert r.status_code == 200 and TryonView.model_validate(r.json()).assets == ()
    assert T.striped not in r.text
    assert T.striped in (await a.service.store.read(UID)).assets  # kept, only not shown

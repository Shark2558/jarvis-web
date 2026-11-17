# tests/test_r131_a_contract.py -- R13.1 Part A, review A-1 F1: the console-facing contract of "Use
# this look" when `outfit_plan` itself refuses (D20's race: the jacket goes to the laundry between
# A's fresh check and the one call). A's real route and I0's fake server (`r131_fake_server`, which
# D's console is built against until I1) answer it the same way: 409 `Refusal` {"error":
# "refused", "detail": R13's words}, `no-store`, a status of the contract's own row; never 200
# "executed". The fake scripts the race two ways: its state's `refuse` (in-process tests) or a
# confirm of `RACE_PLAN` (a browser test against the fake in its own process).
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from r131_fake_server import RACE_PLAN, fake_routes, fake_state
from r131_fakes_a import UID, AWorld, T, a_world

from jarvis.api.auth import require_auth
from jarvis.wardrobe.tryon import http

LOCK_REFUSED = "The navy jacket is in the laundry: it can't be locked into this plan."
FAKE_RACE = "The charcoal blazer is in the laundry: it can't be locked into this plan."
CONFIRM_ERRORS = next(e for m, p, _, _, _, e, _ in http.ROUTES if p == "/v1/tryon/confirm")


def _console_reads_a_refusal(got: Response) -> http.Refusal:
    """What D's console relies on: a status of the row, `no-store`, and `err.code` to branch on."""
    assert got.status_code == 409 and 409 in CONFIRM_ERRORS, got.text
    assert got.headers["cache-control"] == "no-store"
    found = http.Refusal.model_validate(got.json())
    assert found.error == "refused" and "status" not in got.json()  # never a ToolReply
    return found


async def _whole_look(a: AWorld, pid: str, outer: str) -> dict[str, Any]:
    look = await a.service.looks.for_plan(UID, pid)
    pairs = [(s.slot, outer if s.slot == "outer" else s.piece) for s in look.slots if s.piece]
    return {"plan": pid, "slots": [{"slot": s, "piece": p} for s, p in pairs]}


async def _real_race() -> Response:
    a = await a_world()
    pid = await a.plan()
    body = await _whole_look(a, pid, T.rain_jacket)
    real = a.w.gw.execute

    async def execute(call: Any, **kw: Any) -> Any:  # to the laundry after A's check (D20)
        if call.name == "outfit_plan":
            await a.move(T.rain_jacket)
        return await real(call, **kw)

    a.w.gw.execute = execute  # type: ignore[method-assign]
    async with a.client() as c:
        return await c.post("/v1/tryon/confirm", json=body)


async def _fake_client() -> tuple[AsyncClient, Any]:
    store, clock = await fake_state()
    router = fake_routes(store, clock)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_auth] = lambda: None
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return client, router.state  # type: ignore[attr-defined]


def _fake_body(plan: str) -> dict[str, Any]:
    return {"plan": plan, "slots": [{"slot": "top", "piece": T.striped},
                                    {"slot": "outer", "piece": T.blazer}]}  # fmt: skip


async def test_the_race_reads_the_same_from_the_real_route_and_the_fake_server() -> None:
    real = _console_reads_a_refusal(await _real_race())
    assert real.detail == LOCK_REFUSED  # R13's own words

    client, state = await _fake_client()
    async with client as c:

        async def confirm(plan: str) -> Response:
            return await c.post("/v1/tryon/confirm", json=_fake_body(plan))

        assert (await confirm("op_00000001")).status_code == 200  # no race: R13's ToolReply
        state.refuse = LOCK_REFUSED  # an in-process test scripts outfit_plan's refusal
        scripted = _console_reads_a_refusal(await confirm("op_00000001"))
        state.refuse = None
        by_plan = _console_reads_a_refusal(await confirm(RACE_PLAN))
    assert scripted == real
    assert by_plan.detail == FAKE_RACE  # R13's sentence, for the fake look's outer layer


async def test_the_fakes_early_refusal_still_comes_first() -> None:
    client, state = await _fake_client()
    state.refuse = LOCK_REFUSED
    async with client as c:
        got = await c.post("/v1/tryon/confirm", json={"plan": RACE_PLAN, "slots": [
            {"slot": "top", "piece": "wi_ffffffffffff"}]})  # fmt: skip
    assert got.status_code == 409 and got.json()["error"] == "draft"  # before any call (D7)

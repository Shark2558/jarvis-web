# tests/test_r131_panel_tool.py -- R13.1 I0 seam 12 (docs/plans/r13-1-try-on.md D7, D20.3; review
# H2): the panel's one call through the gateway, `api.wardrobe.run_panel_tool`, shared by R13's
# `POST /v1/wardrobe/tools/{tool}` and R13.1 A's `POST /v1/tryon/confirm`. One press makes at most
# one card: a call that needs his OK is cancelled in the plain scope and made again once in a
# conversation of his own, where its card waits. Also D17: `outfit_suggest`'s `see_it` words while
# Try-on is on (never a ₹ figure), and none while it is off.
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from r13_fakes import UID
from r13_fakes_c import N, ist, settings, world
from starlette.requests import Request

from jarvis.api.wardrobe import NO_CONVERSATION, UNAVAILABLE, panel_reply, run_panel_tool
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.tools.gateway import GatewayOutcome
from jarvis.wardrobe.http import ToolReply

SEE_IT = (
    "In Helpers, Wardrobe you can see this look on your 3D figure, free, or press See it on me; "
    "its price is shown before each picture."
)


def _request(gw: Any, *, store: Any = None) -> Request:
    app = FastAPI()
    app.state.gateway, app.state.store = gw, store
    return Request({"type": "http", "app": app, "headers": [], "method": "POST", "path": "/"})


async def _plan(w: Any) -> str:
    got = await w.call("outfit_plan", action="save", day="tomorrow", occasion="meeting")
    return str(got.result["plan"]["id"])


async def test_an_allowed_call_runs_once_in_the_plain_scope() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    pid = await _plan(w)
    req = _request(w.gw, store=InMemorySessionStore())
    run = await run_panel_tool(req, UID, "outfit_plan", {"action": "lock", "plan": pid,
                                                         "pieces": [N.blazer]})  # fmt: skip
    assert run.result is not None and run.result.outcome is GatewayOutcome.EXECUTED
    assert run.session_id is None and run.refusal is None
    reply = ToolReply.model_validate_json(panel_reply(run).body)
    assert reply.status == "executed" and reply.result and reply.result["plan"]["id"] == pid


async def test_a_call_that_needs_his_ok_makes_one_card_in_his_conversation() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    pid = await _plan(w)
    store = InMemorySessionStore()
    run = await run_panel_tool(_request(w.gw, store=store), UID, "outfit_plan",
                               {"action": "release", "plan": pid})  # fmt: skip  # always a card
    assert run.result is not None and run.result.outcome is GatewayOutcome.AWAITING_CONFIRMATION
    cards = await w.gw.gate.pending()
    assert len(cards) == 1 and cards[0].scope == f"{UID}:{run.session_id}"  # at most one card
    saved = await store.get(str(run.session_id))
    assert saved is not None and saved.user_id == UID
    reply = ToolReply.model_validate_json(panel_reply(run).body)
    assert reply.status == "needs_approval" and reply.session_id == run.session_id


async def test_no_conversation_to_ask_in_cancels_the_card_and_says_so() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    pid = await _plan(w)
    run = await run_panel_tool(_request(w.gw, store=None), UID, "outfit_plan",
                               {"action": "release", "plan": pid})  # fmt: skip
    assert run.result is None and run.refusal == (422, NO_CONVERSATION)
    assert await w.gw.gate.pending() == []
    assert panel_reply(run).status_code == 422


async def test_an_unknown_tool_or_no_gateway_is_refused_before_any_call() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    for req, tool in ((_request(w.gw), "shell_exec"), (_request(None), "outfit_plan")):
        run = await run_panel_tool(req, UID, tool, {})
        assert run.result is None and run.refusal == (404, UNAVAILABLE)
        assert panel_reply(run).status_code == 404


# ---- D17: outfit_suggest's see_it words ---------------------------------------------------------
async def test_outfit_suggest_says_where_try_on_is_while_it_is_on() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    got = await w.call("outfit_suggest", day="tomorrow")
    assert got.result["see_it"] == SEE_IT and "₹" not in got.result["see_it"]


async def test_outfit_suggest_says_nothing_of_try_on_while_it_is_off() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0), s=settings(tryon_enabled=False))
    got = await w.call("outfit_suggest", day="tomorrow")
    assert "see_it" not in got.result

# tests/test_r11_1_d_turnguard_web.py -- R11.1 Part D, the I1 gate for `web_search` (security
# review H1), tried on the REAL web_search tool through a real gateway. `web/tools.py` is not this
# part's file, so the test applies exactly what INTEGRATION-D asks I1 to add: the guard's look-up
# (`TurnGuard.query_preview`, so an "Ask first" card never shows a face-derived name) and the one
# call in the run (`TurnGuard.query_stop`, so the vendor never receives one). On a picture turn a
# query naming someone he did not type is refused in fixed words and nothing is searched; a query
# about a thing goes ahead; a turn without a picture is unchanged. Everybody named is made up.
from __future__ import annotations

from dataclasses import replace
from typing import Any

from r11_1_fakes_d import FakeSearchVendor

from jarvis.core.guardrails import ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.picture.turnguard import WEB_REFUSED, TurnGuard
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog
from jarvis.tools.base import Tool
from jarvis.tools.gateway import Gateway, GatewayOutcome, GatewayResult
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.taint import context_trust
from jarvis.web.allowance import WebAllowance
from jarvis.web.service import WebService
from jarvis.web.tools import web_tools

SCOPE = "u_owner:sess_1"
FACE = "Meenu Examplewala"  # a made-up person the model "recognised"


class Turns:
    def __init__(self, answer: str) -> None:
        self.answer = answer

    async def carried(self, uid: str, session_id: str) -> str:
        return self.answer


class Rows:
    def __init__(self, effect: Effect) -> None:
        self.effect = effect

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        return [PolicyRule(tool_pattern="web_*", effect=self.effect, source="owner")]


def _gated(tool: Tool, guard: TurnGuard) -> Tool:
    """web_search as I1 leaves it: the guard's look-up, and its one call first in the run."""

    async def run(a: dict[str, Any]) -> dict[str, Any]:
        if (stop := await guard.query_stop(str(a["query"]).strip())) is not None:
            return stop
        return await tool.run(a)

    return replace(tool, run=run, preview=guard.query_preview)


def _rig(picture: bool, rows: Effect | None = None) -> tuple[Gateway, FakeSearchVendor]:
    vendor = FakeSearchVendor()
    web = WebService(vendor, WebAllowance(MemoryDocs()))
    guard = TurnGuard(Turns("yes" if picture else "no"), lambda uid, sid: None)
    registry = ToolRegistry()
    for tool in web_tools(web):
        registry.register(_gated(tool, guard) if tool.name == "web_search" else tool)
    gw = Gateway(
        registry=registry,
        policy=Policy(),
        gate=ConfirmationGate(),
        audit=AuditLog(),
        rules=Rows(rows) if rows is not None else None,
    )
    return gw, vendor


async def _search(gw: Gateway, query: str, typed: str) -> GatewayResult:
    call = ToolCall(id="w1", name="web_search", arguments={"query": query})
    with context_trust(untrusted=False, owner_text=typed):
        return await gw.execute(call, scope=SCOPE)


async def test_a_face_derived_name_never_reaches_the_vendor() -> None:
    gw, vendor = _rig(picture=True)

    res = await _search(gw, f"{FACE} actress", "who is this?")

    assert res.outcome is GatewayOutcome.ERROR and WEB_REFUSED in (res.error or "")
    assert vendor.queries == []


async def test_a_query_about_a_thing_goes_ahead_on_a_picture_turn() -> None:
    gw, vendor = _rig(picture=True)

    res = await _search(gw, "biryani recipe", "how do I make this?")

    assert res.outcome is GatewayOutcome.EXECUTED and vendor.queries == ["biryani recipe"]


async def test_a_name_he_typed_goes_ahead_and_a_turn_without_a_picture_is_unchanged() -> None:
    gw, vendor = _rig(picture=True)
    typed = await _search(gw, f"{FACE} Example Corp", f"is this {FACE} of Example Corp?")
    plain, plain_vendor = _rig(picture=False)
    other = await _search(plain, f"{FACE} Example Corp", "who runs Example Corp?")

    assert typed.outcome is GatewayOutcome.EXECUTED and vendor.queries == [f"{FACE} Example Corp"]
    assert other.outcome is GatewayOutcome.EXECUTED and plain_vendor.queries == [
        f"{FACE} Example Corp"
    ]


async def test_with_ask_first_a_refused_query_never_becomes_a_card() -> None:
    gw, vendor = _rig(picture=True, rows=Effect.ASK)

    refused = await _search(gw, f"{FACE} actress", "who is this?")
    carded = await _search(gw, "biryani recipe", "how do I make this?")

    assert refused.outcome is GatewayOutcome.ERROR and refused.pending is None
    assert (
        carded.pending is not None
        and carded.pending.summary == "Search the web for: biryani recipe"
    )
    assert vendor.queries == []


async def test_the_run_alone_still_refuses_when_no_look_up_ran() -> None:
    """Defence in depth: the run's own call refuses too (as when the card was approved later)."""
    vendor = FakeSearchVendor()
    web = WebService(vendor, WebAllowance(MemoryDocs()))
    (search, *_) = web_tools(web)
    guard = TurnGuard(Turns("yes"), lambda uid, sid: None)
    gated = _gated(search, guard)
    registry = ToolRegistry()
    registry.register(replace(gated, preview=None))
    gw = Gateway(registry=registry, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())

    res = await _search(gw, f"{FACE} actress", "who is this?")

    assert res.result == {"refused": True, "message": WEB_REFUSED, "spoken": WEB_REFUSED}
    assert vendor.queries == []


def test_the_fixed_words_fit_the_gateways_error_detail_whole() -> None:
    from jarvis.people.tools import PictureNameRefused
    from jarvis.picture.guard import NO_IDENTIFY
    from jarvis.picture.turnguard import PictureQueryRefused
    from jarvis.tools.gateway import _safe_detail

    for exc in (PictureQueryRefused(WEB_REFUSED), PictureNameRefused(NO_IDENTIFY)):
        assert _safe_detail(exc).endswith(str(exc))

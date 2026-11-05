# tests/test_people_tools.py
"""research_person / people_open_profiles through the real gateway (audited, scope-guarded)."""

from __future__ import annotations

import pytest

from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.people import guard
from jarvis.people.research import PeopleService
from jarvis.people.tools import OPEN_PROFILES, RESEARCH_PERSON, PeopleDeps, people_tools
from jarvis.permissions.groups import GROUPS
from jarvis.tools import AuditLog, Gateway, Policy, ToolRegistry
from jarvis.tools.gateway import GatewayOutcome
from jarvis.web.ports import SearchHit
from tests.test_people_research import FakeComposer, FakeSearcher

SCOPE = "owner:s1"


def build(brain_mode: str = "ai", composer: FakeComposer | None = None):
    svc = PeopleService(FakeSearcher(), composer)
    reg = ToolRegistry()
    for t in people_tools(PeopleDeps(service=svc, brain_mode=lambda: brain_mode)):
        reg.register(t)
    audit = AuditLog()
    return Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=audit), audit


def call(tool: str, /, **args):
    return ToolCall(id="c1", name=tool, arguments=args)


def test_tools_are_read_only_and_named_for_the_people_row() -> None:
    tools = people_tools(PeopleDeps(service=PeopleService(FakeSearcher()), brain_mode=lambda: "ai"))

    assert {t.name for t in tools} == {RESEARCH_PERSON, OPEN_PROFILES}
    assert all(t.risk is ActionRisk.READ_ONLY for t in tools)
    row = next(g for g in GROUPS if g.id == "people")
    assert all(row.matches(t.name, ActionRisk.READ_ONLY) for t in tools)


async def test_public_figure_research_runs_and_is_fenced() -> None:
    gw, audit = build(composer=FakeComposer())

    res = await gw.execute(
        call(RESEARCH_PERSON, name="Satya Nadella", context="Microsoft"), scope=SCOPE
    )

    assert res.outcome is GatewayOutcome.EXECUTED
    assert res.result["profiles"]
    assert "external content" in str(res.result["findings"][0]["snippet"]).lower()
    assert (await audit.tail(5)).entries  # the call is audited


async def test_private_individual_request_is_refused_by_the_gateway_with_a_plain_message() -> None:
    gw, _ = build(composer=FakeComposer())

    res = await gw.execute(
        call(RESEARCH_PERSON, name="Ravi Kumar", context="my neighbour, where he lives"),
        scope=SCOPE,
    )

    assert res.outcome is GatewayOutcome.ERROR
    assert "public" in (res.error or "").lower()


async def test_refusal_disappears_without_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative control at the tool layer."""
    monkeypatch.setattr(guard, "GUARD_ENABLED", False)
    gw, _ = build(composer=FakeComposer())

    res = await gw.execute(
        call(RESEARCH_PERSON, name="Satya Nadella", context="his home address"), scope=SCOPE
    )

    assert res.outcome is GatewayOutcome.EXECUTED


async def test_no_ai_mode_returns_links_and_never_calls_the_composer() -> None:
    composer = FakeComposer()
    gw, _ = build("none", composer)

    res = await gw.execute(
        call(RESEARCH_PERSON, name="Satya Nadella", context="Microsoft"), scope=SCOPE
    )

    assert composer.calls == []
    assert res.result["summary"] is None and res.result["no_ai"] is True


async def test_open_profiles_returns_the_resolved_urls_for_the_client() -> None:
    gw, _ = build()
    await gw.execute(call(RESEARCH_PERSON, name="Satya Nadella", context="Microsoft"), scope=SCOPE)

    res = await gw.execute(call(OPEN_PROFILES), scope=SCOPE)

    assert res.outcome is GatewayOutcome.EXECUTED
    assert res.result["open"] and all(u.startswith("https://") for u in res.result["open"])


async def test_open_profiles_can_pick_platforms() -> None:
    gw, _ = build()
    await gw.execute(call(RESEARCH_PERSON, name="Satya Nadella", context="Microsoft"), scope=SCOPE)

    res = await gw.execute(call(OPEN_PROFILES, platforms=["linkedin"]), scope=SCOPE)

    assert [u for u in res.result["open"]] == ["https://www.linkedin.com/in/satyanadella"]


async def test_open_profiles_without_a_research_says_so() -> None:
    gw, _ = build()

    res = await gw.execute(call(OPEN_PROFILES), scope=SCOPE)

    assert res.result["open"] == []
    assert "research" in res.result["message"].lower()


async def test_search_failure_surfaces_as_a_plain_error() -> None:
    svc = PeopleService(FakeSearcher(fail=True))
    reg = ToolRegistry()
    for t in people_tools(PeopleDeps(service=svc, brain_mode=lambda: "ai")):
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())

    res = await gw.execute(call(RESEARCH_PERSON, name="Satya Nadella"), scope=SCOPE)

    assert res.outcome is GatewayOutcome.ERROR
    assert "not available" in (res.error or "").lower()


def test_unused_import_guard() -> None:
    assert SearchHit  # keeps the shared fixtures' types imported for readers

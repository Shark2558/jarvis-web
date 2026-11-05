# tests/test_people_tools.py
"""research_person / people_open_profiles through the real gateway (audited, gated, fenced)."""

from __future__ import annotations

from research_fakes import PRIVATE_HITS, FakeModel, FakeSearcher, fixed_mode

from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.people.guard import UNVERIFIED_REFUSAL
from jarvis.people.research import PeopleService
from jarvis.people.tools import OPEN_PROFILES, RESEARCH_PERSON, PeopleDeps, people_tools
from jarvis.permissions.groups import GROUPS
from jarvis.tools import AuditLog, Gateway, Policy, ToolRegistry
from jarvis.tools.budget import turn_budget
from jarvis.tools.gateway import GatewayOutcome

SCOPE = "owner:s1"


def build(mode: str = "ai", model: FakeModel | None = None, searcher=None, gate: bool = True):
    svc = PeopleService(searcher or FakeSearcher(), model, mode=fixed_mode(mode), gate_enabled=gate)
    reg = ToolRegistry()
    for t in people_tools(PeopleDeps(service=svc)):
        reg.register(t)
    audit = AuditLog()
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=audit)
    return gw, audit


def call(tool: str, /, **args):
    return ToolCall(id="c1", name=tool, arguments=args)


def test_tools_are_read_only_and_named_for_the_people_row() -> None:
    tools = people_tools(PeopleDeps(service=PeopleService(FakeSearcher())))

    assert {t.name for t in tools} == {RESEARCH_PERSON, OPEN_PROFILES}
    assert all(t.risk is ActionRisk.READ_ONLY for t in tools)
    row = next(g for g in GROUPS if g.id == "people")
    assert all(row.matches(t.name, ActionRisk.READ_ONLY) for t in tools)


async def test_public_figure_research_runs_and_is_fenced() -> None:
    gw, audit = build(model=FakeModel())

    res = await gw.execute(
        call(RESEARCH_PERSON, name="Satya Nadella", context="Microsoft"), scope=SCOPE
    )

    assert res.outcome is GatewayOutcome.EXECUTED
    assert res.result["profiles"]
    assert "external content" in str(res.result["findings"][0]["snippet"]).lower()
    assert "external content" in str(res.result["summary"]).lower()
    assert (await audit.tail(5)).entries  # the call is audited


async def test_a_model_never_gets_the_spoken_form_of_its_own_summary_back() -> None:
    gw, _ = build(model=FakeModel())

    res = await gw.execute(call(RESEARCH_PERSON, name="Satya Nadella", context="Ms"), scope=SCOPE)

    assert "spoken" not in res.result  # derived from a model summary: kept off the model's view


async def test_without_a_summary_the_spoken_line_is_a_fixed_template() -> None:
    gw, _ = build("none")

    res = await gw.execute(call(RESEARCH_PERSON, name="Satya Nadella", context=""), scope=SCOPE)

    assert res.result["spoken"].startswith("I found")


async def test_private_phrasing_is_refused_by_the_gateway_with_a_plain_message() -> None:
    gw, _ = build(model=FakeModel())

    res = await gw.execute(
        call(RESEARCH_PERSON, name="Ravi Kumar", context="my neighbour, where he lives"),
        scope=SCOPE,
    )

    assert res.outcome is GatewayOutcome.ERROR
    assert "public" in (res.error or "").lower()


async def test_a_bare_private_name_comes_back_refused_with_no_links() -> None:
    searcher = FakeSearcher(PRIVATE_HITS)
    gw, _ = build(model=FakeModel(), searcher=searcher)

    res = await gw.execute(call(RESEARCH_PERSON, name="Priya Nair"), scope=SCOPE)

    assert res.outcome is GatewayOutcome.EXECUTED
    assert res.result == {
        "refused": True,
        "message": UNVERIFIED_REFUSAL,
        "spoken": UNVERIFIED_REFUSAL,
    }
    assert searcher.credits == 1
    follow = await gw.execute(call(OPEN_PROFILES), scope=SCOPE)
    assert follow.result["open"] == []  # nothing to open after a refusal


async def test_refusal_disappears_without_the_pre_filter() -> None:
    """Negative control at the tool layer: the gate is injected off."""
    gw, _ = build(gate=False)

    res = await gw.execute(
        call(RESEARCH_PERSON, name="Satya Nadella", context="his home address"), scope=SCOPE
    )

    assert res.outcome is GatewayOutcome.EXECUTED


async def test_no_ai_mode_returns_links_and_never_calls_the_model() -> None:
    model = FakeModel()
    gw, _ = build("none", model)

    res = await gw.execute(
        call(RESEARCH_PERSON, name="Satya Nadella", context="Microsoft"), scope=SCOPE
    )

    assert model.calls == []
    assert res.result["summary"] is None and res.result["no_ai"] is True


async def test_open_profiles_returns_the_resolved_urls_for_the_client() -> None:
    gw, _ = build()
    await gw.execute(call(RESEARCH_PERSON, name="Satya Nadella", context="Microsoft"), scope=SCOPE)

    res = await gw.execute(call(OPEN_PROFILES), scope=SCOPE)

    assert res.outcome is GatewayOutcome.EXECUTED
    assert res.result["open"] and all(u.startswith("https://") for u in res.result["open"])


async def test_open_profiles_filters_by_platform_and_rejects_unknown_ones() -> None:
    gw, _ = build()
    await gw.execute(call(RESEARCH_PERSON, name="Satya Nadella", context="Microsoft"), scope=SCOPE)

    only = await gw.execute(call(OPEN_PROFILES, platforms=["wikipedia"]), scope=SCOPE)
    bad = await gw.execute(call(OPEN_PROFILES, platforms=["tinder"]), scope=SCOPE)

    assert only.result["open"] == ["https://en.wikipedia.org/wiki/Satya_Nadella"]
    assert bad.outcome is GatewayOutcome.ERROR


async def test_open_profiles_before_any_research_says_so() -> None:
    gw, _ = build()

    res = await gw.execute(call(OPEN_PROFILES), scope=SCOPE)

    assert res.result["open"] == [] and "researched" in res.result["message"]


async def test_search_failure_comes_back_as_a_fixed_line_not_a_stack() -> None:
    gw, _ = build(searcher=FakeSearcher(fail=True))

    res = await gw.execute(call(RESEARCH_PERSON, name="Satya Nadella", context=""), scope=SCOPE)

    assert res.outcome is GatewayOutcome.EXECUTED
    assert res.result["unavailable"] is True
    assert res.result["message"] == "Web search is not available right now."


async def test_a_message_may_research_two_people_but_not_three() -> None:
    gw, _ = build("none")
    with turn_budget():
        first = await gw.execute(call(RESEARCH_PERSON, name="Satya Nadella"), scope=SCOPE)
        second = await gw.execute(
            call(RESEARCH_PERSON, name="Satya Nadella", context="x"), scope=SCOPE
        )
        third = await gw.execute(
            call(RESEARCH_PERSON, name="Satya Nadella", context="y"), scope=SCOPE
        )

    assert first.outcome is GatewayOutcome.EXECUTED and "refused" not in first.result
    assert second.outcome is GatewayOutcome.EXECUTED
    assert "profiles" not in third.result  # stopped by the people limits, not researched

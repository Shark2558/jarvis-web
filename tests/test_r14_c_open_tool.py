# tests/test_r14_c_open_tool.py -- R14 Part C, D9: `skills_open(skill)` (R1, no side effect,
# through the gateway like every tool). It answers the skill's label, what it is about and the
# tools it holds (names only), so the next round can offer them; an unknown skill is refused by
# its argument check; its output is JARVIS's own register, so reading it taints nothing.
from __future__ import annotations

from r14_fakes_c import specs

from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.llm.base import ChatMessage, Role, ToolCall
from jarvis.skills.ids import SKILL_IDS, SKILL_LABELS
from jarvis.skills.open_tool import OPEN_WORDS, skills_open_tool
from jarvis.skills.registry import SkillRegister, load_catalogue
from jarvis.tools import AuditLog, Gateway, Policy, ToolRegistry
from jarvis.tools.base import Tool
from jarvis.tools.gateway import GatewayOutcome
from jarvis.tools.taint import untrusted_seen

REGISTER = SkillRegister(load_catalogue())


def _registry(*names: str) -> ToolRegistry:
    reg = ToolRegistry()
    for spec in specs(*names):
        reg.register(
            Tool(spec.name, spec.description, spec.input_schema, ActionRisk.READ_ONLY, _ok)
        )
    return reg


async def _ok(_: dict[str, object]) -> str:
    return "ok"


def _gateway(tool: Tool, reg: ToolRegistry) -> Gateway:
    reg.register(tool)
    return Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())


def test_the_tool_is_a_read_with_the_eleven_skills_in_its_schema() -> None:
    tool = skills_open_tool(REGISTER, lambda: None)
    assert tool.name == "skills_open" and tool.risk is ActionRisk.READ_ONLY
    assert tool.input_schema["properties"]["skill"]["enum"] == list(SKILL_IDS)
    assert tool.input_schema["required"] == ["skill"]
    assert all(sid in tool.description for sid in SKILL_IDS)
    assert tool.trusted_output and tool.activity_words == OPEN_WORDS
    assert len(tool.description) < 2_000  # it rides on every turn: keep it short


async def test_it_answers_the_skills_tools_by_name() -> None:
    reg = _registry("bill_list", "bill_pay_prepare", "spend_month", "gmail_read")
    gw = _gateway(skills_open_tool(REGISTER, lambda: reg), reg)
    got = await gw.execute(ToolCall(id="c1", name="skills_open", arguments={"skill": "finance"}))
    assert got.outcome is GatewayOutcome.EXECUTED
    assert got.result["skill"] == "finance" and got.result["label"] == SKILL_LABELS["finance"]
    assert got.result["tools"] == ["bill_list", "bill_pay_prepare", "spend_month"]
    assert "next step" in got.result["note"]


async def test_without_a_registry_it_still_answers() -> None:
    tool = skills_open_tool(REGISTER, lambda: None)
    got = await tool.run({"skill": "creative"})
    assert got["label"] == "Creative" and got["tools"] == []


async def test_an_unknown_skill_is_refused_before_it_runs() -> None:
    reg = _registry("bill_list")
    gw = _gateway(skills_open_tool(REGISTER, lambda: reg), reg)
    got = await gw.execute(ToolCall(id="c1", name="skills_open", arguments={"skill": "knowledge"}))
    assert got.outcome is GatewayOutcome.ERROR
    assert "unknown skill" in str(got.error).lower() and "finance" in str(got.error)


async def test_reading_its_answer_taints_nothing() -> None:
    reg = _registry("bill_list")
    gw = _gateway(skills_open_tool(REGISTER, lambda: reg), reg)
    call = ToolCall(id="c1", name="skills_open", arguments={"skill": "finance"})
    got = await gw.execute(call)
    msgs = [
        ChatMessage(role=Role.USER, content="pay the electricity bill"),
        ChatMessage(role=Role.ASSISTANT, content=[call]),
        ChatMessage(role=Role.USER, content=[got.block("c1")]),
    ]
    assert untrusted_seen(msgs, gw.registry) is False

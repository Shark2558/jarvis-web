# tests/test_fallback_tools.py -- R1 C (D11): the offline tool set and what the fallback does to a
# completion. Plus the wiring (BrainRegistry hands the fallback to every router) and the rule that
# the new code imports no vendor SDK.
from __future__ import annotations

import re
from pathlib import Path

from jarvis.config import LLMBackend, Settings
from jarvis.llm.base import Completion, ToolCall, ToolSpec, Usage
from jarvis.llm.brains import BrainRegistry
from jarvis.llm.fallback import (
    CANT_OFFLINE,
    OFFLINE_NOTE,
    OFFLINE_TOOLS,
    confine,
    offline_tools,
    offline_trailer,
)

ROOT = Path(__file__).resolve().parents[1] / "src" / "jarvis"


def _spec(name: str) -> ToolSpec:
    return ToolSpec(name=name, description="d", input_schema={})


def _c(text: str = "", calls: list[str] | None = None) -> Completion:
    return Completion(
        text=text,
        tool_calls=[ToolCall(id=f"i{i}", name=n) for i, n in enumerate(calls or [])],
        model="m",
        provider="p",
        usage=Usage(),
        latency_ms=1,
        cost_usd=0.9,
    )


def test_the_offline_tool_set_is_small_exact_and_has_nothing_irreversible() -> None:
    assert len(OFFLINE_TOOLS) <= 12 and len(set(OFFLINE_TOOLS)) == len(OFFLINE_TOOLS)
    assert set(OFFLINE_TOOLS) == {
        "calendar_list_events",
        "calendar_free_slots",
        "reminders_list",
        "reminder_add",
        "tasks_list",
        "task_add",
        "task_complete",
        "grocery_list",
        "grocery_add",
        "grocery_remove",
        "gmail_unread_digest",
        "gmail_track_packages",
    }
    assert not any(
        re.search(r"send|delete|pay|remove_all|draft|whatsapp", n) for n in OFFLINE_TOOLS
    )


def test_offline_tools_filters_and_never_returns_an_empty_list() -> None:
    got = offline_tools([_spec("gmail_send"), _spec("task_add"), _spec("doc_read")])
    assert got is not None and [t.name for t in got] == ["task_add"]
    assert offline_tools([_spec("gmail_send")]) is None
    assert offline_tools([]) is None and offline_tools(None) is None


def test_trailer_appends_the_note() -> None:
    assert offline_trailer(None) == OFFLINE_NOTE
    assert offline_trailer("dyn").startswith("dyn") and offline_trailer("dyn").endswith(
        OFFLINE_NOTE
    )
    assert "fewer tools" in OFFLINE_NOTE and "every change asks first" in OFFLINE_NOTE


def test_confine_marks_offline_zero_cost_and_keeps_allowed_calls() -> None:
    out = confine(_c("ok", ["task_add"]), [_spec("task_add")])
    assert out.offline is True and out.cost_usd == 0.0
    assert [c.name for c in out.tool_calls] == ["task_add"] and out.stop_reason == "tool_use"
    assert out.text == "ok"


def test_confine_drops_calls_that_were_not_offered_even_if_the_name_is_in_the_set() -> None:
    out = confine(_c("", ["grocery_add"]), [_spec("task_add")])
    assert out.tool_calls == [] and out.text == CANT_OFFLINE


def test_confine_drops_a_call_to_something_else_and_says_so() -> None:
    out = confine(_c("Sending now.", ["gmail_send"]), [_spec("task_add")])
    assert out.tool_calls == [] and out.text.endswith(CANT_OFFLINE) and "Sending now." in out.text
    assert out.stop_reason == "end_turn"


def test_confine_with_one_good_and_one_bad_call_keeps_the_good_one_quietly() -> None:
    out = confine(_c("", ["gmail_send", "task_add"]), [_spec("task_add")])
    assert [c.name for c in out.tool_calls] == ["task_add"] and CANT_OFFLINE not in out.text


def test_confine_with_no_tools_offered_drops_everything() -> None:
    out = confine(_c("", ["task_add"]), None)
    assert out.tool_calls == [] and out.text == CANT_OFFLINE


def test_confine_does_not_change_its_input() -> None:
    c = _c("x", ["gmail_send"])
    confine(c, None)
    assert c.offline is False and c.cost_usd == 0.9 and len(c.tool_calls) == 1


class _Fb:
    async def ready(self) -> bool:
        return True

    async def cloud_ok(self) -> None: ...


def test_the_registry_hands_the_fallback_to_every_router() -> None:
    s = Settings(_env_file=None, env="dev", llm_backend=LLMBackend.MOCK, usd_inr_live=False)
    fb = _Fb()
    reg = BrainRegistry.from_settings(s, local=fb)  # type: ignore[arg-type]
    assert all(reg.router_for(b.id).fallback is fb for b in reg.list())
    assert BrainRegistry.from_settings(s).router_for("mock").fallback is None


def test_new_offline_code_imports_no_vendor_sdk() -> None:
    vendor = re.compile(r"^\s*(?:import|from)\s+(anthropic|google|openai|ollama)\b", re.M)
    for path in [
        *(ROOT / "offline").glob("*.py"),
        ROOT / "api" / "offline.py",
        ROOT / "llm" / "fallback.py",
        ROOT / "llm" / "local_provider.py",
    ]:
        assert not vendor.search(path.read_text()), path

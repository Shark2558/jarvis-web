# tests/test_r51b_vitals_tools.py -- R5.1 D2: `vitals_show` and the brief's Vitals section include
# JARVIS's own items; `vitals_show` also answers a fixed-template `spoken` line, which is what the
# No-AI mode reads out (never raw JSON, never a key value).
from __future__ import annotations

import json
from typing import Any

from r51b_fakes import SECRET, Brain, Github, Meta, OwnRig, Usage, Web, with_keys
from vitals_fakes import UID, FakeBilling, usage_view

from jarvis.config import Settings
from jarvis.core.guardrails import ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.offline.no_ai import _render
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry
from jarvis.vitals.brief import SPOKEN_MAX, spoken_summary, vitals_lines
from jarvis.vitals.own import OwnSources
from jarvis.vitals.tools import VitalsDeps, tools


def gateway(rig: OwnRig, settings: Settings) -> Gateway:
    reg = ToolRegistry()
    for t in tools(VitalsDeps(rig.svc, settings)):
        reg.register(t)
    return Gateway(registry=reg, policy=Policy([]), gate=ConfirmationGate(), audit=AuditLog())


async def show(rig: OwnRig, **args: Any) -> Any:
    gw = gateway(rig, rig.settings)
    res = await gw.execute(ToolCall(id="c", name="vitals_show", arguments=args), scope="u_owner:s")
    return res.result


def hot_rig() -> OwnRig:
    rig = OwnRig(OwnSources(claude=Brain("refused"), web=Web(Usage(850, 1000))))
    return rig


async def test_show_lists_own_items_and_says_them_in_fixed_words() -> None:
    result = await show(hot_rig())

    ids = {i["id"] for i in result["items"]}
    assert {"brain_claude", "web_credits", "ai_spend"} <= ids
    spoken = result["spoken"]
    assert spoken.startswith("Vitals: 2 need attention.")
    assert "Act now: Claude (paid AI) key was refused." in spoken
    assert "Watch: Web search credits is at 85% of its limit." in spoken
    assert "AI spend: ₹100 of ₹500 this month." in spoken
    assert SECRET not in json.dumps(result)


async def test_show_attention_only_keeps_the_spoken_line() -> None:
    result = await show(hot_rig(), attention_only=True)

    assert {i["id"] for i in result["items"]} == {"brain_claude", "web_credits"}
    assert "Act now" in result["spoken"]


async def test_no_ai_mode_reads_the_spoken_line_not_json() -> None:
    result = await show(hot_rig())

    assert _render(result) == result["spoken"]


async def test_nothing_hot_says_so_and_unreadable_items_are_counted() -> None:
    rig = OwnRig(
        OwnSources(claude=Brain(boom=True)),
        settings=with_keys(gemini_api_key=None, telegram_bot_token=None),
        billing=FakeBilling(usage_view(10, 500)),
    )

    spoken = spoken_summary(await rig.svc.board(UID))

    assert spoken.startswith("Vitals: nothing needs attention.")
    assert "1 can't be read just now." in spoken


async def test_spoken_mentions_manual_trouble_and_is_capped() -> None:
    rig = OwnRig(OwnSources(claude=Brain("refused")))

    async def down(*_a: object) -> list[object]:
        from jarvis.vitals.store import VitalsUnavailable

        raise VitalsUnavailable("x")

    rig.store.list_manual = down  # type: ignore[method-assign]
    board = await rig.svc.board(UID)

    spoken = spoken_summary(board)
    assert "track yourself can't be read" in spoken and len(spoken) <= SPOKEN_MAX


async def test_brief_lines_include_own_items() -> None:
    rig = OwnRig(OwnSources())
    past = Github(Meta(rig.epoch, rig.epoch - 60))
    rig = OwnRig(OwnSources(github=past), clock=rig.clock)

    lines = await vitals_lines(rig.svc, UID)

    assert "Red: GitHub token has expired" in lines

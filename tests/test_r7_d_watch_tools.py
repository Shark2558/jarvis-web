# tests/test_r7_d_watch_tools.py -- R7 Part D (docs/plans/r7-mobile.md D18, D25): the watch and
# sleep tools speak fixed sentences, go through the gateway under the "Watch and sleep" row (Never
# refuses them), are refused on Telegram until the private switch is on, never reach a brain that
# learns, and the No-AI phrases ("how did I sleep", "steps today", "I slept 11:30 to 6") answer with
# no model at all. `sos_status` names no contact and can never send.
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from r7_fakes_d import UID, Clock, settings
from telegram_fakes import Clock as TgClock

from jarvis.core.brain import Brain
from jarvis.core.channel import telegram_turn
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.core.models import ChatRequest
from jarvis.keyring import Keyring
from jarvis.llm.base import ToolCall
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.offline.no_ai import run_no_ai
from jarvis.offline.rules import route_no_ai
from jarvis.permissions.groups import rules_for
from jarvis.storage.docs import MemoryDocs
from jarvis.telegram.rules import REFUSAL, ChannelRules
from jarvis.telegram.store import TelegramStore
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry
from jarvis.watch.phrases import watch_phrases
from jarvis.watch.service import WatchService
from jarvis.watch.store import WatchStore
from jarvis.watch.tools import watch_tools
from jarvis.watch.words import ESTIMATE

SCOPE = f"{UID}:sess_1"
R1, R2 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE
NIGHT = {
    "v": 1,
    "days": [
        {
            "date": "2026-11-12",
            "steps": {"count": 8123, "writer": "com.noisefit"},
            "heart": {"min": 58, "avg": 74, "max": 131, "writer": "com.noisefit"},
            "sleep": [
                {
                    "start": "2026-11-11T23:50:00+05:30",
                    "end": "2026-11-12T06:30:00+05:30",
                    "writer": "com.noisefit",
                    "stages": {"awake": 12, "light": 210, "deep": 80, "rem": 98},
                }
            ],
        }
    ],
}


class Rules:
    def __init__(self, rules: list[PolicyRule]) -> None:
        self._rules = rules

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        return list(self._rules)


def _service(*, keyring: bool = True) -> WatchService:
    s = settings()
    clock = Clock()
    ring = Keyring.from_settings(s) if keyring else None
    return WatchService(WatchStore(MemoryDocs(), ring, now=clock), s, now=clock)


def _gw(svc: WatchService, rules: Any = None) -> Gateway:
    reg = ToolRegistry()
    for t in watch_tools(svc):
        reg.register(t)
    return Gateway(
        registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog(), rules=rules
    )


async def _call(gw: Gateway, name: str, **args: Any) -> Any:
    return await gw.execute(ToolCall(id="c", name=name, arguments=args), scope=SCOPE)


def _said(res: Any) -> str:
    assert res.outcome is GatewayOutcome.EXECUTED, (res.outcome, res.error)
    return str(res.result["message"])


def test_the_tools_and_their_rows() -> None:
    tools = {t.name: t for t in watch_tools(_service())}
    assert set(tools) == {"sleep_last_night", "sleep_week", "watch_today", "sleep_note"}
    assert {n: t.risk for n, t in tools.items()} == {
        "sleep_last_night": R1,
        "sleep_week": R1,
        "watch_today": R1,
        "sleep_note": R2,
    }
    assert all(t.trusted_output and t.activity_words for t in tools.values())
    assert "{" not in tools["sleep_note"].activity_words  # no time lands in Activity


async def test_last_night_in_a_fixed_sentence_with_stages_and_the_estimate_note() -> None:
    svc = _service()
    await svc.intake(UID, json.dumps(NIGHT).encode())
    said = _said(await _call(_gw(svc), "sleep_last_night"))
    assert said == (
        "Last night you slept 6 h 40 min, 23:50 to 06:30, from your watch. Stages: 12 min awake, "
        "3 h 30 min light, 1 h 20 min deep, 1 h 38 min REM. " + ESTIMATE["watch"]
    )
    assert "diagnos" in ESTIMATE["watch"] and "should" not in said.lower()  # never advice


async def test_the_week_today_and_a_night_he_types() -> None:
    svc = _service()
    gw = _gw(svc)
    await svc.intake(UID, json.dumps(NIGHT).encode())
    week = _said(await _call(gw, "sleep_week"))
    assert week.startswith("Over the last 7 nights you slept 6 h 40 min on average (1 night")
    today = _said(await _call(gw, "watch_today"))
    assert "8,123 steps" in today and "58 lowest, 74 average, 131 highest" in today
    assert "from your watch" in today and "Last synced at 14:05" in today
    noted = _said(await _call(gw, "sleep_note", start="23:30", end="06:00"))
    assert noted == "Noted, Sir: last night you slept 6 h 30 min, 23:30 to 06:00 (typed by you)."


async def test_with_nothing_yet_each_says_so_plainly() -> None:
    gw = _gw(_service())
    assert "no sleep for last night" in _said(await _call(gw, "sleep_last_night"))
    assert "hasn't synced yet" in _said(await _call(gw, "watch_today"))
    assert "no nights" in _said(await _call(gw, "sleep_week"))


async def test_without_a_token_key_they_say_why() -> None:
    gw = _gw(_service(keyring=False))
    for name in ("sleep_last_night", "sleep_week", "watch_today"):
        assert "token key" in _said(await _call(gw, name))
    res = await _call(gw, "sleep_note", start="23:30", end="06:00")
    assert "token key" in _said(res) and res.result.get("unavailable") is True


async def test_a_bad_typed_time_is_refused_in_plain_words_before_anything_is_kept() -> None:
    svc = _service()
    res = await _call(_gw(svc), "sleep_note", start="noon", end="06:00")
    assert "Sir" in _said(res) and res.result.get("refused") is True
    assert await svc.store.count(UID) == 0


async def test_the_row_set_to_never_refuses_them() -> None:
    gw = _gw(_service(), Rules(rules_for({"watch": Effect.DENY})))
    for name in ("sleep_last_night", "sleep_week", "watch_today"):
        assert (await _call(gw, name)).outcome is GatewayOutcome.DENIED, name


async def test_on_telegram_they_are_refused_until_the_private_switch_is_on() -> None:
    store = TelegramStore(MemoryDocs(), prefix="t_", clock=TgClock())
    gw = _gw(_service(), ChannelRules(None, store))
    with telegram_turn():
        for name in ("sleep_last_night", "sleep_week", "watch_today"):
            res = await _call(gw, name)
            assert res.outcome is GatewayOutcome.DENIED and res.error == REFUSAL, name


async def test_a_brain_that_learns_never_gets_them() -> None:
    provider = MockProvider()
    tiers = {t: f"mock-{t.value}" for t in ModelTier}
    spec = BrainSpec(
        id="free", label="Free", provider=provider, tiers=tiers, trains_on_content=True
    )
    brain = Brain(
        brains=BrainRegistry([spec], default_id="free"),
        store=InMemorySessionStore(),
        settings=settings(),
        gateway=_gw(_service()),
    )
    await brain.chat(ChatRequest(message="how did I sleep last night?"))
    assert provider.calls and all(not c.tools for c in provider.calls)


NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("text", "tool", "args"),
    [
        ("how did I sleep", "sleep_last_night", {}),
        ("Jarvis, how did I sleep last night?", "sleep_last_night", {}),
        ("how was my sleep", "sleep_last_night", {}),
        ("how did I sleep this week", "sleep_week", {}),
        ("my sleep this week", "sleep_week", {}),
        ("steps today", "watch_today", {}),
        ("how many steps today?", "watch_today", {}),
        ("what's my heart rate today", "watch_today", {}),
        ("I slept 11:30 to 6", "sleep_note", {"start": "23:30", "end": "06:00"}),
        ("i slept from 10 pm to 5:45 am", "sleep_note", {"start": "22:00", "end": "05:45"}),
        ("I slept 1 to 9", "sleep_note", {"start": "01:00", "end": "09:00"}),
        ("I slept 23:15 till 07:05", "sleep_note", {"start": "23:15", "end": "07:05"}),
        ("sos status", "sos_status", {}),
        ("who are my emergency contacts", "sos_status", {}),
    ],
)
def test_the_no_ai_phrases(text: str, tool: str, args: dict[str, str]) -> None:
    route = watch_phrases(text, NOW)
    assert route is not None and [(c.tool, c.arguments) for c in route.calls] == [(tool, args)]


@pytest.mark.parametrize(
    "text",
    [
        "remind me to sleep at 11",
        "how did I sleep through the meeting and what did I miss",
        "I slept badly",
        "send an sos",
        "steps to bake bread",
        "I slept 11:30 to 6 and then went for a run",
    ],
)
def test_other_sentences_are_not_taken(text: str) -> None:
    assert watch_phrases(text, NOW) is None


async def test_no_ai_answers_how_did_i_sleep_with_no_model_at_all() -> None:
    svc = _service()
    await svc.intake(UID, json.dumps(NIGHT).encode())
    out = await run_no_ai(_gw(svc), "how did I sleep?", NOW, scope=SCOPE, extra=(watch_phrases,))
    assert out.reply.startswith("Last night you slept 6 h 40 min")  # no provider exists here
    assert route_no_ai("how did I sleep?", NOW).calls == ()  # only our phrasebook takes it

# tests/test_camera_tools.py -- R3 D8/D15 through the gateway: a spoken "arm" in a clean round needs
# no card and never says armed before the ack; a tainted round makes a card; "disarm" is ALWAYS a
# card, and a call that skips the card refuses; camera_history is fenced, vouched and masked.
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from camera_fakes import PERSON, T0, UID, Rig, rig

from jarvis.camera.tools import camera_tools
from jarvis.core.channel import telegram_turn
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.faces.ports import Resolved
from jarvis.llm.base import ToolCall
from jarvis.tools import Effect, PolicyRule
from jarvis.tools.audit import AuditLog
from jarvis.tools.external import FENCE_END
from jarvis.tools.gateway import Gateway, GatewayOutcome, GatewayResult
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.taint import context_trust

SCOPE = f"{UID}:sess_1"


def build(r: Rig, *, rules: list[PolicyRule] | None = None) -> Gateway:
    reg = ToolRegistry()
    for t in camera_tools(r.alarm, r.gate, r.history, confirm_wait_s=0.0):
        reg.register(t)
    return Gateway(registry=reg, policy=Policy(rules), gate=ConfirmationGate(), audit=AuditLog())


async def call(gw: Gateway, name: str, **args: Any) -> GatewayResult:
    return await gw.execute(ToolCall(id="c", name=name, arguments=args), scope=SCOPE)


async def test_registered_with_declared_risks_flags_and_activity_words() -> None:
    r = await rig()
    by = {t.name: t for t in camera_tools(r.alarm, r.gate, r.history, confirm_wait_s=0.0)}
    assert set(by) == {"home_arm", "home_disarm", "camera_history"}
    assert by["home_arm"].risk is ActionRisk.REVERSIBLE and by["home_arm"].spoken_ok
    assert by["home_disarm"].risk is ActionRisk.IRREVERSIBLE and not by["home_disarm"].spoken_ok
    assert by["camera_history"].risk is ActionRisk.READ_ONLY and by["camera_history"].may_vouch
    assert by["home_arm"].activity_words == "Armed the home alarm"
    assert by["home_disarm"].activity_words == "Disarmed the home alarm"
    assert by["camera_history"].activity_words == "Searched camera history"


async def test_spoken_arm_in_a_clean_round_needs_no_card_and_says_pending_before_the_ack() -> None:
    r = await rig()
    gw = build(r)
    with context_trust(untrusted=False, spoken=True):
        res = await call(gw, "home_arm", mode="away")
    assert res.outcome is GatewayOutcome.EXECUTED
    assert res.result["confirmed"] is False and res.result["status"] == "pending"
    assert "waiting for your laptop" in res.result["message"]
    assert (await r.alarm.record(UID)).set_via == "voice"


async def test_arm_says_confirmed_only_after_the_laptop_acked() -> None:
    r = await rig()
    gw = build(r)

    async def ack_when_pushed(*_: Any, **__: Any) -> None:
        await r.alarm.ack(UID, 1)

    orig = r.caller.call

    async def call_then_ack(uid: str, method: Any, path: str, body: Any = None, **kw: Any) -> Any:
        out = await orig(uid, method, path, body, **kw)
        await ack_when_pushed()
        return out

    r.caller.call = call_then_ack  # type: ignore[method-assign]
    res = await call(gw, "home_arm")
    assert res.result["confirmed"] is True and res.result["status"] == "done"


async def test_arm_after_reading_other_peoples_words_is_a_card() -> None:
    r = await rig()
    gw = build(r)
    with context_trust(untrusted=True, spoken=True):
        res = await call(gw, "home_arm")
    assert res.outcome is GatewayOutcome.AWAITING_CONFIRMATION
    assert (await r.alarm.view(UID)).armed is False


async def test_arm_works_from_telegram_and_records_it() -> None:
    r = await rig()
    gw = build(r)
    with telegram_turn():
        res = await call(gw, "home_arm", mode="night")
    assert res.outcome is GatewayOutcome.EXECUTED
    rec = await r.alarm.record(UID)
    assert rec.set_via == "telegram" and rec.mode == "night"


async def test_a_bad_mode_is_refused_before_anything_runs() -> None:
    r = await rig()
    res = await call(build(r), "home_arm", mode="party")
    assert res.outcome is GatewayOutcome.ERROR and (await r.alarm.record(UID)).rev == 0


async def test_disarm_is_always_a_card_spoken_typed_or_telegram() -> None:
    r = await rig()
    await r.alarm.arm(UID, "away", "console")
    gw = build(r)
    outcomes = []
    with context_trust(untrusted=False, spoken=True):
        outcomes.append((await call(gw, "home_disarm")).outcome)
    outcomes.append((await call(gw, "home_disarm")).outcome)
    with telegram_turn():
        outcomes.append((await call(gw, "home_disarm")).outcome)
    assert outcomes == [GatewayOutcome.AWAITING_CONFIRMATION] * 3
    assert (await r.alarm.view(UID)).armed is True


async def test_disarm_never_runs_on_an_allow_rule() -> None:
    r = await rig()
    await r.alarm.arm(UID, "away", "console")
    rules = [PolicyRule(tool_pattern="home_disarm", effect=Effect.ALLOW)]
    res = await call(build(r, rules=rules), "home_disarm")
    assert res.outcome is GatewayOutcome.AWAITING_CONFIRMATION
    assert (await r.alarm.view(UID)).armed is True


async def test_an_approved_card_disarms() -> None:
    r = await rig()
    await r.alarm.arm(UID, "away", "console")
    gw = build(r)
    card = await call(gw, "home_disarm")
    assert card.pending is not None and card.pending.summary == "Turn off the home burglar alarm"
    done = await gw.execute(
        ToolCall(id="c", name="home_disarm", arguments={}),
        confirmation_id=card.pending.id,
        scope=SCOPE,
    )
    assert done.outcome is GatewayOutcome.EXECUTED and done.result["armed"] is False
    assert (await r.alarm.view(UID)).armed is False


async def test_the_tool_body_refuses_without_an_approved_card() -> None:
    r = await rig()
    await r.alarm.arm(UID, "away", "console")
    tool = next(
        t
        for t in camera_tools(r.alarm, r.gate, r.history, confirm_wait_s=0.0)
        if t.name == "home_disarm"
    )
    from jarvis.tools.context import tool_context

    with tool_context(SCOPE, spoken=True):
        out = await tool.run({})
    assert out["status"] == "refused" and out["code"] == "needs_console"
    with tool_context(SCOPE):
        out = await tool.run({})
    assert out["status"] == "refused"
    assert (await r.alarm.view(UID)).armed is True


def hist(**kw: Any) -> dict[str, Any]:
    now = datetime.fromtimestamp(T0, UTC)
    base = {"start": (now - timedelta(hours=6)).isoformat(), "end": now.isoformat()}
    base.update(kw)
    return base


async def test_history_is_fenced_vouched_and_names_strangers_as_such() -> None:
    r = await rig()
    r.faces.people[PERSON] = Resolved(name="Anjali", person=PERSON)
    r.caller.replies[("GET", "/bridge/v1/events")] = {
        "events": [
            {
                "id": "e1",
                "camera": "gate",
                "zones": ["gate"],
                "label": "person",
                "start": T0 - 600,
                "person": PERSON,
                "score": 0.95,
            },
            {"id": "e2", "camera": "gate", "zones": ["gate"], "label": "person", "start": T0 - 900},
        ]
    }
    res = await call(build(r), "camera_history", **hist(what="person"))
    assert res.outcome is GatewayOutcome.EXECUTED and res.trusted is True
    rows = res.result["items"]
    assert FENCE_END.search(rows[0]["camera"]) and FENCE_END.search(rows[0]["who"])
    assert rows[1]["who"] == "someone JARVIS didn't recognise"
    assert res.result["count"] == 2 and res.result["kept_days"] == 7


async def test_history_on_telegram_hides_a_childs_name_and_masks_numbers() -> None:
    r = await rig()
    r.faces.people[PERSON] = Resolved(name="Mini", person=PERSON, child=True)
    r.caller.replies[("GET", "/bridge/v1/events")] = {
        "events": [
            {
                "id": "e1",
                "camera": "gate",
                "zones": [],
                "label": "person",
                "start": T0 - 600,
                "person": PERSON,
                "score": 0.95,
            }
        ]
    }
    with telegram_turn():
        res = await call(build(r), "camera_history", **hist())
    text = json.dumps(res.result)
    assert "Mini" not in text and "a child from your family" in text


async def test_history_with_the_laptop_off_says_so_plainly() -> None:
    r = await rig()
    r.caller.online = False
    res = await call(build(r), "camera_history", **hist())
    assert res.result["status"] == "unavailable"
    assert "home laptop is off" in res.result["message"]


async def test_history_bad_question_is_plain_words_and_a_bad_time_an_error() -> None:
    r = await rig()
    res = await call(build(r), "camera_history", **hist(camera="back"))
    assert res.result["status"] == "refused"
    bad = await call(build(r), "camera_history", start="yesterday", end="now")
    assert bad.outcome is GatewayOutcome.ERROR
    assert r.caller.calls == []


async def test_never_refuses_all_three() -> None:
    r = await rig()
    gw = build(
        r,
        rules=[
            PolicyRule(tool_pattern=n, effect=Effect.DENY)
            for n in ("home_arm", "home_disarm", "camera_history")
        ],
    )
    for name, args in (("home_arm", {}), ("home_disarm", {}), ("camera_history", hist())):
        assert (await call(gw, name, **args)).outcome is GatewayOutcome.DENIED

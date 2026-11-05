# tests/test_camera_alarm.py -- R3 D8: arm is pending until the laptop acks; disarm needs a pass
# only the gate can issue (passkey for exactly this home and rev, or an approved R3 card); both ends
# filter; a stuck arm raises home_arm_failed once.
from __future__ import annotations

from typing import Any

import pytest
from camera_fakes import HOME, UID, FakeHomes, Rig, rig

from jarvis.camera.alarm import ArmPendingJob, DisarmPass
from jarvis.camera.ports import AlarmRefused
from jarvis.core.guardrails import ActionRisk
from jarvis.permissions.errors import PasskeyRequired
from jarvis.tools.context import ToolContext


class FakePerms:
    """Records the (purpose, target) it was asked to check; passkeys in force or not."""

    def __init__(self, in_force: bool = True) -> None:
        self.in_force = in_force
        self.asked: list[tuple[str, str | None]] = []
        self.good_target: str | None = None

    async def check_purpose(self, uid: str, purpose: str, target: str | None, proof: Any) -> Any:
        self.asked.append((purpose, target))
        if not self.in_force:
            return None
        if proof is None:
            raise PasskeyRequired("needs a passkey")
        if target != self.good_target:
            raise PasskeyRequired("for something else")
        return "passkey abcd1234"


async def test_arm_is_pending_until_the_laptop_acks() -> None:
    r = await rig()
    v = await r.alarm.arm(UID, "away", "console")
    assert v.armed and v.rev == 1 and v.confirmed is False and v.pending_since is not None
    assert r.caller.calls[-1][:2] == ("POST", "/bridge/v1/state")
    assert r.caller.calls[-1][2] == {"arm": {"armed": True, "mode": "away", "rev": 1}}
    assert await r.alarm.ack(UID, 1) is True
    v = await r.alarm.view(UID)
    assert v.confirmed and v.pending_since is None


async def test_an_old_ack_does_not_confirm_a_newer_arm() -> None:
    r = await rig()
    await r.alarm.arm(UID, "away", "console")
    await r.alarm.ack(UID, 1)
    await r.alarm.disarm(UID, await _pass(r), via="console")
    await r.alarm.arm(UID, "night", "console")  # rev 3
    assert await r.alarm.ack(UID, 1) is False
    assert (await r.alarm.view(UID)).confirmed is False


async def test_arming_when_the_laptop_is_off_stays_pending() -> None:
    r = await rig()
    r.caller.online = False
    v = await r.alarm.arm(UID, "away", "voice")
    assert v.armed and v.confirmed is False  # never claimed
    rec = await r.alarm.record(UID)
    assert rec.set_via == "voice"


async def test_arming_twice_the_same_way_is_one_change() -> None:
    r = await rig()
    await r.alarm.arm(UID, "away", "console")
    v = await r.alarm.arm(UID, "away", "console")
    assert v.rev == 1


async def _pass(r: Rig) -> DisarmPass:
    ctx = ToolContext(
        user_id=UID,
        session_id="s",
        scope=f"{UID}:s",
        confirmed=True,
        approved_risk=ActionRisk.IRREVERSIBLE,
    )
    p = await r.gate.card_pass(UID, ctx)
    assert p is not None
    return p


async def test_disarm_drops_alerts_at_once_and_pushes() -> None:
    r = await rig()
    await r.alarm.arm(UID, "away", "console")
    await r.alarm.ack(UID, 1)
    v = await r.alarm.disarm(UID, await _pass(r), via="console")
    assert v.armed is False and v.rev == 2
    assert r.caller.calls[-1][2] == {"arm": {"armed": False, "mode": "away", "rev": 2}}


async def test_disarm_with_no_pass_object_is_refused() -> None:
    r = await rig()
    await r.alarm.arm(UID, "away", "console")
    with pytest.raises(AlarmRefused):
        await r.alarm.disarm(UID, object(), via="console")  # type: ignore[arg-type]
    assert (await r.alarm.view(UID)).armed


async def test_a_pass_for_another_owner_or_an_older_rev_is_refused() -> None:
    r = await rig()
    await r.alarm.arm(UID, "away", "console")
    p = await _pass(r)
    forged = DisarmPass(uid=UID, rev=1, how="made up")  # not issued by the gate
    with pytest.raises(AlarmRefused) as e0:
        await r.alarm.disarm(UID, forged, via="console")
    assert e0.value.code == "no_pass"
    await r.alarm.arm(UID, "night", "console")  # rev moves on
    with pytest.raises(AlarmRefused) as e:
        await r.alarm.disarm(UID, p, via="console")
    assert e.value.code == "changed"
    with pytest.raises(AlarmRefused):
        await r.alarm.disarm("u_other", p, via="console")


async def test_panel_disarm_needs_a_passkey_for_exactly_this_home_and_rev() -> None:
    r = await rig()
    await r.alarm.arm(UID, "away", "console")
    perms = FakePerms()
    r.gate.permissions = perms  # type: ignore[assignment]
    with pytest.raises(PasskeyRequired):
        await r.gate.panel_pass(UID, None, fresh_left_s=900)
    assert perms.asked[-1] == ("home_disarm", f"{HOME}:1")
    perms.good_target = f"{HOME}:7"  # a proof made for another rev
    with pytest.raises(PasskeyRequired):
        await r.gate.panel_pass(UID, object(), fresh_left_s=900)
    perms.good_target = f"{HOME}:1"
    p = await r.gate.panel_pass(UID, object(), fresh_left_s=900)
    assert p is not None and p.rev == 1
    v = await r.alarm.disarm(UID, p, via="console")
    assert v.armed is False


async def test_without_passkeys_a_fresh_google_sign_in_is_needed() -> None:
    r = await rig()
    await r.alarm.arm(UID, "away", "console")
    r.gate.permissions = FakePerms(in_force=False)  # type: ignore[assignment]
    with pytest.raises(AlarmRefused) as e:
        await r.gate.panel_pass(UID, None, fresh_left_s=0)
    assert e.value.code == "reauth_required"
    with pytest.raises(AlarmRefused):
        await r.gate.panel_pass(UID, None, fresh_left_s=None)
    assert await r.gate.panel_pass(UID, None, fresh_left_s=120) is not None


async def test_no_permissions_service_means_the_sign_in_rule_not_a_free_pass() -> None:
    r = await rig()
    await r.alarm.arm(UID, "away", "console")
    r.gate.permissions = None
    with pytest.raises(AlarmRefused):
        await r.gate.panel_pass(UID, None, fresh_left_s=0)


async def test_an_unlinked_home_can_not_be_disarmed_through_the_panel() -> None:
    r = await rig()
    await r.alarm.arm(UID, "away", "console")
    r.gate.homes = FakeHomes(None)
    with pytest.raises(AlarmRefused) as e:
        await r.gate.panel_pass(UID, object(), fresh_left_s=900)
    assert e.value.code == "not_linked"


async def test_a_card_pass_needs_an_approved_irreversible_card() -> None:
    r = await rig()
    await r.alarm.arm(UID, "away", "console")
    for ctx in (
        ToolContext(user_id=UID, session_id="s", scope="x", spoken=True),
        ToolContext(user_id=UID, session_id="s", scope="x", confirmed=True),
        ToolContext(
            user_id=UID,
            session_id="s",
            scope="x",
            confirmed=True,
            approved_risk=ActionRisk.REVERSIBLE,
        ),
    ):
        with pytest.raises(AlarmRefused) as e:
            await r.gate.card_pass(UID, ctx)
        assert e.value.code == "needs_console"


async def test_disarming_what_is_already_disarmed_changes_nothing() -> None:
    r = await rig()
    assert await r.gate.panel_pass(UID, None, fresh_left_s=None) is None
    v = await r.alarm.view(UID)
    assert v.armed is False and v.rev == 0


async def test_wait_confirmed_returns_when_the_ack_lands() -> None:
    r = await rig()
    await r.alarm.arm(UID, "away", "console")

    async def sleep(_: float) -> None:
        await r.alarm.ack(UID, 1)

    v = await r.alarm.wait_confirmed(UID, 3.0, sleep=sleep)
    assert v.confirmed


async def test_wait_confirmed_gives_up_and_says_pending() -> None:
    r = await rig()
    await r.alarm.arm(UID, "away", "console")

    async def sleep(_: float) -> None:
        r.clock.advance(1.0)

    v = await r.alarm.wait_confirmed(UID, 3.0, sleep=sleep)
    assert v.confirmed is False


async def test_a_stuck_arm_raises_home_arm_failed_once() -> None:
    r = await rig()
    job = ArmPendingJob(r.alarm, r.notifier, tz="Asia/Kolkata")
    await r.alarm.arm(UID, "away", "console")
    r.clock.advance(299)
    assert await job.run([UID]) == {"alerted": 0, "failed": 0}
    r.clock.advance(2)
    assert await job.run([UID]) == {"alerted": 1, "failed": 0}
    assert r.notifier.sent[-1].signal.kind == "home_arm_failed"
    assert "didn't answer" in r.notifier.sent[-1].message
    assert await job.run([UID]) == {"alerted": 0, "failed": 0}  # once per rev


async def test_an_acked_or_disarmed_pending_state_raises_nothing() -> None:
    r = await rig()
    job = ArmPendingJob(r.alarm, r.notifier, tz="Asia/Kolkata")
    await r.alarm.arm(UID, "away", "console")
    await r.alarm.ack(UID, 1)
    r.clock.advance(1000)
    assert (await job.run([UID]))["alerted"] == 0
    await r.alarm.disarm(UID, await _pass(r), via="console")
    r.clock.advance(1000)
    assert (await job.run([UID]))["alerted"] == 0


async def test_the_job_counts_an_owner_it_could_not_read_as_failed() -> None:
    r = await rig()
    job = ArmPendingJob(r.alarm, r.notifier, tz="Asia/Kolkata")
    r.docs._data[f"jarvis_home_arm/{UID}"] = {"armed": "not a bool", "rev": "x"}
    assert (await job.run([UID]))["failed"] == 1


async def test_dropped_disarmed_is_counted() -> None:
    r = await rig()
    assert await r.alarm.count_dropped(UID) == 1
    assert await r.alarm.count_dropped(UID) == 2
    assert (await r.alarm.record(UID)).dropped_disarmed == 2

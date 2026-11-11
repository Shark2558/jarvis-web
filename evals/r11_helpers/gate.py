# evals/r11_helpers/gate.py
"""I0's part of the R11 eval: the one sender and the nudge limits (plan D4-D6, D21), on fakes.

Cases: the per-kind cap, the day and hour totals, snooze and stop, the night rules through the real
policy (a nudge dropped, a reminder held, a disaster rung), an unreadable state sends nothing, the
send log holds no words, and 14 simulated days on the 5-minute clock (with up to 40 s of Scheduler
jitter) where a daily 09:00 reminder goes out on time every day and a nudge job never exceeds the
caps. Control: the caps switched off (the gate then lets a ninth water nudge through), which must
make this part fail.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from r11_fakes import NOON_IST, TWO_AM_IST, UID, Clock, FakeNotifier, sender

from jarvis.helpers import gate as gate_module
from jarvis.helpers.gate import ALL, fortnight
from jarvis.storage.docs import Set

PART = "gate"
BUILT = True
Case = Callable[[], Awaitable[list[str]]]
DAY = "2026-11-10"


async def _caps() -> list[str]:
    clock = Clock()
    send, notifier, _, _ = sender(clock=clock, nudges_max_per_hour=8, nudges_max_per_day=40)
    for i in range(9):
        clock.at = NOON_IST + timedelta(minutes=10 * i)
        await send.send(UID, "nudge_hydrate", "Time for some water, Sir.", due=clock.at)
    sent = len(notifier.calls)
    return [] if sent == 8 else [f"{sent} water nudges went out, the cap is 8"]


async def _totals() -> list[str]:
    clock = Clock()
    send, notifier, _, _ = sender(clock=clock, nudges_max_per_hour=4, nudges_max_per_day=6)
    kinds = ("nudge_standup", "nudge_hydrate")
    for i in range(12):
        clock.at = NOON_IST + timedelta(minutes=15 * i)
        await send.send(UID, kinds[i % 2], "Nudge.", due=clock.at)
    sent = len(notifier.calls)
    return [] if sent == 6 else [f"{sent} nudges in a day, the total is 6"]


async def _snooze_stop() -> list[str]:
    clock = Clock()
    send, notifier, _, _ = sender(clock=clock)
    await send.store.snooze(UID, "nudge_standup", 60, clock.at)
    await send.send(UID, "nudge_standup", "Up.", due=clock.at)
    await send.store.stop_today(UID, ALL, DAY)
    await send.send(UID, "nudge_hydrate", "Water.", due=clock.at)
    return (
        [] if notifier.calls == [] else [f"a snoozed or stopped nudge went out: {notifier.calls}"]
    )


async def _night() -> list[str]:
    clock = Clock(TWO_AM_IST)
    send, _, _, _ = sender(clock=clock, notifier=FakeNotifier(clock=clock, policy=True))
    want = {"nudge_hydrate": "dropped:stale_at_night", "bill_due": "held", "disaster_alert": "rang"}
    got = {k: (await send.send(UID, k, "Text.", due=clock.at)).outcome for k in want}  # type: ignore[arg-type]
    return [] if got == want else [f"at 02:00: {got}"]


async def _fail_closed() -> list[str]:
    send, notifier, docs, _ = sender()
    await docs.write([Set(f"jarvis_helpers_nudge/{UID}", {"state": {"caps": "broken"}})])
    got = await send.send(UID, "nudge_hydrate", "Water.", due=NOON_IST)
    return [] if got.outcome == "unavailable" and not notifier.calls else [got.outcome]


async def _no_words() -> list[str]:
    send, _, _, _ = sender()
    await send.send(UID, "bill_due", "NEEDLE-ELECTRICITY-1240", due=NOON_IST)
    log = str(await send.store.days(UID))
    return ["the send log holds the message"] if "NEEDLE" in log else []


async def _fourteen_days() -> list[str]:
    """A daily 09:00 IST reminder and a water nudge every 60 minutes 09:30-18:30, run by a 5-minute
    clock with jitter for 14 days: every reminder on time, never twice; nudges inside the caps."""
    start = NOON_IST.replace(hour=0, minute=0) - timedelta(days=13, hours=5, minutes=30)
    clock = Clock(start)
    send, _, _, _ = sender(clock=clock)
    told: set[str] = set()
    for tick in range(14 * 288):
        clock.at = start + timedelta(minutes=5 * tick, seconds=(tick * 37) % 41)
        local = clock.at + timedelta(hours=5, minutes=30)
        due = (local.replace(hour=9, minute=0, second=0, microsecond=0)) - timedelta(
            hours=5, minutes=30
        )
        day = send.today()
        if clock.at >= due and day not in told:
            told.add(day)
            await send.send(UID, "bill_due", "Electricity due today.", due=due)
        if 9 * 60 + 30 <= local.hour * 60 + local.minute <= 18 * 60 + 30 and local.minute < 5:
            await send.send(UID, "nudge_hydrate", "Water.", due=clock.at)
    got = fortnight(await send.store.days(UID), send.today(), max_per_day=16)
    want = {"reminders_on_time": 14, "reminders_late": 0, "reminders_early": 0}
    fails = [f"{k}={got[k]} want {v}" for k, v in want.items() if got[k] != v]
    if got["nudge_days_within_limits"] != 14:
        fails.append(f"nudges inside the limits on {got['nudge_days_within_limits']} of 14 days")
    return fails


CASES: dict[str, Case] = {
    "caps-per-kind": _caps,
    "day-and-hour-totals": _totals,
    "snooze-and-stop": _snooze_stop,
    "night-rules": _night,
    "fail-closed": _fail_closed,
    "log-has-no-words": _no_words,
    "fourteen-days-on-time": _fourteen_days,
}


async def _run() -> list[dict[str, Any]]:
    out = []
    for name, case in CASES.items():
        failures = await case()
        out.append({"id": f"{PART}:{name}", "passed": not failures, "failures": failures})
    return out


async def cases() -> list[dict[str, Any]]:
    return await _run()


async def control() -> dict[str, Any]:
    """Caps off: the gate's refusal check always says "go"."""
    original = gate_module.HelperSender._refusal

    async def never(self: Any, uid: str, kind: str, now: Any, day: str) -> None:
        return None

    gate_module.HelperSender._refusal = never  # type: ignore[method-assign,assignment]
    try:
        got = await _run()
    finally:
        gate_module.HelperSender._refusal = original  # type: ignore[method-assign]
    failed = [r["id"] for r in got if not r["passed"]]
    return {"name": "caps_off", "suite_failed": bool(failed), "failed_cases": failed}

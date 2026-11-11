# evals/r11_helpers/nudges.py
"""C's part of the R11 eval (plan docs/plans/r11-free-helpers.md "Tests and evals", nudges), on
fakes:

- fourteen-days-on-time: 14 days on the 5-minute clock with jitter and a restart after every run
  that sent: every nudge in the first run at or after due, none early, twice or missed; the caps
  held (his own cap of 3 too); snooze and stop by phrase and by tap; the missed walk asked once;
  the free-time pick fits the gap, avoids rain, skips what he did in the last 3 days.
- dont-remind-me-sets-no-reminder, every-feature-by-phrase (No-AI covers all of Part C),
  missed-activity-asked-once (across a restart), night-drops-a-nudge, retry-is-released (a send no
  channel took goes in the next run), sealed-or-off (no keyring: nothing stored, the log says off).

Control: claims off (`NudgeStore.claim` always yes, `release` does nothing), so a restart sends
twice: the fourteen-day case and the asked-once case must then fail.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from r11_fakes import UID
from r11_fakes_c import FakeCalendar, Planned, at_ist, judge, part, run_phrase, run_tool, simulate

from jarvis.helpers.gate import GateStore
from jarvis.helpers.nudges import store as store_module
from jarvis.helpers.nudges.phrases import PHRASES
from jarvis.helpers.nudges.store import OFF_WORDS
from jarvis.notify.ports import Delivery
from jarvis.offline.rules import route_no_ai

PART = "nudges"
BUILT = True
Case = Callable[[], Awaitable[list[str]]]
TUESDAY = date(2026, 11, 10)
ONE_PHRASE_EACH = {
    "nudge_status": "show my nudges",
    "nudge_set": "turn on water reminders",
    "nudge_snooze": "snooze the water reminder for an hour",
    "nudge_stop": "stop water",
    "nudge_resume": "resume water reminders",
    "nudge_water_log": "I had a glass of water",
    "nudge_standup_log": "I stood up",
    "nudge_activity_checkin": "walk done",
    "freetime_suggest": "what can I do with my free time?",
    "freetime_list": "show my free-time list",
    "freetime_add": "add to my free-time list: sketch the garden, 30 minutes",
    "freetime_remove": "remove sketch the garden from my free-time list",
    "freetime_done": "I did sketch the garden from my list",
}


async def _fourteen_days() -> list[str]:
    return await judge(await simulate())


async def _dont_remind_me() -> list[str]:
    now = at_ist(TUESDAY, "12:00")
    got = [c.tool for c in route_no_ai("don't remind me to stand up", now, extra=PHRASES).calls]
    rig = part(at=now)
    tools = await run_phrase(rig, "don't remind me to stand up")
    stopped = (await GateStore(rig.docs).state(UID)).stopped_on("nudge_standup", "2026-11-10")
    fails = [] if got == tools == ["nudge_stop"] else [f"routed to {got} / {tools}"]
    return fails + ([] if stopped else ["the stand-up nudge was not stopped"])


async def _every_feature() -> list[str]:
    rig = part(at=at_ist(TUESDAY, "12:00"))
    names = {t.name for t in rig.part.tools}
    fails = [f"no phrase for {n}" for n in sorted(names - set(ONE_PHRASE_EACH))]
    for tool, text in ONE_PHRASE_EACH.items():
        if route_no_ai(text, rig.clock(), extra=PHRASES).calls[0].tool != tool:
            fails.append(f"{text!r} did not reach {tool}")
    return fails


async def _asked_once() -> list[str]:
    cal = FakeCalendar(every_day=[Planned("Evening walk", "17:00", "17:45")])
    rig = part(calendar=cal)
    await run_tool(rig, "nudge_set", kind="activity", on="true")
    for hhmm, who in (("18:00", rig), ("18:00", rig.rebuilt()), ("18:05", rig), ("18:30", rig)):
        rig.clock.at = at_ist(TUESDAY, hhmm)
        await who.job("activity_check").run(())
    asks = [c for c in rig.notifier.calls if c[1] == "nudge_activity"]
    return [] if len(asks) == 1 else [f"asked {len(asks)} times"]


async def _night() -> list[str]:
    rig = part()
    await run_tool(
        rig, "nudge_set", kind="water", on="true", start="05:00", end="23:59", days="every day"
    )
    for hhmm in ("23:05", "23:10"):
        rig.clock.at = at_ist(TUESDAY, hhmm)
        await rig.job("nudges").run(())
    got = [e["o"] for e in await GateStore(rig.docs).sends(UID, "2026-11-10")]
    return [] if got == ["dropped:stale_at_night"] else [f"at night: {got}"]


async def _retry() -> list[str]:
    rig = part(policy=False)
    rig.notifier.delivery = Delivery(action="ring", reason="eval")  # no channel took it
    await run_tool(rig, "nudge_set", kind="water", on="true")
    for hhmm, took in (("11:00", False), ("11:05", True), ("11:10", True)):
        if took:
            rig.notifier.delivery = Delivery(action="ring", reason="eval", telegram=True)
        rig.clock.at = at_ist(TUESDAY, hhmm)
        await rig.job("nudges").run(())
    got = [e["o"] for e in await GateStore(rig.docs).sends(UID, "2026-11-10")]
    return [] if got == ["undelivered", "rang"] else [f"retry: {got}"]


async def _sealed_or_off() -> list[str]:
    rig = part(sealed=False, at=at_ist(TUESDAY, "12:00"))
    said = (await run_tool(rig, "nudge_water_log"))["spoken"]
    stored = [p for p in rig.docs._data if "wellbeing/" in p]  # noqa: SLF001
    sealed = part(at=at_ist(TUESDAY, "12:00"))
    await run_tool(sealed, "nudge_water_log", glasses="3")
    raw = str(sealed.docs._data)  # noqa: SLF001
    fails = [] if said == OFF_WORDS and not stored else ["the log kept something with no keyring"]
    return fails + (["a count is stored in clear"] if "'water': 3" in raw else [])


CASES: dict[str, Case] = {
    "fourteen-days-on-time": _fourteen_days,
    "dont-remind-me-sets-no-reminder": _dont_remind_me,
    "every-feature-by-phrase": _every_feature,
    "missed-activity-asked-once": _asked_once,
    "night-drops-a-nudge": _night,
    "retry-is-released": _retry,
    "sealed-or-off": _sealed_or_off,
}


async def _run() -> list[dict[str, Any]]:
    out = []
    for name, case in CASES.items():
        failures = await case()
        out.append({"id": f"{PART}:{name}", "passed": not failures, "failures": failures[:10]})
    return out


async def cases() -> list[dict[str, Any]]:
    return await _run()


async def control() -> dict[str, Any]:
    """Claims off: every run may send, so a restart (or a second run) sends twice."""
    original = (store_module.NudgeStore.claim, store_module.NudgeStore.release)

    async def always(self: Any, uid: str, day: str, key: str) -> bool:
        return True

    async def never(self: Any, uid: str, day: str, key: str) -> None:
        return None

    store_module.NudgeStore.claim = always  # type: ignore[method-assign]
    store_module.NudgeStore.release = never  # type: ignore[method-assign]
    try:
        got = await _run()
    finally:
        store_module.NudgeStore.claim, store_module.NudgeStore.release = original  # type: ignore[method-assign]
    failed = [r["id"] for r in got if not r["passed"]]
    return {"name": "claims_off", "suite_failed": bool(failed), "failed_cases": failed}

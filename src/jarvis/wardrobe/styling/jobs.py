# src/jarvis/wardrobe/styling/jobs.py
"""R13 Part C's one job, `outfit_clock`, on the existing 5-minute clock (no new Scheduler job;
advisory on the watchdog). For each of the brief's owners, in this order:

1. the weather (`outlook.refresh`): at most twice a day, from 05:00 and from 18:00 his time;
2. his calendar, when he has picked one (`Calendar.read`, governed, "Allow" only): at most every
   `wardrobe_calendar_refresh_min` (60) minutes, the next 48 hours; a failed read waits 15
   minutes. New events make plans (their looks picked at once), edited ones refresh, a missing
   one inside the read's window is cancelled (a draft, D13). With his calendar off: no read.
3. `outfit_ready` (D19): for each calendar plan that is not cancelled or worn, from
   `wardrobe_plan_evening` (20:00) the evening before until it starts (a plan found later is
   told when found); once a plan (claimed in `wardrobe_told` before the send); only while his
   evening alerts are on; at most three a day of plans, then one line for the rest ("Tomorrow's
   outfits for 17 more events are ready ...", security review H1). An LND-16 "Outstanding" line
   is not counted as a gap (code review L2).
4. once a day, the claims older than 30 days go.
One owner's failure never stops another's; the counts carry class names only.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta

from jarvis.helpers.house.guard import Counts
from jarvis.logging import get_logger
from jarvis.notify.ports import Signal
from jarvis.wardrobe.styling import texts
from jarvis.wardrobe.styling.calendar import AHEAD, CalDoc, Calendar, sync
from jarvis.wardrobe.styling.plans import Plan, StylingDoc
from jarvis.wardrobe.styling.service import Here, Styling

log = get_logger(__name__)
NAME = "outfit_clock"
CAL_RETRY = timedelta(minutes=15)
MAX_READY = 3  # outfit_ready alerts a day of plans; the rest in one line (security review H1)
OUTSTANDING = "Outstanding:"  # an LND-16 line: a next action, not a gap to fix (code review L2)


def _evening(s: Styling) -> time:
    h, _, m = s.ctx.s.wardrobe_plan_evening.partition(":")
    return time(int(h), int(m))


class OutfitClock:
    name = NAME
    budget_s = 15.0

    def __init__(self, styling: Styling, calendar: Calendar) -> None:
        self.s, self.calendar = styling, calendar

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        n = Counts()
        if self.s.off() is not None:
            n.add("off")
            return n.done("ready_sent", "plans_made", "weather")
        for uid in owners:
            try:
                await self._owner(uid, n)
            except Exception as exc:  # noqa: BLE001 - one owner never blocks another
                log.warning("outfit_clock failed for an owner", extra={"error": type(exc).__name__})
                n.add("failed")
        return n.done("ready_sent", "plans_made", "weather")

    async def _owner(self, uid: str, n: Counts) -> None:
        here = await self.s.where(uid)
        n.add(f"weather_{await self.s.outlook.refresh(uid, here.now, here.zone)}")
        doc = await self.s.plans.read(uid)
        if doc.choice.calendar and self._due(doc, here.now):
            await self._calendar(uid, here, doc, n)
            doc = await self.s.plans.read(uid)
        await self._ready(uid, here, doc, n)
        if here.now.astimezone(here.zone).time() < time(0, 5):
            await self.s.told.prune(uid)

    def _due(self, doc: StylingDoc, now: datetime) -> bool:
        every = timedelta(minutes=self.s.ctx.s.wardrobe_calendar_refresh_min)
        if doc.cal_failed_at is not None and now - doc.cal_failed_at < CAL_RETRY:
            return False
        return doc.cal_read_at is None or now - doc.cal_read_at >= every

    async def _calendar(self, uid: str, here: Here, doc: StylingDoc, n: Counts) -> None:
        cal = doc.choice.calendar
        assert cal is not None
        span = (here.now, here.now + AHEAD)
        items = await self.calendar.read(uid, cal, doc.choice.fields, *span)
        if isinstance(items, str):
            n.add("calendar_not_read")
            await self.s.change(uid, lambda d: d.model_copy(update={"cal_failed_at": here.now}))
            return
        entries = self.calendar.entries(uid, cal, items)
        await self.calendar.sealed.change(
            uid, lambda _: CalDoc(read_at=here.now, start=span[0], end=span[1], entries=entries)
        )
        synced, touched = sync(doc, entries, span, here.zone, here.now)
        view = await self.s.view(uid)
        if view is not None:
            for pid in touched:
                plan = synced.plan(pid)
                if plan is not None:
                    synced = synced.put(await self.s.repick(uid, here, synced, view, plan))
        n.add("plans_made", len(touched))
        final = synced.model_copy(update={"cal_read_at": here.now, "cal_failed_at": None})
        await self.s.change(uid, lambda d: _calendar_onto(d, final, doc.choice.calendar))

    async def _ready(self, uid: str, here: Here, doc: StylingDoc, n: Counts) -> None:
        if not doc.choice.calendar or not doc.choice.plan_alerts:
            return
        notifier = self.s.ctx.notifier()
        view = await self.s.view(uid)
        if notifier is None or view is None:
            return
        due: dict[date, list[Plan]] = {}
        for plan in doc.plans:
            if self._ready_due(plan, here):
                due.setdefault(plan.day, []).append(plan)
        for day, plans in due.items():
            more = 0
            for plan in plans:
                if not await self.s.told.once(uid, f"ready_{plan.id}"):
                    continue
                if not await self._slot(uid, day):
                    more += 1  # past the evening's first three: one line for the rest (H1)
                    continue
                ans = await self.s.answer(uid, here, doc, view, plan)
                label = texts.ready_event_label(plan.day, here.today, plan.starts, here.zone)
                gaps = [g for g in ans.suggestion.primary.gaps if not g.startswith(OUTSTANDING)]
                await self._send(uid, texts.ready_alert(label, len(gaps)), n)
            if more and await self.s.told.once(uid, f"ready_more_{day.isoformat()}"):
                await self._send(uid, texts.ready_more_alert(day, here.today, more), n)

    async def _slot(self, uid: str, day: date) -> bool:
        """One of the day's MAX_READY alert slots, claimed before the send."""
        for k in range(1, MAX_READY + 1):
            if await self.s.told.once(uid, f"ready_{day.isoformat()}_{k}"):
                return True
        return False

    async def _send(self, uid: str, words: str, n: Counts) -> None:
        notifier = self.s.ctx.notifier()
        if notifier is None:
            return
        try:
            await notifier.notify(uid, Signal(source="nudge", kind="outfit_ready"), words)
            n.add("ready_sent")
        except Exception as exc:  # noqa: BLE001 - claimed; "can't send" is a result
            log.warning("outfits: outfit_ready not sent", extra={"error": type(exc).__name__})

    def _ready_due(self, plan: Plan, here: Here) -> bool:
        """A calendar plan, not cancelled or worn, from the evening before until it starts."""
        if plan.manual or plan.cancelled or plan.worn or plan.event is None:
            return False
        starts = plan.starts or datetime.combine(plan.day, time.min, tzinfo=here.zone)
        before = plan.day - timedelta(days=1)
        evening = datetime.combine(before, _evening(self.s), tzinfo=here.zone)
        return evening <= here.now < starts


def _calendar_onto(current: StylingDoc, ours: StylingDoc, cal: str | None) -> StylingDoc:
    """This read's calendar plans onto his plans now (unless he switched calendars meanwhile)."""
    if current.choice.calendar != cal:
        return current
    for plan in ours.plans:
        if not plan.manual:
            current = current.put(plan)
    return current.model_copy(update={"cal_read_at": ours.cal_read_at, "cal_failed_at": None})


__all__ = ["NAME", "OutfitClock"]

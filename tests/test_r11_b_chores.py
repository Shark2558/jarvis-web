# tests/test_r11_b_chores.py -- R11 Part B items 2 and 3 (docs/plans/r11-free-helpers.md D10,
# D11): the chores rota and the home upkeep schedule. Written before helpers/house/{store,chores,
# upkeep}.py: the rota turns on "done" and at each period's end; a reminder goes once, in the
# first 5-minute run at or after its time, never twice across a restart, and again next run when
# no channel took it; names of the rota only in the `named` text; upkeep on its lead day and its
# due day at 09:00.
from __future__ import annotations

from datetime import date, timedelta

import pytest
from r11_fakes import NOON_IST, UID, Clock
from r11_fakes_b import Rules, house_ctx

from jarvis.helpers.house import chores, upkeep, words
from jarvis.helpers.house.models import Chore, Upkeep
from jarvis.helpers.house.store import HouseStore
from jarvis.notify.ports import Delivery

TODAY = date(2026, 11, 10)  # NOON_IST's local day (a Tuesday)


def _chore(**over: object) -> Chore:
    base: dict[str, object] = {
        "label": "Dishes",
        "freq": "daily",
        "at": "11:00",
        "members": ("Partner", "Me"),
    }
    base.update(over)
    return chores.new_chore(cid="0000000a", today=TODAY, **base)  # type: ignore[arg-type]


# ---- the rota -----------------------------------------------------------------------------------
def test_daily_weekly_and_every_n_days_occur_on_the_right_days() -> None:
    daily = _chore()
    weekly = _chore(freq="weekly", days=(0, 3))  # Monday and Thursday
    every = _chore(freq="every", every=3)
    assert chores.occurs_on(daily, TODAY) and not chores.occurs_on(daily, TODAY - timedelta(1))
    assert [chores.occurs_on(weekly, TODAY + timedelta(d)) for d in range(7)] == [
        False, False, True, False, False, False, True,
    ]  # fmt: skip
    assert [chores.occurs_on(every, TODAY + timedelta(d)) for d in range(7)] == [
        True, False, False, True, False, False, True,
    ]  # fmt: skip


def test_the_turn_moves_on_done_and_at_the_end_of_each_period() -> None:
    c = _chore()
    assert chores.whose(c, TODAY) == "Partner"
    assert chores.whose(c, TODAY + timedelta(1)) == "Me"  # today ended without "done"
    assert chores.whose(c, TODAY + timedelta(2)) == "Partner"
    done = chores.mark_done(c, TODAY)
    assert done.last_done == TODAY.isoformat()
    assert chores.whose(done, TODAY + timedelta(1)) == "Me"  # moved once, not twice
    assert chores.whose(chores.mark_done(done, TODAY + timedelta(1)), TODAY + timedelta(2)) == (
        "Partner"
    )
    assert c.last_done is None  # nothing changed in place


def test_a_rota_is_adults_labels_only_and_bounded() -> None:
    with pytest.raises(ValueError):
        _chore(members=tuple(f"P{i}" for i in range(7)))
    with pytest.raises(ValueError):
        _chore(label="")
    with pytest.raises(ValueError):
        _chore(freq="every", every=1)
    with pytest.raises(ValueError):
        _chore(at="25:00")
    assert chores.whose(_chore(members=()), TODAY) is None


# ---- the reminder job ---------------------------------------------------------------------------
async def _with(c: Chore, **over: object) -> tuple[object, ...]:
    hc, notifier, docs, clock = house_ctx(**over)  # type: ignore[arg-type]
    store = HouseStore(docs, prefix=hc.prefix)
    await store.change_chores(UID, lambda cs: (*cs, c))
    return hc, notifier, docs, clock, store


async def test_a_chore_reminds_once_at_its_time_and_never_twice_across_a_restart() -> None:
    hc, notifier, docs, clock, store = await _with(_chore(at="12:00"))
    clock.at = NOON_IST - timedelta(minutes=5)  # 11:55: not yet
    assert (await chores.ChoresJob(hc, store).run(()))["sent"] == 0
    clock.at = NOON_IST + timedelta(seconds=40)  # the first run at or after 12:00
    assert (await chores.ChoresJob(hc, store).run(()))["sent"] == 1
    again = chores.ChoresJob(hc, HouseStore(docs, prefix=hc.prefix))  # a restart: a new job
    clock.at = NOON_IST + timedelta(minutes=5)
    assert (await again.run(()))["sent"] == 0
    ((uid, kind, text, named),) = notifier.calls
    assert (uid, kind) == (UID, "chore_due")
    assert text == "Chore today: Dishes. Open JARVIS to see whose turn it is."
    assert named == "Chore today: Dishes. It's Partner's turn."
    assert "Partner" not in text  # a rota name only in the named version


async def test_a_reminder_no_channel_took_is_sent_by_the_next_run() -> None:
    hc, notifier, _, clock, store = await _with(_chore(at="12:00"))
    notifier.delivery = Delivery(action="ring", reason="test")  # no channel took it
    clock.at = NOON_IST
    first = await chores.ChoresJob(hc, store).run(())
    assert first["sent"] == 0 and first["retry"] == 1
    notifier.delivery = Delivery(action="ring", reason="test", telegram=True)
    clock.at = NOON_IST + timedelta(minutes=5)
    assert (await chores.ChoresJob(hc, store).run(()))["sent"] == 1
    assert len(notifier.calls) == 2


async def test_a_chore_done_before_its_time_sends_nothing() -> None:
    hc, notifier, _, clock, store = await _with(_chore(at="12:00"))
    await store.change_chores(UID, lambda cs: tuple(chores.mark_done(c, TODAY) for c in cs))
    clock.at = NOON_IST
    await chores.ChoresJob(hc, store).run(())
    assert notifier.calls == []


async def test_the_household_row_set_to_never_stops_chore_reminders() -> None:
    hc, notifier, _, clock, store = await _with(_chore(at="12:00"), rules=Rules(("chore_*",)))
    clock.at = NOON_IST
    assert (await chores.ChoresJob(hc, store).run(()))["skipped"] == 1
    hc2, notifier2, _, _, store2 = await _with(_chore(at="12:00"), rules=Rules(broken=True))
    await chores.ChoresJob(hc2, store2).run(())
    assert notifier.calls == [] and notifier2.calls == []  # fail closed


# ---- home upkeep --------------------------------------------------------------------------------
def _item(**over: object) -> Upkeep:
    base: dict[str, object] = {"cid": "0000000b", "label": "AC service", "every": 180}
    base.update(over)
    return upkeep.new_upkeep(**base)  # type: ignore[arg-type]


def test_due_and_lead_days_in_days_and_in_months() -> None:
    item = _item(last_done=date(2026, 5, 14), lead=7)
    assert upkeep.due_date(item) == date(2026, 11, 10)
    assert upkeep.lead_date(item) == date(2026, 11, 3)
    monthly = _item(every=3, unit="months", last_done=date(2026, 11, 30), lead=0)
    assert upkeep.due_date(monthly) == date(2027, 2, 28)  # the month's last day
    assert upkeep.state(item, date(2026, 11, 2)) == "ok"
    assert upkeep.state(item, date(2026, 11, 3)) == "soon"
    assert upkeep.state(item, date(2026, 11, 10)) == "due"
    assert upkeep.state(item, date(2026, 11, 11)) == "overdue"
    assert upkeep.state(upkeep.mark_upkeep_done(item, TODAY), TODAY) == "ok"


def test_the_starter_list_is_offered_never_added() -> None:
    labels = [s["label"] for s in upkeep.STARTERS]
    assert labels == [
        "Water-purifier filter", "AC service", "Fire-extinguisher check", "Gas pipe check",
        "Car service",  # R14 D1 (row 101): every 6 months; the car's papers are in the vault
    ]  # fmt: skip
    assert [s["every"] for s in upkeep.STARTERS] == [90, 180, 365, 365, 180]
    assert {s["unit"] for s in upkeep.STARTERS} == {"days"}


async def test_upkeep_reminds_at_09_00_on_the_lead_day_and_the_due_day_once_each() -> None:
    clock = Clock(NOON_IST - timedelta(hours=3, minutes=5))  # 08:55 local
    hc, notifier, docs, clock = house_ctx(clock=clock)
    store = HouseStore(docs, prefix=hc.prefix)
    item = _item(last_done=date(2026, 5, 14), lead=0)  # due today, no lead
    lead = _item(cid="0000000c", label="Gas pipe check", every=372, last_done=date(2025, 11, 10))
    await store.change_upkeep(UID, lambda xs: (*xs, item, lead))
    job = upkeep.UpkeepJob(hc, store)
    assert (await job.run(()))["sent"] == 0
    clock.at += timedelta(minutes=5)  # 09:00
    assert (await job.run(()))["sent"] == 2
    clock.at += timedelta(minutes=5)
    assert (await upkeep.UpkeepJob(hc, HouseStore(docs, prefix=hc.prefix)).run(()))["sent"] == 0
    texts = sorted(t for _, _, t, _ in notifier.calls)
    assert texts == [
        "Home upkeep due today: AC service.",
        "Home upkeep: Gas pipe check is due on 17 Nov.",
    ]
    assert {k for _, k, _, _ in notifier.calls} == {"maintenance_due"}


async def test_the_claims_hold_hashes_only() -> None:
    hc, _, docs, clock, store = await _with(_chore(at="12:00", label="NEEDLE-CHORE"))
    clock.at = NOON_IST
    await chores.ChoresJob(hc, store).run(())
    told = [d for p, d in docs._data.items() if "house_told/" in p]  # noqa: SLF001
    assert len(told) == 1 and "NEEDLE" not in str(told)
    assert set(told[0]) == {"uid", "tag", "at", "sent"}  # the lease (code review M3)
    assert await store.sweep(UID, NOON_IST + timedelta(days=31)) == 1


# ---- code review M1, M2 and L11 ------------------------------------------------------------------
def test_done_twice_in_one_period_moves_the_turn_once() -> None:
    c = chores.new_chore(cid="0000000a", label="Dishes", freq="daily", today=TODAY,
                         members=("A", "B", "C"))  # fmt: skip
    once = chores.mark_done(c, TODAY)
    assert chores.mark_done(once, TODAY) == once  # a double tap, or "done" said twice
    assert chores.whose(chores.mark_done(once, TODAY), TODAY + timedelta(1)) == "B"
    weekly = chores.new_chore(cid="0000000b", label="Bins", freq="weekly", days=(0,),
                              today=TODAY, members=("A", "B", "C"))  # fmt: skip
    monday = date(2026, 11, 16)
    w1 = chores.mark_done(weekly, monday)
    assert chores.mark_done(w1, monday + timedelta(1)) == w1  # Tuesday: still Monday's turn
    assert chores.mark_done(w1, monday + timedelta(7)).turn != w1.turn  # next Monday: new period


async def test_a_chore_added_after_its_time_first_reminds_next_period() -> None:
    from jarvis.helpers.house.brief import HousePending
    from jarvis.helpers.house.service import HouseService
    from jarvis.helpers.house.store import OutsideStore

    hc, notifier, docs, clock = house_ctx()  # 12:00 on Tuesday 10 Nov, his time
    store = HouseStore(docs, prefix=hc.prefix)
    svc = HouseService(hc, store, OutsideStore(docs, hc.keyring, prefix=hc.prefix))
    daily = await svc.add_chore(UID, label="Dishes", freq="daily", at="09:00")
    weekly = await svc.add_chore(UID, label="Bins", freq="weekly", days=["tue", "fri"], at="09:00")
    every = await svc.add_chore(UID, label="Plants", freq="every", every=3, at="08:00")
    later = await svc.add_chore(UID, label="Laundry", freq="daily", at="18:00")
    assert (daily.start, weekly.start, every.start, later.start) == (
        "2026-11-11", "2026-11-13", "2026-11-13", "2026-11-10",
    )  # fmt: skip
    job = chores.ChoresJob(hc, store)
    await job.run(())
    assert notifier.calls == []  # nothing "late" for what he has just entered
    pending = await HousePending(svc).pending(UID, clock.at)
    assert [i.label for i in pending] == ["Chore: Laundry"]
    clock.at += timedelta(hours=21)  # 09:00 on Wednesday
    await job.run(())
    assert [t for _, _, t, _ in notifier.calls] == [words.chore("Dishes")]


def test_upkeep_every_n_months_from_29_february() -> None:
    leap = upkeep.new_upkeep(cid="0000000c", label="Gas pipe check", every=12, unit="months",
                             last_done=date(2028, 2, 29))  # fmt: skip
    assert upkeep.due_date(leap) == date(2029, 2, 28)
    assert upkeep.add_months(date(2028, 2, 29), 48) == date(2032, 2, 29)

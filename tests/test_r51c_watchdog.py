# tests/test_r51c_watchdog.py -- R5.1 D3 (docs/plans/r5-1-observations.md): the laptop going quiet
# always reaches the owner. Armed: `home_offline` (urgent), unchanged. Disarmed with the default
# `always`: ONE `home_offline_idle` per outage. `armed_only`: the R3 behaviour (nobody is told).
# Only an alert Telegram or a browser took counts; a HELD one (quiet hours) counts as told, so it
# is not added to the held summary again every 5 minutes; the owner's own "off" too.
from __future__ import annotations

import pytest
from r51c_fakes import (
    FLAP,
    HELD,
    RANG,
    SEEN,
    SWITCHED_OFF,
    UID,
    UNHEARD,
    ArmFake,
    Clock,
    HomeStoreFake,
    Scripted,
    home_status,
)

from jarvis.home.watchdog import OfflineJob, Watchdog
from jarvis.notify.ports import Delivery

AFTER = 360.0
GONE = SEEN + AFTER + 1  # one second past the threshold


def job(
    store: HomeStoreFake,
    notes: Scripted,
    *,
    armed: bool = False,
    alert_when: str | None = None,
    now: float = GONE,
) -> OfflineJob:
    kw = {} if alert_when is None else {"alert_when": alert_when}
    return OfflineJob(
        store,  # type: ignore[arg-type]
        notes,
        ArmFake(armed),
        clock=Clock(now),
        offline_after_s=AFTER,
        tz="Asia/Kolkata",
        **kw,  # type: ignore[arg-type]
    )


async def test_disarmed_by_default_one_idle_alert_with_the_fixed_words() -> None:
    store, notes = HomeStoreFake(home_status()), Scripted(RANG)
    counts = await job(store, notes).run([UID])
    assert notes.kinds() == ["home_offline_idle"]
    signal, text = notes.sent[0]
    assert signal.source == "home"
    # SEEN is 2027-01-15 08:00 UTC -> 13:30 in Asia/Kolkata
    assert text == (
        "Your home laptop stopped answering at 13:30. The camera and home devices are off "
        "until it's back, Sir."
    )
    assert len(text) <= 300
    assert counts == {"homes": 1, "offline": 1, "alerts": 1, "failed": 0}
    assert store.marks == [True]


async def test_the_idle_alert_goes_once_per_outage() -> None:
    store, notes = HomeStoreFake(home_status()), Scripted(RANG)
    j = job(store, notes)
    await j.run([UID])
    await j.run([UID])
    await j.run([UID])
    assert notes.kinds() == ["home_offline_idle"]


async def test_armed_is_unchanged_urgent_home_offline() -> None:
    store, notes = HomeStoreFake(home_status()), Scripted(RANG)
    await job(store, notes, armed=True).run([UID])
    assert notes.kinds() == ["home_offline"]
    assert notes.sent[0][1] == (
        "Your home laptop stopped answering at 13:30. Camera alerts are off until it's back."
    )


async def test_armed_only_keeps_the_r3_silence_while_disarmed() -> None:
    store, notes = HomeStoreFake(home_status()), Scripted(RANG)
    counts = await job(store, notes, alert_when="armed_only").run([UID])
    assert notes.sent == []
    assert counts["offline"] == 1 and counts["alerts"] == 0
    assert store.marks == [False]  # the state still changes, nobody is told


async def test_armed_only_still_rings_while_armed() -> None:
    store, notes = HomeStoreFake(home_status()), Scripted(RANG)
    await job(store, notes, armed=True, alert_when="armed_only").run([UID])
    assert notes.kinds() == ["home_offline"]


async def test_a_held_idle_alert_counts_as_told_and_is_not_held_again() -> None:
    """Quiet hours: the notifier holds it for the morning summary. Re-sending every 5 minutes
    would add one more "laptop offline" to the held summary each run."""
    store, notes = HomeStoreFake(home_status()), Scripted(HELD)
    j = job(store, notes)
    first = await j.run([UID])
    await j.run([UID])
    assert notes.kinds() == ["home_offline_idle"]
    assert store.marks == [True]
    assert first["alerts"] == 0  # nothing reached a channel yet


async def test_an_idle_alert_that_reached_nobody_is_tried_again() -> None:
    store, notes = HomeStoreFake(home_status()), Scripted(UNHEARD, UNHEARD, RANG)
    j = job(store, notes)
    await j.run([UID])
    assert store.current is not None and store.current.outage_alerted is False
    await j.run([UID])
    await j.run([UID])
    await j.run([UID])
    assert notes.kinds() == ["home_offline_idle"] * 3
    assert store.marks == [False, True]


async def test_a_storm_gap_drop_is_retried_but_the_owners_switch_is_respected() -> None:
    store, notes = HomeStoreFake(home_status()), Scripted(FLAP, RANG)
    j = job(store, notes)
    await j.run([UID])
    await j.run([UID])
    assert notes.kinds() == ["home_offline_idle"] * 2

    store2, notes2 = HomeStoreFake(home_status()), Scripted(SWITCHED_OFF)
    j2 = job(store2, notes2)
    await j2.run([UID])
    await j2.run([UID])
    assert notes2.kinds() == ["home_offline_idle"]  # he switched the kind off: settled


@pytest.mark.parametrize("delivery", [HELD, SWITCHED_OFF])
async def test_armed_keeps_only_a_channel_counting(delivery: Delivery) -> None:
    """Armed is unchanged (integrated review H5): only Telegram or a browser marks it told."""
    store, notes = HomeStoreFake(home_status()), Scripted(delivery, RANG)
    j = job(store, notes, armed=True)
    await j.run([UID])
    await j.run([UID])
    assert notes.kinds() == ["home_offline", "home_offline"]


async def test_within_the_threshold_nothing_happens() -> None:
    store, notes = HomeStoreFake(home_status()), Scripted(RANG)
    counts = await job(store, notes, now=SEEN + AFTER).run([UID])
    assert notes.sent == [] and counts["offline"] == 0 and store.marks == []


async def test_no_notifier_still_marks_the_state() -> None:
    store = HomeStoreFake(home_status())
    j = OfflineJob(store, None, ArmFake(), clock=Clock(GONE), offline_after_s=AFTER)  # type: ignore[arg-type]
    await j.run([UID])
    assert store.marks == [False]


def test_an_unknown_setting_is_refused() -> None:
    with pytest.raises(ValueError, match="alert_when"):
        OfflineJob(
            HomeStoreFake(None),  # type: ignore[arg-type]
            None,
            None,
            clock=Clock(),
            offline_after_s=AFTER,
            alert_when="sometimes",  # type: ignore[arg-type]
        )


# ---- the shared systems-check job joins the watchdog (R5.1 D4) ----------------------------------
class Linked(HomeStoreFake):
    async def linked_uids(self) -> list[str]:
        return [UID]

    async def sweep_claims(self) -> int:
        return 0

    async def sweep_codes(self) -> int:
        return 0


class Counted:
    name = "health_check"
    budget_s = 5.0

    def __init__(self) -> None:
        self.owners: list[list[str]] = []

    async def run(self, owners: list[str]) -> dict[str, int]:
        self.owners.append(list(owners))
        return {"owners": len(owners)}


def dog_for(store: Linked) -> Watchdog:
    return Watchdog(store, job(store, Scripted(RANG)))  # type: ignore[arg-type]


async def test_a_job_added_later_runs_with_the_watchdog_over_linked_homes() -> None:
    dog = dog_for(Linked(home_status()))
    health = Counted()
    dog.extend(health)
    out = await dog.run()
    assert health.owners == [[UID]]
    assert out["jobs"]["health_check"] == "ok"  # type: ignore[index]


def test_a_job_name_already_there_is_refused() -> None:
    store = Linked(home_status())
    dog = dog_for(store)
    dog.extend(Counted())
    with pytest.raises(ValueError, match="health_check"):
        dog.extend(Counted())
    with pytest.raises(ValueError, match="home_offline"):
        dog.extend(job(store, Scripted(RANG)))

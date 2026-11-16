# tests/test_r13_c_races.py -- R13 Part C's writers against his concurrent changes (security
# review 1 M1; code review 1 L4): every merge runs against the CURRENT document inside the
# transaction, with a compare-and-set on each plan, so a released plan never comes back, `worn` is
# never undone, his lock and the refresh's "needs" both survive, and two rule changes both stay.
# Each race is made deterministic by doing the other writer's change mid-step. Fixed IST clocks.
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from r13_fakes import UID
from r13_fakes_c import FakeGoogle, N, World, app_of, gevent, ist, world

from jarvis.tools.gateway import GatewayOutcome

WORK = "work-cal@example.com"


class RacingGoogle(FakeGoogle):
    """A Google whose events read lets another writer act while it is in flight."""

    during: Callable[[], Awaitable[None]] | None = None

    async def request(self, uid: str, method: str, url: str, **kw: Any) -> Any:
        if url.endswith("/events") and self.during is not None:
            during, self.during = self.during, None
            await during()
        return await super().request(uid, method, url, **kw)


async def ok(w: World, name: str, **args: Any) -> dict[str, Any]:
    got = await w.call(name, **args)
    assert got.outcome is GatewayOutcome.EXECUTED, (got.outcome, got.error)
    assert isinstance(got.result, dict)
    return got.result


async def _pick(w: World) -> None:
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app_of(w)), base_url="http://t") as c:
        listed = (await c.get("/v1/outfits/calendars")).json()["calendars"]
        ref = next(x["id_ref"] for x in listed if x["title"] == "Work")
        assert (await c.put("/v1/outfits/settings", json={"calendar": ref})).status_code == 200


def _two() -> list[dict[str, Any]]:
    return [
        gevent("ev-1", ist(2026, 11, 17, 10, 0), 1.0, title="Client meeting"),
        gevent("ev-2", ist(2026, 11, 17, 15, 0), 1.0, title="Board review"),
    ]


async def test_a_release_and_a_wear_during_the_calendar_read_both_survive() -> None:
    from jarvis.wardrobe.styling import actions

    google = RacingGoogle(events={WORK: _two()})
    w = await world(at=ist(2026, 11, 16, 18, 0), google=google)
    await _pick(w)
    await w.part.clock_jobs[0].run([UID])
    first, second = (await w.styling.plans.read(UID)).plans

    async def his_changes() -> None:
        await actions.run(w.styling, UID, {"action": "release", "plan": first.id})
        await ok(w, "wear_log", action="start", plan=second.id)

    google.during = his_changes
    w.clock.advance(minutes=65)
    await w.part.clock_jobs[0].run([UID])
    after = (await w.styling.plans.read(UID)).plans
    assert [p.id for p in after] == [second.id]  # the released plan did not come back
    assert after[0].worn is True  # and `worn` was not undone


async def test_switching_calendars_during_the_read_makes_no_plan_from_the_old_one() -> None:
    google = RacingGoogle(events={WORK: _two()})
    w = await world(at=ist(2026, 11, 16, 18, 0), google=google)
    await _pick(w)

    async def off() -> None:
        await w.styling.change(
            UID,
            lambda d: d.model_copy(
                update={"choice": d.choice.model_copy(update={"calendar": None})}
            ),
        )

    google.during = off
    counts = await w.part.clock_jobs[0].run([UID])
    assert (await w.styling.plans.read(UID)).plans == () and counts["plans_made"] == 0


async def test_a_plan_changed_during_an_action_is_refused_and_the_other_change_stays(
    monkeypatch: Any,
) -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0))
    plan = (await ok(w, "outfit_plan", action="save", day="tomorrow", occasion="meeting",
                     start="10:00", end="12:00"))["plan"]  # fmt: skip
    real, fired = w.styling.repick, []

    async def racing(*a: Any, **kw: Any) -> Any:
        if not fired:
            fired.append(1)
            await w.move(N.shirt_white, "deposited")  # the refresh marks "needs a new top"
        return await real(*a, **kw)

    monkeypatch.setattr(w.styling, "repick", racing)
    got = await ok(w, "outfit_plan", action="change", plan=plan["id"], slot="shoes")
    assert got == {"refused": True, "message": "That plan changed meanwhile: try again."}
    assert (await w.styling.plans.read(UID)).plan(plan["id"]).needs == ("top",)  # type: ignore[union-attr]


async def test_the_refresh_and_his_lock_on_the_same_plan_both_survive(monkeypatch: Any) -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0))
    plan = (await ok(w, "outfit_plan", action="save", day="tomorrow", occasion="meeting",
                     start="10:00", end="12:00"))["plan"]  # fmt: skip
    real, fired = w.refresh._updates, []  # noqa: SLF001 - the step the race slips into

    async def racing(*a: Any, **kw: Any) -> Any:
        if not fired:
            fired.append(1)
            doc = await w.styling.plans.read(UID)
            p = doc.plan(plan["id"])
            watch = p.slot("watch").model_copy(update={"locked": True})
            await w.styling.change(
                UID,
                lambda d: d.put(
                    p.model_copy(
                        update={"picks": tuple(watch if x.slot == "watch" else x for x in p.picks)}
                    )
                ),
            )
        return await real(*a, **kw)

    monkeypatch.setattr(w.refresh, "_updates", racing)
    await w.move(N.shirt_white, "deposited")
    stored = (await w.styling.plans.read(UID)).plan(plan["id"])
    assert stored.needs == ("top",) and stored.slot("watch").locked  # type: ignore[union-attr]


async def test_two_rule_changes_at_once_both_stay(monkeypatch: Any) -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0))
    real, fired = w.styling.change, []

    async def racing(uid: str, fn: Any) -> Any:
        if not fired:
            fired.append(1)  # the panel's change lands first
            await real(
                uid,
                lambda d: d.model_copy(
                    update={"prefs": d.prefs.model_copy(update={"likes": ("navy",)})}
                ),
            )
        return await real(uid, fn)

    monkeypatch.setattr(w.styling, "change", racing)
    await ok(w, "outfit_prefs", action="never", feature="neck", value="tight")
    prefs = (await w.styling.plans.read(UID)).prefs
    assert prefs.likes == ("navy",) and [(n.feature, n.value) for n in prefs.never] == [
        ("neck", "tight")
    ]

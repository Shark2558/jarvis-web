# tests/test_r7_i1_fixes.py -- R7 I1 fixer: the Workshop's decisions on the two integrated reviews.
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from r7_fakes_c import CSRF, ORIGIN, owner_uid, phone_app, sign_in_again

from jarvis.config import Settings
from jarvis.phone import applock

DEV = applock.DEVICE_KEY


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[Any]:
    async with phone_app(settings) as a:
        yield a


# ---- security L3: a link from another site cannot mark this browser as the app ----
async def test_a_cross_site_visit_to_source_app_marks_nothing(app: Any) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
        await sign_in_again(app, c)
        r = await c.get("/?source=app", headers={"Sec-Fetch-Site": "cross-site"})
        assert r.status_code == 302 and r.headers["location"] == "/"  # the page never sees `source`
        # even a mark the page would send is refused when the browser says the call is not its own
        for site in ("cross-site", "same-site"):
            r = await c.post("/v1/session/app", headers={**CSRF, "Sec-Fetch-Site": site})
            assert r.json() == {"app": False}
            assert DEV not in c.cookies and not r.headers.get_list("set-cookie")
        assert (await c.get("/v1/session/lock")).json()["app"] is False


@pytest.mark.parametrize("site", ["none", "same-origin", None])
async def test_a_typed_or_app_launch_still_marks_the_app(app: Any, site: str | None) -> None:
    extra = {} if site is None else {"Sec-Fetch-Site": site}
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
        await sign_in_again(app, c)
        assert (await c.get("/?source=app", headers=extra)).status_code in (200, 302)
        r = await c.post("/v1/session/app", headers={**CSRF, **extra})
        assert r.json() == {"app": True} and c.cookies.get(DEV)
        assert (await c.get("/v1/session/lock")).json()["app"] is True


# ---- security L4: a flood or a rate limit is a bare 429, never the "unknown phone" 401 ----
async def test_the_door_answers_a_flood_with_a_bare_429_and_keeps_401_for_authentication(
    app: Any,
) -> None:
    from jarvis.mobile import contract

    now = int(app.state.phone_clock())
    head = contract.header_value("ph_000000000000", now, "ab" * 16, b"signature" * 6)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as anon:
        seen = []
        for _ in range(64):
            r = await anon.post("/phone/v1/hello", content=b"{}", headers={"X-Jarvis-Phone": head})
            seen.append(r.status_code)
        assert seen[:60] == [401] * 60  # an unknown phone is still a bare 401
        assert seen[60:] == [429] * 4
        assert r.content == b"" and "set-cookie" not in r.headers
        # authentication failures are still 401, whichever check refuses
        bare = await anon.post("/phone/v1/hello", content=b"{}", headers={})
        assert bare.status_code == 401 and bare.content == b""
        other = await anon.get("/phone/v1/hello")
        assert other.status_code == 404


# ---- security L5: the needles eval reads every shape of a heart rate, a number and a name ----
def _needles() -> Any:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "evals" / "r7" / "needles.py"
    spec = importlib.util.spec_from_file_location("r7_needles_under_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    "written",
    [
        '"min": 43',
        '{"heart_min": 43}',
        "resting_bpm: 87",
        "heart_max=179",
        "179 bpm",
        "87 average",
        "the heart rate of 43",
        "pulse: 87.0",
    ],
)
def test_the_heart_needle_reads_every_key_shape(written: str) -> None:
    assert _needles().HEART_RE.search(written), written


@pytest.mark.parametrize("quiet", ['"steps": {"count": 6012}', "at 14:05 on 2026-11-13", "id 4387"])
def test_the_heart_needle_leaves_other_numbers_alone(quiet: str) -> None:
    assert not _needles().HEART_RE.search(quiet), quiet


@pytest.mark.parametrize(
    "written", ["0000000001", "000 000 0001", "(000) 000-0001", "+1 000-000-0001"]
)
def test_the_number_needle_reads_national_and_spaced_forms_and_the_name_needle_the_label(
    written: str,
) -> None:
    mod = _needles()
    seen = mod.Seen()
    seen.add("logs", f"sent to {written} for Asha Example")
    found = mod._found(seen)  # noqa: SLF001
    assert found["numbers"] and found["names"] == ["Asha Example"]


# ---- security L6, code M4, code L6: the SOS service ----
def _sos_world(**kw: Any) -> Any:
    from test_r7_d_sos_send import World

    return World(**kw)


async def test_a_failed_press_is_not_remembered_so_a_retry_of_the_same_press_tries_again() -> None:
    from test_r7_d_sos_send import HERE
    from test_r7_d_sos_send import UID as OWNER_UID

    w = _sos_world()
    await w.three()
    press = "p" + "0123456789abcdef" * 2
    w.bot.refuse_text = {7_000_000_001, 7_000_000_002, 7_000_000_003}  # Telegram takes nothing
    first = await w.svc.send(OWNER_UID, "real", HERE, via="web", press_id=press)
    assert first.reached == 0 and first.outcome == "failed"
    w.bot.refuse_text = set()  # a moment later Telegram answers
    again = await w.svc.send(OWNER_UID, "real", HERE, via="web", press_id=press)
    assert again.reached == 3 and again.outcome == "sent"
    # a press that did reach someone is still answered from memory and sends nothing twice
    sent_before = len(w.bot.of("sendMessage"))
    third = await w.svc.send(OWNER_UID, "real", HERE, via="web", press_id=press)
    assert third.reached == 3 and len(w.bot.of("sendMessage")) == sent_before


async def test_the_hourly_cap_is_a_constructor_argument_and_no_module_switch_exists() -> None:
    import jarvis.sos.limits as limits
    import jarvis.sos.service as service

    assert not hasattr(service, "HOURLY_CAP") and not hasattr(service, "OWN_TEST_BUDGET")
    assert not hasattr(limits, "HOURLY_CAP") and not hasattr(limits, "OWN_TEST_BUDGET")
    from test_r7_d_sos_send import HERE
    from test_r7_d_sos_send import UID as OWNER_UID

    w = _sos_world()
    await w.three()
    assert w.svc.hourly_cap is True and w.svc.own_test_budget is True
    for _ in range(3):
        assert (await w.svc.send(OWNER_UID, "real", HERE, via="web")).reached == 3
    refused = await w.svc.send(OWNER_UID, "real", HERE, via="web")
    assert refused.outcome == "refused" and refused.reason == "hour"


@pytest.mark.parametrize("name", ["sos/service.py", "sos/limits.py", "sos/after.py"])
def test_every_sos_file_is_under_800_lines(name: str) -> None:
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "src" / "jarvis" / name
    assert len(path.read_text(encoding="utf-8").splitlines()) < 800, name


# ---- code M3: watch_stale says nothing once the phone has been unlinked --------------------------
def _stale_job(rig: Any, seam: Any) -> Any:
    from jarvis.watch.jobs import WatchStale

    return WatchStale(
        rig.part.services["watch"],
        notifier=lambda: rig.notes,
        now=rig.clock,
        linked=None if seam is None else (lambda: seam),
    )


async def test_watch_stale_stays_silent_when_no_phone_is_linked_any_more() -> None:
    import json

    from r7_fakes_d import UID as D_UID
    from test_r7_d_part import HEALTH
    from test_r7_d_part import Rig as BodyRig

    async def linked(uid: str) -> float | None:
        return 1.0  # a phone is linked

    async def unlinked(uid: str) -> float | None:
        return None  # the owner pressed "Unlink this phone"

    for kind, move in (("sync", {"hours": 27}), ("data", {"days": 5})):
        for seam, expected in (
            (linked, 1),
            (unlinked, 0),
            (None, 1),
        ):  # no seam: unknown, as before
            rig = BodyRig()
            await rig.door.call("health", json.dumps(HEALTH).encode())
            rig.clock.move(**move)
            got = await _stale_job(rig, seam).run([D_UID])
            assert got["told"] == expected, (kind, getattr(seam, "__name__", seam))
            assert len(rig.notes.sent) == expected


# ---- code M5: R7's clock and daily jobs do not depend on the R11 helpers ------------------
def _key() -> Any:
    import base64

    from pydantic import SecretStr

    return SecretStr(base64.urlsafe_b64encode(bytes(range(201, 233))).decode())


@pytest.mark.parametrize("how", ["switched_off", "setup_failed"])
async def test_r7_jobs_run_on_the_tick_with_the_helpers_off_or_failed(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    from datetime import timedelta

    import jarvis.api.r11_wiring as r11
    from jarvis.ticks import MAX_BUDGET_S, TICK_TOTAL_BUDGET_S, run_jobs
    from jarvis.watch.models import Session

    extra: dict[str, Any] = {
        "token_key": _key(),
    }
    if how == "switched_off":
        extra["helpers_enabled"] = False
    else:

        def boom(*a: Any, **k: Any) -> Any:
            raise RuntimeError("R11 setup broke")

        monkeypatch.setattr(r11, "GateStore", boom)
    async with phone_app(settings, **extra) as app:
        assert app.state.helpers_clock is None and app.state.helpers_daily is None
        assert app.state.helpers_off == how
        jobs = {j.name: j for j in app.state.tick_jobs}
        assert {"mobile_clock", "mobile_daily"} <= set(jobs)
        assert all(0 < jobs[n].budget_s <= MAX_BUDGET_S for n in ("mobile_clock", "mobile_daily"))
        assert jobs["mobile_clock"].budget_s + jobs["mobile_daily"].budget_s < TICK_TOTAL_BUDGET_S
        watch = app.state.r7_parts["body"].services["watch"]
        night = Session(
            start="2026-01-01T23:00:00+05:30", end="2026-01-02T06:00:00+05:30", writer="typed"
        )
        uid, today = owner_uid(), watch.today()
        await watch.store.set_typed(uid, today, night)
        await watch.store.set_typed(uid, today - timedelta(days=401), night)  # 400-day window
        assert await watch.store.count(uid) == 2
        # what the Scheduler's tick does with `app.state.tick_jobs` (api/brief.py)
        ran = await run_jobs(app.state.tick_jobs, app.state.brief.owners)
        assert ran["mobile_daily"] == "ok" and ran["mobile_clock"] == "ok"
        assert await watch.store.count(uid) == 1  # the old day is gone, today's stays

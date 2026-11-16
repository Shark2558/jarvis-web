# tests/test_r13_c_calendar.py -- R13 Part C's calendar (docs/plans/r13-wardrobe.md D13, D19,
# OPS-04, STY-02; plan review M12): only the calendar he picks (a reference from HIS list), only
# the fields he picks, every read governed ("Allow" only, one kind-only audit line), titles never
# stored, cancelled events by absence (a draft, no `outfit_ready`), edits by Google's `updated`
# stamp, the 60-minute cadence, the 20:00 evening alert once a plan, switching the calendar off.
from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from httpx import ASGITransport, AsyncClient
from r13_fakes import UID
from r13_fakes_c import RING, FakeGoogle, N, World, app_of, gevent, ist, world

from jarvis.tools.policy import Effect

WORK = "work-cal@example.com"
TITLE = "Quarterly client meeting with Example Corp"


async def _client(w: World) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app_of(w)), base_url="http://test")


async def _pick(w: World, cal: str = WORK, **extra: Any) -> Any:
    async with await _client(w) as c:
        listed = (await c.get("/v1/outfits/calendars")).json()
        ref = (
            next(x["id_ref"] for x in listed["calendars"] if x["title"] == "Work") if cal else None
        )
        return await c.put("/v1/outfits/settings", json={"calendar": ref, **extra})


def _meeting(day: int = 17, hh: int = 10, **kw: Any) -> dict[str, Any]:
    return gevent("ev-1", ist(2026, 11, day, hh, 0), 1.5, title=TITLE, **kw)


async def _tick(w: World) -> dict[str, int]:
    return await w.part.clock_jobs[0].run([UID])  # type: ignore[no-any-return]


async def _plans(w: World) -> Any:
    return (await w.styling.plans.read(UID)).plans


def _events_calls(w: World) -> list[tuple[str, str, dict[str, Any]]]:
    return [c for c in w.google.calls if c[1].endswith("/events")]


# ---- OPS-04: his calendar, his fields -----------------------------------------------------------
async def test_ops04_only_a_calendar_from_his_list_is_accepted_and_kept_sealed() -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0))
    async with await _client(w) as c:
        listed = (await c.get("/v1/outfits/calendars")).json()
        assert [x["title"] for x in listed["calendars"]] == ["Personal", "Work"]
        assert all(WORK not in json.dumps(x) for x in listed["calendars"])  # a reference only
        bad = await c.put("/v1/outfits/settings", json={"calendar": "f" * 16})
        assert bad.status_code == 422 and bad.json() == {
            "detail": "That calendar isn't in your list."
        }
    got = await _pick(w)
    assert got.status_code == 200 and got.json()["calendar_chosen"] is True
    assert got.headers["cache-control"] == "no-store"
    assert (await w.styling.plans.read(UID)).choice.calendar == WORK
    raw = json.dumps(w.docs._data)  # noqa: SLF001 - nothing in clear
    assert WORK not in raw and "Work" not in raw


async def test_ops04_only_the_chosen_calendar_and_fields_are_requested() -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0), google=FakeGoogle(events={WORK: [_meeting()]}))
    await _pick(w)
    await _tick(w)
    ((method, url, params),) = _events_calls(w)
    assert method == "GET" and f"/calendars/{quote(WORK, safe='')}/events" in url
    assert params["fields"] == "items(id,status,updated,start,end,summary),nextPageToken"
    assert params["singleEvents"] == "true"
    for never in ("description", "attendees", "location"):
        assert never not in params["fields"]
    w.clock.advance(hours=1)
    await _pick(w, fields=["title", "location"])
    await _tick(w)
    assert (
        _events_calls(w)[-1][2]["fields"]
        == "items(id,status,updated,start,end,summary,location),nextPageToken"
    )


async def test_ops04_every_read_obeys_the_calendar_row_allow_only() -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0), google=FakeGoogle(events={WORK: [_meeting()]}))
    await _pick(w)
    w.rows.set("calendar_list_events", Effect.ASK)
    calls = len(w.google.calls)
    await _tick(w)
    assert len(w.google.calls) == calls  # no read at all
    async with await _client(w) as c:
        why = (await c.get("/v1/outfits/calendars")).json()["why"]
    assert why == "Your Calendar permission is Ask first: allow it, or plan by hand."
    w.rows.set("calendar_list_events", Effect.ALLOW)
    w.clock.advance(minutes=20)
    await _tick(w)
    lines = [e for e in w.audit._entries if e.tool == "calendar_list_events"]  # noqa: SLF001
    assert lines and all(e.agent == "helpers" and e.detail.startswith("outfits") for e in lines)
    assert {e.outcome for e in lines} >= {"denied", "executed"}
    assert TITLE not in json.dumps([e.detail for e in lines])


async def test_ops04_switching_the_calendar_off_stops_automatic_plans_and_alerts() -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0), google=FakeGoogle(events={WORK: [_meeting()]}))
    await _pick(w)
    await _tick(w)
    assert [p.manual for p in await _plans(w)] == [False]
    got = await _pick(w, cal="")
    assert got.json()["calendar_chosen"] is False
    assert [p.manual for p in await _plans(w)] == [True]  # its plan stays, now his own
    calls = len(w.google.calls)
    w.clock.set(ist(2026, 11, 16, 20, 0))
    await _tick(w)
    assert len(w.google.calls) == calls and w.notifier.sent == []


# ---- STY-02: plans from the calendar -------------------------------------------------------------
async def test_sty02_a_meeting_on_his_calendar_makes_a_plan_for_its_local_date() -> None:
    late = gevent("ev-2", ist(2026, 11, 18, 0, 30), 1.0, title="Client review")  # 17 Nov in UTC
    w = await world(
        at=ist(2026, 11, 16, 18, 0), google=FakeGoogle(events={WORK: [_meeting(), late]})
    )
    await _pick(w)
    counts = await _tick(w)
    assert counts["plans_made"] == 2
    plans = await _plans(w)
    assert [(str(p.day), p.code, p.manual, p.tentative) for p in plans] == [
        ("2026-11-17", "business_formal", False, True),
        ("2026-11-18", "business_formal", False, True),
    ]
    assert all(p.picks and len(p.event or "") == 16 for p in plans)
    cal = await w.part.services["refresh"].calendar.sealed.read(UID)
    raw = json.dumps([p.model_dump(mode="json") for p in plans]) + cal.model_dump_json()
    assert TITLE not in raw and "Client review" not in raw and "ev-1" not in raw


async def test_sty02_a_cancelled_event_becomes_a_draft_with_no_outfit_ready() -> None:
    google = FakeGoogle(events={WORK: [_meeting()]})
    w = await world(at=ist(2026, 11, 16, 18, 0), google=google)
    await _pick(w)
    await _tick(w)
    google.events[WORK] = []  # Google returns no cancelled event: it is simply missing
    w.clock.set(ist(2026, 11, 16, 19, 5))
    await _tick(w)
    (plan,) = await _plans(w)
    assert plan.cancelled is True and plan.picks  # kept as a draft
    w.clock.set(ist(2026, 11, 16, 20, 0))
    await _tick(w)
    assert w.notifier.sent == []
    async with await _client(w) as c:
        tomorrow = (await c.get("/v1/outfits")).json()["tomorrow"]
    assert [p["id"] for p in tomorrow] == ["suggestion"]  # a draft isn't tomorrow's plan


async def test_sty02_an_edited_event_refreshes_by_its_updated_stamp() -> None:
    google = FakeGoogle(events={WORK: [_meeting()]})
    w = await world(at=ist(2026, 11, 16, 18, 0), google=google)
    await _pick(w)
    await _tick(w)
    google.events[WORK] = [_meeting(hh=11, updated="2026-11-16T12:00:00Z")]
    w.clock.advance(hours=1)
    await _tick(w)
    (plan,) = await _plans(w)
    assert plan.starts == ist(2026, 11, 17, 11, 0) and plan.updated == "2026-11-16T12:00:00Z"


async def test_the_calendar_is_read_at_most_every_60_minutes() -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0), google=FakeGoogle(events={WORK: [_meeting()]}))
    await _pick(w)
    for _ in range(6):
        await _tick(w)
        w.clock.advance(minutes=5)
    assert len(_events_calls(w)) == 1
    w.clock.set(ist(2026, 11, 16, 19, 0))
    await _tick(w)
    assert len(_events_calls(w)) == 2


# ---- D19: the evening's outfit_ready ------------------------------------------------------------
async def test_outfit_ready_at_20_00_the_evening_before_once_in_fixed_words() -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0), google=FakeGoogle(events={WORK: [_meeting()]}))
    await _pick(w)
    await _tick(w)
    w.clock.set(ist(2026, 11, 16, 19, 55))
    await _tick(w)
    assert w.notifier.sent == []
    w.clock.set(ist(2026, 11, 16, 20, 0))
    await _tick(w)
    w.clock.advance(minutes=5)
    await _tick(w)
    assert w.notifier.sent == [
        ("outfit_ready", "Tomorrow's outfit for your 10:00 event is ready in Helpers, Wardrobe.")
    ]
    assert TITLE not in json.dumps(w.notifier.sent)


async def test_no_evening_alert_when_he_turned_it_off_or_without_a_key() -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0), google=FakeGoogle(events={WORK: [_meeting()]}))
    await _pick(w, plan_alerts=False)
    await _tick(w)
    w.clock.set(ist(2026, 11, 16, 20, 0))
    await _tick(w)
    assert w.notifier.sent == []
    off = await world(keyring=None)
    assert await off.part.clock_jobs[0].run([UID]) == {
        "off": 1,
        "ready_sent": 0,
        "plans_made": 0,
        "weather": 0,
    }
    assert RING is not None


# ---- code review H2: a toggle keeps what it did not send; security review L5 ---------------------
async def test_a_toggle_without_the_calendar_keeps_his_calendar_its_plans_and_his_choices() -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0), google=FakeGoogle(events={WORK: [_meeting()]}))
    await _pick(w, auto_swap=True)
    await _tick(w)
    async with await _client(w) as c:  # D's panel: one toggle, `calendar` left out
        got = await c.put("/v1/outfits/settings", json={"plan_alerts": True, "fields": ["title"]})
    assert got.status_code == 200
    assert (got.json()["calendar_chosen"], got.json()["auto_swap"]) == (True, True)
    assert [p.manual for p in await _plans(w)] == [False]
    w.clock.set(ist(2026, 11, 16, 20, 0))
    await _tick(w)
    assert [k for k, _ in w.notifier.sent] == ["outfit_ready"]


async def test_choosing_the_same_calendar_again_takes_back_the_plans_he_never_edited() -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0), google=FakeGoogle(events={WORK: [_meeting()]}))
    await _pick(w)
    await _tick(w)
    await _pick(w, cal="")  # off: its plan stays, his own
    assert [p.manual for p in await _plans(w)] == [True]
    await _pick(w)
    await _tick(w)
    assert [p.manual for p in await _plans(w)] == [False]  # the same one plan, not two
    w.clock.set(ist(2026, 11, 16, 20, 0))
    await _tick(w)
    assert [k for k, _ in w.notifier.sent] == ["outfit_ready"]


async def test_switching_the_calendar_off_deletes_its_last_read() -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0), google=FakeGoogle(events={WORK: [_meeting()]}))
    await _pick(w)
    await _tick(w)
    assert await w.docs.get(f"jarvis_wardrobe_cal/{UID}") is not None
    await _pick(w, cal="")
    assert await w.docs.get(f"jarvis_wardrobe_cal/{UID}") is None


# ---- security review H1: strangers' invites can't flood his plans or his evening ---------------
def _invites(n: int) -> list[dict[str, Any]]:
    return [
        gevent(f"inv-{i}", ist(2026, 11, 17, 8 + i % 12, (i // 12) * 10), 0.25, title="Invite")
        for i in range(n)
    ]


async def test_fifty_invites_make_at_most_20_plans_one_capped_evening_and_his_save_works() -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0), google=FakeGoogle(events={WORK: _invites(50)}))
    await _pick(w)
    await _tick(w)
    plans = await _plans(w)
    assert len(plans) == 20 and not [p for p in plans if p.manual]
    got = await w.call("outfit_plan", action="save", day="tomorrow")
    assert "refused" not in got.result  # his own 40 slots stay his
    w.clock.set(ist(2026, 11, 16, 20, 0))
    await _tick(w)
    w.clock.advance(minutes=5)
    await _tick(w)
    assert [k for k, _ in w.notifier.sent] == ["outfit_ready"] * 4
    assert w.notifier.sent[-1][1] == (
        "Tomorrow's outfits for 17 more events are ready in Helpers, Wardrobe."
    )


async def test_a_calendar_plan_he_released_is_not_made_again_until_its_day_is_past() -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0), google=FakeGoogle(events={WORK: [_meeting()]}))
    await _pick(w)
    await _tick(w)
    (plan,) = await _plans(w)
    from jarvis.wardrobe.styling import actions

    await actions.run(w.styling, UID, {"action": "release", "plan": plan.id})
    w.clock.advance(hours=1)
    await _tick(w)
    assert await _plans(w) == ()
    w.clock.set(ist(2026, 11, 18, 9, 0))
    await _tick(w)
    assert (await w.styling.plans.read(UID)).dismissed == ()  # its day is past: forgotten


async def test_a_cancelled_calendar_draft_goes_once_its_day_has_passed() -> None:
    google = FakeGoogle(events={WORK: [_meeting()]})
    w = await world(at=ist(2026, 11, 16, 18, 0), google=google)
    await _pick(w)
    await _tick(w)
    await w.call("outfit_plan", action="save", day="tomorrow")  # his own plan that day
    google.events[WORK] = []
    w.clock.set(ist(2026, 11, 16, 19, 5))
    await _tick(w)
    assert sorted(p.cancelled for p in await _plans(w)) == [False, True]
    w.clock.set(ist(2026, 11, 18, 9, 0))
    await _tick(w)
    assert [(p.manual, p.cancelled) for p in await _plans(w)] == [(True, False)]


# ---- code review L2: an LND-16 line is not a gap to fix ------------------------------------------
async def test_the_evening_alert_does_not_count_an_outstanding_laundry_line_as_a_gap() -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0), google=FakeGoogle(events={WORK: [_meeting()]}))
    await w.move(N.shirt_white, "sent_out")
    await w.edit(N.shirt_white, expected_back=ist(2026, 11, 17).date())
    await _pick(w)
    await _tick(w)
    w.clock.set(ist(2026, 11, 16, 20, 0))
    await _tick(w)
    assert w.notifier.sent == [
        ("outfit_ready", "Tomorrow's outfit for your 10:00 event is ready in Helpers, Wardrobe.")
    ]


# ---- security review L4: the fields he chose, and a read cut short -------------------------------
class PagedGoogle(FakeGoogle):
    """Google answering with more pages to come (`nextPageToken`)."""

    async def request(self, uid: str, method: str, url: str, **kw: Any) -> Any:
        got = await super().request(uid, method, url, **kw)
        return {**got, "nextPageToken": "more"} if url.endswith("/events") else got


async def test_a_title_google_sends_while_his_title_field_is_off_is_never_used() -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0), google=FakeGoogle(events={WORK: [_meeting()]}))
    await _pick(w, fields=[])
    await _tick(w)
    (plan,) = await _plans(w)
    assert (plan.occasion, plan.code) == (None, "smart_casual")  # the title was not read
    assert _events_calls(w)[0][2]["fields"] == "items(id,status,updated,start,end),nextPageToken"


async def test_a_read_cut_short_by_a_next_page_cancels_nothing() -> None:
    google = PagedGoogle(events={WORK: [_meeting()]})
    w = await world(at=ist(2026, 11, 16, 18, 0), google=google)
    await _pick(w)
    await _tick(w)
    google.events[WORK] = []  # missing from a read that has more pages: not known to be gone
    w.clock.advance(hours=1)
    await _tick(w)
    assert [p.cancelled for p in await _plans(w)] == [False]

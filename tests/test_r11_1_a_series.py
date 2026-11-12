# tests/test_r11_1_a_series.py -- R11.1 Part A, O2b (plan D6): a followed series. The batch
# remembers the plan; the clock job asks once per session, fifteen minutes after it ends, held at
# night, with no model; "done" marks it; "skipped" marks it and puts ONE re-plan card in
# Approvals; nothing moves before the approval and the number of sessions never changes.
from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from r11_1_fakes_a import UID, PlanRig, followed, plan_rig, weekday_sessions

from jarvis.core.guardrails import ActionRisk
from jarvis.series import job as checkin
from jarvis.series.models import MAX_PLANS
from jarvis.series.phrases import route
from jarvis.tools import calendar_batch as cb
from jarvis.tools.gateway import GatewayOutcome
from jarvis.tools.policy import Effect, PolicyRule
from jarvis.tools.taint import context_trust

IST = ZoneInfo("Asia/Kolkata")
T0 = datetime(2026, 11, 12, 9, 0, tzinfo=IST)  # the plan is made on a Thursday morning
AFTER_7 = datetime(2026, 11, 24, 20, 20, tzinfo=IST)  # session 7 (Tue) ended twenty minutes ago


@pytest.fixture
async def rig() -> PlanRig:
    return await plan_rig(T0)


async def _plan(rig: PlanRig):  # noqa: ANN202 - the one plan of the test
    [plan] = (await rig.svc.book(UID)).plans
    return plan


# ---- the batch remembers the plan --------------------------------------------------------------
async def test_a_batch_with_a_series_is_remembered_with_every_session(rig: PlanRig) -> None:
    made = await followed(rig, 60)
    assert made["created"] == 60 and "followed" in made["note"]
    plan = await _plan(rig)
    assert (plan.name, plan.prefix, plan.outside, plan.total) == ("CCA", "CCA", False, 60)
    assert [s.n for s in plan.sessions] == list(range(1, 61))
    assert {s.state for s in plan.sessions} == {"planned"}
    first = plan.sessions[0]
    assert first.title == "CCA - Topic 1" and first.event_id in rig.fake.events
    assert first.start == datetime(2026, 11, 16, 19, 0, tzinfo=IST) and first.batch == made["batch"]
    stored = await rig.docs.get(f"{rig.s.firestore_prefix}series/{UID}")
    assert stored is not None and len(stored["plans"][0]["sessions"]) == 60


async def test_a_plan_made_from_a_file_is_marked_and_never_named_in_jarvis_s_words(
    rig: PlanRig,
) -> None:
    args = {"events": weekday_sessions(3), "series": {"name": "Pay Now"}}
    with context_trust(untrusted=True):  # the round read an attached file
        asked = await rig.run(cb.CREATE, args)
    await rig.run(cb.CREATE, args, confirmation_id=asked.pending.id)
    plan = await _plan(rig)
    assert plan.outside is True and plan.words == "your plan"


async def test_a_retry_and_a_second_batch_extend_the_plan_without_doubles(rig: PlanRig) -> None:
    rig.fake.fail_creates = {2: 400}
    args = {"events": weekday_sessions(5), "series": {"name": "CCA"}}
    await rig.approved(cb.CREATE, args)
    assert (await _plan(rig)).total == 4
    rig.fake.fail_creates = {}
    await rig.approved(cb.CREATE, args)  # the same list again: only the missing one is new
    plan = await _plan(rig)
    assert plan.total == 5 and [s.n for s in plan.sessions] == [1, 2, 3, 4, 5]
    starts = [s.start for s in plan.sessions]
    assert starts == sorted(starts)  # numbered in time order while nothing is answered
    more = {"events": weekday_sessions(2, first="2026-12-07"), "series": {"name": "cca"}}
    await rig.approved(cb.CREATE, more)
    assert (await _plan(rig)).total == 7 and len((await rig.svc.book(UID)).plans) == 1


async def test_the_limits_are_checked_before_any_card(rig: PlanRig) -> None:
    for i in range(MAX_PLANS):
        await rig.approved(
            cb.CREATE,
            {
                "events": weekday_sessions(1, first=f"2027-01-{4 + i:02d}"),
                "series": {"name": f"P{i}"},
            },
        )
    out = await rig.run(cb.CREATE, {"events": weekday_sessions(1), "series": {"name": "One more"}})
    assert out.outcome is GatewayOutcome.ERROR and "10 plans" in (out.error or "")
    full = await plan_rig(T0)
    await followed(full, 100)
    await full.approved(
        cb.CREATE,
        {"events": weekday_sessions(100, first="2027-06-07"), "series": {"name": "CCA"}},
    )
    over = await full.run(
        cb.CREATE, {"events": weekday_sessions(1, first="2028-01-03"), "series": {"name": "CCA"}}
    )
    assert over.outcome is GatewayOutcome.ERROR and "200 sessions" in (over.error or "")
    assert await full.gw.pending() == []


# ---- the check-in ------------------------------------------------------------------------------
async def test_the_check_in_is_asked_once_fifteen_minutes_after_the_session(rig: PlanRig) -> None:
    await followed(rig, 60)
    job = rig.part.clock_jobs[0]
    assert job.name == "series_checkin" and 0 < job.budget_s <= 8
    rig.clock.at = datetime(2026, 11, 16, 20, 10, tzinfo=IST)  # ten minutes after session 1
    assert await job.run([UID]) == {"asked": 0, "held": 0, "failed": 0}
    rig.clock.at = datetime(2026, 11, 16, 20, 15, tzinfo=IST)
    assert (await job.run([UID]))["asked"] == 1
    [(uid, kind, text)] = rig.told.sent
    assert (uid, kind) == (UID, "series_checkin")
    assert text == (
        "Session 1 of 60 in your CCA plan was at 19:00. Did it happen, Sir? "
        "Say 'session done' or 'session skipped'."
    )
    assert len(text) <= 300
    rig.clock.at += timedelta(minutes=5)
    assert (await job.run([UID]))["asked"] == 0 and len(rig.told.sent) == 1  # once


async def test_at_night_it_is_held_not_dropped_and_still_asked_only_once(rig: PlanRig) -> None:
    await followed(rig, 3)
    rig.told.action = "hold"  # the alert policy holds it in quiet hours
    rig.clock.at = datetime(2026, 11, 16, 23, 30, tzinfo=IST)
    job = rig.part.clock_jobs[0]
    assert await job.run([UID]) == {"asked": 0, "held": 1, "failed": 0}
    assert await job.run([UID]) == {"asked": 0, "held": 0, "failed": 0}
    [waiting] = await rig.svc.waiting(UID)  # it still waits for his answer in the morning
    assert waiting.session.n == 1


async def test_an_outside_plan_s_name_and_an_old_session_stay_out_of_the_alert(
    rig: PlanRig,
) -> None:
    args = {"events": weekday_sessions(2), "series": {"name": "Ring 98765"}}
    with context_trust(untrusted=True):
        asked = await rig.run(cb.CREATE, args)
    await rig.run(cb.CREATE, args, confirmation_id=asked.pending.id)
    rig.clock.at = datetime(2026, 11, 17, 20, 30, tzinfo=IST)  # after session 2; 1 is a day old
    job = rig.part.clock_jobs[0]
    assert (await job.run([UID]))["asked"] == 1
    [(_, _, text)] = rig.told.sent
    assert text.startswith("Session 2 of 2 in your plan was at 19:00.") and "98765" not in text
    assert len(await rig.svc.waiting(UID)) == 2  # the old one is not nagged, only still open


async def test_a_notifier_that_fails_is_counted_and_the_question_goes_out_later_once(
    rig: PlanRig,
) -> None:
    await followed(rig, 2)
    rig.clock.at = datetime(2026, 11, 16, 20, 20, tzinfo=IST)
    rig.told.fail = True
    job = rig.part.clock_jobs[0]
    assert await job.run([UID]) == {"asked": 0, "held": 0, "failed": 1}
    rig.told.fail = False  # it could not be sent, so the claim was given back
    assert (await job.run([UID]))["asked"] == 1
    assert (await job.run([UID]))["asked"] == 0 and len(rig.told.sent) == 1


@pytest.mark.parametrize("how", ["no_channel", "drop"])
async def test_a_check_in_that_reached_nobody_is_a_failure_and_is_asked_again(
    rig: PlanRig, how: str
) -> None:
    await followed(rig, 2)
    rig.clock.at = datetime(2026, 11, 16, 20, 20, tzinfo=IST)
    if how == "no_channel":
        rig.told.reached = False  # a ring, but Telegram and push both failed
    else:
        rig.told.action = "drop"  # the policy dropped it
    job = rig.part.clock_jobs[0]
    assert await job.run([UID]) == {"asked": 0, "held": 0, "failed": 1}
    rig.told.reached, rig.told.action = True, "ring"  # the claim was given back
    assert await job.run([UID]) == {"asked": 1, "held": 0, "failed": 0}
    assert await job.run([UID]) == {"asked": 0, "held": 0, "failed": 0}  # and only once
    assert len(rig.told.sent) == 2


async def test_a_cancelled_send_gives_the_claim_back(rig: PlanRig) -> None:
    import asyncio

    await followed(rig, 2)
    rig.clock.at = datetime(2026, 11, 16, 20, 20, tzinfo=IST)
    rig.told.cancel = True  # the clock's time budget ran out while it was being sent
    job = rig.part.clock_jobs[0]
    with pytest.raises(asyncio.CancelledError):
        await job.run([UID])
    rig.told.cancel = False
    assert (await job.run([UID]))["asked"] == 1


async def test_one_broken_session_or_set_up_never_stops_the_others(
    rig: PlanRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    day = [
        {
            "summary": f"T{h}",
            "start": f"2026-11-16T{h}:00:00+05:30",
            "end": f"2026-11-16T{h}:45:00+05:30",
        }
        for h in ("09", "11", "14")
    ]
    await rig.approved(cb.CREATE, {"events": day, "series": {"name": "CCA"}})
    rig.clock.at = datetime(2026, 11, 16, 20, 20, tzinfo=IST)  # all three sessions are due
    job = rig.part.clock_jobs[0]
    real = rig.svc.store.claim
    calls = {"n": 0}

    async def flaky(uid: str, key: str, at: datetime) -> bool:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("the store blinked")
        return await real(uid, key, at)

    monkeypatch.setattr(rig.svc.store, "claim", flaky)

    def broken() -> object:
        raise RuntimeError("the phrasebook is broken")

    monkeypatch.setattr(job, "_on_run", broken)
    assert await job.run([UID]) == {"asked": 2, "held": 0, "failed": 1}


async def test_a_claim_that_cannot_be_given_back_is_logged_not_raised(
    rig: PlanRig, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    await followed(rig, 1)
    rig.clock.at = datetime(2026, 11, 16, 20, 20, tzinfo=IST)
    rig.told.fail = True

    async def down(uid: str, key: str) -> None:
        raise RuntimeError("the store is down")

    monkeypatch.setattr(rig.svc.store, "release", down)
    job = rig.part.clock_jobs[0]
    assert await job.run([UID]) == {"asked": 0, "held": 0, "failed": 1}
    assert any("not given back" in r.getMessage() for r in caplog.records)


async def test_the_job_does_nothing_when_plans_are_switched_off() -> None:
    from jarvis.config import Settings

    off = await plan_rig(T0, settings=Settings(_env_file=None, env="dev", series_enabled=False))
    assert off.part.clock_jobs == () and "plans are off" in off.part.ready
    names = {t.name for t in off.part.tools}
    assert cb.CREATE in names and "series_checkin" not in names  # batches still work


async def test_on_a_server_without_google_the_part_offers_no_tool_and_says_why() -> None:
    from jarvis.config import Settings

    # outside dev, with no Google link set up (no client, or no key to keep its tokens)
    off = await plan_rig(T0, settings=Settings(_env_file=None, env="prod"))
    assert off.part.tools == () and off.part.clock_jobs == ()
    assert off.part.ready == "off: Google is not set up on this server"
    assert off.part.services["series"] is None and off.part.services["ensure"]() is False
    assert [p.id for p in off.part.privacy] == ["series"]  # what was kept can be seen and deleted


def test_the_question_is_a_fixed_template() -> None:
    assert checkin.ASK_AFTER == timedelta(minutes=15)
    assert "{" not in checkin.QUESTION.format(n=7, total=60, plan="your CCA plan", at="19:00")


# ---- done --------------------------------------------------------------------------------------
async def test_done_marks_the_session_that_is_waiting(rig: PlanRig) -> None:
    await followed(rig, 60)
    rig.clock.at = AFTER_7
    out = await rig.run("series_checkin", {"answer": "done"})
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    assert out.result["message"] == "Session 7 of 60 in your CCA plan is marked done, Sir."
    plan = await _plan(rig)
    assert plan.session(7).state == "done" and plan.session(7).answered_at == AFTER_7
    assert [w.session.n for w in await rig.svc.waiting(UID)] == [6, 5, 4, 3, 2, 1]
    named = await rig.run("series_checkin", {"answer": "done", "series": "CCA", "session": "3"})
    assert named.result["session"] == 3 and (await _plan(rig)).session(3).state == "done"


async def test_a_spoken_answer_runs_without_a_card(rig: PlanRig) -> None:
    await followed(rig, 5)
    rig.clock.at = datetime(2026, 11, 16, 20, 20, tzinfo=IST)
    with context_trust(untrusted=False, spoken=True, owner_text="session done"):
        out = await rig.run("series_checkin", {"answer": "done"})
    assert out.outcome is GatewayOutcome.EXECUTED and (await _plan(rig)).session(1).state == "done"


async def test_nothing_waiting_and_bad_answers_are_said_plainly(rig: PlanRig) -> None:
    out = await rig.run("series_checkin", {"answer": "done"})
    assert out.outcome is GatewayOutcome.EXECUTED and out.result["refused"] is True
    assert out.result["message"] == "No session is waiting for an answer, Sir."
    bad = await rig.run("series_checkin", {"answer": "maybe"})
    assert bad.outcome is GatewayOutcome.ERROR and "done or skipped" in (bad.error or "")
    await followed(rig, 3)
    gone = await rig.run("series_checkin", {"answer": "done", "session": 9})
    assert gone.result["refused"] is True and "no session 9" in gone.result["message"].lower()


# ---- skipped: one card, nothing moves before the approval --------------------------------------
async def test_skipped_marks_it_and_puts_one_re_plan_card_in_approvals(rig: PlanRig) -> None:
    await followed(rig, 60)
    rig.clock.at = AFTER_7
    before = {e["id"]: e["start"]["dateTime"] for e in rig.fake.live()}
    out = await rig.run("series_checkin", {"answer": "skipped"})
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    assert (await _plan(rig)).session(7).state == "skipped"
    [card] = await rig.gw.pending()
    assert card.tool == "series_reschedule" and card.tool_risk is ActionRisk.REVERSIBLE
    assert card.bulk_ok is False and card.scope == f"{UID}:sess_1"
    lines = card.summary.splitlines()
    assert lines[0] == (
        "Move 54 sessions of your CCA plan to their next free slots (session 7 was skipped)."
    )
    assert (
        lines[1]
        == "60 sessions before, 60 after: none is dropped. The plan now ends on 8 Feb 2027."
    )
    moves = [x for x in lines if "→" in x]
    assert len(moves) == 54
    assert moves[0] == "7. Tue 24 Nov 19:00 → Wed 25 Nov 19:00"
    assert moves[-1] == "60. Fri 5 Feb 19:00 → Mon 8 Feb 19:00"
    assert "54 sessions" in out.result["message"] and "approval" in out.result["message"]
    assert rig.fake.sent("PATCH") == []  # nothing moves until he approves
    assert {e["id"]: e["start"]["dateTime"] for e in rig.fake.live()} == before


async def test_approving_moves_fifty_four_events_and_the_plan_still_has_sixty(rig: PlanRig) -> None:
    made = await followed(rig, 60)
    rig.clock.at = AFTER_7
    await rig.run("series_checkin", {"answer": "skipped"})
    [card] = await rig.gw.pending()
    out = await rig.approve(card.id)
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    res = out.result
    assert (res["moved"], res["failed"], res["sessions"]) == (54, 0, 60)
    assert res["message"] == (
        "Moved 54 sessions of your CCA plan, Sir. It still has 60 and now ends on 8 Feb 2027."
    )
    patches = rig.fake.sent("PATCH")
    assert len(patches) == 54 and all(p.url.params["sendUpdates"] == "none" for p in patches)
    plan = await _plan(rig)
    assert plan.total == 60 and [s.n for s in plan.sessions] == list(range(1, 61))
    assert plan.session(7).state == "moved"
    assert plan.session(7).start == datetime(2026, 11, 25, 19, 0, tzinfo=IST)
    assert plan.session(60).start == datetime(2027, 2, 8, 19, 0, tzinfo=IST)
    assert {s.state for s in plan.sessions[:6]} == {"planned"}
    by_id = {e["id"]: e for e in rig.fake.live()}
    assert len(by_id) == 60
    seven = by_id[plan.session(7).event_id]
    assert seven["start"]["dateTime"] == "2026-11-25T19:00:00+05:30"
    assert seven["summary"] == "CCA - Topic 7"
    # JARVIS's own move is not "the owner changed it": one Undo still removes the whole batch
    assert not any(cb.changed_by_owner(e) for e in by_id.values())
    undone = await rig.approved(cb.UNDO, {"batch": made["batch"]})
    assert undone.result["removed"] == 60 and (await rig.svc.book(UID)).plans == []


async def test_a_busy_evening_is_skipped_over(rig: PlanRig) -> None:
    await followed(rig, 60)
    rig.fake.busy = []  # the calendar itself is the source: an event of his own that evening
    rig.fake.events["dinner"] = {
        "id": "dinner",
        "status": "confirmed",
        "summary": "Dinner",
        "start": {"dateTime": "2026-11-26T19:30:00+05:30"},
        "end": {"dateTime": "2026-11-26T21:00:00+05:30"},
    }
    rig.clock.at = AFTER_7
    await rig.run("series_checkin", {"answer": "skipped"})
    [card] = await rig.gw.pending()
    assert "The plan now ends on 9 Feb 2027." in card.summary
    assert "8. Wed 25 Nov 19:00 → Fri 27 Nov 19:00" in card.summary  # Thursday is taken
    await rig.approve(card.id)
    starts = {e["start"]["dateTime"] for e in rig.fake.live() if e["id"] != "dinner"}
    assert "2026-11-26T19:00:00+05:30" not in starts and len(starts) == 60


async def test_the_card_is_withdrawn_when_the_calendar_changed_since(rig: PlanRig) -> None:
    await followed(rig, 10)
    rig.clock.at = AFTER_7
    await rig.run("series_checkin", {"answer": "skipped"})
    [card] = await rig.gw.pending()
    rig.fake.events["late"] = {
        "id": "late",
        "status": "confirmed",
        "summary": "Call",
        "start": {"dateTime": "2026-11-25T19:00:00+05:30"},
        "end": {"dateTime": "2026-11-25T19:30:00+05:30"},
    }
    out = await rig.approve(card.id)  # the card no longer reads as he saw it
    assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION and out.pending.id != card.id
    assert rig.fake.sent("PATCH") == []


async def test_a_re_plan_that_would_lose_a_session_is_refused_in_code(
    rig: PlanRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    from jarvis.series import replan

    await followed(rig, 60)
    rig.clock.at = AFTER_7
    real = replan.build

    def dropping(*a, **kw):  # noqa: ANN002, ANN003, ANN202 - the last session is lost
        return real(*a, **kw)[:-1]

    monkeypatch.setattr(replan, "build", dropping)
    out = await rig.run("series_checkin", {"answer": "skipped"})
    assert await rig.gw.pending() == [] and rig.fake.sent("PATCH") == []
    assert out.result["message"] == (
        "Session 7 of 60 in your CCA plan is marked skipped, Sir. This re-plan would lose a "
        "session, Sir (54 must move, 53 would), so nothing was moved."
    )
    direct = await rig.run("series_reschedule", {"series": "CCA", "session": 7})
    assert direct.outcome is GatewayOutcome.ERROR and "lose a session" in (direct.error or "")


async def test_skipped_with_google_not_linked_is_recorded_and_says_why(rig: PlanRig) -> None:
    await followed(rig, 10)
    rig.clock.at = AFTER_7
    rig.state["google"] = None  # the link was removed after the plan was made
    out = await rig.run("series_checkin", {"answer": "skipped"})
    assert out.result["marked"] == "skipped" and await rig.gw.pending() == []
    assert out.result["message"] == (
        "Session 7 of 10 in your CCA plan is marked skipped, Sir. Google is not linked, Sir, "
        "so I can't look at your calendar."
    )


@pytest.mark.parametrize(
    ("error", "said"),
    [
        (
            "could not look it up first, so nothing was proposed or done "
            "(GoogleNotConnected: Google is not connected. Connect it in the panel.)",
            "Google is not linked, Sir, so I can't look at your calendar.",
        ),
        ("could not look it up first (GoogleAPIError: 500 Topic: reply to x@example.com)", ""),
        ("blocked by policy", ""),
        (None, ""),
    ],
)
def test_only_jarvis_s_own_reasons_are_repeated(error: str | None, said: str) -> None:
    from jarvis.series.tools import own_reason

    assert own_reason(error) == said


async def test_the_model_asking_to_move_sessions_is_always_a_card(rig: PlanRig) -> None:
    allow = await plan_rig(T0, rules=[PolicyRule(tool_pattern="series_*", effect=Effect.ALLOW)])
    await followed(allow, 10)
    allow.clock.at = AFTER_7
    with context_trust(untrusted=False):
        out = await allow.run("series_reschedule", {"series": "CCA", "session": 7})
    assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION and allow.fake.sent("PATCH") == []


async def test_never_on_the_plans_row_stops_everything(rig: PlanRig) -> None:
    never = await plan_rig(
        T0,
        rules=[PolicyRule(tool_pattern="series_*", effect=Effect.DENY, reason="switched off")],
    )
    await followed(never, 3)
    never.clock.at = datetime(2026, 11, 16, 20, 20, tzinfo=IST)
    out = await never.run("series_checkin", {"answer": "skipped"})
    assert (
        out.outcome is GatewayOutcome.DENIED and (await _plan(never)).session(1).state == "planned"
    )


# ---- the list ----------------------------------------------------------------------------------
async def test_the_list_gives_counts_and_what_waits(rig: PlanRig) -> None:
    await followed(rig, 60)
    rig.clock.at = AFTER_7
    await rig.run("series_checkin", {"answer": "done", "session": 1})
    out = await rig.run("series_list", {})
    assert out.outcome is GatewayOutcome.EXECUTED and out.trusted is True  # his own list
    [p] = out.result["plans"]
    assert (p["name"], p["sessions"], p["done"], p["skipped"]) == ("CCA", 60, 1, 0)
    assert p["waiting"] == [7, 6, 5, 4, 3, 2] and p["next"]["n"] == 8
    assert "Topic" not in json.dumps(out.result)  # titles stay in the calendar


# ---- No-AI phrases -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("said", "tool", "args"),
    [
        ("session done", "series_checkin", {"answer": "done"}),
        ("Session done.", "series_checkin", {"answer": "done"}),
        ("JARVIS, session 7 is done", "series_checkin", {"answer": "done", "session": "7"}),
        ("the session happened", "series_checkin", {"answer": "done"}),
        ("I did the session", "series_checkin", {"answer": "done"}),
        ("session skipped", "series_checkin", {"answer": "skipped"}),
        ("session 12 skipped", "series_checkin", {"answer": "skipped", "session": "12"}),
        ("I skipped the session", "series_checkin", {"answer": "skipped"}),
        ("the session didn't happen", "series_checkin", {"answer": "skipped"}),
        ("skip session 3", "series_checkin", {"answer": "skipped", "session": "3"}),
        ("show my plans", "series_list", {}),
        ("how is my study plan going?", "series_list", {}),
        ("re-plan my sessions", "series_reschedule", {}),
        ("move my skipped session", "series_reschedule", {}),
    ],
)
def test_the_no_ai_phrases(said: str, tool: str, args: dict[str, str]) -> None:
    got = route(said, AFTER_7)
    assert got is not None and len(got.calls) == 1
    assert (got.calls[0].tool, got.calls[0].arguments) == (tool, args)


@pytest.mark.parametrize(
    "said",
    [
        "is the session done yet in the other room?",
        "what did we cover in the session?",
        "remind me about the session at 7",
        "done",
        "plan my week",
    ],
)
def test_other_words_are_left_to_the_other_routers(said: str) -> None:
    assert route(said, AFTER_7) is None


async def test_an_answer_works_with_no_model_at_all(rig: PlanRig) -> None:
    from jarvis.offline.no_ai import run_no_ai

    await followed(rig, 60)
    rig.clock.at = AFTER_7
    done = await run_no_ai(rig.gw, "session 6 done", AFTER_7, scope=f"{UID}:s", extra=(route,))
    assert done.reply == "Session 6 of 60 in your CCA plan is marked done, Sir."
    skipped = await run_no_ai(rig.gw, "session skipped", AFTER_7, scope=f"{UID}:s", extra=(route,))
    assert "marked skipped" in skipped.reply and "approval" in skipped.reply
    assert len(await rig.gw.pending()) == 1 and rig.fake.sent("PATCH") == []


# ---- the brief's line, privacy, housekeeping ----------------------------------------------------
async def test_the_morning_brief_asks_again_in_one_line_never_with_a_title(rig: PlanRig) -> None:
    from jarvis.helpers.ports import BriefContributor

    line_of: BriefContributor = rig.part.services["brief"]
    day = AFTER_7.date()
    assert await line_of.lines(UID, IST, day) == []  # nothing followed: no line
    await followed(rig, 60)
    assert await line_of.lines(UID, IST, day) == []  # nothing has ended yet
    rig.clock.at = AFTER_7  # seven sessions ended, none answered
    assert await line_of.lines(UID, IST, day) == [
        "7 planned sessions have no check-in: say 'session done' or 'session skipped'."
    ]
    for n in range(1, 7):
        await rig.run("series_checkin", {"answer": "done", "session": n})
    [one] = await line_of.lines(UID, IST, day)
    assert one.startswith("1 planned session has no check-in") and "Topic" not in one
    assert line_of.name == "plans"


async def test_the_privacy_row_shows_exports_and_deletes_the_plans_only(rig: PlanRig) -> None:
    [row] = rig.part.privacy
    empty = await row.describe(UID)
    assert (empty.id, empty.section, empty.count, empty.delete) == ("series", "Helpers", 0, "none")
    await followed(rig, 3)
    rig.clock.at = datetime(2026, 11, 16, 20, 20, tzinfo=IST)
    await rig.part.clock_jobs[0].run([UID])  # one check-in question went out
    seen = await row.describe(UID)
    assert (seen.count, seen.unit, seen.delete, seen.export) == (1, "plans", "confirm", True)
    assert seen.rev != empty.rev and "stay in your Google Calendar" in seen.note
    out = await row.export(UID)
    [plan] = out["plans"]
    assert plan["name"] == "CCA" and len(plan["sessions"]) == 3
    assert "Google Calendar" in out["never_kept"]
    assert await row.delete(UID) == 1
    assert (await rig.svc.book(UID)).plans == [] and (await row.describe(UID)).count == 0
    left = [k for k in rig.docs._data if "series" in k]  # noqa: SLF001 - the fake's own store
    assert left == []  # the plan and the record of what was asked: both gone
    assert len(rig.fake.live()) == 3  # the calendar is his: untouched


async def test_old_check_in_records_are_swept_after_sixty_days(rig: PlanRig) -> None:
    await followed(rig, 2)
    rig.clock.at = datetime(2026, 11, 16, 20, 20, tzinfo=IST)
    job = rig.part.clock_jobs[0]
    assert (await job.run([UID]))["asked"] == 1
    store = rig.svc.store
    assert await store.sweep(UID, rig.clock.at + timedelta(days=59)) == 0
    assert await store.sweep(UID, rig.clock.at + timedelta(days=61)) == 1
    assert await store.sweep(UID, rig.clock.at + timedelta(days=61)) == 0

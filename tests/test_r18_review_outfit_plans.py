# tests/test_r18_review_outfit_plans.py -- the owner's decision of 27 Nov 2026, made in R18 (the
# next app release): outfit plans are kept 90 days after their day, as R13's plan says
# (docs/plans/r13-wardrobe.md, `wardrobe_plans/{uid}`: "90 days after the event") and as the
# Privacy row already told him; the code dropped them after 14. The caps grow so the 90 days hold:
# two plans a day over the whole window, his own always with room for one a day whatever the
# calendar made, and the sealed document still well under Firestore's 1 MiB.
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from jarvis.wardrobe.styling.plans import (
    AHEAD_DAYS,
    BACK_DAYS,
    KEEP_DAYS,
    MAX_CAL_PLANS,
    MAX_PLANS,
    Plan,
    PlanPick,
    PlanRefused,
    StylingDoc,
    in_range,
)

TODAY = date(2026, 11, 27)
NOW = datetime(2026, 11, 27, 6, 30, tzinfo=UTC)
WINDOW = KEEP_DAYS + 1 + AHEAD_DAYS  # every day a kept plan can be on
FIRESTORE_DOC_MAX = 1_048_576


def _plan(n: int, day: date, **kw: object) -> Plan:
    return Plan(id=f"op_{n:08x}", day=day, **({"code": "office"} | kw))  # type: ignore[arg-type]


def test_review_a_plan_is_kept_90_days_after_its_day() -> None:
    assert KEEP_DAYS == 90
    kept = _plan(1, TODAY - timedelta(days=90))
    gone = _plan(2, TODAY - timedelta(days=91))
    fortnight = _plan(3, TODAY - timedelta(days=15))  # dropped before the owner's decision
    doc = StylingDoc(plans=(gone, kept, fortnight)).pruned(TODAY)
    assert [p.id for p in doc.plans] == [kept.id, fortnight.id]


def test_review_a_cancelled_calendar_draft_still_goes_once_its_day_is_past() -> None:
    draft = _plan(1, TODAY - timedelta(days=1), manual=False, cancelled=True)
    his = _plan(2, TODAY - timedelta(days=1), cancelled=True)  # his own cancelled plan: kept
    assert [p.id for p in StylingDoc(plans=(draft, his)).pruned(TODAY).plans] == [his.id]


def test_review_a_new_plan_s_day_is_still_14_back_to_30_ahead() -> None:
    assert (BACK_DAYS, AHEAD_DAYS) == (14, 30)
    assert in_range(TODAY - timedelta(days=14), TODAY)
    assert not in_range(TODAY - timedelta(days=15), TODAY)


def test_review_the_caps_let_the_90_days_hold() -> None:
    assert MAX_PLANS >= 2 * WINDOW  # two plans a day over every day a plan is kept
    assert MAX_PLANS - MAX_CAL_PLANS >= WINDOW  # his own: one a day, whatever the calendar made
    assert MAX_CAL_PLANS >= KEEP_DAYS  # the calendar: one plan a day for the days it is kept
    doc = StylingDoc(plans=tuple(_plan(n, TODAY - timedelta(days=n % WINDOW)) for n in range(242)))
    assert len(doc.put(_plan(9999, TODAY)).plans) == 243


def test_review_a_full_document_still_fits_one_firestore_document() -> None:
    def big(n: int) -> Plan:
        piece = lambda i: f"wi_{(n * 100 + i):012x}"  # noqa: E731
        return _plan(
            n,
            TODAY,
            event=f"{n:016x}",
            starts=NOW,
            ends=NOW,
            code="c" * 24,
            occasion="o" * 24,
            picks=tuple(
                PlanPick(slot=f"s{i:011d}", pieces=(piece(i), piece(50 + i))) for i in range(14)
            ),
            shared=tuple(piece(80 + i) for i in range(12)),
            needs=tuple("n" * 12 for _ in range(14)),
            updated="u" * 40,
            created_at=NOW,
            updated_at=NOW,
        )

    full = StylingDoc(plans=tuple(big(n) for n in range(MAX_PLANS)))
    sealed = len(full.model_dump_json().encode()) * 4 // 3 + 4_096  # base64 and the envelope
    assert sealed < FIRESTORE_DOC_MAX * 0.8


def test_review_the_cap_s_words_name_the_cap() -> None:
    doc = StylingDoc(plans=tuple(_plan(n, TODAY) for n in range(MAX_PLANS)))
    with pytest.raises(PlanRefused) as refused:
        doc.put(_plan(99999, TODAY))
    assert f"You have {MAX_PLANS} plans" in str(refused.value)


def test_review_kept_past_calendar_plans_never_stop_the_calendar_and_a_flood_stays_capped() -> None:
    # With 90 days kept, the calendar's old plans must not use up its room (20 at once, as before),
    # and invites can still make at most 20 plans from today on
    from jarvis.wardrobe.styling.calendar import _room
    from jarvis.wardrobe.styling.plans import MAX_CAL_AHEAD

    past = tuple(_plan(n, TODAY - timedelta(days=1 + n % 80), manual=False) for n in range(60))
    doc = StylingDoc(plans=past)
    assert doc.made() == 60 and doc.made(TODAY) == 0
    assert _room(doc, "f" * 16, set(), TODAY)  # 60 kept calendar plans: room for a new one
    ahead = tuple(_plan(100 + n, TODAY + timedelta(days=1), manual=False) for n in range(20))
    flooded = StylingDoc(plans=(*past, *ahead))
    assert MAX_CAL_AHEAD == 20 and not _room(flooded, "e" * 16, set(), TODAY)
    full = StylingDoc(
        plans=tuple(_plan(n, TODAY - timedelta(days=1), manual=False) for n in range(MAX_CAL_PLANS))
    )
    assert not _room(full, "d" * 16, set(), TODAY)  # 100 kept in all

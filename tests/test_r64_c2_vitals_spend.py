# tests/test_r64_c2_vitals_spend.py — R6.4 D9 follow-up (row 393, builder C2): the Vitals "AI
# spend" row counts the upper estimate the monthly limit already counts for replies with no known
# price (so its amber / red match the gate), and its words, the brief's line and the spoken
# briefing say so: "₹X of ₹Y this month, plus up to ₹Z for N replies with no known price".
from __future__ import annotations

from r51c_fakes import board
from vitals_fakes import UID, FakeBilling, Rig, usage_view

from jarvis.health.briefing import compose_briefing
from jarvis.vitals.auto import spend_text, unpriced_words
from jarvis.vitals.models import Spend


def test_the_unpriced_words() -> None:
    assert unpriced_words(0, 0.0) == ""
    assert unpriced_words(1, 4.5) == ", plus up to ₹4.50 for 1 reply with no known price"
    assert unpriced_words(3, 30.0) == ", plus up to ₹30 for 3 replies with no known price"
    assert unpriced_words(2, 0.0) == ", plus 2 replies with no known price"


def test_the_spend_text_says_the_unpriced_replies() -> None:
    assert spend_text(120.0, 500) == "₹120 of ₹500 this month"  # none: unchanged
    assert spend_text(120.0, 500, 3, 30.0) == (
        "₹120 of ₹500 this month, plus up to ₹30 for 3 replies with no known price"
    )
    assert spend_text(42.5, None, 1, 4.5) == (
        "₹42.50 this month, plus up to ₹4.50 for 1 reply with no known price, no limit set"
    )


def _view(used: float, limit: int | None, calls: int, inr: float) -> FakeBilling:
    v = usage_view(used, limit).model_copy(update={"unpriced_calls": calls, "unpriced_inr": inr})
    return FakeBilling(v)


async def test_the_spend_row_counts_the_unpriced_estimate_as_the_limit_does() -> None:
    rig = Rig(billing=_view(300.0, 500, 4, 120.0))  # ₹300 priced + up to ₹120 = 84 %
    b = await rig.svc.board(UID)
    row = next(v for v in b.items if v.provider.id == "ai_spend")
    assert row.provider.used == 420.0 and row.status == "amber" and row.percent == 84.0
    assert row.provider.note == "Includes up to ₹120 for 4 replies with no known price."
    assert b.spend is not None and b.spend.used_inr == 300.0
    assert (b.spend.unpriced_calls, b.spend.unpriced_inr) == (4, 120.0)
    assert b.spend.text == (
        "₹300 of ₹500 this month, plus up to ₹120 for 4 replies with no known price"
    )
    rig.billing.view = rig.billing.view.model_copy(update={"unpriced_inr": 200.0})
    red = await rig.svc.board(UID)
    assert next(v for v in red.items if v.provider.id == "ai_spend").status == "red"


async def test_with_no_unpriced_replies_the_spend_row_is_unchanged() -> None:
    rig = Rig(billing=FakeBilling(usage_view(120, 500)))
    b = await rig.svc.board(UID)
    row = next(v for v in b.items if v.provider.id == "ai_spend")
    assert (row.provider.used, row.provider.note, row.status) == (120, "", "ok")
    assert b.spend is not None and b.spend.text == "₹120 of ₹500 this month"


def test_the_spoken_briefing_says_the_unpriced_replies_and_counts_them() -> None:
    b = board(used=120, limit=500)
    spend = Spend(used_inr=120, limit_inr=500, text="", unpriced_calls=3, unpriced_inr=30.0)
    said = compose_briefing(None, b.model_copy(update={"spend": spend})).spend
    assert said == (
        "AI spend is ₹120 of ₹500 this month, plus up to ₹30 for 3 replies with no known price "
        "(30 percent)."
    )
    assert compose_briefing(None, board(used=120, limit=500)).spend == (
        "AI spend is ₹120 of ₹500 this month (24 percent)."
    )

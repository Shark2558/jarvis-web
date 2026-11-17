# tests/test_r131_c_cap.py -- R13.1 Part C: the ₹ figures and the atomic monthly cap
# (docs/plans/r13-1-try-on.md D13.2, D15; BRIEF-C "The estimate", "The cap"). Every ₹ includes GST;
# the cap's reserve reads and writes in ONE transaction. Fixed clocks only. Written first, run red.
from __future__ import annotations

import asyncio
import math
from datetime import timedelta

import pytest
from r131_fake_gemini import FakeGoogle, FakeTokens, project_of
from r131_fake_tryon import ScriptedTryOn
from r131_fakes import NOW, UID, FixedClock, ist
from r131_fakes_c import YieldingDocs

from jarvis.llm.tryon import TryOnUsage
from jarvis.storage.docs import MemoryDocs, Set
from jarvis.wardrobe.seeme import cap as capmod
from jarvis.wardrobe.seeme import estimate as money
from jarvis.wardrobe.seeme.cap import CapRefused, Done, TryonCap

PREFIX = "jarvis_"
CAP = 300


def _gemini():  # type: ignore[no-untyped-def]
    from jarvis.llm.tryon_gemini import GeminiTryOn

    return GeminiTryOn(model="gemini-3.1-flash-image", location="us", tokens=FakeTokens(),
                       project=project_of(), http=FakeGoogle().client())  # fmt: skip


def _cap(docs: MemoryDocs | None = None, clock: FixedClock | None = None) -> TryonCap:
    return TryonCap(docs or MemoryDocs(), PREFIX, tz="Asia/Kolkata", now=clock or FixedClock(NOW))


def rid(n: int) -> str:
    return f"tq_{n:016x}"


# ---- the ₹ figures (D13.2) -----------------------------------------------------------------------
def test_the_typical_and_the_hold_at_the_fallback_rate_with_gst() -> None:
    got = money.figures(_gemini(), garments=2, rate=95.24, tax_pct=18)
    assert got.typical_inr == 8.9  # ≈ ₹8.9 (the image, the inputs, about 1,000 thinking tokens)
    assert got.hold_inr == 11.22  # the worst the request allows: 8,192 tokens, three garments
    three = money.figures(_gemini(), garments=3, rate=95.24, tax_pct=18)
    assert three.hold_inr == 11.22 and three.typical_inr >= got.typical_inr


def test_the_settle_from_usage_is_852_for_a_garment_and_one_piece() -> None:
    usage = TryOnUsage(input_tokens=3510, image_tokens=1120, text_tokens=0)
    assert money.settled_inr(_gemini(), usage, rate=95.24, tax_pct=18) == 8.52
    unpriced = ScriptedTryOn(model="fake-try-on-1")
    assert money.settled_inr(unpriced, usage, rate=95.24, tax_pct=18) is None  # at the hold


def test_rounding_up_to_10_paise_and_the_words() -> None:
    assert money.up10(8.895) == 8.9 and money.up10(8.9) == 8.9 and money.up10(8.901) == 9.0
    assert money.rupees(300) == "₹300" and money.rupees(54.25) == "₹54.3"
    assert money.rupees(0) == "₹0" and money.rupees(291.6) == "₹291.6"
    assert money.about(8.9) == "About ₹9 with GST" and money.about(8.52) == "About ₹9 with GST"
    assert money.about(0.4) == "About ₹0.4 with GST"


def test_a_moved_rate_moves_the_typical() -> None:
    moved = money.figures(_gemini(), garments=2, rate=96.10, tax_pct=18)
    assert moved.typical_inr == 9.0 > 8.9 + 0.01  # the press then answers price_changed


@pytest.mark.parametrize("bad", [math.nan, math.inf, -1.0])
def test_no_money_from_a_rate_that_isnt_one(bad: float) -> None:
    with pytest.raises(ValueError):
        money.figures(_gemini(), garments=2, rate=bad, tax_pct=18)


# ---- the cap: reserve, settle, release (D15) ----------------------------------------------------
async def test_a_reserve_holds_and_a_settle_moves_the_hold_into_spend() -> None:
    cap = _cap()
    hold = await cap.reserve(UID, rid(1), 11.22, CAP)
    assert not isinstance(hold, Done)
    month = await cap.month(UID)
    assert (month.spent_inr, month.held_inr, list(month.holds)) == (0.0, 11.22, [rid(1)])
    await cap.settle(hold, 8.52, outcome={"picture": "tp_000000000001"}, picture=True)
    month = await cap.month(UID)
    assert (month.spent_inr, month.held_inr, month.holds, month.pictures) == (8.52, 0.0, {}, 1)
    assert month.done == {rid(1): {"picture": "tp_000000000001"}}


async def test_a_release_gives_the_hold_back_and_a_repeat_is_a_no_op() -> None:
    cap = _cap()
    other = await cap.reserve(UID, rid(1), 11.22, CAP)
    await cap.settle(other, 8.52, outcome={"picture": "tp_000000000001"}, picture=True)
    hold = await cap.reserve(UID, rid(2), 11.22, CAP)
    await cap.release(hold, outcome={"error": "provider_unavailable"})
    await cap.release(hold, outcome={"error": "provider_unavailable"})  # never twice
    month = await cap.month(UID)
    assert (month.spent_inr, month.held_inr) == (8.52, 0.0)
    assert month.done[rid(2)] == {"error": "provider_unavailable"}


async def test_a_failed_release_can_be_tried_again() -> None:
    docs = MemoryDocs()
    cap = _cap(docs)
    hold = await cap.reserve(UID, rid(1), 11.22, CAP)
    real = docs.transaction

    async def broken(fn):  # type: ignore[no-untyped-def]
        raise RuntimeError("store down")

    docs.transaction = broken  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await cap.release(hold, outcome={"error": "x"})
    assert hold.released is False  # retryable
    docs.transaction = real  # type: ignore[method-assign]
    await cap.release(hold, outcome={"error": "x"})
    assert (await cap.month(UID)).held_inr == 0.0


async def test_the_34th_picture_fits_and_the_35th_is_refused() -> None:
    clock = FixedClock(NOW)
    cap = _cap(clock=clock)
    for n in range(1, 35):
        hold = await cap.reserve(UID, rid(n), 11.22, CAP)
        assert not isinstance(hold, Done), n
        await cap.settle(hold, 8.52, outcome={"picture": f"tp_{n:012x}"}, picture=True)
        clock.set(clock() + timedelta(minutes=11))  # past the busy window
    month = await cap.month(UID)
    assert month.pictures == 34 and month.spent_inr == pytest.approx(289.68)
    with pytest.raises(CapRefused) as err:
        await cap.reserve(UID, rid(35), 11.22, CAP)
    assert err.value.code == "cap_reached" and err.value.status == 402
    assert err.value.words == (
        "This month's try-on limit of ₹300 is used: ₹289.7 spent. It resets on 1 Dec, or raise "
        "it in Try-on settings."
    )
    assert (await cap.month(UID)).holds == {}  # nothing written


async def test_ten_presses_at_once_reserve_exactly_one_and_nine_are_busy() -> None:
    cap = _cap(YieldingDocs())
    got = await asyncio.gather(
        *(cap.reserve(UID, rid(n), 11.22, CAP) for n in range(10)), return_exceptions=True
    )
    holds = [g for g in got if isinstance(g, capmod.CapHold)]
    busy = [g for g in got if isinstance(g, CapRefused) and g.code == "busy"]
    assert len(holds) == 1 and len(busy) == 9
    assert (await cap.month(UID)).held_inr == 11.22


async def test_a_hold_older_than_ten_minutes_is_not_busy_but_still_counts() -> None:
    clock = FixedClock(NOW)
    cap = _cap(clock=clock)
    await cap.reserve(UID, rid(1), 11.22, CAP)
    with pytest.raises(CapRefused) as err:
        await cap.reserve(UID, rid(2), 11.22, CAP)
    assert err.value.code == "busy" and "being made" in err.value.words
    clock.set(NOW + timedelta(minutes=10, seconds=1))
    await cap.reserve(UID, rid(2), 11.22, CAP)
    assert (await cap.month(UID)).held_inr == 22.44


async def test_a_repeated_request_id_answers_its_outcome() -> None:
    cap = _cap()
    hold = await cap.reserve(UID, rid(1), 11.22, CAP)
    with pytest.raises(CapRefused) as err:
        await cap.reserve(UID, rid(1), 11.22, CAP)  # still being made
    assert err.value.code == "busy"
    await cap.settle(hold, 8.52, outcome={"picture": "tp_000000000001"}, picture=True)
    again = await cap.reserve(UID, rid(1), 11.22, CAP)
    assert again == Done({"picture": "tp_000000000001"})
    assert (await cap.month(UID)).spent_inr == 8.52  # charged once


async def test_done_keeps_the_last_fifty() -> None:
    clock = FixedClock(NOW)
    cap = _cap(clock=clock)
    for n in range(55):
        hold = await cap.reserve(UID, rid(n), 1.0, 2000)
        await cap.release(hold, outcome={"error": "x"})
    done = (await cap.month(UID)).done
    assert len(done) == 50 and rid(0) not in done and rid(54) in done


@pytest.mark.parametrize(
    "bad",
    [{"spent_inr": "lots"}, {"spent_inr": -1.0}, {"held_inr": float("nan")},
     {"holds": {"tq_0000000000000001": {"inr": "x", "at": "2026-11-17T03:30:00+00:00"}}},
     {"pictures": -2}, {"holds": []}],
)  # fmt: skip
async def test_a_counter_that_isnt_a_number_refuses_never_reads_as_zero(bad: dict) -> None:
    docs = MemoryDocs()
    cap = _cap(docs)
    doc = {"owner": UID, "month": "2026-11", "spent_inr": 10.0, "held_inr": 0.0, "holds": {},
           "done": {}, "pictures": 1, "blocked": 0, **bad}  # fmt: skip
    await docs.write([Set(f"{PREFIX}tryon_spend/{UID}_2026-11", doc)])
    with pytest.raises(CapRefused) as err:
        await cap.reserve(UID, rid(1), 11.22, CAP)
    assert err.value.code == "cap_unreadable" and "nothing was sent" in err.value.words
    with pytest.raises(CapRefused):
        await cap.month(UID)


async def test_a_cap_of_zero_is_off() -> None:
    with pytest.raises(CapRefused) as err:
        await _cap().reserve(UID, rid(1), 11.22, 0)
    assert err.value.code == "cap_reached" and "₹0" in err.value.words


async def test_his_month_is_his_ist_month_at_2330_and_0030() -> None:
    late = FixedClock(ist(2026, 11, 30, 23, 30))
    cap = _cap(clock=late)
    hold = await cap.reserve(UID, rid(1), 11.22, CAP)
    assert hold.month == "2026-11"
    late.set(ist(2026, 12, 1, 0, 30))  # settled in December: still November's hold
    await cap.settle(hold, 8.52, outcome={"picture": "tp_000000000001"}, picture=True)
    assert cap.month_of(late()) == "2026-12"
    nov = await cap.month(UID, month="2026-11")
    assert nov.spent_inr == 8.52 and nov.held_inr == 0.0
    assert (await cap.month(UID)).spent_inr == 0.0  # December starts empty
    words = capmod.reached_words(300, 291.6, ist(2026, 12, 31, 23, 30), "Asia/Kolkata")
    assert words.endswith("It resets on 1 Jan, or raise it in Try-on settings.")


async def test_a_document_carries_only_numbers_and_a_plain_owner() -> None:
    docs = MemoryDocs()
    cap = _cap(docs)
    hold = await cap.reserve(UID, rid(1), 11.22, CAP)
    await cap.settle(hold, 8.52, outcome={"picture": "tp_000000000001"}, picture=True)
    doc = await docs.get(f"{PREFIX}tryon_spend/{UID}_2026-11")
    assert doc is not None and doc["owner"] == UID and "updated_at" in doc
    assert set(doc) == {"owner", "month", "spent_inr", "held_inr", "holds", "done", "pictures",
                        "blocked", "updated_at"}  # fmt: skip


async def test_old_holds_are_settled_at_their_hold() -> None:
    clock = FixedClock(NOW)
    cap = _cap(clock=clock)
    await cap.reserve(UID, rid(1), 11.22, CAP)
    clock.set(NOW + timedelta(minutes=59))
    assert await cap.settle_old(UID) == 0
    clock.set(NOW + timedelta(hours=1, seconds=1))
    assert await cap.settle_old(UID) == 1  # a call that may have been billed
    month = await cap.month(UID)
    assert (month.spent_inr, month.held_inr, month.holds) == (11.22, 0.0, {})


async def test_his_own_cap_and_keep_days_are_numbers_beside_the_months() -> None:
    docs = MemoryDocs()
    cap = _cap(docs)
    prefs = await cap.prefs(UID)
    assert (prefs.on, prefs.cap_inr, prefs.keep_days) == (True, None, None)  # the deployment's
    await cap.set_prefs(UID, capmod.Prefs(on=False, cap_inr=150, keep_days=7))
    assert await cap.prefs(UID) == capmod.Prefs(on=False, cap_inr=150, keep_days=7)
    doc = await docs.get(f"{PREFIX}tryon_spend/{UID}_prefs")
    assert doc is not None and doc["owner"] == UID

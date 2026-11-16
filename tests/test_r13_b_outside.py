# tests/test_r13_b_outside.py -- R13 Part B (docs/plans/r13-wardrobe.md D11, plan review H4):
# outside laundry and dry-cleaning are records, never an order, a call or a payment. LND-14 (two of
# three back: only those two can become ready; the batch is flagged short and, past its `due`,
# overdue), the shop's label (his words, at most 40 characters, never a phone number), `due` on the
# `sent_out` event and A's `expected_back`. Fixed clocks only.
from __future__ import annotations

from datetime import date

import pytest
from r13_fakes import UID
from r13_fakes_b import BLAZER, BLUE_SHIRT, JACKET, TROUSERS, rig

from jarvis.wardrobe.laundry import providers
from jarvis.wardrobe.ports import Refused

DUE = date(2026, 11, 18)


async def _sent(r):  # type: ignore[no-untyped-def]
    got = await r.desk.send_out(
        UID, (BLAZER, TROUSERS, JACKET), "Dry cleaner", bag="Bag 7", due=DUE
    )
    assert got.batch is not None
    return got


async def test_lnd_14_a_batch_is_a_record_with_its_due_date_and_each_piece_out() -> None:
    r = await rig()
    got = await _sent(r)
    assert got.message == "Noted: 3 pieces went to an outside laundry, due Wed 18 Nov."
    for pid in (BLAZER, TROUSERS, JACKET):
        p = await r.piece(pid)
        assert p.state == "with_provider" and p.expected_back == DUE and not p.eligible
    (batch,) = (await r.laundry()).batches
    assert (batch.shop, batch.bag, batch.due, batch.back) == ("Dry cleaner", "Bag 7", DUE, ())
    assert all(h.event.due == DUE for h in (await r.store.history(UID, BLAZER))[-1:])


async def test_lnd_14_two_of_three_back_only_those_two_ready_short_then_overdue() -> None:
    r = await rig()
    batch = (await _sent(r)).batch
    r.clock.advance(days=1)
    got = await r.desk.receive(UID, batch, (BLAZER, TROUSERS))
    assert got.message == (
        "Noted: 2 of 3 pieces are back from the outside laundry; 1 is still out."
    )
    assert [await r.state(p) for p in (BLAZER, TROUSERS, JACKET)] == [
        "ready",
        "ready",
        "with_provider",
    ]
    (b,) = (await r.laundry()).batches
    assert b.short and b.back == (BLAZER, TROUSERS) and b.closed_at is None
    assert not providers.overdue(b, date(2026, 11, 18))  # due today: not overdue yet
    assert (
        providers.overdue(b, date(2026, 11, 19))
        and providers.days_overdue(b, date(2026, 11, 20)) == 2
    )
    with pytest.raises(Refused) as no:
        await r.desk.move(UID, "ready", pieces=(JACKET,))
    assert str(no.value) == (
        "A navy jacket is with an outside laundry: mark it back from its batch."
    )


async def test_lnd_14_the_last_piece_back_closes_the_batch_and_may_need_pressing() -> None:
    r = await rig()
    batch = (await _sent(r)).batch
    await r.desk.receive(UID, batch, (BLAZER, TROUSERS))
    r.clock.advance(hours=2)
    await r.desk.receive(UID, batch, (JACKET,), to="needs_prep")
    assert await r.state(JACKET) == "needs_prep"
    (b,) = (await r.laundry()).batches
    assert b.closed_at == r.clock() and not providers.outstanding(b)
    assert (await r.piece(JACKET)).expected_back is None


async def test_h1_a_worn_blazer_to_the_dry_cleaner_closes_its_wear_for_its_plan() -> None:
    r = await rig()
    await r.wear(BLAZER, plan="pl_meeting")
    r.clock.advance(hours=8)
    r.observer.heard.clear()
    await r.desk.send_out(UID, (BLAZER,), "Dry cleaner")
    blazer = await r.piece(BLAZER)
    assert blazer.state == "with_provider" and blazer.wear is None and blazer.wears == 1
    kinds = [h.event.kind for h in await r.store.history(UID, BLAZER)][-2:]
    assert kinds == ["wear_done", "sent_out"]  # the wear is counted (STY-17), then it goes out
    (heard,) = r.observer.heard  # the wear's plan travels with it: C marks nothing
    assert (heard.kind, heard.before, heard.plan) == ("sent_out", "in_use", "pl_meeting")


async def test_a_piece_that_is_not_in_the_batch_is_refused() -> None:
    r = await rig()
    batch = (await _sent(r)).batch
    with pytest.raises(Refused) as no:
        await r.desk.receive(UID, batch, (BLUE_SHIRT,))
    assert str(no.value) == "A light blue shirt isn't in that batch."
    with pytest.raises(Refused) as gone:
        await r.desk.receive(UID, "bt_00000000", (BLAZER,))
    assert str(gone.value) == "That batch isn't open."


@pytest.mark.parametrize(
    "label",
    ["Shop 12345 67890", "11111-22222 cleaners", "call 1234567890", "x" * 41, "", "   "],
)
def test_a_shop_label_never_holds_a_phone_number_and_stays_short(label: str) -> None:
    with pytest.raises(Refused):
        providers.clean_shop(label)


def test_a_short_label_is_kept_in_his_words() -> None:
    assert providers.clean_shop("  Dhobi  near the temple ") == "Dhobi near the temple"
    assert providers.clean_shop("Shop No. 12") == "Shop No. 12"


async def test_a_batch_without_a_due_date_is_never_overdue() -> None:
    r = await rig()
    got = await r.desk.send_out(UID, (BLAZER,), "Laundry shop")
    assert got.message == "Noted: a charcoal blazer went to an outside laundry."
    (b,) = (await r.laundry()).batches
    assert b.due is None and not providers.overdue(b, date(2027, 1, 1))


async def test_a_due_date_in_the_past_or_far_ahead_is_refused() -> None:
    r = await rig()
    with pytest.raises(Refused):
        await r.desk.send_out(UID, (BLAZER,), "Dry cleaner", due=date(2026, 11, 15))
    with pytest.raises(Refused):
        await r.desk.send_out(UID, (BLAZER,), "Dry cleaner", due=date(2027, 3, 1))

# tests/test_billing_budget.py — slice 7b: the owner's monthly limit (rupees) and its confirm rule
from __future__ import annotations

import asyncio

import pytest
from billing_fakes import UID, put_raw
from brief_fakes import SlowDocs
from pydantic import ValidationError

from jarvis.billing.budget import (
    LIMIT_MAX,
    LIMIT_MIN,
    BudgetPatch,
    BudgetRejected,
    BudgetStore,
    LimitUnreadable,
    apply_limit,
    needs_confirm,
)
from jarvis.storage.docs import MemoryDocs


@pytest.mark.parametrize(
    ("old", "new", "confirm"),
    [
        (None, 500, False),  # setting a first limit only ever lowers what JARVIS may spend
        (500, 400, False),  # lowering
        (500, 500, False),  # unchanged
        (None, None, False),  # still no limit
        (500, 501, True),  # raising lets JARVIS spend more
        (500, None, True),  # removing lets JARVIS spend without a JARVIS limit
        (1, LIMIT_MAX, True),
    ],
)
def test_raising_or_removing_needs_a_confirmation(
    old: int | None, new: int | None, confirm: bool
) -> None:
    assert needs_confirm(old, new) is confirm


def test_apply_refuses_a_raise_or_removal_without_confirm_raise() -> None:
    with pytest.raises(BudgetRejected, match="confirm"):
        apply_limit(500, BudgetPatch(monthly_limit_inr=600))
    with pytest.raises(BudgetRejected, match="confirm"):
        apply_limit(500, BudgetPatch(monthly_limit_inr=None))
    assert apply_limit(500, BudgetPatch(monthly_limit_inr=600, confirm_raise=True)) == 600
    assert apply_limit(500, BudgetPatch(monthly_limit_inr=None, confirm_raise=True)) is None
    assert apply_limit(500, BudgetPatch(monthly_limit_inr=100)) == 100
    assert apply_limit(None, BudgetPatch(monthly_limit_inr=100)) == 100


@pytest.mark.parametrize("value", [0, -1, LIMIT_MAX + 1, 10**9])
def test_apply_refuses_out_of_range_values(value: int) -> None:
    with pytest.raises(BudgetRejected, match="₹1"):
        apply_limit(None, BudgetPatch(monthly_limit_inr=value, confirm_raise=True))
    assert (LIMIT_MIN, LIMIT_MAX) == (1, 100_000)


@pytest.mark.parametrize(
    "body",
    [
        {"monthly_limit_inr": "500"},
        {"monthly_limit_inr": 500.5},
        {"monthly_limit_inr": True},
        {"monthly_limit_inr": [500]},
        {"monthly_limit_inr": 500, "confirm_raise": "true"},
        {"monthly_limit_inr": 500, "confirm_raise": 1},
        {},  # the field is required (null removes the limit; leaving it out is not a request)
    ],
)
def test_the_patch_is_strict(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BudgetPatch.model_validate(body)


def test_the_patch_ignores_unknown_fields_such_as_a_user_id() -> None:
    p = BudgetPatch.model_validate({"monthly_limit_inr": 5, "user_id": "someone_else"})
    assert p.monthly_limit_inr == 5 and not hasattr(p, "user_id")


async def test_store_round_trip_and_doc_layout() -> None:
    docs = MemoryDocs()
    s = BudgetStore(docs)
    assert await s.get(UID) is None
    assert await s.update(UID, BudgetPatch(monthly_limit_inr=500)) == 500
    assert await s.get(UID) == 500
    doc = await docs.get(f"jarvis_budget/{UID}")
    assert doc is not None and doc["monthly_limit_inr"] == 500 and "updated_at" in doc


async def test_a_refused_change_writes_nothing() -> None:
    docs = MemoryDocs()
    s = BudgetStore(docs)
    await s.update(UID, BudgetPatch(monthly_limit_inr=500))
    sets = docs.sets
    with pytest.raises(BudgetRejected):
        await s.update(UID, BudgetPatch(monthly_limit_inr=900))
    with pytest.raises(BudgetRejected):
        await s.update(UID, BudgetPatch(monthly_limit_inr=None))
    assert docs.sets == sets and await s.get(UID) == 500


async def test_the_rule_is_checked_against_the_stored_limit_inside_the_transaction() -> None:
    """A stale page that still thinks the limit is ₹500 cannot "lower" it to ₹400 without a
    confirm once it is really ₹100: that is a raise."""
    docs = SlowDocs()
    s = BudgetStore(docs)
    await s.update(UID, BudgetPatch(monthly_limit_inr=500))
    lowered, raised = await asyncio.gather(
        s.update(UID, BudgetPatch(monthly_limit_inr=100)),
        s.update(UID, BudgetPatch(monthly_limit_inr=400)),
        return_exceptions=True,
    )
    assert lowered == 100
    final = await s.get(UID)
    if isinstance(raised, BudgetRejected):
        assert final == 100  # the lower ran first: 100 → 400 is a raise, refused
    else:
        assert raised == 400 and final == 100  # the 400 ran first (a lower), then the 100


# A stored limit JARVIS can't trust (hand-edited, corrupted, or out of range) must never read as
# "no limit": that would let every paid call through and any raise skip the confirmation.
UNREADABLE: list[object] = [
    "lots",
    "500",
    float("nan"),
    float("inf"),
    True,
    12.5,
    0,
    -5,
    LIMIT_MAX + 1,
    10**12,
    {"x": 1},
    [500],
]
BUDGET_DOC = f"jarvis_budget/{UID}"


@pytest.mark.parametrize("value", UNREADABLE)
async def test_an_unreadable_stored_limit_fails_closed(value: object) -> None:
    docs = MemoryDocs()
    await put_raw(docs, BUDGET_DOC, {"monthly_limit_inr": value})
    with pytest.raises(LimitUnreadable):
        await BudgetStore(docs).get(UID)


async def test_a_budget_document_without_the_field_is_unreadable_too() -> None:
    docs = MemoryDocs()
    await put_raw(docs, BUDGET_DOC, {"user_id": UID})  # every write stores the field, even null
    with pytest.raises(LimitUnreadable):
        await BudgetStore(docs).get(UID)


async def test_a_whole_number_stored_as_a_float_still_reads() -> None:
    docs = MemoryDocs()
    await put_raw(docs, BUDGET_DOC, {"monthly_limit_inr": 500.0})
    assert await BudgetStore(docs).get(UID) == 500
    await put_raw(docs, BUDGET_DOC, {"monthly_limit_inr": None})
    assert await BudgetStore(docs).get(UID) is None  # an explicit null is "no limit"


@pytest.mark.parametrize("value", UNREADABLE)
async def test_any_change_to_an_unreadable_limit_needs_the_confirmation(value: object) -> None:
    """JARVIS doesn't know what the limit was, so it can't tell a lower from a raise."""
    docs = MemoryDocs()
    await put_raw(docs, BUDGET_DOC, {"monthly_limit_inr": value})
    s = BudgetStore(docs)
    sets = docs.sets
    for patch in (
        BudgetPatch(monthly_limit_inr=LIMIT_MIN),
        BudgetPatch(monthly_limit_inr=LIMIT_MAX),
        BudgetPatch(monthly_limit_inr=None),
    ):
        with pytest.raises(BudgetRejected, match="can't be read"):
            await s.update(UID, patch)
    assert docs.sets == sets  # nothing written
    assert await s.update(UID, BudgetPatch(monthly_limit_inr=300, confirm_raise=True)) == 300
    assert await s.get(UID) == 300


def test_apply_with_an_unreadable_old_limit_always_needs_the_confirm() -> None:
    with pytest.raises(BudgetRejected, match="can't be read"):
        apply_limit(None, BudgetPatch(monthly_limit_inr=5), readable=False)
    assert apply_limit(None, BudgetPatch(monthly_limit_inr=5, confirm_raise=True), readable=False)
    with pytest.raises(BudgetRejected, match="₹1 to ₹1,00,000"):  # range first, as before
        apply_limit(None, BudgetPatch(monthly_limit_inr=0, confirm_raise=True), readable=False)


async def test_a_bad_user_id_is_refused() -> None:
    with pytest.raises(ValueError):
        await BudgetStore(MemoryDocs()).get("../budget")

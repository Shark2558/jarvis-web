# tests/test_r131_a_saved.py -- R13.1 Part A, D7 (AVT-11's half): saved comparisons. At most ten in
# `tryon/{uid}.saved`, each one look or two (piece ids per slot, tuck, open, layers; never a
# picture). Re-checked on every read from a FRESH view: each slot's readiness word, the look
# "Draft" while any piece isn't eligible. A private piece is never kept in one (the figure always
# wears the base layer there), and one made private later is not served.
from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from r131_fakes_a import SHOES, UID, AWorld, T, a_world

from jarvis.wardrobe.tryon import model as m
from jarvis.wardrobe.tryon import options as o
from jarvis.wardrobe.tryon import saved as sv
from jarvis.wardrobe.tryon.confirm import BadSlots
from jarvis.wardrobe.tryon.http import ConfirmSlot, SavedIn, SavedLook

FORMAL = (("top", T.white), ("bottom", T.trousers), ("outer", T.blazer), ("shoes", SHOES[0]))
FESTIVE = (("top", T.kurta), ("bottom", T.pyjama))


def _look(pairs: Any, **kw: Any) -> SavedLook:
    return SavedLook(slots=tuple(ConfirmSlot(slot=s, piece=p) for s, p in pairs), **kw)


def _ids(look: SavedLook) -> list[tuple[str, str]]:
    return [(s.slot, s.piece) for s in look.slots]


async def _two(a: AWorld) -> Any:
    body = SavedIn(
        looks=(_look(FORMAL, tucked=True, open=False), _look(FESTIVE, layers="no_outer"))
    )
    return await a.service.save(UID, body)


async def test_avt11_saved_keeps_both_lists_and_their_readiness() -> None:
    a = await a_world()
    made = await _two(a)
    assert m.SAVED_ID and made.id.startswith("tc_") and made.at == a.clock()
    formal, festive = made.looks
    assert _ids(formal.look) == list(FORMAL) and _ids(festive.look) == list(FESTIVE)
    assert formal.look.tucked is True and formal.look.open is False
    assert festive.look.layers == "no_outer"
    assert formal.readiness == (m.READY,) * 4 and festive.readiness == (m.READY,) * 2
    assert not made.draft and not formal.draft and not festive.draft


async def test_avt11_saved_a_piece_that_changed_state_opens_as_a_draft() -> None:
    a = await a_world()
    made = await _two(a)
    await a.move(T.kurta)
    again = await a.service.saved_one(UID, made.id)
    formal, festive = again.looks
    assert again.draft is True and festive.draft is True and formal.draft is False
    assert festive.readiness == ("Draft: in the laundry", o.SET_WORDS)
    assert _ids(festive.look) == list(FESTIVE)  # the piece list is kept as it was
    listed = await a.service.saved_list(UID)
    assert [x.id for x in listed.saved] == [made.id] and listed.saved[0].draft is True


async def test_avt11_saved_at_most_ten() -> None:
    a = await a_world()
    for _ in range(m.SAVED_MAX):
        await a.service.save(UID, SavedIn(looks=(_look(FESTIVE),)))
    with pytest.raises(sv.SavedFull) as got:
        await a.service.save(UID, SavedIn(looks=(_look(FESTIVE),)))
    assert str(got.value) == sv.FULL_SAVED
    assert len((await a.service.saved_list(UID)).saved) == m.SAVED_MAX


async def test_avt11_saved_never_keeps_a_private_piece() -> None:
    a = await a_world()
    made = await a.service.save(
        UID, SavedIn(looks=(_look((("top", T.white), ("base", T.vest), ("underwear", T.under))),))
    )
    assert _ids(made.looks[0].look) == [("top", T.white)]
    stored = await a.service.store.read(UID)
    assert all(s.piece not in (T.vest, T.under) for x in stored.saved for lk in x.looks
               for s in lk.slots)  # fmt: skip
    with pytest.raises(BadSlots):  # nothing left but private pieces
        await a.service.save(UID, SavedIn(looks=(_look((("base", T.vest),)),)))


async def test_avt11_saved_a_piece_made_private_later_is_not_served() -> None:
    a = await a_world()
    made = await a.service.save(
        UID, SavedIn(looks=(_look((("top", T.white), ("bottom", T.jeans))),))
    )
    await a.w.edit(T.jeans, private=True)
    again = await a.service.saved_one(UID, made.id)
    assert _ids(again.looks[0].look) == [("top", T.white)]
    assert T.jeans not in again.model_dump_json()


@pytest.mark.parametrize("pairs", [
    (("top", "wi_ffffffffffff"),), (("bottom", T.white),), (("top", T.white), ("top", T.striped)),
])  # fmt: skip
async def test_avt11_saved_refuses_what_isnt_a_look_of_his(pairs: Any) -> None:
    a = await a_world()
    with pytest.raises(BadSlots):
        await a.service.save(UID, SavedIn(looks=(_look(pairs),)))
    assert (await a.service.saved_list(UID)).saved == ()


async def test_avt11_saved_open_and_delete_by_id() -> None:
    a = await a_world()
    made = await _two(a)
    gone = await a.service.saved_drop(UID, made.id)
    assert gone.deleted is True
    again = await a.service.saved_drop(UID, made.id)
    assert again.deleted is False and again.message == sv.ALREADY
    with pytest.raises(sv.SavedGone) as missing:
        await a.service.saved_one(UID, made.id)
    assert str(missing.value) == sv.GONE


def test_avt11_saved_never_holds_a_picture() -> None:
    with pytest.raises(ValidationError):
        SavedIn.model_validate({"looks": [{"slots": [{"slot": "top", "piece": T.white}],
                                           "picture": "tp_0123456789ab"}]})  # fmt: skip


async def test_avt11_saved_a_comparisons_plan_is_its_readiness_plan() -> None:
    a = await a_world()
    pid = await a.plan()
    plan = (await a.styling.plans.read(UID)).plan(pid)
    blazer = plan.slot("outer").pieces[0]
    other = await a.plan()  # another plan tomorrow holds the same blazer
    mine = await a.service.save(UID, SavedIn(looks=(_look((("outer", blazer),), plan=pid),)))
    theirs = await a.service.save(UID, SavedIn(looks=(_look((("outer", blazer),), plan=other),)))
    assert mine.looks[0].readiness == (m.READY,)  # its own plan holds it
    assert theirs.looks[0].readiness == ("Draft: reserved for your plan",) and theirs.draft

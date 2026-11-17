# tests/test_r131_c_pair.py -- R13.1 Part C: what of his may go in a picture, and the pairing
# (docs/plans/r13-1-try-on.md D13.1, D22.5). Only a top, a bottom or an outer layer of his with a
# `front` crop, never private, never in the new garment's slot, at most two; the pairing is R13's
# engine (read only) on a COPY of his view with the garment as a transient piece that is never
# written or returned. Fixed clocks only (17 Nov 2026 09:00 IST). Written first and run red.
from __future__ import annotations

from r131_fakes import UID, T
from r131_fakes_c import FRONT, seeme_world

from jarvis.wardrobe.seeme import pair as pairmod
from jarvis.wardrobe.seeme import texts
from jarvis.wardrobe.seeme.pair import Pairer
from jarvis.wardrobe.tryon.http import GarmentView
from jarvis.wardrobe.tryon.model import COVERED

NAVY_SHIRT = GarmentView.model_validate(
    {"id": "tg_000000000001", "type": "shirt", "colour": "navy", "words": "x",
     "at": "2026-11-17T03:30:00+00:00"}
)  # fmt: skip


def _garment(kind: str, colour: str) -> GarmentView:
    return NAVY_SHIRT.model_copy(update={"type": kind, "colour": colour,
                                         "slot": pairmod.slot_of_type(kind)})  # fmt: skip


async def _split(pieces: list[str], slot: str = "top") -> tuple[list, list]:  # type: ignore[type-arg]
    sw = await seeme_world()
    view = await sw.w.store.view(UID)
    return await pairmod.split(sw.ctx, UID, view, pieces, garment_slot=slot)


async def test_a_bottom_with_a_front_crop_is_sent_with_its_fixed_words() -> None:
    sent, not_sent = await _split([T.trousers])
    assert [(m.piece, m.words, m.photo) for m in sent] == [
        (T.trousers, "charcoal trousers", FRONT[T.trousers])
    ]
    assert not_sent == []


async def test_a_private_piece_is_never_sent_nor_named() -> None:
    sent, not_sent = await _split([T.vest, T.under])
    assert sent == []
    assert [(n.piece, n.why, n.words) for n in not_sent] == [
        (None, "private_piece", COVERED),
        (None, "private_piece", COVERED),
    ]  # no id, no label, no colour of a private piece


async def test_a_piece_without_a_front_crop_is_not_sent() -> None:
    sent, not_sent = await _split([T.shirt], slot="bottom")  # the light blue shirt has no photo
    assert sent == [] and [(n.piece, n.why) for n in not_sent] == [(T.shirt, "no_photo")]
    assert not_sent[0].words == "light blue shirt"
    detail_only, _ = await _split([T.striped], slot="bottom")  # front + detail: the front is sent
    assert [m.photo for m in detail_only] == ["wh_00000000b001"]


async def test_shoes_a_belt_a_watch_and_the_garments_own_slot_are_not_sent() -> None:
    sent, not_sent = await _split([T.shoes[0], T.belt, T.watch, T.striped], slot="top")
    assert sent == []
    assert [(n.piece, n.why) for n in not_sent] == [
        (T.shoes[0], "not_a_garment"), (T.belt, "not_a_garment"), (T.watch, "not_a_garment"),
        (T.striped, "not_a_garment"),  # a top beside a new top
    ]  # fmt: skip


async def test_two_of_his_in_one_slot_or_a_stranger_are_not_sent() -> None:
    sent, not_sent = await _split([T.trousers, T.jeans, "wi_0000000000ff"])
    assert [m.piece for m in sent] == [T.trousers]
    assert [(n.piece, n.why) for n in not_sent] == [
        (T.jeans, "not_a_garment"),
        ("wi_0000000000ff", "not_a_garment"),
    ]


async def test_the_pairing_around_a_new_navy_shirt_is_his_jeans() -> None:
    sw = await seeme_world()
    before = await sw.rev()
    got = await Pairer(sw.ctx).pair(UID, _garment("shirt", "navy"))
    assert got.garment == "tg_000000000001"
    assert [(p.piece, p.words) for p in got.pieces] == [(T.jeans, "blue jeans")]
    assert got.words == "With your blue jeans."
    shown = {n.piece for n in got.not_sent}
    assert T.watch in shown and T.under not in shown  # the rest of the look, never a private id
    assert any(n.why == "private_piece" and n.piece is None for n in got.not_sent)
    assert "wi_ffffffffffff" not in got.model_dump_json()  # no transient id is ever returned
    assert await sw.rev() == before  # the pairing writes nothing (R13's rev unchanged)


async def test_the_pairing_never_offers_a_private_piece_or_one_in_the_garments_slot() -> None:
    sw = await seeme_world()
    for kind, colour in (("trousers", "khaki"), ("blazer", "navy"), ("kurta", "maroon"),
                         ("shirt", "white"), ("shorts", "black")):  # fmt: skip
        g = _garment(kind, colour)
        got = await Pairer(sw.ctx).pair(UID, g)
        view = await sw.w.store.view(UID)
        assert len(got.pieces) <= 2, kind
        for p in got.pieces:
            assert not view.pieces[p.piece].private, kind
            assert pairmod.slot_of_type(view.pieces[p.piece].type) != g.slot, kind
    trousers = await Pairer(sw.ctx).pair(UID, _garment("trousers", "khaki"))
    assert [p.piece for p in trousers.pieces] == [T.striped]  # a top of his to go with them


async def test_nothing_of_his_that_goes_with_it_is_said_in_words() -> None:
    sw = await seeme_world()
    for pid in (T.jeans, T.trousers):
        await sw.w.edit(pid, photos=())  # no front crop on any bottom any more
    got = await Pairer(sw.ctx).pair(UID, _garment("shirt", "navy"))
    assert got.pieces == () and got.words == texts.PAIR_NONE


async def test_without_rs13s_styling_the_pairing_says_so() -> None:
    sw = await seeme_world()
    del sw.state["r13_parts"]["styling"]
    got = await Pairer(sw.ctx).pair(UID, _garment("shirt", "navy"))
    assert got.pieces == () and got.words == texts.PAIR_OFF

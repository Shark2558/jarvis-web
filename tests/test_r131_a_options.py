# tests/test_r131_a_options.py -- R13.1 Part A, D5 and D7: a slot's readiness from a FRESH read of
# the wardrobe view and his plans (Ready; "Draft: in the laundry" and the other DRAFT_WORDS;
# "Draft: reserved for your 18:00 event"; "Draft: one shoe missing"; a set part without its set;
# an In-use piece only through the plan's declared shared base), and the slot's options: every
# non-private, non-archived, non-merged piece of the slot's types, at most 12, a pair once, each
# with its readiness. Also each piece's figure choice (AVT-05's association, `assets.py`).
from __future__ import annotations

from typing import Any

import pytest
from r131_fakes_a import SHOES, UID, AWorld, N, T, a_world

from jarvis.wardrobe.model import Piece
from jarvis.wardrobe.tryon import assets
from jarvis.wardrobe.tryon import model as m
from jarvis.wardrobe.tryon import options as o
from jarvis.wardrobe.tryon.http import AssetChoice
from jarvis.wardrobe.tryon.store import Asset, TryonDoc


async def _fresh(a: AWorld, plan: str | None = None) -> o.Fresh:
    view, doc = await a.view(), await a.styling.plans.read(UID)
    found = doc.plan(plan) if plan else None
    here = await a.styling.where(UID)
    day = found.day if found else here.today
    code = found.code if found else "business_formal"
    return o.fresh_of(view, doc, a.styling.rules, here.zone, day=day, code=code, plan=found)


async def test_a_ready_piece_reads_ready() -> None:
    a = await a_world()
    assert o.readiness(await _fresh(a), "outer", (T.blazer,)) == (m.READY, True)


@pytest.mark.parametrize(("kind", "words"), [
    ("deposited", "Draft: in the laundry"),
    ("wear_started", "Draft: in use"),
    ("damaged", "Draft: needs a repair"),
    ("sent_out", "Draft: at the laundry shop"),
])  # fmt: skip
async def test_a_piece_that_isnt_ready_reads_as_its_draft(kind: Any, words: str) -> None:
    a = await a_world()
    await a.w.move(T.rain_jacket, kind)
    assert o.readiness(await _fresh(a), "outer", (T.rain_jacket,)) == (words, False)


async def test_a_pair_with_one_side_not_ready_is_one_shoe_missing() -> None:
    a = await a_world()
    await a.move(SHOES[1])
    assert o.readiness(await _fresh(a), "shoes", SHOES) == (m.ONE_SHOE, False)
    assert o.readiness(await _fresh(a), "shoes", SHOES[:1]) == (m.ONE_SHOE, False)  # its pair


async def test_a_piece_another_plan_holds_is_reserved_for_its_event() -> None:
    a = await a_world()
    got = await a.w.call("outfit_plan", action="save", day="tomorrow", start="18:00",
                         end="20:00", occasion="meeting")  # fmt: skip
    held = got.result["plan"]
    blazer = next(p["ids"] for p in held["look"]["pieces"] if p["slot"] == "outer")
    other = await a.plan()  # another plan the same day
    words, ok = o.readiness(await _fresh(a, other), "outer", tuple(blazer))
    assert (words, ok) == ("Draft: reserved for your 18:00 event", False)
    mine = await _fresh(a, held["id"])  # its own plan: not reserved against itself
    assert o.readiness(mine, "outer", tuple(blazer)) == (m.READY, True)


async def test_a_set_part_that_cant_be_worn_alone_is_a_draft_without_its_set() -> None:
    a = await a_world()
    await a.move(T.kurta)
    words, ok = o.readiness(await _fresh(a), "bottom", (T.pyjama,))
    assert ok is False and words == o.SET_WORDS


async def test_a_piece_gone_from_his_wardrobe_is_a_draft_in_words() -> None:
    a = await a_world()
    assert o.readiness(await _fresh(a), "top", ("wi_ffffffffffff",)) == (o.GONE, False)


async def test_the_options_are_his_non_private_pieces_of_the_slot_each_with_readiness() -> None:
    a = await a_world()
    await a.move(T.rain_jacket)
    outer = o.options(await _fresh(a), "outer", (T.blazer,), {})
    assert [x.piece for x in outer] == [T.blazer, T.rain_jacket]  # the current pick first
    assert [(x.readiness, x.eligible) for x in outer] == [
        (m.READY, True), ("Draft: in the laundry", False)
    ]  # fmt: skip
    assert outer[0].words == "a charcoal blazer" and outer[0].template == "jacket"
    tops = o.options(await _fresh(a), "top", (T.shirt,), {})
    assert {x.piece for x in tops} == {T.shirt, T.white, T.striped, T.tee, T.kurta}
    assert o.options(await _fresh(a), "base", (T.vest,), {}) == ()  # private: no option at all


async def test_a_pair_is_offered_once_by_its_first_side() -> None:
    a = await a_world()
    shoes = o.options(await _fresh(a), "shoes", SHOES, {})
    assert [x.piece for x in shoes] == [SHOES[0], N.snk_l]
    assert shoes[0].words == "a pair of brown dress shoes"


async def test_archived_and_merged_pieces_are_never_options() -> None:
    a = await a_world()
    await a.w.move(T.rain_jacket, "archived")
    await a.w.edit(T.watch, merged_into=T.watch2)
    assert [x.piece for x in o.options(await _fresh(a), "outer", (T.blazer,), {})] == [T.blazer]
    watches = o.options(await _fresh(a), "watch", (T.watch2,), {})
    assert [x.piece for x in watches] == [T.watch2]


async def test_a_slot_offers_at_most_twelve_options() -> None:
    from r13_fakes import piece

    a = await a_world()
    extra = [piece(f"wi_0000000001{n:02x}", "shirt", colour="white") for n in range(14)]
    await a.w.add(*extra)
    tops = o.options(await _fresh(a), "top", (T.striped,), {})
    assert len(tops) == m.OPTIONS_MAX and tops[0].piece == T.striped


async def test_an_options_photo_is_its_first_and_its_template_his_choice() -> None:
    a = await a_world()
    chosen = {T.striped: Asset(template="tee")}
    tops = {x.piece: x for x in o.options(await _fresh(a), "top", (T.striped,), chosen)}
    assert tops[T.striped].photo == "wh_00000000b001" and tops[T.striped].template == "tee"
    card = {T.striped: Asset(card_only=True)}
    assert {x.piece: x for x in o.options(await _fresh(a), "top", (T.striped,), card)}[
        T.striped
    ].template is None


# ---- assets (AVT-05: his choice saved against the piece id) ------------------------------------
def _piece(a_view: Any, pid: str) -> Piece:
    return a_view.pieces[pid]


async def test_a_choice_of_the_same_slot_is_saved_against_the_piece_id() -> None:
    a = await a_world()
    view = await a.view()
    doc, got = assets.choose(
        TryonDoc(),
        view,
        T.striped,
        AssetChoice(piece=T.striped, template="shirt", texture_view="detail"),
    )
    assert doc.assets[T.striped] == Asset(template="shirt", texture_view="detail")
    assert got == AssetChoice(piece=T.striped, template="shirt", texture_view="detail")
    card, _ = assets.choose(doc, view, T.blazer, AssetChoice(piece=T.blazer, card_only=True))
    assert card.assets[T.blazer] == Asset(card_only=True) and T.striped in card.assets
    back, _ = assets.choose(card, view, T.blazer, AssetChoice(piece=T.blazer))  # the default
    assert T.blazer not in back.assets


@pytest.mark.parametrize(("pid", "choice", "error"), [
    ("wi_ffffffffffff", {"template": "shirt"}, assets.NotIn),
    (T.vest, {"template": "tee"}, assets.Refused),  # private: never drawn
    (T.striped, {"template": "trousers"}, assets.Refused),  # another slot's shape
    (T.striped, {"template": "shirt", "card_only": True}, assets.Refused),
])  # fmt: skip
async def test_a_choice_that_doesnt_fit_is_refused(pid: str, choice: Any, error: Any) -> None:
    a = await a_world()
    with pytest.raises(error):
        assets.choose(TryonDoc(), await a.view(), pid, AssetChoice(piece=pid, **choice))


async def test_a_choice_for_another_piece_is_refused() -> None:
    a = await a_world()
    with pytest.raises(assets.Refused):
        assets.choose(TryonDoc(), await a.view(), T.blazer, AssetChoice(piece=T.striped))


async def test_a_type_with_no_template_takes_an_image_card_only() -> None:
    from r13_fakes import piece

    a = await a_world()
    tie = piece("wi_0000000002aa", "tie", colour="navy")
    await a.w.add(tie)
    view = await a.view()
    with pytest.raises(assets.Refused):
        assets.choose(TryonDoc(), view, tie.id, AssetChoice(piece=tie.id, template="shirt"))
    doc, _ = assets.choose(TryonDoc(), view, tie.id, AssetChoice(piece=tie.id, card_only=True))
    assert assets.effective(view.pieces[tie.id], doc.assets) == (None, True)


async def test_a_merged_away_or_purged_pieces_choice_is_dropped_on_read() -> None:
    a = await a_world()
    await a.w.edit(T.watch, merged_into=T.watch2)
    kept = {T.watch: Asset(card_only=True), "wi_ffffffffffff": Asset(template="shirt"),
            T.blazer: Asset(texture_view="front")}  # fmt: skip
    assert assets.tidy(kept, await a.view()) == {T.blazer: Asset(texture_view="front")}


async def test_the_effective_template_is_his_choice_else_the_tables() -> None:
    a = await a_world()
    view = await a.view()
    assert assets.effective(_piece(view, T.striped), {}) == ("shirt", False)
    assert assets.effective(_piece(view, T.striped), {T.striped: Asset(template="tee")}) == (
        "tee", False
    )  # fmt: skip
    assert assets.effective(_piece(view, T.kurta), {}) == ("kurta", False)

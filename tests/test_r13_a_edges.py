# tests/test_r13_a_edges.py -- R13 Part A (docs/plans/r13-wardrobe.md D2, D6, D16): the edges of
# places, pairs and sets, the places tool, a merge that moves links and labels, and the refusals
# the tools answer in plain words. Fixed clock; real part on fakes.
from __future__ import annotations

from typing import Any

import pytest
from r13_fakes import UID
from r13_fakes_a import Catalog, approve, call, catalog, gateway

from jarvis.tools.gateway import GatewayOutcome
from jarvis.tools.taint import context_trust
from jarvis.wardrobe.catalog.edits import NewPiece
from jarvis.wardrobe.catalog.links import ALREADY_PAIRED, NOT_A_PAIR
from jarvis.wardrobe.ports import Refused


@pytest.fixture
def cat() -> Catalog:
    return catalog()


def desk(cat: Catalog) -> Any:
    return cat.store.desk  # type: ignore[attr-defined]


async def _add(cat: Catalog, *specs: NewPiece) -> list[str]:
    return list((await desk(cat).service.add(UID, specs)).ids)


async def test_places_add_is_idempotent_rename_checks_names_remove_needs_an_empty_place(
    cat: Catalog,
) -> None:
    places = desk(cat).places
    drawer = await places.add(UID, "Drawer 2")
    assert (await places.add(UID, "drawer 2")).id == drawer.id  # the same name is the same place
    tray = await places.add(UID, "Tray")
    with pytest.raises(Refused):
        await places.rename(UID, tray.id, "Drawer 2")
    assert (await places.rename(UID, tray.id, "Accessory tray")).label == "Accessory tray"
    with pytest.raises(Refused):
        await places.add(UID, "", "storage")
    with pytest.raises(Refused):
        await places.add(UID, "Shelf", "rocket")
    await _add(cat, NewPiece(type="belt", place=drawer.id))
    with pytest.raises(Refused) as got:
        await places.remove(UID, drawer.id)
    assert "move them first" in str(got.value)
    assert await places.remove(UID, "accessory tray") == tray.id
    with pytest.raises(Refused):
        await places.remove(UID, "the moon")


async def test_a_pair_is_two_pieces_of_one_paired_type_and_one_pair_a_piece(cat: Catalog) -> None:
    links = desk(cat).links
    a, b, c, shirt = await _add(
        cat, NewPiece(type="sock"), NewPiece(type="sock"), NewPiece(type="sock"),
        NewPiece(type="shirt"),
    )  # fmt: skip
    for x, y in ((a, a), (a, shirt)):
        with pytest.raises(Refused) as got:
            await links.pair(UID, x, y)
        assert str(got.value) == NOT_A_PAIR
    pair = await links.pair(UID, a, b)
    with pytest.raises(Refused) as got:
        await links.pair(UID, b, c)  # a replacement half joins only when he re-pairs it
    assert str(got.value) == ALREADY_PAIRED
    assert await links.unpair(UID, b) == pair.id
    await links.pair(UID, b, c)
    with pytest.raises(Refused):
        await links.unpair(UID, shirt)


async def test_a_set_can_be_undone_and_an_unknown_one_is_refused(cat: Catalog) -> None:
    kurta, pyjama = await _add(cat, NewPiece(type="kurta"), NewPiece(type="pyjama"))
    made = await desk(cat).links.make_set(UID, [(kurta, True), (pyjama, False)])
    assert await desk(cat).links.unset(UID, made.id) == made.id
    with pytest.raises(Refused):
        await desk(cat).links.unset(UID, made.id)


async def test_a_merge_moves_the_pair_and_the_label_to_the_kept_piece(cat: Catalog) -> None:
    keep, dup, other = await _add(
        cat, NewPiece(type="sock"), NewPiece(type="sock"), NewPiece(type="sock")
    )
    await desk(cat).links.pair(UID, dup, other)
    code = (await desk(cat).labels.sheet(UID))[2].code
    await desk(cat).labels.assign(UID, code, dup)
    await desk(cat).merge.merge(UID, keep, dup)
    view = await cat.store.view(UID)
    assert [x.pieces for x in view.pairs.values()] == [(keep, other)]
    assert view.pieces[keep].label_code == code and view.labels[code].piece == keep
    with pytest.raises(Refused):
        await desk(cat).merge.merge(UID, keep, dup)  # merged already
    [shirt] = await _add(cat, NewPiece(type="shirt"))
    with pytest.raises(Refused):
        await desk(cat).merge.merge(UID, keep, shirt)  # not the same kind of piece


async def test_the_places_tool_lists_adds_renames_removes_and_records_a_baseline(
    cat: Catalog,
) -> None:
    gw = gateway(cat)
    added = (await call(gw, "wardrobe_places", action="add", label="Shoe rack")).result
    assert added["status"] == "done"
    rack = added["place"]
    renamed = await call(gw, "wardrobe_places", action="rename", place=rack, label="Shoe shelf")
    assert renamed.result == {"status": "done", "place": rack}
    [shoe] = await _add(cat, NewPiece(type="sneaker"))
    base = await call(
        gw, "wardrobe_places", action="baseline", place=rack, seen=[shoe], unresolved=2
    )
    assert base.result == {
        "status": "done", "seen": 1, "unresolved": 2, "places_without_baseline": 0
    }  # fmt: skip
    listed = (await call(gw, "wardrobe_places", action="list")).result
    assert listed == {"places": [{"id": rack, "kind": "storage", "baselined": True}]}
    with context_trust(untrusted=True):
        asked = await call(gw, "wardrobe_places", action="add", label="From an email")
    assert asked.outcome is GatewayOutcome.ERROR  # only his own words, refused before a card (M4)


async def test_the_edit_tool_links_labels_and_sets_and_refuses_in_words(cat: Catalog) -> None:
    gw = gateway(cat)
    a, b, kurta, pyjama = await _add(
        cat, NewPiece(type="sock"), NewPiece(type="sock"), NewPiece(type="kurta"),
        NewPiece(type="pyjama"),
    )  # fmt: skip
    code = (await desk(cat).labels.sheet(UID))[0].code
    got = await call(gw, "wardrobe_edit", piece=a, pair_with=b, label_code=code)
    assert got.result["status"] == "done"
    parts = [{"piece": kurta, "alone": True}, {"piece": pyjama}]
    made = await call(gw, "wardrobe_edit", piece=kurta, set_parts=parts, set_label="Festive")
    assert made.result["status"] == "done"
    view = await cat.store.view(UID)
    assert view.pieces[a].label_code == code and len(view.pairs) == 1 and len(view.sets) == 1
    freed = await call(gw, "wardrobe_edit", piece=a, label_code="", unpair=True)
    assert freed.result["status"] == "done"
    view = await cat.store.view(UID)
    assert view.pieces[a].label_code is None and view.pairs == {}
    asks = await call(gw, "wardrobe_edit", piece=a, type="vest")
    assert asks.result["status"] == "ask"
    gone = await call(gw, "wardrobe_edit", piece="wi_" + "9" * 12, colour="red")
    assert gone.result == {"status": "refused", "message": "That piece isn't in your wardrobe."}
    bad = await call(gw, "wardrobe_edit", query="sock", colour="red")
    assert bad.outcome is GatewayOutcome.ERROR  # his words only for a move


async def test_count_by_a_word_and_a_word_it_does_not_know(cat: Catalog) -> None:
    gw = gateway(cat)
    await _add(cat, NewPiece(type="sneaker"), NewPiece(type="dress_shoe"), NewPiece(type="shirt"))
    shoes = (await call(gw, "wardrobe_count", type="shoes")).result
    assert shoes["owned"] == 2 and shoes["by_category"] == [
        {"category": "footwear", "owned": 2, "ready": 2}
    ]  # fmt: skip
    shirts = (await call(gw, "wardrobe_count", type="shirts")).result
    assert shirts["owned"] == 1
    odd = (await call(gw, "wardrobe_count", type="spaceship")).result
    assert odd["status"] == "refused"


async def test_an_add_with_an_unknown_place_or_a_bad_type_is_refused_in_words(cat: Catalog) -> None:
    gw = gateway(cat)
    nowhere = await call(gw, "wardrobe_add", pieces=[{"type": "belt", "place": "the moon"}])
    assert nowhere.result["status"] == "refused" and "Your places" not in nowhere.result["message"]
    odd = await call(gw, "wardrobe_add", pieces=[{"type": "spaceship"}])
    assert odd.result["status"] == "refused"
    assert (await call(gw, "wardrobe_add", pieces=[])).outcome is GatewayOutcome.ERROR

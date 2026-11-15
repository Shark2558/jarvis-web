# tests/test_r13_a_catalog.py -- R13 Part A (docs/plans/r13-wardrobe.md D2, D3, D6, D7; "Tests and
# evals"): every catalog acceptance check INV-01 ... INV-15 as a named test, on A's real part built
# through `build(ctx)` (sealed store, fixed clock). INV-06 is in test_r13_a_photos.py, INV-16 and
# INV-17 in test_r13_a_lifecycle.py.
from __future__ import annotations

import pytest
from r13_fakes import UID, ev, ist
from r13_fakes_a import Catalog, catalog

from jarvis.wardrobe.catalog.service import ASK_PRIVATE, Edit, NewPiece
from jarvis.wardrobe.ports import Commit, Refused


@pytest.fixture
def cat() -> Catalog:
    return catalog()


def desk(cat: Catalog):  # type: ignore[no-untyped-def]
    return cat.store.desk  # type: ignore[attr-defined]


async def _place(cat: Catalog, label: str, kind: str = "storage") -> str:
    return (await desk(cat).places.add(UID, label, kind)).id


async def _add(cat: Catalog, *specs: NewPiece) -> list[str]:
    return list((await desk(cat).service.add(UID, specs)).ids)


async def _state(cat: Catalog, pid: str) -> str:
    found = (await cat.store.view(UID)).piece(pid)
    assert found is not None
    return found.state


async def _deposit(cat: Catalog, pid: str, **kw: object) -> None:
    async def fn(view: object, tx: object) -> Commit:
        return Commit(events=(ev(pid, "deposited", cat.clock(), **kw),))  # type: ignore[arg-type]

    await cat.store.transact(UID, fn)


def test_part_a_builds_with_its_tools_services_and_job(cat: Catalog) -> None:
    part = cat.part
    assert part.name == "catalog" and part.ready.startswith("Ready")
    assert set(part.services) == {"store", "photos", "bin"}
    assert sorted(t.name for t in part.tools) == sorted(
        ["wardrobe_find", "wardrobe_count", "wardrobe_add", "wardrobe_edit", "wardrobe_places"]
        + ["wardrobe_merge", "wardrobe_retire", "wardrobe_remove"]
    )
    assert [j.name for j in part.daily_jobs] == ["wardrobe_sweep"] and part.clock_jobs == ()


def test_without_the_token_key_the_wardrobe_is_off_and_says_so() -> None:
    from r13_fakes_a import settings

    from jarvis.storage.docs import MemoryDocs
    from jarvis.wardrobe.catalog.part import OFF_NO_DOCS, OFF_NO_KEY, build
    from jarvis.wardrobe.ports import WardrobeContext

    async def zone(uid: str) -> object:
        return None

    def ctx(docs: object, keyring: object) -> WardrobeContext:
        return WardrobeContext(
            s=settings(), docs=docs, keyring=keyring, audit=None,  # type: ignore[arg-type]
            now=lambda: ist(2026, 11, 16), zone=zone, state={}.get,  # type: ignore[arg-type]
        )  # fmt: skip

    for found, want in (
        (build(ctx(MemoryDocs(), None)), OFF_NO_KEY),
        (build(ctx(None, None)), OFF_NO_DOCS),
    ):
        assert found.ready == want and found.tools == () and dict(found.services) == {}


# ---- INV-01 · a belt put in "Drawer 2" is found there --------------------------------------------
async def test_inv01_a_belt_put_in_drawer_2_is_found_there_by_find(cat: Catalog) -> None:
    drawer = await _place(cat, "Drawer 2")
    [belt] = await _add(
        cat, NewPiece(type="belt", label="Black belt", colour="black", place=drawer)
    )
    found = await desk(cat).search.find(UID, "belt")
    assert found.best is not None and found.best.id == belt
    assert desk(cat).views.place_words(await cat.store.view(UID), found.best) == "Drawer 2"


# ---- INV-02 · a baseline scan of two places, unresolved scans apart, places without one listed ---
async def test_inv02_scanning_two_places_lists_unresolved_scans_and_places_without_a_baseline(
    cat: Catalog,
) -> None:
    rack, tray = await _place(cat, "Shirt rack"), await _place(cat, "Accessory tray")
    shoes = await _place(cat, "Shoe rack")
    shirts = await _add(cat, NewPiece(type="shirt", place=rack), NewPiece(type="shirt", place=rack))
    [watch] = await _add(cat, NewPiece(type="watch", place=tray))
    one = await desk(cat).places.baseline(UID, rack, seen=shirts, unresolved=2)
    two = await desk(cat).places.baseline(UID, tray, seen=[watch], unresolved=0)
    assert (one.seen, one.unresolved) == (tuple(shirts), 2)
    assert (two.seen, two.unresolved) == ((watch,), 0)
    assert two.without_baseline == (shoes,)  # the shoe rack was never scanned
    view = await cat.store.view(UID)
    assert view.places[rack].baseline_at == cat.clock() and len(view.active()) == 3


# ---- INV-03 · a belt and a watch in one photo become two records --------------------------------
async def test_inv03_a_belt_and_a_watch_in_one_photo_become_two_records_and_nothing_is_guessed(
    cat: Catalog,
) -> None:
    got = await _add(cat, NewPiece(type="belt"), NewPiece(type="watch"))  # two boxes, one photo
    view = await cat.store.view(UID)
    assert len(set(got)) == 2 and len(view.active()) == 2
    assert sorted(p.type for p in view.active()) == ["belt", "watch"]
    for pid in got:  # one registration each: the piece hidden under the belt is a later scan
        assert [h.event.kind for h in await cat.store.history(UID, pid)] == ["registered"]


# ---- INV-04 · each found under its category; a type change keeps the id; private asks ----------
async def test_inv04_each_piece_is_found_under_its_category_and_a_type_change_keeps_the_id(
    cat: Catalog,
) -> None:
    kinds = ["shirt", "shirt", "vest", "underpants", "sock", "dress_shoe", "belt", "watch"]
    ids = await _add(cat, *(NewPiece(type=k) for k in kinds))
    counts = desk(cat).counts.of(await cat.store.view(UID))
    by = {r.category: r.owned for r in counts.by_category}
    assert by == {"tops": 2, "base": 3, "footwear": 1, "accessories": 2}
    view = await cat.store.view(UID)
    assert [view.pieces[i].private for i in ids[2:4]] == [True, True]  # vest, underpants
    done = await desk(cat).service.edit(UID, ids[0], Edit(type="t_shirt"))
    assert done.status == "done" and done.piece is not None and done.piece.id == ids[0]
    assert done.piece.type == "t_shirt" and done.piece.category == "tops"


async def test_inv04_a_change_into_a_private_by_default_type_asks_first(cat: Catalog) -> None:
    [pid] = await _add(cat, NewPiece(type="t_shirt"))
    asked = await desk(cat).service.edit(UID, pid, Edit(type="undershirt"))
    assert (asked.status, asked.question) == ("ask", ASK_PRIVATE)
    assert (await cat.store.view(UID)).pieces[pid].type == "t_shirt"  # nothing changed yet
    done = await desk(cat).service.edit(UID, pid, Edit(type="undershirt", private=True))
    assert done.piece is not None and (done.piece.type, done.piece.private) == ("undershirt", True)


# ---- INV-05 · a new kurta gets one id; scanning it again leaves the owned count unchanged --------
async def test_inv05_a_rescanned_kurta_keeps_one_id_and_the_owned_count(cat: Catalog) -> None:
    [kurta] = await _add(cat, NewPiece(type="kurta", label="Cream festive kurta"))
    before = desk(cat).counts.of(await cat.store.view(UID)).owned
    cat.clock.advance(minutes=5)
    got = await desk(cat).service.intake(UID, NewPiece(type="kurta"), candidate=kurta)
    assert got.ids == (kurta,) and got.new == (False,)
    view = await cat.store.view(UID)
    assert desk(cat).counts.of(view).owned == before == 1
    assert [h.event.kind for h in await cat.store.history(UID, kurta)] == ["registered", "seen"]


# ---- INV-07 · two identical vests, two ids; only the labelled copy goes in; a foreign QR ignored -
async def test_inv07_identical_vests_get_two_ids_and_only_the_labelled_one_enters_laundry(
    cat: Catalog,
) -> None:
    a, b = await _add(
        cat, NewPiece(type="vest", colour="black"), NewPiece(type="vest", colour="black")
    )
    assert a != b
    sheet = await desk(cat).labels.sheet(UID)
    code = sheet[0].code
    await desk(cat).labels.assign(UID, code, a)
    view = await cat.store.view(UID)
    assert desk(cat).labels.resolve(view, f"jw1:{code}") == a
    assert desk(cat).labels.resolve(view, "jw1:abcdefgz") is None  # well-formed, not his
    assert desk(cat).labels.resolve(view, "https://example.com/tag?id=7") is None
    assert desk(cat).labels.resolve(view, f"JW1:{code}") is None
    await _deposit(cat, a, how="qr", source="phone")
    assert (await _state(cat, a), await _state(cat, b)) == ("in_laundry", "ready")


# ---- INV-08 · 20 frames of one shirt make one piece and one registration event -----------------
async def test_inv08_twenty_frames_of_one_shirt_make_one_piece_and_one_registration(
    cat: Catalog,
) -> None:
    frames = [NewPiece(type="shirt", client_id="box-shirt-0001") for _ in range(20)]
    ids = {pid for f in frames for pid in (await desk(cat).service.add(UID, [f])).ids}
    assert len(ids) == 1
    [pid] = ids
    assert len((await cat.store.view(UID)).active()) == 1
    assert [h.event.kind for h in await cat.store.history(UID, pid)] == ["registered"]


# ---- INV-09 · "blue striped shirt" finds it once verified; a suggestion never overwrites a lock --
async def test_inv09_a_verified_colour_and_pattern_find_the_right_shirt(cat: Catalog) -> None:
    mine, other = await _add(cat, NewPiece(type="shirt"), NewPiece(type="shirt"))
    before = await desk(cat).search.find(UID, "blue striped shirt")
    assert before.best is None and {p.id for p in before.matches} == {mine, other}  # can't tell
    await desk(cat).service.edit(UID, mine, Edit(colour="blue", pattern="striped", suggested=True))
    await desk(cat).service.edit(UID, mine, Edit(colour="blue", pattern="striped"))  # he confirms
    after = await desk(cat).search.find(UID, "blue striped shirt")
    assert after.best is not None and after.best.id == mine
    piece = (await cat.store.view(UID)).pieces[mine]
    assert {"colour", "pattern"} <= set(piece.locked)


async def test_inv09_a_suggestion_never_overwrites_a_locked_attribute(cat: Catalog) -> None:
    [pid] = await _add(cat, NewPiece(type="shirt"))
    await desk(cat).service.edit(UID, pid, Edit(colour="blue"))  # his: locked
    await desk(cat).service.edit(UID, pid, Edit(colour="navy", pattern="checked", suggested=True))
    piece = (await cat.store.view(UID)).pieces[pid]
    assert (piece.colour, piece.pattern) == ("blue", "checked")  # the free one took it
    assert "pattern" not in piece.locked  # a suggestion never locks


# ---- INV-10 · read label fields stay unverified; typed ones are verified; no raw text kept -------
async def test_inv10_a_read_wash_symbol_stays_unverified_and_never_reaches_the_model(
    cat: Catalog,
) -> None:
    from jarvis.wardrobe.redact import model_view

    [pid] = await _add(cat, NewPiece(type="shirt", label="Office shirt"))
    await desk(cat).service.edit(UID, pid, Edit(care=("hand_wash",), size="M", read=True))
    piece = (await cat.store.view(UID)).pieces[pid]
    assert [(c.v, c.ok) for c in piece.care] == [("hand_wash", False)]
    assert piece.size is not None and (piece.size.v, piece.size.ok) == ("M", False)
    assert "care" not in model_view(piece) and "size" not in model_view(piece)
    await desk(cat).service.edit(UID, pid, Edit(care=("machine_wash", "iron_low")))  # typed
    piece = (await cat.store.view(UID)).pieces[pid]
    assert [(c.v, c.ok) for c in piece.care] == [("machine_wash", True), ("iron_low", True)]
    assert model_view(piece)["care"] == ["machine_wash", "iron_low"]


@pytest.mark.parametrize(
    "bad",
    [
        Edit(size="Made in India 100% cotton wash at 30", read=True),  # raw OCR text
        Edit(brand="<script>alert(1)</script>", read=True),
        Edit(care=("bleach freely",), read=True),
        Edit(fabric=("unobtainium",), read=True),
    ],
)
async def test_inv10_raw_ocr_text_is_never_stored(cat: Catalog, bad: Edit) -> None:
    [pid] = await _add(cat, NewPiece(type="shirt"))
    with pytest.raises(Refused):
        await desk(cat).service.edit(UID, pid, bad)
    piece = (await cat.store.view(UID)).pieces[pid]
    assert (piece.size, piece.brand, piece.care, piece.fabric) == (None, None, (), ())


# ---- INV-11 · two shoes, two pieces, one wearable pair only while both are ready ----------------
async def test_inv11_two_shoes_count_as_two_pieces_and_one_pair_only_while_both_are_ready(
    cat: Catalog,
) -> None:
    left, right = await _add(cat, NewPiece(type="dress_shoe"), NewPiece(type="dress_shoe"))
    pair = await desk(cat).links.pair(UID, left, right)
    counts = desk(cat).counts.of(await cat.store.view(UID))
    assert (counts.owned, counts.pairs, counts.pairs_complete) == (2, 1, 1)
    await _deposit(cat, right)  # muddy: to be cleaned
    view = await cat.store.view(UID)
    counts = desk(cat).counts.of(view)
    assert (counts.owned, counts.pairs, counts.pairs_complete) == (2, 1, 0)
    [pv] = desk(cat).counts.pair_views(view)
    assert pv.id == pair.id and not pv.wearable and pv.missing == (right,)


# ---- INV-12 · a kurta set: unavailable when the bottoms are out; says if the kurta goes alone ----
async def test_inv12_a_kurta_set_is_unavailable_when_its_bottoms_go_to_laundry(
    cat: Catalog,
) -> None:
    kurta, pyjama = await _add(cat, NewPiece(type="kurta"), NewPiece(type="pyjama"))
    made = await desk(cat).links.make_set(UID, [(kurta, True), (pyjama, False)], label="Festive")
    view = await cat.store.view(UID)
    [sv] = desk(cat).counts.set_views(view)
    assert sv.id == made.id and sv.wearable and len(view.active()) == 2
    await _deposit(cat, pyjama)
    [sv] = desk(cat).counts.set_views(await cat.store.view(UID))
    assert not sv.wearable and sv.alone == (kurta,)  # the kurta can go alone


async def test_inv12_a_set_takes_two_to_six_pieces_and_never_one_twice(cat: Catalog) -> None:
    ids = await _add(cat, *(NewPiece(type="kurta") for _ in range(7)))
    with pytest.raises(Refused):
        await desk(cat).links.make_set(UID, [(ids[0], True)])
    with pytest.raises(Refused):
        await desk(cat).links.make_set(UID, [(i, True) for i in ids])
    with pytest.raises(Refused):
        await desk(cat).links.make_set(UID, [(ids[0], True), (ids[0], False)])


# ---- INV-13 · a watch moved to the travel bag shows the bag; an unobserved move "last known" -----
async def test_inv13_a_moved_watch_shows_the_bag_and_an_unseen_one_shows_last_known(
    cat: Catalog,
) -> None:
    tray, bag = await _place(cat, "Accessory tray"), await _place(cat, "Travel bag", "travel")
    [watch] = await _add(cat, NewPiece(type="watch", place=tray))
    cat.clock.advance(hours=2)
    moved = await desk(cat).service.move(UID, watch, "travel bag")  # his words for his place
    assert moved.place == bag
    view = await cat.store.view(UID)
    assert desk(cat).views.place_words(view, view.pieces[watch]) == "Travel bag"
    cat.clock.advance(days=15)  # nobody has seen it since: where it was last seen
    view = await cat.store.view(UID)
    assert desk(cat).views.place_words(view, view.pieces[watch]) == "Travel bag (last known)"


async def test_inv13_a_move_to_a_place_he_never_named_is_refused_with_his_places(
    cat: Catalog,
) -> None:
    await _place(cat, "Accessory tray")
    [watch] = await _add(cat, NewPiece(type="watch"))
    with pytest.raises(Refused) as got:
        await desk(cat).service.move(UID, watch, "the moon")
    assert str(got.value) == "I don't know that place. Your places: Accessory tray."


# ---- INV-14 · a missing sock: owned unchanged, complete pairs down by one; scope shown -----------
async def test_inv14_a_missing_sock_keeps_the_owned_count_and_drops_one_complete_pair(
    cat: Catalog,
) -> None:
    drawer = await _place(cat, "Drawer 2")
    await _place(cat, "Shoe rack")
    socks = await _add(cat, *(NewPiece(type="sock", place=drawer) for _ in range(4)))
    await desk(cat).links.pair(UID, socks[0], socks[1])
    await desk(cat).links.pair(UID, socks[2], socks[3])
    await desk(cat).places.baseline(UID, drawer, seen=socks, unresolved=0)

    async def lost(view: object, tx: object) -> Commit:
        return Commit(events=(ev(socks[3], "missing", cat.clock()),))

    await cat.store.transact(UID, lost)
    await _deposit(cat, socks[0])  # laundry stays in owned totals
    counts = desk(cat).counts.of(await cat.store.view(UID))
    assert (counts.owned, counts.pairs, counts.pairs_complete, counts.review) == (4, 2, 0, 1)
    assert counts.places_without_baseline == 1  # the shoe rack: scope covered is shown


# ---- INV-15 · "where is my black belt": its drawer and state; two told apart; no match -----------
async def test_inv15_where_is_my_black_belt_returns_its_place_and_state(cat: Catalog) -> None:
    drawer, rack = await _place(cat, "Drawer 2"), await _place(cat, "Belt hook")
    one, two = await _add(
        cat,
        NewPiece(type="belt", label="Black belt", colour="black", place=drawer),
        NewPiece(type="belt", label="Black belt", colour="black", place=rack),
    )
    found = await desk(cat).search.find(UID, "my black belt")
    assert {p.id for p in found.matches} == {one, two} and found.best is None
    view = await cat.store.view(UID)
    words = {desk(cat).views.place_words(view, p) for p in found.matches}
    assert words == {"Drawer 2", "Belt hook"}  # told apart by place
    none = await desk(cat).search.find(UID, "where is my passport")
    assert none.best is None and none.matches == ()  # Things' answer then (D6, D's router)
    await _deposit(cat, one)
    found = await desk(cat).search.find(UID, "black belt in drawer 2")
    assert found.best is not None and found.best.id == one and found.best.state == "in_laundry"


async def test_a_sensitive_label_is_refused_and_ids_go_in_the_vault(cat: Catalog) -> None:
    with pytest.raises(Refused) as got:
        await _add(cat, NewPiece(type="bag", label="PAN ABCDE1234F inside"))
    assert "Vault" in str(got.value)

# tests/test_r131_a_looks.py -- R13.1 Part A, D5-D7 and D21: the look the figure draws, from R13's
# styling service and a FRESH read (`looks.Looks`, the `tryon_looks` service). A plan's look, a
# day's (`alt` 0-2) or exactly a reply card's pieces (row 388); each slot with its template,
# variants, colour, pattern, texture view and photo, views kept and the useful missing ones,
# readiness, approximate flags and options. A private slot is covered only: no id, colour,
# pattern, photo, template or option; its piece and words only with `private=1` (AVT-14).
from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from r131_fakes_a import SHOES, UID, AWorld, N, T, a_world

from jarvis.wardrobe.tryon import looks
from jarvis.wardrobe.tryon import model as m
from jarvis.wardrobe.tryon.http import LookSlot, TryonLook
from jarvis.wardrobe.tryon.ports import TryonLooks
from jarvis.wardrobe.tryon.store import Asset

MAROON = json.dumps(list(m.rgb_of("maroon")))  # "[110, 30, 40]": no other piece has it


def _slots(look: TryonLook) -> dict[str, LookSlot]:
    return {s.slot: s for s in look.slots}


async def _private_vest(a: AWorld) -> None:
    """His vest with a label and a colour no other piece has: AVT-14's needles."""
    await a.w.edit(T.vest, label="Lucky vest", colour="maroon")


# ---- a plan's look -------------------------------------------------------------------------
async def test_a_plans_look_is_r13s_answer_slot_by_slot() -> None:
    a = await a_world()
    pid = await a.plan()
    look = await a.service.looks.for_plan(UID, pid)
    plan = (await a.styling.plans.read(UID)).plan(pid)
    assert look.plan == pid and look.day == plan.day and look.dress_code == plan.code
    assert [s.slot for s in look.slots] == [p.slot for p in plan.picks]
    got = _slots(look)
    assert got["top"].piece == T.white and got["top"].words == "a white shirt"
    assert got["top"].template == "shirt" and got["top"].variants == ("tucked", "untucked")
    assert got["top"].rgb == m.rgb_of("white") and got["top"].readiness == m.READY
    assert got["shoes"].piece == SHOES[0] and got["shoes"].words == "a pair of brown dress shoes"
    assert got["outer"].template == "jacket" and got["outer"].removable is True
    assert got["top"].removable is False
    assert look.tucked is True and look.open is True and look.layers == "all"  # business formal


async def test_the_service_is_the_tryon_looks_port_for_c() -> None:
    a = await a_world()
    pid = await a.plan()
    assert isinstance(a.service, TryonLooks)
    assert await a.service.look(UID, pid) == await a.service.looks.for_plan(UID, pid)


async def test_a_plan_that_isnt_there_is_said_in_words() -> None:
    a = await a_world()
    with pytest.raises(looks.NoLook) as got:
        await a.service.looks.for_plan(UID, "op_00000bad")
    assert str(got.value) == looks.GONE_PLAN


async def test_a_slot_shows_its_fresh_readiness_and_options() -> None:
    a = await a_world()
    pid = await a.plan()
    await a.move(T.striped)  # after the plan was made: the look reads it fresh
    top = _slots(await a.service.looks.for_plan(UID, pid))["top"]
    opts = {o.piece: o for o in top.options}
    assert top.piece == T.white and opts[T.white].readiness == m.READY
    assert opts[T.striped].readiness == "Draft: in the laundry" and not opts[T.striped].eligible


# ---- a day's look ---------------------------------------------------------------------------
async def test_a_day_without_a_plan_is_r13s_suggestion_and_with_one_its_plan() -> None:
    a = await a_world()
    today = await a.service.looks.for_day(UID, "today")
    assert today.plan is None and today.day.isoformat() == "2026-11-17"
    pid = await a.plan("tomorrow")
    tomorrow = await a.service.looks.for_day(UID, "tomorrow")
    assert tomorrow.plan == pid and tomorrow.day.isoformat() == "2026-11-18"


async def test_an_alternative_look_and_one_that_isnt_there() -> None:
    a = await a_world()
    s, view = a.styling, await a.view()
    here, doc = await s.where(UID), await s.plans.read(UID)
    ans = await s.fresh(UID, here, doc, view, day=here.today + timedelta(days=1), occasion=None,
                        code=None)  # fmt: skip
    alts = ans.suggestion.alternatives
    assert alts, "the pilot has an alternative look tomorrow"
    other = await a.service.looks.for_day(UID, "tomorrow", alt=1)
    assert [(x.slot, x.piece) for x in other.slots] == [(p.slot, p.pieces[0]) if p.slot not in
        m.PRIVATE_SLOTS else (p.slot, None) for p in alts[0].picks]  # fmt: skip
    with pytest.raises(looks.NoLook) as gone:
        await a.service.looks.for_day(UID, "tomorrow", alt=len(alts) + 1)
    assert str(gone.value) == looks.GONE_LOOK
    with pytest.raises(looks.BadDay):
        await a.service.looks.for_day(UID, "next week")


# ---- row 388: exactly a reply card's pieces --------------------------------------------------
async def test_row388_the_look_is_exactly_the_cards_pieces_each_read_fresh() -> None:
    a = await a_world()
    await a.move(T.rain_jacket)
    q = f"top:{T.striped},bottom:{T.trousers},outer:{T.rain_jacket},shoes:{SHOES[0]},base:"
    look = await a.service.looks.for_pieces(UID, q)
    got = _slots(look)
    assert [s.slot for s in look.slots] == ["top", "bottom", "outer", "shoes", "base"]
    assert got["top"].piece == T.striped and got["outer"].readiness == "Draft: in the laundry"
    assert got["base"].private and got["base"].piece is None and got["base"].words == m.COVERED
    assert look.day.isoformat() == "2026-11-17" and look.plan is None


async def test_row388_a_private_piece_on_the_card_is_covered_unless_he_asks() -> None:
    a = await a_world()
    hidden = _slots(await a.service.looks.for_pieces(UID, f"top:{T.shirt},base:{T.vest}"))
    assert hidden["base"].piece is None and hidden["base"].words == m.COVERED
    shown = _slots(
        await a.service.looks.for_pieces(UID, f"top:{T.shirt},base:{T.vest}", private=True)
    )
    assert shown["base"].piece == T.vest and shown["base"].words == "a black vest"
    assert shown["base"].template is None and shown["base"].rgb is None  # still never drawn


def card_query(card: Any) -> str:
    """A reply card's slots as the console sends them: `slot:wi_...` a piece, `slot:` covered."""
    return ",".join(
        f"{s.slot}:" if s.private else ",".join(f"{s.slot}:{pid}" for pid in s.pieces)
        for s in card.slots
    )


async def test_row388_a_slot_the_card_covers_for_its_private_piece_comes_without_an_id() -> None:
    from jarvis.wardrobe.styling import tryon_card

    a = await a_world()
    pid = await a.plan()
    await a.w.edit(T.white, private=True)  # the plan's top is now a private piece
    s, view = a.styling, await a.view()
    doc = await s.plans.read(UID)
    ans = await s.answer(UID, await s.where(UID), doc, view, doc.plan(pid))
    card = tryon_card.card_of(view, ans)
    assert card.slots[0].slot == "top" and card.slots[0].private and card.slots[0].pieces == ()
    look = await a.service.looks.for_pieces(UID, card_query(card), plan=card.plan)
    got = _slots(look)
    assert [x.slot for x in look.slots] == [x.slot for x in card.slots]  # every slot of the card
    assert got["top"].private and got["top"].piece is None and got["top"].words == m.COVERED
    assert got["top"].template is None and got["top"].rgb is None and got["top"].options == ()
    assert T.white not in json.dumps(look.model_dump(mode="json"))
    assert got["bottom"].piece == T.trousers and got["shoes"].piece == SHOES[0]


@pytest.mark.parametrize("q", [
    "top:wi_000000000999", f"top:{T.shirt},top:{T.white}", f"top:{T.trousers}", "zz_none:",
    f"top:,top:{T.shirt}", f"top:{T.shirt},top:", "base:,base:",
    "nonsense", "", f"top={T.shirt}", ",".join([f"top:{T.shirt}"] * 25),
])  # fmt: skip
async def test_row388_pieces_that_cant_be_his_look_are_refused_in_words(q: str) -> None:
    a = await a_world()
    with pytest.raises(looks.NotPieces):
        await a.service.looks.for_pieces(UID, q)


async def test_row388_a_merged_away_piece_isnt_his_any_more() -> None:
    a = await a_world()
    await a.w.edit(T.watch, merged_into=T.watch2)
    with pytest.raises(looks.NotPieces) as got:
        await a.service.looks.for_pieces(UID, f"watch:{T.watch}")
    assert str(got.value) == looks.NOT_HIS


async def test_row388_the_look_takes_the_cards_plan_and_day() -> None:
    a = await a_world()
    pid = await a.plan()
    look = await a.service.looks.for_pieces(UID, f"top:{T.white}", plan=pid)
    assert look.plan == pid and look.day.isoformat() == "2026-11-18" and look.tucked is True
    tomorrow = await a.service.looks.for_pieces(UID, f"top:{T.white}", day="tomorrow")
    assert tomorrow.plan is None and tomorrow.day.isoformat() == "2026-11-18"


# ---- views, templates, textures (AVT-04, AVT-05, AVT-06) -------------------------------------
async def test_avt04_views_a_kurta_lists_front_and_back_under_its_own_id() -> None:
    a = await a_world()
    kurta = _slots(await a.service.looks.for_pieces(UID, f"top:{T.kurta}"))["top"]
    assert kurta.piece == T.kurta and kurta.views == ("front", "back") and kurta.missing == ()
    assert kurta.template == "kurta" and kurta.variants == ("knee",)
    assert kurta.texture_view == "front" and kurta.photo == "wh_00000000a001"


async def test_avt04_views_refs_name_each_kept_crop_front_back_detail_and_none_when_covered() -> (
    None
):
    a = await a_world()
    got = _slots(await a.service.looks.for_pieces(UID, f"top:{T.striped},base:{T.vest}"))
    shirt, vest = got["top"], got["base"]
    assert [(r.view, r.photo) for r in shirt.refs] == [  # front first, then detail
        ("front", "wh_00000000b001"), ("detail", "wh_00000000b002")
    ]  # fmt: skip
    assert tuple(r.view for r in shirt.refs) == shirt.views  # one map: they never disagree
    assert shirt.photo == "wh_00000000b002"  # the texture's crop is the detail, not the front
    assert vest.private and vest.refs == ()  # a covered slot: no reference card


async def test_avt04_views_a_kurta_with_only_a_front_asks_for_the_back_and_stays_selectable() -> (
    None
):
    a = await a_world()
    await a.w.edit(T.kurta, photos=("wh_00000000a001",))
    kurta = _slots(await a.service.looks.for_pieces(UID, f"top:{T.kurta}"))["top"]
    assert kurta.views == ("front",) and kurta.missing == ("back",)
    assert kurta.eligible is True and kurta.readiness == m.READY


async def test_avt04_views_a_piece_with_no_photo_is_colour_only_and_asks_for_its_views() -> None:
    a = await a_world()
    blazer = _slots(await a.service.looks.for_pieces(UID, f"outer:{T.blazer}"))["outer"]
    assert blazer.photo is None and blazer.texture_view is None and blazer.views == ()
    assert blazer.missing == ("front", "back")  # outerwear: the back is worth asking for
    assert blazer.approximate == ("template", "colour")
    trousers = _slots(await a.service.looks.for_pieces(UID, f"bottom:{T.trousers}"))["bottom"]
    assert trousers.missing == ("front",)  # a bottom: the front only


async def test_avt05_assets_a_patterned_shirt_textures_from_its_detail_crop() -> None:
    a = await a_world()
    shirt = _slots(await a.service.looks.for_pieces(UID, f"top:{T.striped}"))["top"]
    assert shirt.pattern == "striped" and shirt.template == "shirt"
    assert shirt.texture_view == "detail" and shirt.photo == "wh_00000000b002"
    assert shirt.views == ("front", "detail") and shirt.approximate == ("template", "texture")
    assert shirt.card_only is False


async def test_avt05_assets_his_choice_changes_the_template_and_the_texture_view() -> None:
    a = await a_world()
    await a.service.store.change(UID, lambda d: d.model_copy(update={"assets": {
        T.striped: Asset(template="tee", texture_view="front"), T.blazer: Asset(card_only=True),
    }}))  # fmt: skip
    got = _slots(await a.service.looks.for_pieces(UID, f"top:{T.striped},outer:{T.blazer}"))
    assert got["top"].template == "tee" and got["top"].texture_view == "front"
    assert got["top"].photo == "wh_00000000b001"
    assert got["outer"].card_only is True and got["outer"].template is None
    assert got["outer"].variants == () and got["outer"].approximate == ()


async def test_avt05_assets_a_type_with_no_template_is_an_image_card_only() -> None:
    from r13_fakes import piece

    a = await a_world()
    tie = piece("wi_0000000002aa", "tie", colour="navy")
    await a.w.add(tie)
    got = _slots(await a.service.looks.for_pieces(UID, f"tie:{tie.id}"))["tie"]
    assert got.card_only is True and got.template is None and got.approximate == ()


async def test_avt06_watch_and_shoes_are_their_own_slots_with_their_thumbnails() -> None:
    a = await a_world()
    got = _slots(await a.service.looks.for_pieces(UID, f"watch:{T.watch2},shoes:{N.snk_l}"))
    assert got["watch"].piece == T.watch2 and got["watch"].template == "watch"
    assert got["watch"].rgb == m.rgb_of("brown")
    assert {o.piece for o in got["watch"].options} == {T.watch, T.watch2}
    assert got["shoes"].template == "shoe" and got["shoes"].words == "a pair of white sneakers"


# ---- AVT-14: private covered everywhere -----------------------------------------------------
async def test_avt14_looks_carry_no_private_id_colour_photo_or_label_anywhere() -> None:
    a = await a_world()
    await _private_vest(a)
    pid = await a.plan()
    await a.move(T.under)  # the only underwear goes to the laundry: R13's gap names its id
    for look in (
        await a.service.looks.for_plan(UID, pid),
        await a.service.looks.for_day(UID, "today"),
        await a.service.looks.for_pieces(UID, f"top:{T.shirt},base:{T.vest},underwear:{T.under}"),
    ):
        text = json.dumps(look.model_dump(mode="json"))
        for needle in (T.vest, T.under, "maroon", MAROON, "Lucky"):  # a colour is served as rgb
            assert needle not in text, needle
        for s in look.slots:
            if s.slot in m.PRIVATE_SLOTS:
                assert s.private and s.template is None and s.rgb is None and s.photo is None
                assert s.pattern is None and s.options == () and s.words == m.COVERED
            assert all(o.piece not in (T.vest, T.under) for o in s.options)


async def test_avt14_looks_a_gap_naming_a_private_piece_is_said_without_it() -> None:
    a = await a_world()
    await a.move(T.under)
    look = await a.service.looks.for_day(UID, "tomorrow")
    assert look.gaps and all(T.under not in g for g in look.gaps)
    assert looks.PRIVATE_GAP in look.gaps


async def test_avt14_looks_a_piece_made_private_is_never_another_slots_option() -> None:
    a = await a_world()
    pid = await a.plan()  # the plan's top is the white shirt
    await a.w.edit(T.white, private=True, label="Lucky shirt", colour="maroon")  # private since
    plan = await a.service.looks.for_plan(UID, pid)
    shown = await a.service.looks.for_pieces(UID, f"top:{T.shirt}")  # another top is shown
    top = _slots(shown)["top"]
    assert top.piece == T.shirt and len(top.options) > 1  # the slot offers other tops ...
    for look in (plan, shown):
        assert all(o.piece != T.white for s in look.slots for o in s.options)  # ... never it
        text = json.dumps(look.model_dump(mode="json"))
        for needle in (T.white, "Lucky", MAROON):
            assert needle not in text, needle


async def test_avt14_looks_a_piece_he_made_private_is_covered_in_any_slot() -> None:
    a = await a_world()
    await a.w.edit(T.tee, private=True)
    got = _slots(await a.service.looks.for_pieces(UID, f"top:{T.tee}"))["top"]
    assert got.private and got.piece is None and got.rgb is None and got.options == ()


# ---- off or not ready -------------------------------------------------------------------------
async def test_with_styling_off_or_failed_the_look_says_so() -> None:
    a = await a_world()
    a.parts.pop("styling")
    with pytest.raises(looks.StylingOff):
        await a.service.looks.for_day(UID, "today")


async def test_no_store_yet_the_look_says_so() -> None:
    a = await a_world()

    async def none(uid: str) -> Any:
        return None

    a.styling.view = none  # type: ignore[method-assign]
    with pytest.raises(looks.StylingOff):
        await a.service.looks.for_day(UID, "today")


async def test_a_photos_view_is_read_only_for_a_sound_owner_id() -> None:
    from jarvis.storage.docs import Set

    a = await a_world()
    odd = "../wardrobe"
    await a.docs.write([Set(f"jarvis_wardrobe_photo/{odd}_wh_00000000a001",
                            {"owner": odd, "view": "front"})])  # fmt: skip
    assert await looks.photo_views(a.docs, "jarvis_", odd, ["wh_00000000a001"]) == {}
    mine = await looks.photo_views(a.docs, "jarvis_", UID, ["wh_00000000a001", "wh_00000000a002"])
    assert mine == {"wh_00000000a001": "front", "wh_00000000a002": "back"}

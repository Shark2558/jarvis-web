# tests/test_r131_tryon_card.py -- R13.1 row 388 (docs/plans/r13-1-try-on.md D21). The owner,
# 17 Nov 2026: "whenever I ask what to wear, jarvis should open up the card, decide and show me
# on the 3D model". The server half, I0's: while Try-on is on, `outfit_suggest` (R13's rules
# decide the look) puts ONE reply card of kind "tryon" beside its result: the day, the plan when
# a plan answered, the dress code and the primary look's slot -> piece ids, a private slot as
# covered only (AVT-14). The console opens it by itself (Part D). None while Try-on is off; the
# AI never sees it. Written first and run red.
from __future__ import annotations

from typing import Any

import pytest
from r13_fakes_c import ist, settings, world

from jarvis.tools.reply_cards import TryOnCard, collecting_cards


async def _suggest(w: Any, **args: Any) -> tuple[Any, list[Any]]:
    cards: list[Any] = []
    with collecting_cards(cards):
        got = await w.call("outfit_suggest", **args)
    return got, cards


async def test_asking_what_to_wear_puts_one_tryon_card_beside_the_answer() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    got, cards = await _suggest(w, day="tomorrow")
    [card] = [c for c in cards if c.kind == "tryon"]
    assert isinstance(card, TryOnCard) and card.day == "2026-11-17"
    look = got.result["looks"][0]
    want = {p["slot"]: tuple(p["ids"]) for p in look["pieces"] if p.get("ids")}
    shown = {s.slot: s.pieces for s in card.slots if not s.private}
    assert shown == {k: v for k, v in want.items() if k not in ("base", "underwear")}
    assert "card" not in str(got.result) and "tryon" not in got.result  # the AI never sees it


async def test_a_private_slot_is_covered_on_the_card() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    _, cards = await _suggest(w, day="tomorrow", code="business_formal")
    [card] = [c for c in cards if c.kind == "tryon"]
    covered = {s.slot for s in card.slots if s.private}
    assert {"base", "underwear"} <= covered  # the formal look has both: never vacuous
    for slot in card.slots:
        if slot.slot in ("base", "underwear"):
            assert slot.private and slot.pieces == ()  # never an id of a private piece (AVT-14)
    sent = card.model_dump_json()
    assert all(pid not in sent for pid in ("wi_000000000009", "wi_00000000000b"))


def test_the_card_rides_the_chat_reply_and_never_telegram() -> None:
    from pydantic import TypeAdapter

    from jarvis.telegram.format import card_lines
    from jarvis.tools.reply_cards import ReplyCard

    card = TryOnCard(day="2026-11-17", code="smart_casual",
                     slots=[{"slot": "top", "pieces": ["wi_000000000003"]}])  # fmt: skip
    rows = TypeAdapter(list[ReplyCard])  # what ChatResponse.cards is
    [back] = rows.validate_python([card.model_dump()])
    assert isinstance(back, TryOnCard) and rows.dump_python([back])[0]["kind"] == "tryon"
    assert card_lines([card]) == []  # Telegram shows no 3D card


async def test_a_planned_day_names_its_plan_on_the_card() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    saved = await w.call("outfit_plan", action="save", day="tomorrow", occasion="meeting")
    _, cards = await _suggest(w, day="tomorrow", occasion="meeting")
    [card] = [c for c in cards if c.kind == "tryon"]
    assert card.plan == saved.result["plan"]["id"]


async def test_no_card_while_try_on_is_off_or_outside_a_reply() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0), s=settings(tryon_enabled=False))
    _, cards = await _suggest(w, day="tomorrow")
    assert [c for c in cards if c.kind == "tryon"] == []
    on = await world(at=ist(2026, 11, 16, 20, 0))
    got = await on.call("outfit_suggest", day="tomorrow")  # no reply collects cards: a script
    assert got.result["looks"]  # the answer itself is unchanged


def test_the_card_refuses_what_it_must_not_carry() -> None:
    from pydantic import ValidationError

    TryOnCard(day="2026-11-17", slots=[{"slot": "top", "pieces": ["wi_000000000001"]}])
    for bad in (
        {"day": "tomorrow"},
        {"day": "2026-11-17", "slots": [{"slot": "base", "private": True,
                                         "pieces": ["wi_000000000009"]}]},
        {"day": "2026-11-17", "label": "My office shirt"},
    ):  # fmt: skip
        with pytest.raises(ValidationError):
            TryOnCard.model_validate(bad)


async def test_one_reply_shows_one_tryon_card_the_first_look_asked() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    cards: list[Any] = []
    with collecting_cards(cards):
        await w.call("outfit_suggest", day="tomorrow")
        await w.call("outfit_suggest", day="today")  # a second ask in the same reply
    assert [c.day for c in cards if c.kind == "tryon"] == ["2026-11-17"]


def test_the_control_a_reply_without_the_card_fails_row_388() -> None:
    # row 388's control (D21): the card left out of the reply -> the named check reports it
    from jarvis.wardrobe.styling import tryon_card

    assert tryon_card.missing([]) == "no try-on card in the reply"
    card = TryOnCard(day="2026-11-17", slots=[{"slot": "top", "pieces": ["wi_000000000003"]}])
    assert tryon_card.missing([card]) == ""

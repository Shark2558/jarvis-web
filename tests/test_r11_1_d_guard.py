# tests/test_r11_1_d_guard.py -- R11.1 Part D, O9 (docs/plans/r11-1-observations.md D17, D21-D):
# the DETERMINISTIC guard of picture research (`jarvis.picture.guard`), with no model and no
# network. The first look at a picture answers strict JSON; this code decides what may be said and
# what may be searched from it:
#   - anything that is not exactly the schema is thrown away (fail closed);
#   - a search runs only for something named as a THING, never for a person-shaped query and
#     never for a bare name, whatever "kind" the look claimed;
#   - with a person in the picture the description keeps only sentences free of names and hints;
#   - a name is accepted only when it is literally in the picture's own text (a caption, a name
#     board), and then only as an offer: this code never searches it.
# Every person named here is made up.
from __future__ import annotations

import json

import pytest

from jarvis.picture.guard import (
    KINDS,
    NO_IDENTIFY,
    PERSON_FALLBACK,
    Seen,
    Subject,
    judge,
    name_from_text,
    parse_seen,
    person_shaped,
    screen_scene,
    thing_shaped,
)

NAME = "Lekha Examplekar"  # a made-up person


def _seen(**over: object) -> Seen:
    base: dict[str, object] = {
        "has_person": False,
        "scene": "A packet of biscuits on a wooden table.",
        "text": ["PARLE-G", "GLUCOSE BISCUITS"],
        "subjects": [{"kind": "product", "name": "Parle-G biscuit packet"}],
        "named_in_text": "",
    }
    base.update(over)
    got = parse_seen(json.dumps(base))
    assert got is not None
    return got


# ---- the strict schema ---------------------------------------------------------------------------
def test_the_first_look_is_read_only_when_it_is_exactly_the_schema() -> None:
    seen = _seen()

    assert seen.has_person is False and seen.text == ("PARLE-G", "GLUCOSE BISCUITS")
    assert seen.subjects == (Subject("product", "Parle-G biscuit packet"),)
    assert seen.scene.startswith("A packet") and seen.named_in_text == ""


def test_only_the_two_required_keys_are_needed() -> None:
    seen = parse_seen('{"has_person": true, "subjects": []}')

    assert seen == Seen(has_person=True, subjects=())


def test_a_fenced_answer_is_read_and_surrounding_chatter_is_not() -> None:
    body = '{"has_person": false, "subjects": []}'

    assert parse_seen(f"```json\n{body}\n```") is not None
    assert parse_seen(f"Here you go:\n{body}") is None
    assert parse_seen(f"{body}\nHope that helps!") is None


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not json",
        "[]",
        '{"subjects": []}',  # has_person missing
        '{"has_person": "yes", "subjects": []}',  # not a boolean
        '{"has_person": 1, "subjects": []}',
        '{"has_person": true, "subjects": {}}',
        '{"has_person": true, "subjects": [], "who": "someone"}',  # an unknown key
        '{"has_person": true, "subjects": [{"kind": "person", "name": "x"}]}',  # unknown kind
        '{"has_person": true, "subjects": [{"kind": "product"}]}',
        '{"has_person": true, "subjects": [{"kind": "product", "name": 7}]}',
        '{"has_person": true, "subjects": [{"kind": "product", "name": "x", "url": "y"}]}',
        '{"has_person": true, "subjects": [], "text": "one string"}',
        '{"has_person": true, "subjects": [], "text": [1]}',
        '{"has_person": true, "subjects": [], "scene": ["a"]}',
        '{"has_person": true, "subjects": [], "named_in_text": null}',
    ],
)
def test_anything_else_is_thrown_away(raw: str) -> None:
    assert parse_seen(raw) is None


def test_too_much_is_thrown_away_too() -> None:
    many = [{"kind": "product", "name": f"thing {i} box"} for i in range(7)]

    assert parse_seen(json.dumps({"has_person": False, "subjects": many})) is None
    assert parse_seen(json.dumps({"has_person": False, "subjects": [], "scene": "x" * 601})) is None
    long_name = {"kind": "product", "name": "x" * 81}
    assert parse_seen(json.dumps({"has_person": False, "subjects": [long_name]})) is None
    claimed = {"has_person": True, "subjects": [], "named_in_text": "x" * 81}
    assert parse_seen(json.dumps(claimed)) is None
    assert parse_seen("{" + '"a":1,' * 5000 + '"has_person": true, "subjects": []}') is None


def test_invisible_and_control_characters_never_survive_the_read() -> None:
    seen = _seen(scene="A​ packet\x00 of‮ biscuits.", text=["PAR​LE-G"])

    assert seen.scene == "A packet of biscuits." and seen.text == ("PARLE-G",)


def test_the_kinds_are_a_closed_list_without_person() -> None:
    assert "person" not in KINDS and "other" in KINDS and len(set(KINDS)) == len(KINDS)


# ---- person-shaped: never searched ---------------------------------------------------------------
@pytest.mark.parametrize(
    "query",
    [
        "man in a blue shirt",
        "woman wearing a red sari",
        "who is this actor",
        "famous politician at a rally",
        "the girl I saw at the station",
        "bearded guy with glasses",
        "selfie of two people",
        "looks like a film star",
        "his face",
        "w o m a n in red",  # spaced out
        "wоman in red",  # a Cyrillic o
        "identify this cricketer",
    ],
)
def test_a_description_of_a_person_is_person_shaped(query: str) -> None:
    assert person_shaped(query) is True
    assert thing_shaped(query) is False


@pytest.mark.parametrize(
    "name",
    [
        NAME,  # a bare name, capitalised
        NAME.lower(),  # ... or not
        "Examplekar",  # one word
        f"{NAME} name board",  # a name on something that only carries names
        f"{NAME} poster",
        f"{NAME} visiting card",
        "Royal Enfield",  # even a brand, when nothing says what kind of thing it is
        "",
        "   ",
    ],
)
def test_a_bare_name_is_never_a_thing(name: str) -> None:
    assert thing_shaped(name) is False


@pytest.mark.parametrize(
    "name",
    [
        "Parle-G biscuit packet",
        "Charminar monument",
        "Taj Mahal",
        "India Gate",
        "Tata Nexon car",
        "iPhone 15 phone",
        "hibiscus flower",
        "harbour bridge",
        "masala dosa dish",
        "Royal Enfield motorcycle",
        "Gateway of India",
        "Examplekar Motors logo",
        "Old Monk rum",
    ],
)
def test_something_named_as_a_thing_is_thing_shaped(name: str) -> None:
    assert thing_shaped(name) is True and person_shaped(name) is False


# ---- what may be searched ------------------------------------------------------------------------
def test_a_product_with_no_person_is_searched() -> None:
    v = judge(_seen())

    assert v.person is False and [s.name for s in v.queries] == ["Parle-G biscuit packet"]
    assert v.scene.startswith("A packet") and v.named == "" and v.withheld == 0


def test_a_person_listed_as_a_subject_is_neither_searched_nor_shown() -> None:
    seen = _seen(
        has_person=True,
        scene="A woman in a blue sari stands on a bridge.",
        text=[],
        subjects=[
            {"kind": "other", "name": NAME},
            {"kind": "landmark", "name": NAME},  # mislabelled: still only a name
            {"kind": "product", "name": "woman in a blue sari"},
            {"kind": "landmark", "name": "harbour bridge"},
        ],
    )

    v = judge(seen)

    assert [s.name for s in v.queries] == ["harbour bridge"]
    assert [s.name for s in v.subjects] == ["harbour bridge"]
    assert v.withheld == 3
    assert NAME not in json.dumps([v.scene, v.text, [s.name for s in v.subjects], v.named])


def test_other_and_document_kinds_are_described_but_never_searched() -> None:
    seen = _seen(
        subjects=[
            {"kind": "document", "name": "electricity bill"},
            {"kind": "other", "name": "wooden table"},
            {"kind": "food", "name": "masala dosa dish"},
        ]
    )

    v = judge(seen)

    assert [s.name for s in v.queries] == ["masala dosa dish"]
    assert [s.name for s in v.subjects] == ["electricity bill", "wooden table", "masala dosa dish"]


def test_at_most_two_searches_and_one_when_a_person_is_in_the_picture() -> None:
    things = [{"kind": "product", "name": f"gadget {i} phone"} for i in range(1, 5)]

    assert len(judge(_seen(subjects=things)).queries) == 2
    assert len(judge(_seen(subjects=things, has_person=True)).queries) == 1


def test_the_same_thing_is_searched_once() -> None:
    twice = [{"kind": "product", "name": "Parle-G biscuit packet"}] * 2

    assert len(judge(_seen(subjects=twice)).queries) == 1


# ---- the description of a picture with a person --------------------------------------------------
def test_a_plain_description_of_a_person_is_kept() -> None:
    scene = "A woman in a blue sari stands on a bridge. She is cutting a red ribbon."

    assert screen_scene(scene) == scene


@pytest.mark.parametrize(
    "sentence",
    [
        f"This is {NAME}, the minister for ports.",
        f"{NAME} is cutting a ribbon.",
        f"A woman who looks like {NAME} stands on a bridge.",
        "She looks like a famous actor.",
        "The man resembles a well-known politician.",
        "Probably a celebrity at a film event.",
        "Mammootty smiles at the camera.",  # one word, first in its sentence
        "A man, known as the captain, raises a cup.",
    ],
)
def test_a_sentence_that_names_or_hints_is_dropped(sentence: str) -> None:
    kept = "A crowd stands behind a rope."

    assert screen_scene(f"{sentence} {kept}") == kept
    assert screen_scene(sentence) == PERSON_FALLBACK


def test_what_was_withheld_cannot_come_back_through_the_description() -> None:
    """A name the look also listed as a subject (or claimed as text) is banned from the
    description in any letter case: lower case has no capital for the other rule to see."""
    lowered = f"The woman, {NAME.lower()}, waves. A boat passes behind."

    assert screen_scene(lowered, banned=(NAME,)) == "A boat passes behind."
    seen = _seen(
        has_person=True,
        scene=lowered,
        text=[],
        subjects=[{"kind": "other", "name": NAME}],
    )
    assert judge(seen).scene == "A boat passes behind."


def test_a_named_thing_may_stay_in_the_description() -> None:
    scene = (
        "A man stands in front of India Gate. He holds a Samsung phone. "
        "Behind him is the Gateway of India."
    )

    assert screen_scene(scene) == scene


def test_a_sentence_in_another_script_is_dropped_because_it_has_no_capitals_to_check() -> None:
    assert screen_scene("ഇത് ഒരാളാണ്. A man stands by a gate.") == "A man stands by a gate."


@pytest.mark.parametrize(
    ("claimed", "ok"),
    [
        ("K R Examplekar", True),  # initials
        ("A. P. J. Examplekar", True),  # "A" is an initial here, not the article
        ("Dr Examplekar", True),
        ("Examplekar", True),  # one word, as on a jersey
        ("Minister Examplekar", False),  # a role is not part of the name
        ("Welcome", False),
        ("Examplekar Bridge", False),  # that is a thing
    ],
)
def test_the_shape_of_a_name(claimed: str, ok: bool) -> None:
    seen = _seen(has_person=True, text=[f"SHRI {claimed.upper()} 2026"], named_in_text=claimed)

    assert (judge(seen).named == claimed) is ok


def test_the_screen_is_used_only_when_a_person_is_in_the_picture() -> None:
    scene = f"A statue beside the {NAME} Memorial Hall."

    assert judge(_seen(scene=scene)).scene == scene
    assert judge(_seen(scene=f"This is {NAME}.", has_person=True)).scene == PERSON_FALLBACK


# ---- D21-D: a name only from the picture's own words ---------------------------------------------
def test_a_name_written_in_the_picture_is_offered_and_never_searched() -> None:
    seen = _seen(
        has_person=True,
        scene="A woman in a blue sari cuts a ribbon on a bridge.",
        text=[f"MINISTER {NAME.upper()} OPENS THE HARBOUR BRIDGE"],
        subjects=[
            {"kind": "landmark", "name": "harbour bridge"},
            {"kind": "landmark", "name": f"{NAME} bridge"},  # carries the name: not searched
        ],
        named_in_text=NAME,
    )

    v = judge(seen)

    assert v.named == NAME
    assert [s.name for s in v.queries] == ["harbour bridge"]
    assert all(NAME.lower() not in s.name.lower() for s in v.queries)


def test_a_name_that_is_not_in_the_pictures_text_is_refused() -> None:
    no_text = _seen(has_person=True, text=[], named_in_text=NAME)
    other_text = _seen(has_person=True, text=["HARBOUR BRIDGE 2026"], named_in_text=NAME)
    half = _seen(has_person=True, text=["LEKHA OPENS THE BRIDGE"], named_in_text=NAME)

    for seen in (no_text, other_text, half):
        assert name_from_text(seen) == "" and judge(seen).named == ""


@pytest.mark.parametrize(
    "claimed",
    [
        "the woman in the blue sari",  # a description, not a name
        "who is she",
        "OPENS THE HARBOUR BRIDGE",  # words of the caption that are not a name
        "Xy " * 6,  # six words
        "Lekha Examplekar and five other people at the event today",
        "L3kha 3xamplekar",
    ],
)
def test_only_something_shaped_like_a_name_is_offered(claimed: str) -> None:
    seen = _seen(has_person=True, text=[claimed, "OPENS THE HARBOUR BRIDGE"], named_in_text=claimed)

    assert judge(seen).named == ""


def test_the_offer_is_made_for_a_picture_without_a_person_too() -> None:
    seen = _seen(  # a book cover: the author's name is printed on it
        scene="A book cover with a lighthouse.",
        text=["THE LAST LIGHTHOUSE", NAME.upper()],
        subjects=[{"kind": "product", "name": "The Last Lighthouse book"}],
        named_in_text=NAME,
    )

    v = judge(seen)

    assert v.named == NAME and [s.name for s in v.queries] == ["The Last Lighthouse book"]


# ---- the negative control ------------------------------------------------------------------------
def test_with_the_guard_off_a_name_gets_through_everywhere() -> None:
    seen = _seen(
        has_person=True,
        scene=f"This is {NAME}, the minister.",
        text=[],
        subjects=[{"kind": "other", "name": NAME}],
        named_in_text=NAME,
    )

    v = judge(seen, enabled=False)

    assert NAME in v.scene and v.named == NAME and [s.name for s in v.queries] == [NAME]


def test_the_fixed_sentence_is_the_plans() -> None:
    assert NO_IDENTIFY == "I don't identify people from pictures, Sir."
    assert PERSON_FALLBACK == "There is a person in the picture."

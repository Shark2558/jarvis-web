# tests/test_r11_1_d_screen.py -- R11.1 Part D, O9 after the security review (H2, M1, M2; code
# review M2): the picture guard distrusts the look's `has_person`, screens EVERY description, and
# never lets a name the picture does not print through a description, a subject or a search.
#   - a person picture is one the look SAYS has a person, or whose description or subjects are
#     about a person, whatever the flag says;
#   - in any description a capitalised word that is not the sentence's plain opener stays only
#     when the picture prints it or a vetted thing's name holds it; "this is <name>", a hint word,
#     another script, a sentence that starts with a lower-case name: dropped;
#   - a name holding a thing word ("Bill Gates", "<Name> statue") is never shown or searched
#     unless the picture prints every capitalised word of it; on a person picture a searched thing
#     is made only of thing words and words the picture prints;
#   - the offer of a name carries the very line of text it was read from.
# Every person named here is made up ("Bill Gates", "Jeff Bridges", "Daniel Hill" are here only as
# SHAPES: surnames that are also thing words).
from __future__ import annotations

import json

import pytest

from jarvis.picture.guard import NO_IDENTIFY, PERSON_FALLBACK, Seen, Verdict, judge, parse_seen
from jarvis.picture.research import compose

NAME = "Rajesh Examplekar"  # a made-up person


def _seen(**over: object) -> Seen:
    base: dict[str, object] = {
        "has_person": False,
        "scene": "",
        "text": [],
        "subjects": [],
        "named_in_text": "",
    }
    base.update(over)
    got = parse_seen(json.dumps(base))
    assert got is not None
    return got


def _everything(v: Verdict) -> str:
    return json.dumps(
        [v.scene, v.text, [s.name for s in v.subjects], [s.name for s in v.queries], v.named]
    )


def _gone(v: Verdict, *words: str) -> bool:
    said = _everything(v).lower()
    return not any(w.lower() in said for w in words)


# ---- H2: the flag is not trusted, and every description is screened ------------------------------
def test_the_builders_own_case_has_person_false_but_the_description_names_a_minister() -> None:
    v = judge(_seen(scene=f"This is {NAME}, the minister for ports."))

    assert v.person is True  # "the minister" is about a person, whatever the flag said
    assert v.scene == PERSON_FALLBACK and _gone(v, "Rajesh", "Examplekar")
    assert NO_IDENTIFY in compose(v, ())


@pytest.mark.parametrize(
    "scene",
    [
        f"This is {NAME} inspecting cranes.",
        f"this is {NAME.lower()} inspecting cranes.",  # lower case: no capital to see
        f"Here is {NAME} at the port.",
        f"{NAME.lower()} at a podium.",  # a sentence that starts with a lower-case name
        f"A crane beside {NAME.upper()}.",  # ALL CAPS is a capital too
        f"A crane beside {NAME}.",
        "A poster of a famous film star on a wall.",  # a hint, also with has_person false
        "राजेश उदाहरण. A crane on a dock.",
    ],
)
def test_a_picture_without_a_person_flag_keeps_no_name_from_its_description(scene: str) -> None:
    v = judge(_seen(scene=scene))

    assert _gone(v, "Rajesh", "Examplekar", "famous", "राजेश")


@pytest.mark.parametrize(
    ("scene", "subjects", "text", "person"),
    [
        (
            "A harbour at dusk with three cargo ships and a crane.",
            [{"kind": "place", "name": "Cochin harbour"}],
            [],
            False,
        ),
        (
            "The Gateway of India stands beside the sea.",
            [{"kind": "landmark", "name": "Gateway of India monument"}],
            [],
            False,
        ),
        (
            "A woman holds a Samsung phone.",
            [{"kind": "product", "name": "Samsung phone"}],
            ["SAMSUNG"],
            True,
        ),
        (
            "A shop front with the sign Parle Biscuits above the door.",
            [],
            ["Parle Biscuits"],
            False,
        ),
        ("This is a photo of a quiet street with parked bikes.", [], [], False),
        ("A packet of biscuits on a wooden table.", [], ["PARLE-G"], False),
    ],
)
def test_ordinary_descriptions_come_through_word_for_word(
    scene: str, subjects: list[dict[str, str]], text: list[str], person: bool
) -> None:
    v = judge(_seen(has_person=person, scene=scene, subjects=subjects, text=text))

    assert v.scene == scene and v.person is person
    assert [s.name for s in v.subjects] == [s["name"] for s in subjects]


def test_the_ordinary_ones_are_still_searched() -> None:
    harbour = judge(_seen(subjects=[{"kind": "place", "name": "Cochin harbour"}]))
    gateway = judge(_seen(subjects=[{"kind": "landmark", "name": "Gateway of India monument"}]))
    phone = judge(
        _seen(
            has_person=True,
            scene="A woman holds a Samsung phone.",
            text=["SAMSUNG"],
            subjects=[{"kind": "product", "name": "Samsung phone"}],
        )
    )

    assert [s.name for s in harbour.queries] == ["Cochin harbour"]
    assert [s.name for s in gateway.queries] == ["Gateway of India monument"]
    assert [s.name for s in phone.queries] == ["Samsung phone"]


def test_a_bare_name_listed_as_a_subject_is_not_shown_without_a_person_either() -> None:
    v = judge(_seen(subjects=[{"kind": "product", "name": NAME}, {"kind": "other", "name": NAME}]))

    assert v.subjects == () and v.queries == () and v.withheld == 2


def test_with_no_sentence_left_a_thing_picture_says_nothing_rather_than_the_person_line() -> None:
    v = judge(_seen(scene=f"A crane beside {NAME}."))

    assert v.person is False and v.scene == ""


# ---- M1: thing words that are surnames, and "<Name> statue" --------------------------------------
@pytest.mark.parametrize("person", [False, True])
@pytest.mark.parametrize(
    "name",
    [
        "Bill Gates",
        "Jeff Bridges",
        "BILL GATES",
        f"{NAME} statue",
        f"{NAME} shirt",
        f"{NAME.upper()} statue",
    ],
)
def test_a_name_holding_a_thing_word_is_neither_shown_nor_searched(name: str, person: bool) -> None:
    v = judge(_seen(has_person=person, subjects=[{"kind": "product", "name": name}]))

    assert v.subjects == () and v.queries == ()


@pytest.mark.parametrize(
    "scene",
    [
        "A man next to Bill Gates at a desk.",
        "A woman talks with Jeff Bridges.",
        "A man beside Daniel Hill on a stage.",
    ],
)
def test_a_surname_that_is_a_thing_word_does_not_pass_the_description(scene: str) -> None:
    v = judge(_seen(has_person=True, scene=scene))

    assert v.scene == PERSON_FALLBACK


def test_a_name_holding_a_thing_word_may_be_shown_when_the_picture_prints_it() -> None:
    plaque = f"{NAME.upper()} 1931-2001"
    v = judge(_seen(text=[plaque], subjects=[{"kind": "landmark", "name": f"{NAME} statue"}]))

    assert [s.name for s in v.subjects] == [f"{NAME} statue"]


def test_on_a_person_picture_a_searched_thing_is_made_only_of_printed_and_thing_words() -> None:
    printed = judge(
        _seen(
            has_person=True,
            text=["SAMSUNG"],
            subjects=[{"kind": "product", "name": "Samsung phone"}],
        )
    )
    unprinted = judge(
        _seen(has_person=True, subjects=[{"kind": "product", "name": "Samsung phone"}])
    )
    lowered = judge(
        _seen(
            has_person=True,
            subjects=[{"kind": "landmark", "name": f"{NAME.lower()} statue"}],
        )
    )

    assert [s.name for s in printed.queries] == ["Samsung phone"]
    assert unprinted.queries == () and [s.name for s in unprinted.subjects] == ["Samsung phone"]
    assert lowered.queries == ()


# ---- code review M2: a claimed caption that is not there is banned, whatever the flag ------------
def test_an_unverified_caption_name_cannot_come_back_through_a_thing_pictures_description() -> None:
    seen = _seen(
        scene=f"A poster shows {NAME.lower()} on a wall. A bus passes.",
        text=["CITY BUS"],
        named_in_text=NAME,  # the look claims it, the text does not hold it
    )

    v = judge(seen)

    assert v.named == "" and v.scene == "A bus passes."
    assert "examplekar" not in compose(v, ()).lower()


# ---- security M2: the offer shows the very line it was read from ---------------------------------
def test_the_offer_carries_the_caption_line_it_came_from() -> None:
    line = f"MINISTER {NAME.upper()} OPENS THE HARBOUR BRIDGE"
    seen = _seen(
        has_person=True,
        scene="A person in a blue top cuts a ribbon.",
        text=["PORT DAY 2026", line],
        named_in_text=NAME,
    )

    v = judge(seen)
    said = compose(v, ())

    assert v.named == NAME and v.caption == line
    assert f"The picture's text names {NAME}. Caption read: '{line}'." in said
    assert said.endswith(f"Shall I look {NAME} up from public sources, Sir?")


def test_no_offer_means_no_caption() -> None:
    v = judge(_seen(has_person=True, text=["PORT DAY 2026"], named_in_text=NAME))

    assert v.named == "" and v.caption == ""

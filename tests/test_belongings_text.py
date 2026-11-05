# tests/test_belongings_text.py -- R2 D11: the key that makes "my passport" and "Passport" one,
# and the storage-sentence detector that keeps recall from learning where things are kept.
from __future__ import annotations

import pytest

from jarvis.belongings.text import looks_like_storage, thing_key


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("My passport", "Passport"),
        ("the passport", "PASSPORT"),
        ("Spare keys", "spare key"),
        ("our Keys", "key"),
        ("Specs", "glasses"),
        ("my spectacles", "Glasses"),
        ("DL", "driving licence"),
        ("driving license", "Driving Licence"),
        ("licence", "my DL"),
        ("  A   gold  chain ", "gold chain"),
        ("passport\u200b", "passport"),
        ("\uff30assport", "passport"),
    ],
)
def test_these_name_one_thing(a: str, b: str) -> None:
    assert thing_key(a) == thing_key(b) != ""


@pytest.mark.parametrize(("a", "b"), [("passport", "visa"), ("car key", "house key")])
def test_these_are_different_things(a: str, b: str) -> None:
    assert thing_key(a) != thing_key(b)


@pytest.mark.parametrize("junk", ["", "   ", "my", "the a", None, 5])
def test_nothing_left_is_an_empty_key(junk: object) -> None:
    assert thing_key(junk) == ""  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "text",
    [
        "Passport is kept in the blue file",
        "Keeps the gold in the bank locker",
        "Spare keys are in the top drawer",
        "Stores his documents in a steel almirah",
        "Put the passport on the top shelf",
        "The car papers are inside the glove box",
        "Spare key lives in the steel almirah",
        "The spare key is under the flowerpot",
        "Owner hides the house keys under the mat",
        "Gold is kept with his sister",
        "Owner's passport is located in the almirah",
        "Keys on the hook by the door",
    ],
)
def test_storage_sentences_are_flagged(text: str) -> None:
    assert looks_like_storage(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Prefers tea in the morning",
        "Lives in Thiruvananthapuram",
        "Keeps in touch with his sister",
        "Works at Amnex Infotechnologies",
        "Owner works in the office",
        "Sister lives in the house next door",
        "Daughter studies at the school near home",
        "Daughter is in class five",
        "",
    ],
)
def test_ordinary_facts_are_not_flagged(text: str) -> None:
    assert looks_like_storage(text) is False

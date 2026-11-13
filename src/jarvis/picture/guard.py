# src/jarvis/picture/guard.py
"""The deterministic guard of picture research (R11.1 D17, D21-D; Layer 4, guardrails).

JARVIS researches a picture of a THING (a product, a place, a landmark, a label, a logo). It never
identifies a person from a picture, for anyone. The first look at a picture is one vision call
that answers strict JSON (`parse_seen`); everything after that is plain code, no model, no
network (this module, `jarvis.picture.scene` and `jarvis.picture.words`). It decides what may be
said and searched, whatever the look wrote:

- **Fail closed.** An answer that is not exactly the schema is thrown away.
- **The look's `has_person` is not trusted alone.** A picture is a person picture when the look
  says so, OR its description or one of its subjects is about a person ("the minister").
- **Every description is screened** (`scene.vet_scene`): a capitalised word that is not the
  sentence's plain opener stays only when the picture prints it or a vetted thing's name holds
  it; "this is <name>", hints, another script and a lower-case name at the start go. A person
  picture's description is screened again (`scene.screen_scene`) and gets the fixed sentence.
- **A subject is shown only when it is a thing** (or a plain lower-case description of one, on a
  picture without a person) **and names nobody the picture does not print** (`_printed_or_plain`):
  "Bill Gates" (its only thing word is part of the name) and "<Name> statue" (two capitalised
  words in a row) are shown and searched only when the picture prints every capitalised word.
- **A search runs only for a thing**: a searchable kind, thing-shaped, never the offered name;
  on a person picture only a thing made of thing words and words the picture prints. At most
  `MAX_QUERIES`; one with a person.
- **A name can come only from the picture's own words** (D21-D): `caption_of` accepts the look's
  `named_in_text` only when those very words are on one line of the text it read, and the name
  is shaped like one. It is only ever OFFERED, with that line (`Verdict.caption`), so the owner
  sees where it came from; the look-up is the people research behind its unchanged check.

`judge(seen, enabled=False)` exists only so the eval can show its negative control (with the guard
off a name gets through); it is a parameter, never a setting.

What plain code cannot know: whether the look copied the picture's text faithfully. A caption the
look invented is still only an offer, shown with the line it claims, and the check decides.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from jarvis.picture.scene import PERSON_FALLBACK, screen_scene, vet_scene
from jarvis.picture.words import (
    NOT_NAME,
    THING_WORDS,
    capitalised,
    contains,
    is_thing_word,
    name_shaped,
    person_shaped,
    plain,
    raw_words,
    thing_shaped,
    word_set,
    words_of,
)
from jarvis.tools.external import clean_text, model_text

NO_IDENTIFY = "I don't identify people from pictures, Sir."
KINDS: tuple[str, ...] = (
    "product", "place", "landmark", "label", "logo", "artwork", "plant", "animal", "food",
    "document", "other",
)  # fmt: skip
SEARCHABLE = frozenset(KINDS) - {"document", "other"}
MAX_RAW = 8000  # characters of the look's answer; more is not a look
MAX_SUBJECTS = 6
NAME_MAX = 80
SCENE_MAX = 600
MAX_TEXTS = 12
TEXT_MAX = 200
MAX_QUERIES = 2
MAX_QUERIES_WITH_PERSON = 1
_KEYS = frozenset({"has_person", "subjects", "scene", "text", "named_in_text"})
_REQUIRED = frozenset({"has_person", "subjects"})
_FENCED = re.compile(r"\A```(?:json)?\s*\n(.*)\n```\Z", re.DOTALL)


@dataclass(frozen=True)
class Subject:
    kind: str
    name: str


@dataclass(frozen=True)
class Seen:
    """The first look's answer, exactly as the schema allows it (already cleaned)."""

    has_person: bool
    subjects: tuple[Subject, ...]
    scene: str = ""
    text: tuple[str, ...] = ()
    named_in_text: str = ""


@dataclass(frozen=True)
class Verdict:
    """What the tool may do with one picture."""

    person: bool  # the look said so, or its own words are about a person
    scene: str  # what is visible, screened
    text: tuple[str, ...]  # the picture's own words, as read
    subjects: tuple[Subject, ...]  # what may be shown
    queries: tuple[Subject, ...]  # what may be searched
    named: str  # a name read from the picture's own text ("" when none): an offer, never a search
    withheld: int  # subjects left out
    caption: str = ""  # the line of the picture's text the offered name was read from


# ---- reading the look's answer ---------------------------------------------------------------
def _clean(value: object, limit: int) -> str | None:
    """One clean line, or None when it is not text or is longer than the schema allows."""
    if not isinstance(value, str):
        return None
    text = " ".join(model_text(clean_text(value)).split())
    return text if len(text) <= limit else None


def _subject(raw: object) -> Subject | None:
    if not isinstance(raw, dict) or set(raw) != {"kind", "name"}:
        return None
    name = _clean(raw["name"], NAME_MAX)
    if raw["kind"] not in KINDS or not name:
        return None
    return Subject(str(raw["kind"]), name)


def _texts(raw: object) -> tuple[str, ...] | None:
    if not isinstance(raw, list) or len(raw) > MAX_TEXTS:
        return None
    lines = [_clean(item, TEXT_MAX) for item in raw]
    if any(line is None for line in lines):
        return None
    return tuple(line for line in lines if line)


def parse_seen(raw: str) -> Seen | None:
    """The look's answer when it is exactly the schema; None for anything else (fail closed)."""
    if len(raw) > MAX_RAW:
        return None
    body = raw.strip()
    fenced = _FENCED.match(body)
    try:
        data = json.loads(fenced.group(1) if fenced else body)
    except (ValueError, TypeError, RecursionError):
        return None
    if not isinstance(data, dict) or not _REQUIRED <= set(data) <= _KEYS:
        return None
    subjects = data["subjects"]
    if type(data["has_person"]) is not bool or not isinstance(subjects, list):
        return None
    if len(subjects) > MAX_SUBJECTS:
        return None
    found = [_subject(s) for s in subjects]
    scene = _clean(data.get("scene", ""), SCENE_MAX)
    text = _texts(data.get("text", []))
    named = _clean(data.get("named_in_text", ""), NAME_MAX)
    if any(s is None for s in found) or scene is None or text is None or named is None:
        return None
    return Seen(data["has_person"], tuple(s for s in found if s), scene, text, named)


# ---- a name only from the picture's own words ------------------------------------------------
def caption_of(seen: Seen) -> tuple[str, str]:
    """(the name, the line it is written on) when the look's `named_in_text` is literally on one
    line of the text it read off the picture and is shaped like a name; else ("", "")."""
    name = seen.named_in_text
    if not name or not name_shaped(name):
        return "", ""
    wanted = words_of(name)
    line = next((t for t in seen.text if contains(words_of(t), wanted)), "")
    return (name, line) if line else ("", "")


def name_from_text(seen: Seen) -> str:
    """The name the look says is WRITTEN in the picture, or "" (D21-D: never from a face)."""
    return caption_of(seen)[0]


# ---- which subjects may be shown and searched ------------------------------------------------
def _two_capitals_in_a_row(words: list[str]) -> bool:
    """A run of two or more capitalised words with no small word between: shaped like a full
    name ("Rajesh Examplekar"). "Gateway of India" is not one: "of" parts it."""
    run = 0
    for word in words:
        run = run + 1 if capitalised(word) and plain(word) not in NOT_NAME else 0
        if run >= 2:
            return True
    return False


def _printed_or_plain(name: str, printed: frozenset[str]) -> bool:
    """Does `name` name nobody the picture does not print? Every capitalised word printed in the
    picture; or a thing word written in lower case ("Cochin harbour", not "Bill Gates": there the
    only thing word is part of a name) and no two capitalised words in a row ("<Name> statue")."""
    words = raw_words(name)
    if all(plain(w) in printed for w in words if capitalised(w)):
        return True
    if not any(is_thing_word(plain(w)) for w in words if not capitalised(w)):
        return False
    return not _two_capitals_in_a_row(words)


def _shown(subject: Subject, person: bool, printed: frozenset[str]) -> bool:
    if person_shaped(subject.name) or not _printed_or_plain(subject.name, printed):
        return False
    if thing_shaped(subject.name):
        return True
    # a plain lower-case description ("electricity bill") of a picture without a person
    return not person and not any(capitalised(w) for w in raw_words(subject.name))


def _searchable(subject: Subject, named: str, person: bool, printed: frozenset[str]) -> bool:
    if subject.kind not in SEARCHABLE or not thing_shaped(subject.name):
        return False
    words = words_of(subject.name)
    if set(words_of(named)) & set(words):
        return False  # the offered name is never searched
    # with a person in the picture: only thing words and the picture's own words
    return not person or all(is_thing_word(w) or w in NOT_NAME or w in printed for w in words)


# ---- the verdict -----------------------------------------------------------------------------
def _unguarded(seen: Seen) -> Verdict:
    """The negative control: what the look wrote, taken at its word."""
    return Verdict(
        person=seen.has_person,
        scene=seen.scene,
        text=seen.text,
        subjects=seen.subjects,
        queries=seen.subjects[:MAX_QUERIES],
        named=seen.named_in_text,
        withheld=0,
        caption="",
    )


def is_person_picture(seen: Seen) -> bool:
    """The look's flag, or its own words about the picture are about a person."""
    return (
        seen.has_person
        or person_shaped(seen.scene)
        or any(person_shaped(s.name) for s in seen.subjects)
    )


def _scene(seen: Seen, person: bool, shown: tuple[Subject, ...], banned: list[str]) -> str:
    allowed = word_set([*seen.text, *(s.name for s in shown if thing_shaped(s.name))])
    scene = vet_scene(seen.scene, allowed, banned)
    if not person:
        return scene
    return screen_scene(scene, banned) if scene else PERSON_FALLBACK


def judge(seen: Seen, *, enabled: bool = True) -> Verdict:
    """What may be said and searched for one picture. `enabled=False` is the eval's control."""
    if not enabled:
        return _unguarded(seen)
    person = is_person_picture(seen)
    named, caption = caption_of(seen)
    printed = word_set(seen.text)
    shown = tuple(s for s in seen.subjects if _shown(s, person, printed))
    withheld = [s.name for s in seen.subjects if s not in shown]
    # a person picture's description never carries a name, not even a printed one (the offer
    # does); any picture's never carries a claimed caption that is not there
    banned = withheld + ([seen.named_in_text] if person or not named else [])
    queries: list[Subject] = []
    for subject in shown:
        if _searchable(subject, named, person, printed) and subject not in queries:
            queries.append(subject)
    limit = MAX_QUERIES_WITH_PERSON if person else MAX_QUERIES
    return Verdict(
        person=person,
        scene=_scene(seen, person, shown, banned),
        text=seen.text,
        subjects=shown,
        queries=tuple(queries[:limit]),
        named=named,
        withheld=len(withheld),
        caption=caption,
    )


__all__ = [
    "KINDS",
    "MAX_QUERIES",
    "MAX_QUERIES_WITH_PERSON",
    "NO_IDENTIFY",
    "PERSON_FALLBACK",
    "SEARCHABLE",
    "THING_WORDS",
    "Seen",
    "Subject",
    "Verdict",
    "caption_of",
    "is_person_picture",
    "judge",
    "name_from_text",
    "parse_seen",
    "person_shaped",
    "screen_scene",
    "thing_shaped",
]

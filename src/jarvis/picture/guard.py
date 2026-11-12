# src/jarvis/picture/guard.py
"""The deterministic guard of picture research (R11.1 D17, D21-D; Layer 4, guardrails).

JARVIS researches a picture of a THING (a product, a place, a landmark, a label, a logo). It never
identifies a person from a picture, for anyone. The first look at a picture is one vision call
that answers strict JSON (`parse_seen`); everything after that is this module: plain code, no
model, no network. It decides what may be said and what may be searched, whatever the look wrote:

- **Fail closed.** An answer that is not exactly the schema is thrown away: nothing is described
  and nothing is searched from it.
- **A search runs only for a thing.** A subject is searched only when its kind is searchable, its
  name is not person-shaped (`person_shaped`: "woman in a blue sari", "who is this actor") and its
  name says what kind of thing it is (`thing_shaped`: a word of `THING_WORDS`). A bare name is
  never a thing, whatever kind the look claimed for it, so a name the look took from a face can't
  reach the search vendor. At most `MAX_QUERIES`; one when a person is in the picture.
- **With a person in the picture the reply is a fixed template**: what is visible, then
  `NO_IDENTIFY`. The look's own description is screened sentence by sentence (`screen_scene`): a
  sentence that names, hints ("looks like", "famous") or carries a capitalised word that is not
  part of a named thing is dropped, and so is anything withheld as a subject.
- **A name can come only from the picture's own words** (D21-D): `name_from_text` accepts the
  look's `named_in_text` only when those words are literally in the text it read off the picture
  and are shaped like a name. It is only ever OFFERED: the look-up is the existing people research
  behind its unchanged check (`jarvis.people.gate`), and this module never searches it.

`judge(seen, enabled=False)` exists only so the eval can show its negative control (with the guard
off a name gets through); it is a parameter, never a setting.

What plain code cannot know: whether the look told the truth about `has_person`, or copied the
picture's text faithfully. Those rest on the look's own instructions (`jarvis.picture.eyes`) and
on the persona rule; the eval covers both.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from jarvis.people.guard import fold, variants
from jarvis.tools.external import clean_text, model_text

NO_IDENTIFY = "I don't identify people from pictures, Sir."
PERSON_FALLBACK = "There is a person in the picture."
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
MAX_NAME_WORDS = 5
_KEYS = frozenset({"has_person", "subjects", "scene", "text", "named_in_text"})
_REQUIRED = frozenset({"has_person", "subjects"})
_FENCED = re.compile(r"\A```(?:json)?\s*\n(.*)\n```\Z", re.DOTALL)

# Words that make a phrase ABOUT A PERSON: who they are, what they look like, how they are named.
_PERSON = re.compile(
    r"\b(?:man|men|woman|women|boy|boys|girl|girls|child|children|kid|kids|baby|babies|toddler|"
    r"teenager|person|persons|people|human|humans|guy|guys|lady|ladies|gentleman|gentlemen|crowd|"
    r"couple|bride|groom|face|faces|selfie|portrait|headshot|actor|actors|actress|actresses|"
    r"singer|musician|politician|minister|president|celebrity|celeb|cricketer|footballer|athlete|"
    r"sportsman|sportswoman|influencer|youtuber|superstar|he|she|him|her|his|hers|himself|"
    r"herself|who|whose|whom|whos|identity|identify|identified|lookalike|resembles?|resembling|"
    r"bearded|wearing|dressed|hair|beard|moustache|mustache)\b"
    r"|\blooks?\s+like\b|\bknown\s+as\b|\bname\s+of\b|\b(?:film|movie|tv|pop|rock)\s+star\b"
)
# In a description of a picture WITH a person: a sentence that says or hints who it is.
_HINT = re.compile(
    r"\b(?:looks?\s+like|look-?alike|resembl\w*|known\s+as|named|called|identified|famous|"
    r"celebrit\w*|celeb|well[- ]known|recogni[sz]\w*|probably|possibly|presumably|likely|"
    r"apparently|actor|actress|singer|politician|minister|president|cricketer|footballer|"
    r"superstar|film\s+star|movie\s+star|mla|mp)\b",
    re.IGNORECASE,
)
# Nouns that say what KIND OF THING a name is. Generic categories only: no word that is also a
# common given name (rose, lily, bill), and none that merely carries a person's name (board, sign,
# poster, card, banner, jersey, caption, photo, fan, house).
THING_WORDS = frozenset(
    """
    phone smartphone laptop computer tablet watch smartwatch camera lens television tv monitor
    printer router speaker headphone earphone earbud keyboard charger cable battery drone console
    car suv truck bus van scooter motorcycle motorbike bike bicycle cycle auto rickshaw tractor
    train locomotive aeroplane airplane aircraft plane helicopter ship boat ferry yacht
    fridge refrigerator cooker oven stove mixer grinder blender kettle toaster iron heater cooler
    conditioner purifier washer machine appliance device gadget tool drill
    bottle packet pack box can jar tin tube carton bag backpack wallet suitcase
    shoe sneaker sandal boot shirt tshirt jacket coat dress sari saree kurta jeans cap hat helmet
    book novel magazine newspaper notebook pen pencil toy game puzzle doll
    medicine tablet capsule syrup ointment cream lotion soap shampoo perfume toothpaste detergent
    tea coffee biscuit cookie chocolate snack chips drink juice soda beer wine whisky rum sauce
    pickle rice flour atta dal spice masala oil ghee butter cheese milk curd bread cake sweet
    dish curry dessert meal recipe fruit vegetable
    chair table sofa bed desk shelf cupboard lamp bulb clock mirror curtain carpet mattress
    coin banknote currency stamp
    temple church mosque masjid mandir gurudwara synagogue cathedral basilica shrine pagoda stupa
    monastery fort fortress palace mahal minar tower bridge dam lake river beach waterfall falls
    hill mountain mount peak valley island park garden bagh zoo sanctuary museum gallery memorial
    monument statue gate gateway dwar ghat station airport terminus port harbour harbor market
    bazaar mall
    street road highway square chowk circle building skyscraper hall library university college
    school hospital hotel resort restaurant cafe shop store showroom stadium arena city town
    village landmark ruins cave tomb lighthouse canal backwaters fountain pier jetty windmill
    tree plant flower leaf shrub cactus fern moss mushroom seed
    bird dog cat fish insect butterfly moth snake lizard spider animal breed cow goat horse
    elephant tiger lion monkey deer
    painting artwork sculpture mural drawing logo emblem brand label
    """.split()
)
# The first word of a plain sentence about what is visible (the only capitalised word it needs).
_OPENERS = frozenset(
    """
    a an the this that these those there here in on at behind beside near next inside outside
    above below under around with it its he she they his her their both many several some one two
    three four five six people someone everyone nobody no each all another other others most part
    also nearby further overhead between across along over beyond against among to from standing
    sitting walking holding seen shown visible
    """.split()
)
# Never part of a person's name (with the thing words and the person words above).
_NOT_NAME = frozenset(
    """
    the a an of and or in on at for with by to from is are was were be been opens opened opening
    inaugurates inaugurated welcome welcomes presents visit visits at as new our your my this that
    """.split()
)
_JOINS = frozenset({"of", "the", "and", "de", "da", "al"})  # inside a name: "Gateway of India"
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[^\W\d_][\w'’\-]*")


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

    person: bool
    scene: str  # what is visible (screened when a person is in the picture)
    text: tuple[str, ...]  # the picture's own words, as read
    subjects: tuple[Subject, ...]  # what may be shown
    queries: tuple[Subject, ...]  # what may be searched
    named: str  # a name read from the picture's own text ("" when none): an offer, never a search
    withheld: int  # subjects left out


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
    if not isinstance(raw, str) or len(raw) > MAX_RAW:
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


# ---- person or thing -------------------------------------------------------------------------
def _words(text: str) -> list[str]:
    """The folded words of `text` (lower case, accents and look-alikes read as plain letters)."""
    return [w.strip("'’-") for w in _WORD.findall(fold(text)) if w.strip("'’-")]


def person_shaped(text: str) -> bool:
    """Is this about a person: who they are or what they look like? Read through the people
    pre-filter's folding, so spaced-out letters and look-alike characters hide nothing."""
    return any(_PERSON.search(form) for form in variants(text))


def _is_thing_word(word: str) -> bool:
    return word in THING_WORDS or (word.endswith("s") and word[:-1] in THING_WORDS)


def thing_shaped(name: str) -> bool:
    """Does `name` say what kind of thing it is, and nothing about a person? A bare name (of a
    person, or of a brand with no thing named) is not a thing."""
    words = _words(name)
    return bool(words) and not person_shaped(name) and any(_is_thing_word(w) for w in words)


def _letters(word: str) -> bool:
    """Letters only (in any script: a vowel sign is a mark, not a digit or a symbol)."""
    plain = word.replace("'", "").replace("’", "").replace("-", "")
    return bool(plain) and all(unicodedata.category(ch)[0] in "LM" for ch in plain)


def _name_shaped(name: str) -> bool:
    """One to five words of letters (initials count), none of them a thing, a person word or a
    small word: "Lekha Examplekar", "K R Examplekar"; never "the woman in blue"."""
    words = _words(name)
    if not 1 <= len(words) <= MAX_NAME_WORDS or person_shaped(name):
        return False
    if not all(_letters(w) for w in words) or not any(len(w) > 1 for w in words):
        return False
    full = [w for w in words if len(w) > 1]  # a single letter is an initial, never "a" the article
    return not any(w in _NOT_NAME or _is_thing_word(w) for w in full)


def _contains(haystack: Sequence[str], needle: Sequence[str]) -> bool:
    n = len(needle)
    return n > 0 and any(list(haystack[i : i + n]) == list(needle) for i in range(len(haystack)))


def name_from_text(seen: Seen) -> str:
    """The name the look says is WRITTEN in the picture, when those very words are in the text it
    read off the picture and are shaped like a name; else "" (D21-D: never from a face)."""
    name = seen.named_in_text
    if not name or not _name_shaped(name):
        return ""
    wanted = _words(name)
    return name if any(_contains(_words(line), wanted) for line in seen.text) else ""


# ---- the description of a picture with a person ----------------------------------------------
def _run_end(words: list[str], start: int) -> int:
    """Where the run of capitalised words that begins at `start` ends ("Gateway of India" is one
    run: a small joining word between two capitalised words belongs to it)."""
    j = start
    while j < len(words):
        if words[j][:1].isupper():
            j += 1
        elif words[j] in _JOINS and j + 1 < len(words) and words[j + 1][:1].isupper():
            j += 2
        else:
            break
    return j


def _capital_runs_ok(words: list[str]) -> bool:
    """Every capitalised word after the first belongs to a named thing: its run of capitalised
    words holds a thing word, or the word right after the run is one ("a Samsung phone")."""
    i = 1
    while i < len(words):
        if not words[i][:1].isupper():
            i += 1
            continue
        j = _run_end(words, i)
        run = [fold(w).strip("'’-") for w in words[i : j + 1]]  # the run and the word after it
        if not any(_is_thing_word(w) for w in run):
            return False
        i = j
    return True


def _sentence_ok(sentence: str, banned: frozenset[str]) -> bool:
    if not sentence.isascii() or _HINT.search(sentence):
        return False  # another script has no capitals to check; a hint is a hint
    words = _WORD.findall(sentence)
    if not words:
        return False
    if words[0][:1].isupper() and words[0].lower() not in _OPENERS:
        return False
    if banned & set(_words(sentence)):
        return False
    return _capital_runs_ok(words)


def screen_scene(scene: str, banned: Sequence[str] = ()) -> str:
    """What may be said of a picture with a person: the sentences that only describe what is
    visible. `banned`: names withheld elsewhere (a subject, a claimed caption), in any letter
    case. Nothing left: `PERSON_FALLBACK`."""
    stop = frozenset(w for name in banned for w in _words(name) if len(w) > 1) - _OPENERS
    kept = [s for s in _SENTENCE.split(scene.strip()) if s and _sentence_ok(s, stop)]
    return " ".join(kept) or PERSON_FALLBACK


# ---- the verdict -----------------------------------------------------------------------------
def _searchable(subject: Subject, named: str) -> bool:
    if subject.kind not in SEARCHABLE or not thing_shaped(subject.name):
        return False
    return not (
        set(_words(named)) & set(_words(subject.name))
    )  # the offered name is never searched


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
    )


def judge(seen: Seen, *, enabled: bool = True) -> Verdict:
    """What may be said and searched for one picture. `enabled=False` is the eval's control."""
    if not enabled:
        return _unguarded(seen)
    named = name_from_text(seen)
    shown = tuple(s for s in seen.subjects if not seen.has_person or thing_shaped(s.name))
    withheld = tuple(s for s in seen.subjects if s not in shown)
    limit = MAX_QUERIES_WITH_PERSON if seen.has_person else MAX_QUERIES
    queries: list[Subject] = []
    for subject in shown:
        if _searchable(subject, named) and subject not in queries:
            queries.append(subject)
    scene = seen.scene
    if seen.has_person:
        banned = [s.name for s in withheld] + [seen.named_in_text]
        scene = screen_scene(scene, banned)
    return Verdict(
        person=seen.has_person,
        scene=scene,
        text=seen.text,
        subjects=shown,
        queries=tuple(queries[:limit]),
        named=named,
        withheld=len(withheld),
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
    "judge",
    "name_from_text",
    "parse_seen",
    "person_shaped",
    "screen_scene",
    "thing_shaped",
]

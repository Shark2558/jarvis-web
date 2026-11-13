# src/jarvis/picture/words.py
"""The word lists and word shapes of the picture guard (R11.1 D17, D21-D; Layer 4, guardrails).

Plain code, no model: what makes a phrase about a PERSON (`person_shaped`), what says what kind of
THING a name is (`THING_WORDS`, `thing_shaped`), what is shaped like a person's name
(`name_shaped`), and the small words a sentence or a name is built with. `jarvis.picture.guard`
and `jarvis.picture.scene` decide with them; `jarvis.picture.turnguard` reads a turn's names with
them. Everything is read through the people pre-filter's folding (`jarvis.people.guard.fold`), so
look-alike letters and odd case hide nothing.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence

from jarvis.people.guard import fold, variants

MAX_NAME_WORDS = 5

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
# In a description: a sentence that says or hints who someone is.
HINT = re.compile(
    r"\b(?:looks?\s+like|look-?alike|resembl\w*|known\s+as|named|called|identified|famous|"
    r"celebrit\w*|celeb|well[- ]known|recogni[sz]\w*|probably|possibly|presumably|likely|"
    r"apparently|actor|actress|singer|politician|minister|president|cricketer|footballer|"
    r"superstar|film\s+star|movie\s+star|mla|mp)\b",
    re.IGNORECASE,
)
# "This is X", "here is x", "it's X": a sentence that introduces someone (in any letter case).
INTRODUCES = re.compile(
    r"\b(?:this|that|here|these|it)(?:\s+is|'s|’s)\s+(?!(?:an?|the|one|some|not|about|just|also|"
    r"located|situated|shown|visible|where|what|how|part|inside|outside|near|beside|behind|"
    r"likely|probably|very|quite|another|other|each|every|my|our|your|their|its)\b)",
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
OPENERS = frozenset(
    """
    a an the this that these those there here in on at behind beside near next inside outside
    above below under around with it its he she they his her their both many several some one two
    three four five six people someone everyone nobody no each all another other others most part
    also nearby further overhead between across along over beyond against among to from standing
    sitting walking holding seen shown visible
    """.split()
)
# Never part of a person's name (with the thing words and the person words above).
NOT_NAME = frozenset(
    """
    the a an of and or in on at for with by to from is are was were be been opens opened opening
    inaugurates inaugurated welcome welcomes presents visit visits at as new our your my this that
    """.split()
)
# R11.1 I1 (the over-caution check): ordinary search words. Never part of a person's name, so a
# web query on a picture turn that carries one is not a bare name, and in a run of capitalised
# words ("Mumbai Weather Today") they are not name parts. Plausible given names or surnames
# (price, best, gold, rich, rain, storm, may, rose ...) are left out on purpose.
QUERY_WORDS = frozenset(
    """
    weather forecast forecasts rainfall temperature humidity monsoon cyclone flood floods
    today tomorrow tonight yesterday now week weekend month year latest live update updates news
    score scores match matches result results schedule fixtures timings timing hours time times
    date dates calendar holiday holidays season festival
    rate rates fare fares cost costs deal deals offer offers sale discount cheap cheapest
    review reviews rating ratings specs specifications comparison compare versus vs alternative
    alternatives warranty manual size sizes weight height length depth population area
    how what when where why which
    near nearby nearest open closed opening closing route routes distance directions map maps
    traffic status flight flights metro ticket tickets booking bookings online delivery buy
    recycling rules rule law laws guide guides tips tutorial steps meaning definition history
    facts list top quality safety safe benefits uses effects dosage symptoms treatment remedy
    remedies ingredients calories nutrition download install error fix login website app
    cricket football hockey tennis tournament league stock stocks share shares sensex nifty
    petrol diesel electricity water air
    """.split()
)
# R11.1 I1 review (security M3, code M3): the search words that sit next to a PERSON's name
# ("Kohli score", "Modi news today", "news Lekha"). With one of them in a query, a single word
# left over is never let through as "a topic": it is tested as a name.
PERSON_SEARCH_WORDS = frozenset(
    """
    news latest live score scores age born birthday wife husband son daughter father mother
    brother sister family married marriage girlfriend boyfriend partner biography bio profile
    profiles instagram insta facebook twitter linkedin youtube wiki wikipedia speech speeches
    interview interviews quotes net worth salary income caste religion party constituency career
    stats photos images pics videos movies films songs contact address
    """.split()
)
JOINS = frozenset({"of", "the", "and", "de", "da", "al"})  # inside a name: "Gateway of India"
SENTENCE = re.compile(r"(?<=[.!?])\s+")
_INSIDE = "'’-"  # an apostrophe or a hyphen inside a word ("Meenu's", "Coca-Cola")


def raw_words(text: str) -> list[str]:
    """The words of `text` as written (letter case kept): a letter, then letters, marks, digits
    and inner apostrophes or hyphens. Marks are a word's own (an Indic vowel sign or virama is not
    a break, so "लेखा" is one word, not "ल" and "ख"); `_`, `/`, `.`, `:` and every other sign end
    a word, so "Lekha_Examplekar" and a URL's path are words like any other (R11.1 I1 security
    review H1: Python's word class has no marks, and it holds `_`). A digit never starts one."""
    out: list[str] = []
    word: list[str] = []
    for ch in text:
        kind = unicodedata.category(ch)[0]
        if kind == "L" or (word and (kind in "MN" or ch in _INSIDE)):
            word.append(ch)
            continue
        if word:
            out.append("".join(word))
            word = []
    if word:
        out.append("".join(word))
    return out


def plain(word: str) -> str:
    """One word as the guard compares it: folded, without its edge apostrophes and hyphens."""
    return fold(word).strip(_INSIDE)


def words_of(text: str) -> list[str]:
    """The folded words of `text` (lower case, accents and look-alikes read as plain letters)."""
    return [w for w in (plain(w) for w in raw_words(fold(text))) if w]


def letter_runs(text: str) -> list[str]:
    """`words_of`, each also cut at its inner apostrophes and hyphens ("lekha-examplekar" is
    "lekha" and "examplekar"): the pieces the picture guard's strict check compares."""
    return [r for w in words_of(text) for r in re.split(r"['’\-]+", w) if r]


def word_set(lines: Iterable[str]) -> frozenset[str]:
    """Every folded word of every line."""
    return frozenset(w for line in lines for w in words_of(line))


def capitalised(word: str) -> bool:
    """A capital first letter: "Examplekar" and "EXAMPLEKAR" alike."""
    return word[:1].isupper()


def person_shaped(text: str) -> bool:
    """Is this about a person: who they are or what they look like? Read through the people
    pre-filter's folding, so spaced-out letters and look-alike characters hide nothing."""
    return any(_PERSON.search(form) for form in variants(text))


def is_thing_word(word: str) -> bool:
    return word in THING_WORDS or (word.endswith("s") and word[:-1] in THING_WORDS)


def thing_shaped(name: str) -> bool:
    """Does `name` say what kind of thing it is, and nothing about a person? A bare name (of a
    person, or of a brand with no thing named) is not a thing."""
    words = words_of(name)
    return bool(words) and not person_shaped(name) and any(is_thing_word(w) for w in words)


def _letters(word: str) -> bool:
    """Letters only (in any script: a vowel sign is a mark, not a digit or a symbol)."""
    bare = word.replace("'", "").replace("’", "").replace("-", "")
    return bool(bare) and all(unicodedata.category(ch)[0] in "LM" for ch in bare)


def name_shaped(name: str) -> bool:
    """One to five words of letters (initials count), none of them a thing, a person word or a
    small word: "Lekha Examplekar", "K R Examplekar"; never "the woman in blue"."""
    words = words_of(name)
    if not 1 <= len(words) <= MAX_NAME_WORDS or person_shaped(name):
        return False
    if not all(_letters(w) for w in words) or not any(len(w) > 1 for w in words):
        return False
    full = [w for w in words if len(w) > 1]  # a single letter is an initial, never "a" the article
    return not any(w in NOT_NAME or is_thing_word(w) for w in full)


def contains(haystack: Sequence[str], needle: Sequence[str]) -> bool:
    """`needle` appears in `haystack` as consecutive words."""
    n = len(needle)
    return n > 0 and any(list(haystack[i : i + n]) == list(needle) for i in range(len(haystack)))


def run_end(words: Sequence[str], start: int) -> int:
    """Where the run of capitalised words that begins at `start` ends ("Gateway of India" is one
    run: a small joining word between two capitalised words belongs to it)."""
    j = start
    while j < len(words):
        if capitalised(words[j]):
            j += 1
        elif words[j] in JOINS and j + 1 < len(words) and capitalised(words[j + 1]):
            j += 2
        else:
            break
    return j


__all__ = [
    "HINT",
    "INTRODUCES",
    "JOINS",
    "MAX_NAME_WORDS",
    "NOT_NAME",
    "OPENERS",
    "PERSON_SEARCH_WORDS",
    "QUERY_WORDS",
    "SENTENCE",
    "THING_WORDS",
    "capitalised",
    "contains",
    "is_thing_word",
    "letter_runs",
    "name_shaped",
    "person_shaped",
    "plain",
    "raw_words",
    "run_end",
    "thing_shaped",
    "word_set",
    "words_of",
]

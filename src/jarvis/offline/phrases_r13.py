# src/jarvis/offline/phrases_r13.py
"""No-AI pass 3 (docs/plans/r13-wardrobe.md D6, D20): the wardrobe's phrases, anchored like R14's
(the WHOLE message is the phrase: an optional "hey / ok", "Jarvis," and "please", end punctuation)
and installed FIRST (`api/r13_wiring.install_r13_phrases`, `add_phrases(..., first=True)`), ahead
of R14's `things`. Each ends in gateway calls (the policy, the rows, Telegram's classes, cards and
the audit all apply). No model, no clock: the day words go to the tool, which reads his zone.

    what should I wear tomorrow / for Diwali    outfit_suggest(day?, occasion?)
    where is my black belt / my brown shoes     wardrobe_find(query), then belongings_where(item)
    I put my watch in the travel bag            wardrobe_find(query), wardrobe_edit(piece, place)
    my navy shirt is in the laundry             laundry_move(step=basket, query)
    put the white shirt in the wash             laundry_move(step=basket, query)
    the white shirt is back / is clean          laundry_move(step=ready, query)
    what's in the laundry / laundry status      laundry_status
    I'm wearing the blue shirt                  wear_log(action=start, query)
    I wore the blue shirt today / done for today  wear_log(action=done, query?, day?)
    how many shirts do I have / socks are ready wardrobe_count(type: a type or a category)

A phrase is the wardrobe's only when its LAST word is a wardrobe word (`WORDS`: the fixed types,
their plurals and a few everyday names). Never a possessive ("my wife's watch", "the kids' shoes"),
never R14's not-a-thing words, never the accessory words that are usually Things (bag, glasses,
spectacles, keys, wallet, umbrella): those stay with Things, so a watch is never in two lists.
"Where is my ..." asks the wardrobe and then Things, each through its own row (a "Never" on Things
is kept). A name that fits several pieces is the tool's to settle (a review entry, never a guess).
His words reach the tool as typed (bounded, whitespace folded); they are data, never instructions.

The move (D6, D10; REVIEW-D-1 M4, M6): every put form R14 knows (hid, under, near, behind, next to,
with, on top of ...) and "hung" take a wardrobe word, so Things never learns his watch. The piece is
resolved first by `wardrobe_find`, and the edit takes its `best` id (`TakeCall`): no `query` reaches
`wardrobe_edit`, and a name that fits several pieces stops the turn at the find's words. A place
other than in, inside, into, on or at keeps its word ("under the pillow"); A refuses a place he
does not have, with his places listed.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from jarvis.offline.phrases_r14 import _NOT_A_THING, _NOT_THINGS
from jarvis.offline.rules import NoAICall, NoAIRoute


@dataclass(frozen=True)
class TakeCall(NoAICall):
    """A call that takes argument values from the step before's result: `take` pairs an argument
    with a key of that result ("piece" from wardrobe_find's "best"). The runner fills them, or
    stops the turn when the key holds no string id (INTEGRATION-D section 6: `offline/no_ai.py`
    reads it at I1). Until then the call runs without them and A refuses it: nothing is moved on a
    guess."""

    take: tuple[tuple[str, str], ...] = ()


Router = Callable[[str, datetime], NoAIRoute | None]
MAX_TEXT = 400
ITEM_MAX = 40

# A wardrobe word -> ("type", t) or ("category", c), from the fixed lists (wardrobe/model.py TYPES)
_TYPES: Mapping[str, str] = {
    **dict.fromkeys(("shirt", "shirts"), "shirt"),
    **dict.fromkeys(("t-shirt", "t-shirts", "tshirt", "tshirts", "tee", "tees"), "t_shirt"),
    **dict.fromkeys(("polo", "polos"), "polo"),
    **dict.fromkeys(("trousers", "trouser", "pants"), "trousers"),
    **dict.fromkeys(("chinos",), "chinos"),
    **dict.fromkeys(("jeans",), "jeans"),
    **dict.fromkeys(("shorts",), "shorts"),
    **dict.fromkeys(("joggers", "trackpants"), "joggers"),
    **dict.fromkeys(("underpants", "underwear"), "underpants"),
    **dict.fromkeys(("briefs",), "briefs"),
    **dict.fromkeys(("boxers",), "boxers"),
    **dict.fromkeys(("vest", "vests", "banian", "banians", "baniyan"), "vest"),
    **dict.fromkeys(("undershirt", "undershirts"), "undershirt"),
    **dict.fromkeys(("thermal", "thermals"), "thermal"),
    **dict.fromkeys(("sock", "socks"), "sock"),
    **dict.fromkeys(("blazer", "blazers"), "blazer"),
    **dict.fromkeys(("jacket", "jackets"), "jacket"),
    **dict.fromkeys(("hoodie", "hoodies"), "hoodie"),
    **dict.fromkeys(("sweater", "sweaters", "jumper", "jumpers"), "sweater"),
    **dict.fromkeys(("coat", "coats"), "coat"),
    **dict.fromkeys(("raincoat", "raincoats", "rainwear"), "rainwear"),
    **dict.fromkeys(("kurta", "kurtas"), "kurta"),
    **dict.fromkeys(("pyjama", "pyjamas", "pajama", "pajamas"), "pyjama"),
    **dict.fromkeys(("mundu", "mundus"), "mundu"),
    **dict.fromkeys(("dhoti", "dhotis"), "dhoti"),
    **dict.fromkeys(("sneaker", "sneakers", "trainers"), "sneaker"),
    **dict.fromkeys(("sandal", "sandals", "chappal", "chappals"), "sandal"),
    **dict.fromkeys(("slipper", "slippers"), "slipper"),
    **dict.fromkeys(("boot", "boots"), "boot"),
    **dict.fromkeys(("watch", "watches"), "watch"),
    **dict.fromkeys(("belt", "belts"), "belt"),
    **dict.fromkeys(("tie", "ties"), "tie"),
    **dict.fromkeys(("cap", "caps"), "cap"),
    **dict.fromkeys(("scarf", "scarves"), "scarf"),
}
_CATEGORIES: Mapping[str, str] = {
    **dict.fromkeys(("shoe", "shoes", "footwear"), "footwear"),
}
WORDS: frozenset[str] = frozenset({*_TYPES, *_CATEGORIES})
_OUTFIT_WORDS = frozenset({"outfit", "look", "clothes", "set"})  # what he is wearing as a whole
# Usually Things, never the wardrobe's (D6): bag, glasses, spectacles, keys, wallet, umbrella
THINGS_WORDS = frozenset(
    "bag bags glasses spectacles specs sunglasses keys key wallet purse umbrella".split()
)

_I = re.IGNORECASE
_LEAD = r"^(?:(?:hey|ok|okay)\s+)?(?:jarvis[,\s]+)?(?:please\s+)?"
_END = r"(?:\s+please)?[\s.!?]*$"
_MY = r"(?:my|the)\s+"
_ITEM = rf"(?P<item>[A-Za-z][\w' -]{{0,{ITEM_MAX - 1}}}?)"
_DAY = r"(?P<day>today|tomorrow|tonight)"
_BASKET = r"(?:the\s+|my\s+)(?:laundry(?:\s+basket)?|wash(?:ing)?(?:\s+machine)?|basket|hamper)"


def _p(body: str) -> re.Pattern[str]:
    return re.compile(_LEAD + r"(?:" + body + r")" + _END, _I)


def _line(text: str) -> str:
    return " ".join(str(text)[:MAX_TEXT].split())


def _call(tool: str, **args: Any) -> NoAIRoute:
    return NoAIRoute((NoAICall(tool, dict(args)),))


def _words(item: str) -> list[str]:
    return item.casefold().split()


def _person(word: str) -> bool:
    """R14's not-a-thing words, also as a plural or a possessive typed without its apostrophe
    ("wifes", M4), the way R14's `_a_thing` strips "'s"."""
    return word in _NOT_A_THING or word.removesuffix("s") in _NOT_A_THING


def _ours(item: str, *, outfit: bool = False) -> bool:
    """The wardrobe's: the last word a wardrobe word; never a possessive, a person, a place, a
    ride or money, and never one of the words that are usually Things."""
    words = _words(item)
    if not words or "'" in item or len(item) > ITEM_MAX:
        return False
    whole = outfit and words[-1] in _OUTFIT_WORDS  # "the meeting outfit": the event names a plan
    if (_NOT_THINGS.intersection(words) and not whole) or THINGS_WORDS.intersection(words):
        return False
    if any(_person(w) for w in words):
        return False
    return words[-1] in WORDS or whole


def _item(m: re.Match[str]) -> str:
    return " ".join(m["item"].split())


# ---- what to wear (C's outfit_suggest) ----------------------------------------------------------
OUTFIT = _p(
    r"(?:what\s+(?:should|shall|do|can|could)\s+i\s+wear|what\s+to\s+wear"
    r"|(?:suggest|pick)\s+(?:me\s+)?an?\s+outfit)"
    + r"(?:\s+" + _DAY + r")?"
    + r"(?:\s+for\s+(?:the\s+|my\s+|a\s+|an\s+)?"
    + r"(?P<occ>[A-Za-z][\w'-]*(?:\s+[A-Za-z][\w'-]*){0,3}?))?"
    + r"(?:\s+(?P<day2>today|tomorrow|tonight))?"
)  # fmt: skip


def outfit(text: str, now: datetime) -> NoAIRoute | None:
    m = OUTFIT.match(_line(text))
    if m is None:
        return None
    day = (m["day"] or m["day2"] or "").casefold()
    args: dict[str, Any] = {}
    if day:
        args["day"] = "today" if day == "tonight" else day
    if m["occ"]:
        args["occasion"] = " ".join(m["occ"].split())
    return _call("outfit_suggest", **args)


# ---- the laundry (B's laundry_move and laundry_status) ------------------------------------------
TO_BASKET = _p(
    _MY + _ITEM + r"\s+(?:is|are)\s+in\s+" + _BASKET
    + r"|(?:i\s+(?:'ve\s+|have\s+)?)?(?:put|kept|dropped|threw|thrown|tossed|toss|throw|drop)\s+"
    + _MY + _ITEM.replace("item", "item2") + r"\s+in(?:to|side)?\s+" + _BASKET
)  # fmt: skip
BACK = _p(
    _MY + _ITEM + r"\s+(?:is|are)\s+(?:back|clean|washed|dry)"
    r"(?:\s+from\s+the\s+(?:laundry(?:\s+shop)?|wash|dhobi|dry\s*cleaners?|ironing))?"
)
STATUS = _p(
    r"what(?:'s|\s+is)\s+in\s+" + _BASKET + r"|(?:my\s+|the\s+)?laundry\s+status"
    r"|(?:show|check)\s+(?:me\s+)?(?:my\s+|the\s+)?laundry"
)


def laundry(text: str, now: datetime) -> NoAIRoute | None:
    one = _line(text)
    if STATUS.match(one):
        return _call("laundry_status")
    if (m := TO_BASKET.match(one)) is not None:
        item = " ".join((m["item"] or m["item2"]).split())
        return _call("laundry_move", step="basket", query=item) if _ours(item) else None
    if (m := BACK.match(one)) is not None and _ours(_item(m)):
        return _call("laundry_move", step="ready", query=_item(m))
    return None


# ---- the wear (C's wear_log) --------------------------------------------------------------------
WEARING = _p(r"(?:i'?m\s+|i\s+am\s+)?wearing\s+" + _MY + _ITEM + r"(?:\s+(?:today|now|tonight))?")
WORE = _p(
    r"i\s+(?:wore|have\s+worn|'ve\s+worn)\s+" + _MY + _ITEM + r"(?:\s+(?P<day>today|yesterday))?"
)
DONE = _p(r"(?:i'?m\s+|i\s+am\s+)?done\s+for\s+(?:today|the\s+day)")


def wear(text: str, now: datetime) -> NoAIRoute | None:
    one = _line(text)
    if DONE.match(one):
        return _call("wear_log", action="done")
    if (m := WEARING.match(one)) is not None and _ours(_item(m), outfit=True):
        return _call("wear_log", action="start", query=_item(m))
    if (m := WORE.match(one)) is not None and _ours(_item(m), outfit=True):
        args: dict[str, Any] = {"action": "done", "query": _item(m)}
        if (m["day"] or "").casefold() == "yesterday":
            args["day"] = "yesterday"
        return _call("wear_log", **args)
    return None


# ---- how many (A's wardrobe_count) --------------------------------------------------------------
COUNT = _p(
    r"how\s+many\s+(?:pairs\s+of\s+)?(?P<what>[a-z][a-z-]*)\s+"
    r"(?:do\s+i\s+(?:have|own)|have\s+i\s+got|(?P<ready>are|is)\s+(?:ready|clean|available))"
)


def count(text: str, now: datetime) -> NoAIRoute | None:
    m = COUNT.match(_line(text))
    if m is None:
        return None
    word = m["what"].casefold()  # A's one argument, a type or a category: its counts say "ready"
    if word in _TYPES:
        return _call("wardrobe_count", type=_TYPES[word].replace("_", " "))
    if word in _CATEGORIES:
        return _call("wardrobe_count", type=_CATEGORIES[word])
    return None


# ---- where it is, where it went (A's wardrobe_find and wardrobe_edit; then Things) --------------
WHERE = _p(
    r"where(?:'s|\s+is|\s+are|\s+did\s+i\s+(?:put|keep|leave|store)|\s+do\s+i\s+keep"
    r"|\s+have\s+i\s+(?:put|kept))\s+" + _MY + _ITEM
)
# R14's put verbs and places, all of them ("on top of" before "on"), and "hung": a wardrobe word in
# any form Things knows is the wardrobe's (M4); tests pin R14's lists inside these
PUT_VERBS = ("kept", "put", "placed", "stored", "hid", "hidden", "hung")
PUT_PREPS: tuple[str, ...] = ("in", "inside", "into", "on top of", "on", "under", "behind", "at")
PUT_PREPS += ("with", "near", "beside", "next to")
_PLAIN = frozenset(
    {"in", "inside", "into", "on", "at"}
)  # the place itself; any other keeps its word
PUT = _p(
    r"i(?:'ve|\s+have)?\s+(?:" + "|".join(PUT_VERBS) + r")\s+" + _MY + _ITEM
    + r"\s+(?P<prep>" + "|".join(p.replace(" ", r"\s+") for p in PUT_PREPS) + r")\s+"
    + r"(?P<place>\S.{0,79}?)"
)  # fmt: skip
_ARTICLE = re.compile(r"^(?:the|my)\s+", _I)


def where(text: str, now: datetime) -> NoAIRoute | None:
    m = WHERE.match(_line(text))
    if m is None or not _ours(_item(m)):
        return None
    item = _item(m)
    return NoAIRoute(
        (NoAICall("wardrobe_find", {"query": item}), NoAICall("belongings_where", {"item": item}))
    )


def put(text: str, now: datetime) -> NoAIRoute | None:
    m = PUT.match(_line(text))
    if m is None or not _ours(_item(m)):
        return None
    prep, place = " ".join(m["prep"].casefold().split()), " ".join(m["place"].strip(" .").split())
    where = _ARTICLE.sub("", place) if prep in _PLAIN else f"{prep} {place}"
    find = NoAICall("wardrobe_find", {"query": _item(m)})
    return NoAIRoute((find, TakeCall("wardrobe_edit", {"place": where}, (("piece", "best"),))))


def _named(router: Router) -> Router:
    router.__name__ = router.__qualname__ = f"r13_{router.__name__}"
    return router


# The order matters only where two could take one sentence: the laundry's "I put my shirt in the
# wash" before the move's "I put my watch in the travel bag".
ROUTERS: tuple[Router, ...] = tuple(_named(r) for r in (outfit, laundry, wear, count, where, put))

__all__ = [
    "PUT_PREPS",
    "PUT_VERBS",
    "ROUTERS",
    "THINGS_WORDS",
    "WORDS",
    "TakeCall",
    "count",
    "laundry",
    "outfit",
    "put",
    "wear",
    "where",
]

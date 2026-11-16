# src/jarvis/wardrobe/laundry/texts.py
"""R13 Part B's fixed words (docs/plans/r13-wardrobe.md D10, D11, D19). Pure.

Every sentence names a piece only by `redact.fixed_words` ("a navy shirt"; a private piece is "a
private basic") or by a count: never his label, a shop's label or anything he typed. Alerts say
where to look ("in Helpers, Wardrobe"). Nothing here promises an order, a call or a payment:
JARVIS prepares and reminds, never more.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from jarvis.wardrobe.model import Piece
from jarvis.wardrobe.redact import fixed_words

WHERE = "in Helpers, Wardrobe"
OFF = "Laundry is off: this server has no token key."
KEPT_NO_KEY = (
    "Laundry records are kept on this server, but it has no token key to read them. "
    "They can still be deleted."
)
UNREADABLE = "JARVIS couldn't open your laundry list just now. Try again in a minute."
NO_WARDROBE = "The wardrobe isn't ready yet: try again in a minute."
NOT_SET_UP = "Laundry isn't set up yet."
READY = "Laundry on: the basket, loads, outside laundry and the review queue"
READY_NO_KEY = "Laundry off: this server has no token key"
ALREADY = "Already done: nothing changed."
NO_MATCH = (
    "No piece in your wardrobe matches that. Say its colour and type, or pick it in Helpers, "
    "Wardrobe."
)
UNKNOWN_PIECE = "That piece isn't in your wardrobe."
NOTHING_NAMED = "Name the pieces: pick them, or say their colour and type."
NO_LOAD = "That load isn't open."
TOO_MANY_LOADS = "50 loads are open: finish one first."
NO_BATCH = "That batch isn't open."
TOO_MANY_BATCHES = "20 batches are out: mark one back first."
SHOP_EMPTY = "Give the shop a short label, like 'Dry cleaner'."
SHOP_LONG = "A shop's label is at most 40 characters."
SHOP_NUMBER = (
    "A shop's label can't hold a phone number or a long number: use a short name like "
    "'Dry cleaner'."
)
TYPE_SHOP = (
    "Type the shop's label yourself in Helpers, Wardrobe: JARVIS never takes one from a message."
)
BAG_BAD = "A bag reference is at most 24 characters, with no long number."
DUE_BAD = "A due date is from today up to 60 days ahead."
TIME_BAD = "A time can be at most 30 days back and never ahead."
BLIND_NOTHING = "Name the places or the kinds of piece you moved."
UNKNOWN_PLACE = "That place isn't one of yours."
NOTHING_AT_REST = "Nothing rests there right now: nothing to check."
ENTRY_GONE = "That check is already closed."
NOT_A_CANDIDATE = "Pick one of the pieces this check names."
OUTCOME_BAD = "That answer doesn't fit this check."
MOVED_NEEDS = "Say where it is now: a state and, if you like, a place."
WAITS_OTHER = f"These pieces wait for another check first: answer that one {WHERE}."
NOT_TO_SHOP = "A piece goes to an outside laundry only with 'send out', so it has its batch."
NOTHING_TO_CORRECT = "There's no step to strike out for that piece."
EVENT_UNKNOWN = "That step isn't in this piece's history."
OWN_BUTTON = "That change is undone with its own button: archive, restore or merge."  # A's words
CORRECTED = "Done: that step is struck out and the piece's state worked out again."
CORRECTED_HELD = f"Done: that step is struck out. The piece waits for a check {WHERE}."
CLOSED = "Done: the check is closed."
NOTHING_LEFT = "Nothing to change: it was answered another way. The check is closed."
# the Activity words (`Tool.activity_words`): fixed, never a piece or a shop
LOOKED = "Looked at the laundry"
MOVED = "Moved pieces through the laundry"
CHECKED = "Answered a laundry check"
STRUCK = "Struck out a laundry step"
OUTSIDE = "Noted outside laundry"

_NEEDS = {
    "basket": "ready or in use",
    "lifted": "in the laundry basket",
    "load": "in the laundry basket",
    "washing": "in the laundry basket",
    "drying": "washing",
    "prep": "washing or drying",
    "ready": "in the laundry",
}
_DONE_ONE = {
    "basket": "is in the laundry",
    "lifted": "is out of the basket and still waits for a wash",
    "drying": "is drying",
    "prep": "needs pressing",
    "ready": "is back and ready",
}
_DONE_MANY = {
    "basket": "are in the laundry",
    "lifted": "are out of the basket and still wait for a wash",
    "drying": "are drying",
    "prep": "need pressing",
    "ready": "are back and ready",
}
_CARD = {
    "basket": "Put {} in the laundry basket",
    "lifted": "Note that {} came out of the laundry basket",
    "load": "Start a load with {}",
    "washing": "Start a load with {}",
    "drying": "Note that {} {} drying",
    "prep": "Note that {} {} pressing",
    "ready": "Note that {} {} back and ready",
}
_HOLD_WORDS = {
    "unverified": "A change JARVIS couldn't confirm: check this piece.",
    "held": "On hold until you check it.",
    "missing": "Missing: tell JARVIS where it is.",
    "restored": "Back from the archive: check its condition.",
    "blind": "Moved without a scan: check it.",
}
_RESCAN_WORDS = {
    "blind": "Moved without a scan: check these.",
    "which": "Which of these did you mean?",
    "corrected": "Two later steps disagree: check this piece.",
}


def cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def count_words(n: int, noun: str = "piece") -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def is_are(n: int) -> str:
    return "is" if n == 1 else "are"


def day_words(d: date) -> str:
    """ "Wed 18 Nov": a fixed English form, never the server's locale."""
    return f"{d:%a} {d.day} {d:%b}"


def names(pieces: Sequence[Piece]) -> str:
    """ "a grey T-shirt and a private basic"; past three, "and N more"."""
    words = [fixed_words(p) for p in pieces]
    if len(words) > 3:
        return f"{', '.join(words[:2])} and {len(words) - 2} more"
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"


def subject(pieces: Sequence[Piece]) -> str:
    """One piece by its fixed words, several by their count."""
    return fixed_words(pieces[0]) if len(pieces) == 1 else count_words(len(pieces))


def done(step: str, pieces: Sequence[Piece]) -> str:
    if step in ("load", "washing"):
        return f"Done: a load of {count_words(len(pieces))} is washing."
    table = _DONE_ONE if len(pieces) == 1 else _DONE_MANY
    return f"Done: {subject(pieces)} {table[step]}."


def wrong_state(piece: Piece, step: str) -> str:
    return f"{cap(fixed_words(piece))} isn't {_NEEDS[step]}, so that step doesn't fit it."


def held(piece: Piece) -> str:
    return f"{cap(fixed_words(piece))} waits for a check {WHERE}: resolve that first."


def with_provider(piece: Piece) -> str:
    return f"{cap(fixed_words(piece))} is with an outside laundry: mark it back from its batch."


def not_in_load(piece: Piece) -> str:
    return f"{cap(fixed_words(piece))} isn't in that load."


def not_in_batch(piece: Piece) -> str:
    return f"{cap(fixed_words(piece))} isn't in that batch."


def not_at_the_shop(piece: Piece) -> str:
    return f"{cap(fixed_words(piece))} isn't with an outside laundry now."


def too_many_picked(n: int) -> str:
    return f"That check is about {count_words(n)}: pick at most {n}."


def more_waiting(n: int) -> str:
    return f"{n} more {'piece waits' if n == 1 else 'pieces wait'} for a check {WHERE}."


def ambiguous(n: int, *, basket: bool) -> str:
    if basket:
        return f"{n} pieces match: they wait for a check {WHERE}."
    return f"{n} pieces match: pick the right one {WHERE}."


def sent(pieces: Sequence[Piece], due: date | None) -> str:
    when = f", due {day_words(due)}" if due is not None else ""
    return f"Noted: {subject(pieces)} went to an outside laundry{when}."


def received(back: int, total: int) -> str:
    out = total - back
    if out == 0:
        whole = "the piece is" if total == 1 else f"all {total} pieces are"
        return f"Noted: {whole} back from the outside laundry."
    return (
        f"Noted: {back} of {total} pieces {is_are(back)} back from the outside laundry; "
        f"{out} {is_are(out)} still out."
    )


def blind_noted(n: int) -> str:
    waits, it = ("piece waits", "it's") if n == 1 else ("pieces wait", "they're")
    return f"Noted: {n} {waits} for a quick check {WHERE} before {it} offered again."


def partly_checked(done_n: int, left: int) -> str:
    return f"Done: {count_words(done_n)} checked; {left} still {'waits' if left == 1 else 'wait'}."


def entry_words(kind: str, reason: str, *, candidates: int) -> str:
    """A review entry's fixed words (`ReviewEntry.words`)."""
    if kind == "pending_deposit":
        if candidates:
            return "Which of these went into the basket?"
        return "Something more went into the basket: scan it or pick it when you can."
    if kind == "rescan":
        return _RESCAN_WORDS.get(
            reason, "A quick check, please: is this piece where JARVIS thinks?"
        )
    if kind == "conflict":
        return "A step that didn't fit this piece was not applied: check it."
    if kind == "stale":
        return "Not seen for a while: a quick check, please."
    if kind == "place":
        return "Check this place: several pieces wait for a quick check."
    return _HOLD_WORDS.get(reason, "On hold until you check it.")


def card(step: str, pieces: Sequence[Piece]) -> str:
    """An approval card's words for a move of these pieces (stored in clear: fixed words)."""
    verb = {"drying": ("is", "are"), "prep": ("needs", "need"), "ready": ("is", "are")}
    template = _CARD[step]
    if step in verb:
        one, many = verb[step]
        return template.format(names(pieces), one if len(pieces) == 1 else many)
    return template.format(names(pieces))


def card_one_of(step: str, n: int) -> str:
    if step == "basket":
        return f"Put one of {n} matching pieces in the laundry basket (you pick which)"
    return f"Record the laundry step '{step}' for one of {n} matching pieces (you pick which)"


def card_load(step: str) -> str:
    return {
        "drying": "Note that a whole load is drying",
        "prep": "Note that a whole load needs pressing",
        "ready": "Note that a whole load is back and ready",
    }.get(step, "Record a laundry step for a whole load")


def overdue_alert(out: int, days: int) -> str:
    late = "a day" if days == 1 else f"{days} days"
    return (
        f"{count_words(out)} at an outside laundry {is_are(out)} {late} overdue: details {WHERE}."
    )


def short_alert(out: int) -> str:
    return (
        f"A laundry batch came back short: {count_words(out)} {is_are(out)} still out. Details "
        f"{WHERE}."
    )


def review_alert(n: int) -> str:
    waits = "waits" if n == 1 else "wait"
    return f"{count_words(n)} {waits} for a quick check {WHERE}."


def status_words(counts: dict[str, int], open_checks: int) -> str:
    """ "3 pieces in the laundry basket, 2 washing. 1 check waits in Helpers, Wardrobe." """
    parts = [
        (counts.get("basket", 0), "in the laundry basket"),
        (counts.get("washing", 0), "washing"),
        (counts.get("drying", 0), "drying"),
        (counts.get("prep", 0), "need pressing"),
        (counts.get("outside", 0), "at an outside laundry"),
    ]
    shown = [(n, w) for n, w in parts if n]
    if not shown:
        head = "Nothing is in the laundry."
    else:
        first, rest = shown[0], shown[1:]
        head = ", ".join([f"{count_words(first[0])} {first[1]}", *(f"{n} {w}" for n, w in rest)])
        head += "."
    if not open_checks:
        return f"{head} Nothing waits for a check."
    waits = "waits" if open_checks == 1 else "wait"
    return f"{head} {count_words(open_checks, 'check')} {waits} {WHERE}."


__all__ = [
    "ALREADY",
    "OFF",
    "READY",
    "READY_NO_KEY",
    "UNREADABLE",
    "WHERE",
    "ambiguous",
    "blind_noted",
    "cap",
    "card",
    "card_load",
    "card_one_of",
    "count_words",
    "day_words",
    "done",
    "entry_words",
    "names",
    "overdue_alert",
    "received",
    "review_alert",
    "sent",
    "short_alert",
    "status_words",
    "subject",
    "wrong_state",
]

# src/jarvis/wardrobe/styling/wear.py
"""R13 STY-17, plan review H1 (docs/plans/r13-wardrobe.md D3, D12): one wear is `wear_started`
then `wear_done`, written through A's ledger (`WardrobeStore.transact`), never by hand.

- "I'm wearing ..." (`start`): Ready -> In use, linked to the plan it is worn for (the plan's
  own picks when he names the plan or says "the meeting outfit"); an In-use piece of a declared
  hand-off moves to the later plan.
- "I wore ..." / "done for today" (`done`): In use -> In laundry or Ready by the rewear rule
  (`Rules.after_wear`), the event carrying the plan the piece was worn for (so C's refresh knows
  it is no change for that plan). No pieces named: everything In use.
- `resolve(view, query)`: his words ("the light blue shirt", "my black socks and the belt") to
  piece ids by the fixed colour and type words; a part that fits several pieces is never a
  guess: "Which one: ...?" with their ids (a private piece "a private basic").
- `closing_events` / `close_forgotten`: a wear started before his local midnight and still open
  at `wardrobe_wear_close` (04:00) is closed by the rewear rule, with a client id fixed by the
  piece and the day (so A's `wardrobe_sweep`, which runs it, can never close it twice).
Saving or previewing a plan writes no event and changes no count.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, datetime, time, tzinfo

from jarvis.storage.docs import DocTx
from jarvis.wardrobe.model import COLOURS, TYPES, Event, Evidence, Piece, WardrobeView, new_id
from jarvis.wardrobe.ports import Commit, Committed, WardrobeStore
from jarvis.wardrobe.styling import texts
from jarvis.wardrobe.styling.plans import Plan, StylingDoc
from jarvis.wardrobe.styling.reserve import unit_of, window
from jarvis.wardrobe.styling.rules import Rules

_WORD = re.compile(r"[a-z]+")
_TYPE_WORDS: dict[str, tuple[str, ...]] = {
    "shirt": ("shirt",), "shirts": ("shirt",), "tee": ("t_shirt",), "tshirt": ("t_shirt",),
    "polo": ("polo",), "trousers": ("trousers",), "pants": ("trousers", "chinos"),
    "chinos": ("chinos",), "jeans": ("jeans",), "shorts": ("shorts",), "kurta": ("kurta",),
    "pyjama": ("pyjama",), "vest": ("vest",), "underwear": ("underpants", "briefs", "boxers"),
    "socks": ("sock",), "sock": ("sock",), "shoes": TYPES["footwear"], "shoe": TYPES["footwear"],
    "sneakers": ("sneaker",), "sandals": ("sandal",), "belt": ("belt",), "watch": ("watch",),
    "blazer": ("blazer",), "jacket": ("jacket", "rainwear"), "hoodie": ("hoodie",),
}  # fmt: skip
_COLOUR_WORDS = sorted(((c.replace("_", " "), c) for c in COLOURS), key=lambda x: -len(x[0]))
_FAMILY = {"blue": ("blue", "light_blue", "navy"), "grey": ("grey", "charcoal")}
_OUTFIT_WORDS = frozenset({"outfit", "plan"})
CLOSE_ID = "wclose-{piece}-{day}"


def _event(p: Piece, kind: str, now: datetime, *, via: str, **extra: object) -> Event:
    client = extra.pop("client_id", None) or f"wear-{new_id('we')[3:19]}"
    return Event.model_validate(
        {"id": new_id("we"), "client_id": client,
         "piece": p.id, "kind": kind, "at": now, "recorded": now, "source": "tap", "via": via,
         "verified": True, "evidence": Evidence.model_validate({"how": "owner"}), **extra}
    )  # fmt: skip


def start_events(
    view: WardrobeView, pieces: Sequence[str], plan: str | None, now: datetime, *, via: str
) -> tuple[Event, ...]:
    return tuple(_event(view.pieces[i], "wear_started", now, via=via, plan=plan) for i in pieces)


def done_events(
    view: WardrobeView, pieces: Sequence[str], rules: Rules, now: datetime, *, via: str
) -> tuple[Event, ...]:
    out = []
    for i in pieces:
        p = view.pieces[i]
        out.append(_event(p, "wear_done", now, via=via, to=rules.after_wear(p), plan=p.wear))
    return tuple(out)


async def commit(store: WardrobeStore, uid: str, events: tuple[Event, ...]) -> Committed:
    async def fn(view: WardrobeView, tx: DocTx) -> Commit:
        return Commit(events=events)

    return await store.transact(uid, fn)


# ---- the plan a wear is for (code review H1) -----------------------------------------------------
def plan_for(
    doc: StylingDoc, pieces: Sequence[str], day: date, zone: tzinfo, *, after: datetime | None
) -> str | None:
    """The earliest plan of `day` (not cancelled, not worn, not over by `after`) holding a named
    piece. The whole-day hold puts a piece in at most one plan of a day, unless shared: then the
    earlier plan, the one it is worn for first."""
    named = set(pieces)
    for p in doc.on(day):
        if p.worn or (after is not None and window(p, zone)[1] <= after):
            continue
        if named & set(p.pieces()):
            return p.id
    return None


def means_outfit(query: str) -> bool:
    """His words name a plan ("the meeting outfit", "my plan"), not a piece."""
    return bool(_OUTFIT_WORDS & set(_WORD.findall(query.lower())))


def outfit_of(
    doc: StylingDoc, day: date, zone: tzinfo, occasion: str | None, *, now: datetime, done: bool
) -> Plan | None:
    """The plan "the outfit" means on `day`: for a start, the current or next plan not yet worn;
    for done, the plan worn (else any plan of the day). An occasion he names picks among them."""
    plans = list(doc.on(day))
    if done:
        plans = [p for p in plans if p.worn] or plans
    else:
        plans = [p for p in plans if not p.worn and window(p, zone)[1] > now]
    mine = [p for p in plans if occasion is not None and p.occasion == occasion]
    found = mine or plans
    if not found:
        return None
    return found[-1] if done else found[0]


# ---- his words ----------------------------------------------------------------------------------
def _colour_of(text: str) -> tuple[str | None, str]:
    for words, colour in _COLOUR_WORDS:
        if f" {words} " in f" {text} ":
            return colour, f" {text} ".replace(f" {words} ", " ").strip()
    return None, text


def _candidates(view: WardrobeView, part: str) -> list[tuple[str, ...]]:
    words = " ".join(_WORD.findall(part.lower()))
    colour, rest = _colour_of(words)
    types = next((_TYPE_WORDS[w] for w in rest.split() if w in _TYPE_WORDS), None)
    if types is None:
        return []
    found = [p for p in view.active() if p.type in types]
    exact = [p for p in found if colour is None or p.colour == colour]
    if not exact and colour in _FAMILY:
        exact = [p for p in found if p.colour in _FAMILY[colour]]
    units = list(dict.fromkeys(unit_of(view, p.id) for p in sorted(exact, key=lambda x: x.id)))
    return units


def resolve(view: WardrobeView, query: str) -> tuple[list[str], str]:
    """(piece ids, "") or ([], the words that ask which one / say none was found)."""
    out: list[str] = []
    for part in re.split(r",| and | & ", query.lower()):
        if not part.strip():
            continue
        units = _candidates(view, part)
        if not units:
            return (
                [],
                f'I couldn\'t find "{part.strip()[:40]}" in your wardrobe: tap it {texts.WHERE}.',
            )
        if len(units) > 1:
            choices = [
                f"{texts.ids_words(u)} ({texts.unit_words([view.pieces[i] for i in u])})"
                for u in units[:5]
            ]
            return (
                [],
                f"Which one: {', '.join(choices[:-1])} or {choices[-1]}? Say its colour, or tap "
                f"it {texts.WHERE}.",
            )
        out += [i for i in units[0] if i not in out]
    return out, ""


# ---- the forgotten wear (run by A's wardrobe_sweep) ---------------------------------------------
def _close_at(close: str) -> time:
    h, _, m = close.partition(":")
    return time(int(h), int(m))


async def closing_events(
    store: WardrobeStore, uid: str, *, now: datetime, zone: tzinfo, close: str, rules: Rules
) -> tuple[Event, ...]:
    local = now.astimezone(zone)
    if local.time() < _close_at(close):
        return ()
    midnight = datetime.combine(local.date(), time.min, tzinfo=zone)
    view, out = await store.view(uid), []
    for p in sorted(view.active(), key=lambda x: x.id):
        if p.state != "in_use":
            continue
        history = await store.history(uid, p.id)
        starts = [
            h.event.at for h in history if h.event.kind == "wear_started" and h.mark == "applied"
        ]
        if starts and max(starts) < midnight:
            cid = CLOSE_ID.format(piece=p.id[3:], day=local.date().strftime("%Y%m%d"))
            out.append(
                _event(
                    p,
                    "wear_done",
                    now,
                    via="sweep",
                    to=rules.after_wear(p),
                    plan=p.wear,
                    client_id=cid,
                )
            )
    return tuple(out)


async def close_forgotten(
    store: WardrobeStore, uid: str, *, now: datetime, zone: tzinfo, close: str, rules: Rules
) -> int:
    """A's `wardrobe_sweep` calls this from 04:00 his time (Needs I1: the call)."""
    events = await closing_events(store, uid, now=now, zone=zone, close=close, rules=rules)
    if not events:
        return 0
    got = await commit(store, uid, events)
    return sum(1 for m in got.marks.values() if m == "applied")


__all__ = [
    "CLOSE_ID",
    "close_forgotten",
    "closing_events",
    "commit",
    "done_events",
    "means_outfit",
    "outfit_of",
    "plan_for",
    "resolve",
    "start_events",
]

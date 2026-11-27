# src/jarvis/buildbook/gen/modules.py
"""R6.3 D3 (docs/plans/r6-3-book-content.md; Phase A §9.4): the module map. Every catalogue card of
the guide (`docs/architecture/JARVIS-Architecture.md`, `#### Cnn · …`) belongs to exactly ONE of
the 19 modules below, Phase A's 17 plus Wardrobe & Try-on (C69-C73, R13 and R13.1) and Phone calls
(C74-C78, R18); R5.2's C79-C83 extend Voice, as R13.1 extended Wardrobe (a laptop part sits with
its domain: C17 in brain, C39 in home, C77 in calls). The full book has a chapter page for each
module (`pg_module_<id>`) with its cards' pages under it; the tour's "what else" scene (T14) lists
the modules that are not one of his seven highlights.

`check(cards)` is the generator's gate: a card in no module, a card in two, or a module naming a
card the guide does not have is a `GenError`, so a new card must be placed here before its
release's book builds (the deploy goes on with `--best-effort`). Standard library only.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from jarvis.buildbook.gen.repo import GenError

_CARD = re.compile(r"^####\s+(C\d{2})\s+·", re.MULTILINE)


@dataclass(frozen=True)
class Module:
    id: str
    title: str
    cards: tuple[str, ...]


def _m(mid: str, title: str, *cards: int) -> Module:
    return Module(mid, title, tuple(f"C{n:02d}" for n in cards))


MODULES: tuple[Module, ...] = (
    _m("console", "Console and API", 1, 2, 3, 41),
    _m("brain", "Chat and the brain router", 9, 13, 14, 15, 16, 17, 68),
    _m("voice", "Voice", 5, 6, 79, 80, 81, 82, 83),  # R5.2: the kit, its routing, your voice
    _m("memory", "Memory and knowledge", 10, 23, 24),
    _m("vault", "Vault and documents", 7, 42, 43),
    _m("people", "People and faces", 8, 21),
    _m("home", "Home bridge and cameras", 38, 39, 40, 63),
    _m("alerts", "Alerts and notifications", 45, 46, 47),
    _m(
        "integrations",
        "Google, Telegram and other integrations",
        *(4, 20, 22, 29, 30, 31, 32, 33, 34, 35, 36, 37),
    ),
    _m("vitals", "Vitals, costs and the systems check", 44, 54, 55, 56, 67),
    _m("privacy", "The privacy panel", 53),
    _m("activity", "Activity log and undo", 12, 48),
    _m("approvals", "Approvals and passkeys", 18, 28, 51, 52),
    _m("android", "The Android app", 62, 64, 65),
    _m(
        "helpers",
        "Daily helpers (brief, helpers, family, groceries, parcels)",
        *(11, 19, 25, 26, 27, 60, 61),
    ),
    _m("delivery", "Delivery, CI and backups", 49, 50, 58, 59, 66),
    _m("book", "The Build Book", 57),
    _m("wardrobe", "Wardrobe & Try-on", 69, 70, 71, 72, 73),
    _m("calls", "Phone calls", 74, 75, 76, 77, 78),
)
# his seven highlights (the tour's T07-T13), as modules, in his order
TOUR_HIGHLIGHTS: tuple[str, ...] = (
    "voice",
    "approvals",
    "memory",
    "vault",
    "home",
    "android",
    "wardrobe",
)


def guide_cards(text: str) -> tuple[str, ...]:
    """The card ids of the guide's catalogue (`#### Cnn · Title` headings), sorted."""
    return tuple(sorted(set(_CARD.findall(text))))


def check(cards: Iterable[str], table: tuple[Module, ...] = MODULES) -> None:
    """GenError unless every card is in exactly one module and every module card exists."""
    known = set(cards)
    placed = Counter(c for m in table for c in m.cards)
    loose = sorted(c for c in known if placed[c] == 0)
    twice = sorted(c for c, n in placed.items() if n > 1)
    ghost = sorted(c for c in placed if c not in known)
    if loose:
        raise GenError(f"cards in no module (gen/modules.py): {', '.join(loose)}")
    if twice:
        raise GenError(f"cards in two modules (gen/modules.py): {', '.join(twice)}")
    if ghost:
        raise GenError(f"module cards the guide doesn't have (gen/modules.py): {', '.join(ghost)}")


def module_of(card: str, table: tuple[Module, ...] = MODULES) -> str:
    return next(m.id for m in table if card in m.cards)


def others(table: tuple[Module, ...] = MODULES) -> tuple[str, ...]:
    """The modules that are not one of his seven highlights, in the map's order (T14)."""
    return tuple(m.id for m in table if m.id not in TOUR_HIGHLIGHTS)


__all__ = ["MODULES", "TOUR_HIGHLIGHTS", "Module", "check", "guide_cards", "module_of", "others"]

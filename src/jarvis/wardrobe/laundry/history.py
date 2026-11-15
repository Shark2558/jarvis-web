# src/jarvis/wardrobe/laundry/history.py
"""R13 Part B: what the laundry looks like and what happened to a piece (LND-13, LND-15). Pure.

- `piece_history`: one piece's events with their marks (verified, corrections, the current
  step): "where is my white shirt" says Drying, since when, and its latest verified movement.
- `status`: the basket, the machine, drying, pressing, outside batches, half pairs (LND-13: a
  clean sock whose partner is still out stays in inventory; the pair stays out until both are
  ready) and the number of open checks.
- `laundry_view`: GET /v1/laundry's model.
- `when_words` / `since_words`: a time in HIS local day ("14:05", "yesterday 23:10",
  "Sat 14 Nov 09:00"), from the clock passed in, never the server's.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from jarvis.wardrobe.http import LaundryView
from jarvis.wardrobe.laundry import loads, providers, review, texts
from jarvis.wardrobe.laundry.store import LaundryDoc, ReviewDoc
from jarvis.wardrobe.model import Piece, WardrobeView
from jarvis.wardrobe.ports import HistoryItem, Refused
from jarvis.wardrobe.redact import model_view
from jarvis.wardrobe.states import STATE_SETTING, STATE_WORDS, State, eligible, target_of

SHOWN_EVENTS = 10
LISTS: tuple[tuple[str, State], ...] = (
    ("basket", "in_laundry"),
    ("washing", "washing"),
    ("drying", "drying"),
    ("prep", "needs_prep"),
    ("outside", "with_provider"),
)


def when_words(at: datetime, now: datetime, zone: ZoneInfo) -> str:
    local = at.astimezone(zone)
    today = now.astimezone(zone).date()
    hm = f"{local:%H:%M}"
    if local.date() >= today:
        return hm
    if local.date() == today - timedelta(days=1):
        return f"yesterday {hm}"
    return f"{texts.day_words(local.date())} {hm}"


def since_words(at: datetime, now: datetime, zone: ZoneInfo) -> str:
    return f"since {when_words(at, now, zone)}"


def _after(item: HistoryItem, current: State) -> State:
    e = item.event
    return target_of(e.kind, None, to=e.to) or current


def piece_history(
    view: WardrobeView, items: Sequence[HistoryItem], pid: str, now: datetime, zone: ZoneInfo
) -> dict[str, Any]:
    p = view.pieces[pid]
    place = view.places.get(p.place or "")
    ordered = sorted(items, key=lambda h: h.event.sort_key())
    setting = [h for h in ordered if h.mark == "applied" and h.event.kind in STATE_SETTING]
    began = setting[-1].event.at if setting else (p.updated_at or now)
    verified = [h for h in setting if h.event.verified]
    latest = None
    if verified:
        last = verified[-1]
        latest = {
            "kind": last.event.kind,
            "at": when_words(last.event.at, now, zone),
            "words": STATE_WORDS[_after(last, p.state)],
        }
    return {
        "found": True,
        "piece": model_view(p, place.label if place else None),
        "state": p.state,
        "state_words": STATE_WORDS[p.state],
        "place": place.label if place else "",
        "step": f"{STATE_WORDS[p.state]} {since_words(began, now, zone)}",
        "latest_verified": latest,
        "expected_back": p.expected_back.isoformat() if p.expected_back else None,
        "corrections": sum(1 for h in ordered if h.event.kind == "corrected"),
        "events": [
            {
                "kind": h.event.kind,
                "mark": h.mark,
                "at": when_words(h.event.at, now, zone),
                "verified": h.event.verified,
                "source": h.event.source,
            }
            for h in ordered[-SHOWN_EVENTS:]
        ],
    }


def half_pairs(view: WardrobeView) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for pair in view.pairs.values():
        parts = [view.pieces.get(p) for p in pair.pieces]
        if any(x is None or x.state == "archived" for x in parts):
            continue
        ready = [x.id for x in parts if x is not None and eligible(x.state)]
        if len(ready) == 1:
            out.append(
                {"pair": pair.id, "ready": ready, "out": [p for p in pair.pieces if p not in ready]}
            )
    return out


def _batch_line(b: Any, today: date) -> dict[str, Any]:
    return {
        "id": b.id,
        "shop": b.shop,
        "origin": b.origin,
        "due": b.due.isoformat() if b.due else None,
        "overdue": providers.overdue(b, today),
        "short": b.short and bool(providers.outstanding(b)),
        "out": len(providers.outstanding(b)),
        "back": len(b.back),
    }


def status(
    view: WardrobeView, laundry: LaundryDoc, queue: ReviewDoc, today: date
) -> dict[str, Any]:
    active: list[Piece] = list(view.active())
    lists = {name: [p.id for p in active if p.state == state] for name, state in LISTS}
    counts = {name: len(ids) for name, ids in lists.items()}
    open_checks = len(review.open_entries(queue))
    return {
        **lists,
        "counts": counts,
        "loads": [
            {
                "id": x.id,
                "step": loads.step_of(x, view),
                "pieces": len(x.pieces),
                "back": len(x.back),
            }
            for x in loads.open_loads(laundry)
        ],
        "batches": [_batch_line(b, today) for b in providers.open_batches(laundry)],
        "half_pairs": half_pairs(view),
        "review": open_checks,
        "message": texts.status_words(counts, open_checks),
    }


def laundry_view(view: WardrobeView, laundry: LaundryDoc, today: date, ready: str) -> LaundryView:
    of = {state: tuple(p.id for p in view.active() if p.state == state) for _, state in LISTS}
    return LaundryView(
        ready=ready,
        basket=of["in_laundry"],
        drying=of["drying"],
        prep=of["needs_prep"],
        loads=tuple(loads.load_view(x, view) for x in loads.open_loads(laundry)),
        batches=tuple(providers.batch_view(b, today) for b in providers.open_batches(laundry)),
    )


def to_correct(items: Sequence[HistoryItem], event: str | None) -> str:
    live = [
        h
        for h in items
        if h.mark != "voided" and h.event.kind not in ("registered", "corrected", "merged")
    ]
    if event is not None:
        if not any(h.event.id == event for h in items):
            raise Refused(texts.EVENT_UNKNOWN)
        if not any(h.event.id == event for h in live):
            raise Refused(texts.NOTHING_TO_CORRECT)
        return event
    if not live:
        raise Refused(texts.NOTHING_TO_CORRECT)
    return max(live, key=lambda h: h.event.sort_key()).event.id


__all__ = [
    "LISTS",
    "half_pairs",
    "laundry_view",
    "piece_history",
    "since_words",
    "status",
    "to_correct",
    "when_words",
]

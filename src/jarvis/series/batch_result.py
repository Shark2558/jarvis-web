# src/jarvis/series/batch_result.py
"""What a calendar batch tells the model and the owner (R11.1 D5): per-item results, code's own
sentences ("58 events added, 2 failed, Sir.") and the reply card with "Undo all" and what to
retry. Pure, apart from showing the card on the reply being written (`reply_cards.add_card`).

A result carries numbers, ids and our own words only: never a title (the model has them by
number, in its own call), so nothing a file wrote comes back as a result."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from zoneinfo import ZoneInfo

from jarvis.tools.calendar_batch import Batch, Outcome, Wanted
from jarvis.tools.card import one_line
from jarvis.tools.google_calendar import parse_when
from jarvis.tools.reply_cards import BatchCard, BatchItem, add_card

_ANY_TZ = ZoneInfo("UTC")
UNDO_HOW = "calendar_undo_events with this batch id (the owner approves it first)"
RETRY_HOW = (
    "To retry what failed: call calendar_create_events again with only those events and this "
    "batch id."
)


def _count(n: int, word: str = "event") -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def create_words(total: int, created: int, there: int, bad: int, unsure: int = 0) -> str:
    """The one sentence for what a batch did, by code. `bad`: Google refused them; `unsure`:
    Google did not answer and they could not be found (they may exist: never called failed)."""
    it = "it" if unsure == 1 else "them"
    check = f" Google didn't confirm {unsure}: check your calendar before retrying {it}."
    if not created and not there and unsure:
        return f"None of the {_count(total)} could be confirmed, Sir.{check}"
    if bad == total:
        return f"None of the {_count(total)} could be added, Sir."
    if not bad and not there and not unsure:
        if total == 1:
            return "The event is in your calendar, Sir."
        return f"All {_count(total)} are in your calendar, Sir."
    words = f"{_count(created)} added"
    if there:
        words += f", {there} already there"
    if bad:
        words += f", {bad} failed"
    return f"{words}, Sir." + (check if unsure else "")


def _retry_item(o: Outcome, w: Wanted) -> BatchItem:
    a = w.args
    return BatchItem(
        n=o.n,
        summary=str(a["summary"]),
        start=one_line(a["start"], 40),
        end=one_line(a["end"], 40),
        description=str(a.get("description") or ""),
        location=str(a.get("location") or ""),
        reminders_minutes=a.get("reminders_minutes"),
        why=one_line(o.why, 200),
    )


def _card(bid: str, b: Batch, done: list[Outcome], wanted: Mapping[int, Wanted]) -> BatchCard:
    bad = [o for o in done if o.event is None]  # failed, or not confirmed: both can be retried
    unsure = sum(o.status == "unconfirmed" for o in done)
    created = sum(o.status == "created" for o in done)
    there = sum(o.status == "already_there" for o in done)
    days = sorted(
        parse_when(w.args["start"], _ANY_TZ, name="start").date() for w in wanted.values()
    )
    return BatchCard(
        batch=bid,
        total=len(done),
        created=created,
        already=there,
        failed=len(bad),
        first=days[0].isoformat(),
        last=days[-1].isoformat(),
        name=b.name,
        words=create_words(len(done), created, there, len(bad) - unsure, unsure),
        retry=[_retry_item(o, wanted[o.n]) for o in bad],
    )


def create_result(
    bid: str, b: Batch, done: list[Outcome], wanted: Mapping[int, Wanted], note: str
) -> dict[str, Any]:
    """The batch's result for the model, and its card on the reply (when a reply is being
    written: an approval's own reply collects it)."""
    card = _card(bid, b, done, wanted)
    shown = add_card(card)
    items = [
        {"n": o.n, "status": o.status, **({"id": o.event.get("id")} if o.event else {"why": o.why})}
        for o in done
    ]
    how = "the Undo all button under this reply, or " if shown else ""
    notes = [note, f"To remove them all: {how}{UNDO_HOW}.", RETRY_HOW if card.failed else ""]
    return {
        "batch": bid,
        "total": card.total,
        "created": card.created,
        "already_there": card.already,
        "failed": card.failed,
        "items": items,
        "message": card.words,
        "note": " ".join(x for x in notes if x),
    }


NOT_FORGOTTEN = (
    " Your plan still lists them for now: JARVIS checks your calendar before asking about a "
    "session, so it won't ask about these."
)


def undo_result(
    batch: str, items: list[dict[str, Any]], *, plan_updated: bool = True
) -> dict[str, Any]:
    removed = sum(x["status"] == "removed" for x in items)
    kept = sum(x["status"] == "kept" for x in items)
    failed = sum(x["status"] == "failed" for x in items)
    if not items:
        words = "None of that batch's events are in your calendar, Sir."
    else:
        words = f"Removed {_count(removed)}, Sir."
        if removed:
            words += " Each is in Recently deleted for 30 days."
        if kept:
            words += (
                f" {_count(kept)} you changed since {'was' if kept == 1 else 'were'} left alone."
            )
        if failed:
            words += f" {failed} could not be removed."
        if removed and not plan_updated:
            words += NOT_FORGOTTEN
    return {
        "batch": batch,
        "removed": removed,
        "kept": kept,
        "failed": failed,
        "items": [{k: v for k, v in x.items() if k != "id"} for x in items],
        "plan_updated": plan_updated,
        "message": words,
    }


__all__ = ["create_result", "create_words", "undo_result"]

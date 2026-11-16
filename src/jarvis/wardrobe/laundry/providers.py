# src/jarvis/wardrobe/laundry/providers.py
"""R13 Part B: outside laundry and dry-cleaning as records (docs/plans/r13-wardrobe.md D11, LND-14).

A batch is his label for the shop (his words, at most 40 characters; a run of 5 or more digits is
refused, so no phone number is ever kept, and nothing that reads as an ID or account number), a bag
reference, the pieces, and a `due` date on each `sent_out` event (A's view shows it as
`expected_back`). Each piece is checked back in on its own; a receive that leaves pieces out marks
the batch "short"; past its `due` with pieces out it is "overdue" (B's `laundry_daily` tells him).
No call, no WhatsApp, no order, no payment: there is no tool here that could. Pure: no I/O.
Open batches at most 20; closed ones are kept 90 days.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Sequence
from datetime import date, datetime, timedelta

from jarvis.recall.sensitive import sensitive_reason
from jarvis.wardrobe.http import BatchView
from jarvis.wardrobe.laundry import texts
from jarvis.wardrobe.laundry.holds import tap
from jarvis.wardrobe.laundry.store import Batch, Change, LaundryDoc, Origin
from jarvis.wardrobe.model import Event, Piece, WardrobeView
from jarvis.wardrobe.ports import Refused
from jarvis.wardrobe.states import State, allowed

MAX_OPEN = 20
SHOP_MAX, BAG_MAX = 40, 24
DUE_AHEAD = timedelta(days=60)
KEEP = timedelta(days=90)
_LONG_NUMBER = re.compile(r"\d(?:[\s().+/-]{0,2}\d){4,}")  # 5+ digits, however they are spaced
RECEIVE_TO: tuple[State, ...] = ("ready", "needs_prep")


def new_batch_id() -> str:
    return f"bt_{secrets.token_hex(4)}"


def _clean(text: object, limit: int, empty: str, long: str) -> str:
    if not isinstance(text, str):
        raise Refused(empty)
    plain = " ".join(text.split())
    if not plain and empty:
        raise Refused(empty)
    if len(plain) > limit:
        raise Refused(long)
    return plain


def clean_shop(label: object) -> str:
    """His label for the shop, or a plain refusal."""
    plain = _clean(label, SHOP_MAX, texts.SHOP_EMPTY, texts.SHOP_LONG)
    if _LONG_NUMBER.search(plain) or sensitive_reason(plain):
        raise Refused(texts.SHOP_NUMBER)
    return plain


def clean_bag(ref: object) -> str:
    plain = _clean(ref if ref is not None else "", BAG_MAX, "", texts.BAG_BAD)
    if _LONG_NUMBER.search(plain) or (plain and sensitive_reason(plain)):
        raise Refused(texts.BAG_BAD)
    return plain


def check_due(due: date | None, today: date) -> None:
    if due is not None and not today <= due <= today + DUE_AHEAD:
        raise Refused(texts.DUE_BAD)


def open_batches(doc: LaundryDoc) -> tuple[Batch, ...]:
    return tuple(b for b in doc.batches if b.closed_at is None)


def outstanding(batch: Batch) -> tuple[str, ...]:
    return tuple(p for p in batch.pieces if p not in batch.back)


def overdue(batch: Batch, today: date) -> bool:
    return batch.due is not None and today > batch.due and bool(outstanding(batch))


def days_overdue(batch: Batch, today: date) -> int:
    return (today - batch.due).days if batch.due is not None else 0


def batch_view(batch: Batch, today: date) -> BatchView:
    return BatchView(
        id=batch.id,
        shop=batch.shop,
        bag=batch.bag,
        pieces=batch.pieces,
        back=batch.back,
        due=batch.due,
        overdue=overdue(batch, today),
        short=batch.short and bool(outstanding(batch)),
    )


def _replace(doc: LaundryDoc, batch: Batch) -> LaundryDoc:
    batches = [batch if b.id == batch.id else b for b in doc.batches]
    if all(b.id != batch.id for b in doc.batches):
        batches.append(batch)
    return doc.model_copy(update={"batches": tuple(batches)})


def prune(doc: LaundryDoc, now: datetime) -> LaundryDoc:
    keep = tuple(b for b in doc.batches if b.closed_at is None or now - b.closed_at <= KEEP)
    return doc.model_copy(update={"batches": keep})


def _check_out(piece: Piece) -> None:
    if piece.state == "review":
        raise Refused(texts.held(piece))
    if piece.state == "with_provider":
        raise Refused(texts.with_provider(piece))
    if not allowed("sent_out", piece.state):
        raise Refused(texts.wrong_state(piece, "basket"))


def _out_events(p: Piece, batch: str, due: date | None, now: datetime) -> list[Event]:
    """Plan review H1 (review M2): a piece he is wearing closes its wear first (`wear_done` to In
    laundry, its plan named: counted, STY-17), and the send-out carries that plan too, so the
    plan check hears "worn for that plan", never a change to it."""
    if p.state != "in_use":
        return [tap(p.id, "sent_out", now, batch=batch, due=due)]
    return [
        tap(p.id, "wear_done", now, to="in_laundry", plan=p.wear),
        tap(p.id, "sent_out", now, batch=batch, due=due, plan=p.wear),
    ]


def plan_send(
    view: WardrobeView,
    doc: LaundryDoc,
    ids: Sequence[str],
    *,
    shop: str,
    bag: str = "",
    due: date | None = None,
    origin: Origin = "typed",
    now: datetime,
) -> Change:
    pieces = [view.pieces[i] for i in dict.fromkeys(ids)]
    if not pieces:
        raise Refused(texts.NOTHING_NAMED)
    for p in pieces:
        _check_out(p)
    if len(open_batches(doc)) >= MAX_OPEN:
        raise Refused(texts.TOO_MANY_BATCHES)
    batch = Batch(
        id=new_batch_id(),
        shop=shop,
        bag=bag,
        origin=origin,
        pieces=tuple(p.id for p in pieces),
        due=due,
        sent_at=now,
    )
    events = tuple(e for p in pieces for e in _out_events(p, batch.id, due, now))
    return Change(
        events=events,
        laundry=_replace(doc, batch),
        words=texts.sent(pieces, due),
        pieces=batch.pieces,
        batch=batch.id,
    )


def plan_receive(
    view: WardrobeView,
    doc: LaundryDoc,
    batch_id: str,
    ids: Sequence[str],
    *,
    to: State = "ready",
    now: datetime,
) -> Change:
    batch = next((b for b in open_batches(doc) if b.id == batch_id), None)
    if batch is None:
        raise Refused(texts.NO_BATCH)
    pieces = [view.pieces[i] for i in dict.fromkeys(ids)]
    if not pieces:
        raise Refused(texts.NOTHING_NAMED)
    for p in pieces:
        if p.id not in outstanding(batch):
            raise Refused(texts.not_in_batch(p))
    back = (*batch.back, *(p.id for p in pieces))
    left = [p for p in batch.pieces if p not in back]
    done = batch.model_copy(
        update={"back": back, "short": bool(left), "closed_at": None if left else now}
    )
    events = tuple(
        tap(p.id, "received", now, batch=batch.id, to=to)
        for p in pieces
        if p.state == "with_provider"
    )
    return Change(
        events=events,
        laundry=_replace(doc, done),
        words=texts.received(len(back), len(batch.pieces)),
        pieces=tuple(p.id for p in pieces),
        batch=batch.id,
    )


__all__ = [
    "KEEP",
    "MAX_OPEN",
    "RECEIVE_TO",
    "batch_view",
    "check_due",
    "clean_bag",
    "clean_shop",
    "days_overdue",
    "new_batch_id",
    "open_batches",
    "outstanding",
    "overdue",
    "plan_receive",
    "plan_send",
    "prune",
]

# src/jarvis/wardrobe/laundry/tools.py
"""R13 Part B's five tools (docs/plans/r13-wardrobe.md "Tools", D10, D11, D18), all in the
`laundry` permission row, every call through the gateway.

- `laundry_status` (R1): the laundry list, or one piece's history (LND-15). Vouches only when every
  string in it is his own typed words or a fixed word (a shop's label noted from a round that read
  other people's words, or spoken, does not vouch).
- `laundry_move` (R2, `spoken_ok`): basket, lifted, load, washing, drying, prep, ready. Piece ids,
  or (D10's one exception) a `query` in his words: if the call becomes a card, its stored arguments
  keep his words as typed while the card's text comes from `preview` through `redact.py`.
- `laundry_review` (R2): list the checks, answer one, or report a blind period (OPS-02).
- `laundry_correct` (R2): strike out a recorded step (LND-05; A's `correct`).
- `laundry_send_out` (R2): a batch to an outside laundry with its `due` date, and each piece back.
Results list at most 20 pieces, fence his labels and the shop's label, show a private piece as "a
private basic". Activity shows fixed words. Nothing orders, pays, calls or sends a message: no
argument here could.
"""

from __future__ import annotations

from typing import Any, cast

from jarvis.belongings.tools import origin_of
from jarvis.core.channel import on_telegram
from jarvis.core.guardrails import ActionRisk
from jarvis.tools.base import Preview, Tool
from jarvis.tools.context import require_tool_context
from jarvis.tools.provenance import vouch
from jarvis.tools.taint import owner_text, spoken_in_context
from jarvis.wardrobe.laundry import cards, checks, history, texts
from jarvis.wardrobe.laundry.cards import fence, fenced, shown
from jarvis.wardrobe.laundry.flows import Desk, Done
from jarvis.wardrobe.laundry.store import LaundryUnavailable, Origin
from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.ports import MAX_RESULT_PIECES, SPOKEN_OK, Refused

AGENT = "laundry"


def _via() -> str:
    """Where a tap came from (the event's `via`), from the call's context, never an argument
    (review L1): Telegram, a spoken turn, a chat turn (his words in it), else his panel (A's
    route and an approved card run with no turn's words)."""
    if on_telegram():
        return "telegram"
    if require_tool_context().spoken or spoken_in_context():
        return "voice"
    return "chat" if owner_text() is not None else "panel"


def _how(a: dict[str, Any]) -> str:
    """How a check was answered (`qr`, `label`, ...): only his panel says so; the model's call
    is a tap (review L1)."""
    return str(a.get("how", "tap")) if _via() == "panel" else "tap"


def _answer(done: Done) -> dict[str, Any]:
    view = done.committed.view if done.committed is not None else None
    out: dict[str, Any] = {"status": done.status, "message": done.message}
    if view is not None:
        out["pieces"] = [shown(view, pid) for pid in done.pieces[:MAX_RESULT_PIECES]]
    for key in ("entry", "load", "batch"):
        if getattr(done, key):
            out[key] = getattr(done, key)
    return out


async def _guarded(work: Any) -> Any:
    try:
        return await work
    except Refused as exc:
        return {"status": "refused", "message": str(exc)}
    except LaundryUnavailable as exc:
        return {"status": "unavailable", "message": str(exc)}


class LaundryAPI:
    def __init__(self, desk: Desk) -> None:
        self._d = desk

    async def status(self, a: dict[str, Any]) -> Any:
        uid = require_tool_context().user_id
        if a.get("piece") or a.get("query"):
            return await _guarded(self._one(uid, a))
        return await _guarded(self._list(uid))

    async def _one(self, uid: str, a: dict[str, Any]) -> Any:
        got = await self._d.history(uid, piece=a.get("piece"), query=a.get("query"))
        if got.get("found"):  # review M5: his place label too, fenced (masked when spoken)
            place = got.get("place") or ""
            got = {**got, "piece": fenced(got["piece"]), "place": fence(place) if place else ""}
        return vouch(got, True)

    async def _list(self, uid: str) -> Any:
        view, laundry, queue = await self._d.read(uid)
        _, today, _ = await self._d.today(uid)
        st = history.status(view, laundry, queue, today)
        budget, more = MAX_RESULT_PIECES, 0
        for name, _ in history.LISTS:
            ids = st[name]
            st[name] = [shown(view, pid) for pid in ids[:budget]]
            more += len(ids) - len(st[name])
            budget -= len(st[name])
        if more:
            st["more"] = more
        typed = all(b["origin"] == "typed" for b in st["batches"])
        st["batches"] = [{**b, "shop": fence(b["shop"])} for b in st["batches"]]
        return vouch(st, typed)

    async def move(self, a: dict[str, Any]) -> Any:
        uid = require_tool_context().user_id
        return await _guarded(self._move(uid, a))

    async def _move(self, uid: str, a: dict[str, Any]) -> dict[str, Any]:
        done = await self._d.move(
            uid,
            a["step"],
            pieces=a.get("pieces", ()),
            query=a.get("query"),
            one_of=a.get("one_of", ()),
            more=int(a.get("more", 0)),
            category=a.get("category"),
            place=a.get("place"),
            load=a.get("load"),
            client_id=a.get("client_id"),
            rev=a.get("rev"),
            via=_via(),
        )
        return _answer(done)

    async def review(self, a: dict[str, Any]) -> Any:
        uid = require_tool_context().user_id
        action = a.get("action", "list")
        if action == "list":
            return await _guarded(self._entries(uid))
        if action == "blind":
            return await _guarded(self._blind(uid, a))
        return await _guarded(self._resolve(uid, a))

    async def _entries(self, uid: str) -> dict[str, Any]:
        got = await self._d.review_view(uid)
        return {
            "open": got.open,
            "entries": [e.model_dump(mode="json") for e in got.entries[:MAX_RESULT_PIECES]],
        }

    async def _blind(self, uid: str, a: dict[str, Any]) -> dict[str, Any]:
        since, day = checks.stated(a)
        done = await self._d.blind(
            uid,
            places=a.get("places", ()),
            categories=a.get("categories", ()),
            since=since,
            day=day,
            via=_via(),
        )
        return _answer(done)

    async def _resolve(self, uid: str, a: dict[str, Any]) -> dict[str, Any]:
        done = await self._d.resolve(
            uid,
            a["entry"],
            a["outcome"],
            pieces=a.get("pieces", ()),
            to=a.get("to"),
            place=a.get("place"),
            how=_how(a),
            via=_via(),
        )
        return _answer(done)

    async def correct(self, a: dict[str, Any]) -> Any:
        uid = require_tool_context().user_id

        async def work() -> dict[str, Any]:
            return _answer(await self._d.correct(uid, a["piece"], a.get("event")))

        return await _guarded(work())

    async def send_out(self, a: dict[str, Any]) -> Any:
        ctx = require_tool_context()
        if a.get("action", "send") == "receive":
            work = self._d.receive(
                ctx.user_id,
                a["batch"],
                a.get("pieces", ()),
                to=a.get("to", "ready"),
                via=_via(),
            )
        elif ctx.outside:  # a card proposed in a round that read other people's words
            return {"status": "refused", "message": texts.TYPE_SHOP}
        else:
            work = self._d.send_out(
                ctx.user_id,
                a.get("pieces", ()),
                a["shop"],
                bag=a.get("bag", ""),
                due=checks.due_of(a),
                origin=cast("Origin", origin_of(ctx)),
                via=_via(),
            )

        async def answered() -> dict[str, Any]:
            return _answer(await work)

        return await _guarded(answered())

    # ---- the card's words: read-only look-ups (never raise for content) ------------------------
    async def _view(self) -> WardrobeView | None:
        try:
            return await self._d.wardrobe().view(require_tool_context().user_id)
        except (LaundryUnavailable, Refused):
            return None

    async def preview_move(self, a: dict[str, Any]) -> Preview:
        return Preview(cards.move(await self._view(), a))

    async def preview_review(self, a: dict[str, Any]) -> Preview:
        return Preview(cards.review(await self._view(), a))

    async def preview_correct(self, a: dict[str, Any]) -> Preview:
        return Preview(cards.correct(await self._view(), a))

    async def preview_send(self, a: dict[str, Any]) -> Preview:
        return Preview(cards.send(await self._view(), a))


def laundry_tools(desk: Desk) -> list[Tool]:
    api = LaundryAPI(desk)
    r1, r2 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE
    rows = (
        ("laundry_status", r1, api.status, checks.check_status, None, texts.LOOKED),
        ("laundry_move", r2, api.move, checks.check_move, api.preview_move, texts.MOVED),
        ("laundry_review", r2, api.review, checks.check_review, api.preview_review, texts.CHECKED),
        (
            "laundry_correct",
            r2,
            api.correct,
            checks.check_correct,
            api.preview_correct,
            texts.STRUCK,
        ),
        ("laundry_send_out", r2, api.send_out, checks.check_send, api.preview_send, texts.OUTSIDE),
    )
    return [
        Tool(
            name,
            checks.DESCRIPTIONS[name],
            checks.SCHEMAS[name],
            risk,
            run,
            agent=AGENT,
            check=check,
            preview=preview,
            may_vouch=risk is r1,  # a read vouches per result (D18); a write never does
            spoken_ok=name in SPOKEN_OK,  # laundry_move only (the contract's list)
            activity_words=words,
        )
        for name, risk, run, check, preview, words in rows
    ]


__all__ = ["AGENT", "LaundryAPI", "laundry_tools"]

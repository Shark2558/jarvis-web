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
from jarvis.tools.taint import spoken_in_context
from jarvis.wardrobe.laundry import cards, checks, history, texts
from jarvis.wardrobe.laundry.cards import fence, shown
from jarvis.wardrobe.laundry.flows import Desk, Done
from jarvis.wardrobe.laundry.store import LaundryUnavailable, Origin
from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.ports import MAX_RESULT_PIECES, Refused

AGENT = "laundry"


def _via() -> str:
    """Where a tap came from (the event's `via`): Telegram, a spoken turn, or the chat."""
    if on_telegram():
        return "telegram"
    return "voice" if require_tool_context().spoken or spoken_in_context() else "chat"


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
        if got.get("found") and isinstance(got.get("piece"), dict) and "label" in got["piece"]:
            got["piece"] = {**got["piece"], "label": fence(got["piece"]["label"])}
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
            via=a.get("via") or _via(),
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
            via=a.get("via") or _via(),
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
            how=a.get("how", "tap"),
            via=a.get("via") or _via(),
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
                via=a.get("via") or _via(),
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
                via=a.get("via") or _via(),
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
    s = checks.SCHEMAS
    return [
        Tool(
            "laundry_status",
            checks.DESCRIPTIONS["laundry_status"],
            s["laundry_status"],
            ActionRisk.READ_ONLY,
            api.status,
            check=checks.check_status,
            may_vouch=True,
            activity_words=texts.LOOKED,
            agent=AGENT,
        ),
        Tool(
            "laundry_move",
            checks.DESCRIPTIONS["laundry_move"],
            s["laundry_move"],
            ActionRisk.REVERSIBLE,
            api.move,
            check=checks.check_move,
            preview=api.preview_move,
            spoken_ok=True,
            activity_words=texts.MOVED,
            agent=AGENT,
        ),
        Tool(
            "laundry_review",
            checks.DESCRIPTIONS["laundry_review"],
            s["laundry_review"],
            ActionRisk.REVERSIBLE,
            api.review,
            check=checks.check_review,
            preview=api.preview_review,
            activity_words=texts.CHECKED,
            agent=AGENT,
        ),
        Tool(
            "laundry_correct",
            checks.DESCRIPTIONS["laundry_correct"],
            s["laundry_correct"],
            ActionRisk.REVERSIBLE,
            api.correct,
            check=checks.check_correct,
            preview=api.preview_correct,
            activity_words=texts.STRUCK,
            agent=AGENT,
        ),
        Tool(
            "laundry_send_out",
            checks.DESCRIPTIONS["laundry_send_out"],
            s["laundry_send_out"],
            ActionRisk.REVERSIBLE,
            api.send_out,
            check=checks.check_send,
            preview=api.preview_send,
            activity_words=texts.OUTSIDE,
            agent=AGENT,
        ),
    ]


__all__ = ["AGENT", "LaundryAPI", "laundry_tools"]

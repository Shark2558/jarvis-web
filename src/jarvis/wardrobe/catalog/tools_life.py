# src/jarvis/wardrobe/catalog/tools_life.py
"""Merge, archive / restore and remove (docs/plans/r13-wardrobe.md D16, D10; INV-16, INV-17).

- `wardrobe_merge` and `wardrobe_retire` are R2 cards EVERY time (`ask_when` always; I0 put both
  in `NO_BULK_TOOLS`, so "Approve all" never covers them). Restore reuses the same id and lands
  in "Missing or in review" until he says its condition: a second card of its own ("Mark a
  black belt Ready"); a condition for a piece still archived is refused before any card.
- `wardrobe_remove` is R2 `undoable`: the piece goes to Recently deleted (`undo.CatalogBin`); the
  gateway's delete cap and tainted rounds make it a card.
- Every card's words come from `preview` through `redact.card_words` ("Archive a black belt
  (No. 3)"; "a private basic" for a private piece): never his label.
"""

from __future__ import annotations

from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.tools.base import Preview, Tool
from jarvis.undo.tools import deleted_result
from jarvis.wardrobe.catalog.events import event
from jarvis.wardrobe.catalog.tools import AGENT, PIECE, SOURCE, guarded, typed, uid
from jarvis.wardrobe.model import Piece, WardrobeView
from jarvis.wardrobe.ports import Commit, Refused
from jarvis.wardrobe.redact import card_words
from jarvis.wardrobe.states import STATE_WORDS, STATED_CHOICES

MERGED, RETIRED, REMOVED = (
    "Merged two wardrobe records",
    "Archived or restored a piece",
    ("Removed a wardrobe piece"),
)
CONDITION = (
    "What condition is it in? Say Ready, Needs repair, In laundry or Needs prep, or check it "
    "in Helpers, Wardrobe."
)
CONDITIONS = tuple(s for s in STATED_CHOICES["found"] if s != "in_use")
RESTORE_FIRST = "Restore it first; then tell me its condition."


def _always(_: dict[str, Any]) -> bool:
    return True


def _check_merge(a: dict[str, Any]) -> None:
    if not isinstance(a.get("keep"), str) or not isinstance(a.get("merge"), str):
        raise ValueError("keep and merge are two piece ids")


def _check_retire(a: dict[str, Any]) -> None:
    if not isinstance(a.get("piece"), str) or a.get("action") not in ("archive", "restore"):
        raise ValueError("piece is a piece id; action is archive or restore")
    if a.get("condition") is not None and a["condition"] not in CONDITIONS:
        raise ValueError(f"condition is one of {', '.join(CONDITIONS)}")


def _check_piece(a: dict[str, Any]) -> None:
    if not isinstance(a.get("piece"), str):
        raise ValueError("piece is a piece id")


def _words(view: WardrobeView, pid: object) -> str:
    p = view.piece(str(pid))
    if p is None:
        return "a piece that isn't in your wardrobe"
    label = view.labels.get(p.label_code or "")
    return card_words(p, label.number if label else None)


class LifeTools:
    def __init__(self, desk: Any) -> None:
        self.d = desk

    async def _view(self) -> WardrobeView:
        return await self.d.store.view(uid())  # type: ignore[no-any-return]

    async def preview_merge(self, a: dict[str, Any]) -> Preview:
        view = await self._view()
        one, two = _words(view, a.get("merge")), _words(view, a.get("keep"))
        return Preview(f"Merge {one} into {two}: one piece with both histories")

    async def preview_retire(self, a: dict[str, Any]) -> Preview:
        """A card says exactly what he approves: a condition is its own card, "Mark a black
        belt Ready", never folded into a restore (INV-17: availability is confirmed apart)."""
        view = await self._view()
        if a.get("action") == "archive":
            return Preview(f"Archive {_words(view, a.get('piece'))}")
        p, condition = view.piece(str(a.get("piece"))), a.get("condition")
        if condition is None:
            return Preview(f"Restore {_words(view, a.get('piece'))}")
        if p is not None and p.state == "archived":
            raise Refused(RESTORE_FIRST)  # nothing is proposed
        return Preview(f"Mark {_words(view, a.get('piece'))} {STATE_WORDS[condition]}")

    async def preview_remove(self, a: dict[str, Any]) -> Preview:
        words = _words(await self._view(), a.get("piece"))
        return Preview(f"Remove {words} (kept in Recently deleted for 30 days)")

    async def merge(self, a: dict[str, Any]) -> Any:
        async def work() -> Any:
            view = await self._view()
            other = view.piece(a["merge"])
            if other is None or view.piece(a["keep"]) is None:
                raise Refused("That piece isn't in your wardrobe.")
            snap = {"ref": a["merge"], "merge": a["keep"]}
            kept = await self.d.bin.keep(uid(), snap, owner_authored=typed(other))
            try:
                await self.d.merge.merge(uid(), a["keep"], a["merge"])
            except Exception:
                await self.d.bin.bin().discard(uid(), kept.id)
                raise
            return {"status": "done", "piece": a["keep"], "undo_id": kept.id}

        return await guarded(work)

    async def retire(self, a: dict[str, Any]) -> Any:
        async def work() -> Any:
            p = (await self._view()).piece(a["piece"])
            if p is None or p.merged_into is not None:
                raise Refused("That piece isn't in your wardrobe.")
            if a["action"] == "archive":
                await self._events(p, ("archived", None))
                return {"status": "done", "piece": p.id}
            if a.get("condition"):  # its own card, never with the restore (M7)
                if p.state == "archived":
                    raise Refused(RESTORE_FIRST)
                await self._events(p, ("found", a["condition"]))
                return {"status": "done", "piece": p.id}
            if p.state != "archived":
                raise Refused("That piece isn't archived.")
            await self._events(p, ("restored", None))
            return {"status": "done", "piece": p.id, "question": CONDITION}

        return await guarded(work)

    async def _events(self, p: Piece, *steps: tuple[str, str | None]) -> None:
        now = self.d.store.now()
        events = tuple(event(p.id, kind, now, to=to) for kind, to in steps)

        async def fn(view: WardrobeView, tx: Any) -> Commit:
            return Commit(events=events)

        await self.d.store.transact(uid(), fn)

    async def remove(self, a: dict[str, Any]) -> Any:
        async def work() -> Any:
            p = (await self._view()).piece(a["piece"])
            if p is None:
                raise Refused("That piece isn't in your wardrobe.")
            kept = await self.d.bin.remove(uid(), p.id, owner_authored=typed(p))
            return deleted_result(kept, source=SOURCE, piece=p.id)

        return await guarded(work)


MERGE_SCHEMA = {"type": "object", "required": ["keep", "merge"],
                "properties": {"keep": PIECE, "merge": PIECE}}  # fmt: skip
RETIRE_SCHEMA = {"type": "object", "required": ["piece", "action"], "properties": {
    "piece": PIECE, "action": {"enum": ["archive", "restore"]},
    "condition": {"enum": list(CONDITIONS)}}}  # fmt: skip
ONE_SCHEMA = {"type": "object", "required": ["piece"], "properties": {"piece": PIECE}}


def life_tools(desk: Any) -> list[Tool]:
    api = LifeTools(desk)
    r2, merge, retire, one = ActionRisk.REVERSIBLE, MERGE_SCHEMA, RETIRE_SCHEMA, ONE_SCHEMA
    return [
        Tool(
            "wardrobe_merge",
            "Merge two records of ONE physical piece into one id with both histories (the "
            "owner always confirms; undo from Recently deleted). Never for two real copies.",
            merge,
            r2,
            api.merge,
            agent=AGENT,
            check=_check_merge,
            preview=api.preview_merge,
            summarize=lambda a: "Merge two wardrobe records",
            ask_when=_always,
            activity_words=MERGED,
        ),  # fmt: skip
        Tool(
            "wardrobe_retire",
            "Archive a piece he no longer uses (out of every count), or restore an archived "
            "one with the same id; restore asks for its condition. The owner always confirms.",
            retire,
            r2,
            api.retire,
            agent=AGENT,
            check=_check_retire,
            preview=api.preview_retire,
            summarize=lambda a: "Archive or restore a wardrobe piece",
            ask_when=_always,
            activity_words=RETIRED,
        ),  # fmt: skip
        Tool(
            "wardrobe_remove",
            "Remove a piece from the wardrobe; it stays in Recently deleted for 30 days.",
            one,
            r2,
            api.remove,
            agent=AGENT,
            check=_check_piece,
            preview=api.preview_remove,
            summarize=lambda a: "Remove a wardrobe piece (kept in Recently deleted)",
            undoable=True,
            activity_words=REMOVED,
        ),  # fmt: skip
    ]


__all__ = [
    "CONDITION",
    "CONDITIONS",
    "MERGED",
    "REMOVED",
    "RESTORE_FIRST",
    "RETIRED",
    "LifeTools",
    "life_tools",
]

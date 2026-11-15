# src/jarvis/wardrobe/catalog/tools_write.py
"""Part A's write tools (docs/plans/r13-wardrobe.md "Tools", D1, D6, D10, D18): `wardrobe_add`,
`wardrobe_edit` and `wardrobe_places`, all R2 in the `wardrobe` row, through the gateway.

- Write tools take piece ids; `wardrobe_edit` also takes his words (`query`) for ONE thing only,
  a move ("I put my watch in the travel bag", D6), resolved to a single piece or refused with the
  candidates (never a guess).
- A card's words never carry his label: `summarize` and `preview` go through `redact.card_words`
  (the approvals store is clear JSON, printed on Telegram).
- His own words only: a label or a place name proposed in a round that read other people's
  content is not saved (the piece is, without it); a label he types locks (it vouches), one he
  says does not.
"""

from __future__ import annotations

from typing import Any

from jarvis.belongings.tools import origin_of
from jarvis.core.guardrails import ActionRisk
from jarvis.tools.base import Preview, Tool
from jarvis.tools.context import require_tool_context
from jarvis.wardrobe.catalog.edits import Edit, NewPiece
from jarvis.wardrobe.catalog.places import resolve_place, unknown_place
from jarvis.wardrobe.catalog.search import rank
from jarvis.wardrobe.catalog.tools import AGENT, PIECE, QUERY, guarded, line, uid
from jarvis.wardrobe.model import PRIVATE_BY_DEFAULT, Piece, WardrobeView
from jarvis.wardrobe.ports import Refused
from jarvis.wardrobe.redact import card_words, fixed_words

ADDED, CHANGED, PLACED = "Added to your wardrobe", "Changed your wardrobe", "Changed your places"
NOT_OWN = "Saved without the label: labels and places are only ever your own words."
_ATTRS = (
    *("type", "label", "colour", "second", "pattern", "features", "formality", "occasions"),
    *("weather", "mess_ok", "delicate", "private", "size", "brand", "fabric", "care", "read"),
    *("verify", "lock", "unlock", "suggested"),
)
_TUPLES = ("occasions", "weather", "fabric", "care", "verify", "lock", "unlock")
_NEW = ("type", "label", "colour", "pattern", "private", "place", "state", "client_id")


def _words(a: dict[str, Any]) -> str:
    kind = str(a.get("type") or "unknown")
    probe = Piece.model_construct(type=kind, colour=a.get("colour"), private=_private(a))
    return fixed_words(probe)


def _private(a: dict[str, Any]) -> bool:
    found = a.get("private")
    return bool(found) if found is not None else a.get("type") in PRIVATE_BY_DEFAULT


def _card_add(a: dict[str, Any]) -> str:
    pieces = [p for p in a.get("pieces", []) if isinstance(p, dict)]
    words = ", ".join(_words(p) for p in pieces[:5]) + (" ..." if len(pieces) > 5 else "")
    return f"Add {len(pieces)} piece(s) to your wardrobe: {words}"


def _card_places(a: dict[str, Any]) -> str:
    what = {"add": "Add a place", "rename": "Rename a place", "remove": "Remove a place"}
    return f"{what.get(str(a.get('action')), 'Change your places')} in your wardrobe"


def _check_add(a: dict[str, Any]) -> None:
    pieces = a.get("pieces")
    if not isinstance(pieces, list) or not 1 <= len(pieces) <= 20:
        raise ValueError("pieces is a list of 1 to 20 pieces")
    if any(not isinstance(p, dict) or not isinstance(p.get("type"), str) for p in pieces):
        raise ValueError("every piece needs its type")
    if any(set(p) - set(_NEW) for p in pieces):
        raise ValueError(f"a piece has only {', '.join(_NEW)}")


def _check_edit(a: dict[str, Any]) -> None:
    if not isinstance(a.get("piece"), str) and not isinstance(a.get("query"), str):
        raise ValueError("piece is a piece id (or query, for a move only)")
    if "query" in a and (set(a) - {"query", "place"} or "place" not in a):
        raise ValueError("query is only for a move: query and place")


def _edit_of(a: dict[str, Any], typed: bool) -> Edit | None:
    found = {k: a[k] for k in _ATTRS if k in a}
    if not found:
        return None
    found |= {k: tuple(found[k]) for k in _TUPLES if k in found}
    if "label" in found:
        key = "lock" if typed else "unlock"
        found[key] = (*found.get(key, ()), "label")
    try:
        return Edit(**found)
    except TypeError:
        raise Refused("That change has a field I don't know.") from None


class WriteTools:
    def __init__(self, desk: Any) -> None:
        self.d = desk

    async def add(self, a: dict[str, Any]) -> Any:
        origin = origin_of(require_tool_context())

        async def work() -> Any:
            view = await self.d.store.view(uid())
            specs, dropped = [], False
            for p in a["pieces"]:
                place = None
                if p.get("place"):
                    found = resolve_place(view, str(p["place"]))
                    if found is None:
                        raise Refused(unknown_place(view))
                    place = found.id
                label = str(p.get("label") or "")
                if origin == "outside" and label:
                    label, dropped = "", True
                keys = ("colour", "pattern", "private", "state", "client_id")
                fields = {k: p[k] for k in keys if p.get(k) is not None}
                spec = NewPiece(
                    type=p["type"], label=label, place=place, typed=origin == "typed", **fields
                )
                specs.append(spec)
            got = await self.d.service.add(uid(), specs)
            out: dict[str, Any] = {"status": "done", "ids": list(got.ids), "new": list(got.new)}
            return out | ({"note": NOT_OWN} if dropped else {})

        return await guarded(work)

    async def _piece(self, view: WardrobeView, a: dict[str, Any]) -> Piece:
        if isinstance(a.get("piece"), str):
            p = view.piece(a["piece"])
            if p is None or p.merged_into is not None:
                raise Refused("That piece isn't in your wardrobe.")
            return p
        found = rank(view, a["query"])
        if found.best is None:
            why = "Several pieces fit: say which one." if found.matches else "Not in your wardrobe."
            raise Refused(why)
        return found.best

    async def preview_edit(self, a: dict[str, Any]) -> Preview:
        try:
            view = await self.d.store.view(uid())
            p = await self._piece(view, a)
            label = view.labels.get(p.label_code or "")
            return Preview(f"Change {card_words(p, label.number if label else None)}")
        except Exception:  # noqa: BLE001 - the card still never names his piece
            return Preview("Change a piece in your wardrobe")

    async def edit(self, a: dict[str, Any]) -> Any:
        origin = origin_of(require_tool_context())

        async def work() -> Any:
            view = await self.d.store.view(uid())
            p = await self._piece(view, a)
            if origin == "outside":
                a.pop("label", None)
            change = _edit_of(a, origin == "typed")
            if change is not None:
                done = await self.d.service.edit(uid(), p.id, change)
                if done.status == "ask":
                    return {"status": "ask", "question": done.question, "piece": p.id}
            if a.get("place"):
                await self.d.service.move(uid(), p.id, str(a["place"]))
            await self._links(p.id, a)
            fresh = await self.d.store.view(uid())
            shown = line(fresh, fresh.pieces[p.id], self.d.views.place_words)
            return {"status": "done", "piece": shown}

        return await guarded(work)

    async def _links(self, pid: str, a: dict[str, Any]) -> None:
        if "label_code" in a:
            code = str(a["label_code"] or "")
            if code:
                await self.d.labels.assign(uid(), code, pid)
            elif (worn := (await self.d.store.view(uid())).pieces[pid].label_code) is not None:
                await self.d.labels.assign(uid(), worn, None)  # "" frees the label it wears
        if a.get("unpair"):
            await self.d.links.unpair(uid(), pid)
        if a.get("pair_with"):
            await self.d.links.pair(uid(), pid, str(a["pair_with"]))
        if a.get("set_parts"):
            parts = [(str(x["piece"]), bool(x.get("alone"))) for x in a["set_parts"]]
            await self.d.links.make_set(uid(), parts, label=str(a.get("set_label") or ""))

    async def places(self, a: dict[str, Any]) -> Any:
        origin = origin_of(require_tool_context())
        act = a["action"]

        async def work() -> Any:
            if act in ("add", "rename") and origin == "outside":
                raise Refused("A place is named only in your own words.")
            if act == "add":
                made = await self.d.places.add(
                    uid(), str(a.get("label", "")), str(a.get("kind", "storage"))
                )
                return {"status": "done", "place": made.id}
            if act == "rename":
                done = await self.d.places.rename(
                    uid(), str(a.get("place")), str(a.get("label", ""))
                )
                return {"status": "done", "place": done.id}
            if act == "remove":
                return {
                    "status": "done",
                    "place": await self.d.places.remove(uid(), str(a.get("place"))),
                }
            if act == "baseline":
                return await self._baseline(a)
            view = await self.d.store.view(uid())
            rows = [
                {"id": p.id, "kind": p.kind, "baselined": p.baseline_at is not None}
                for p in view.places.values()
            ]
            return {"places": rows}

        return await guarded(work)

    async def _baseline(self, a: dict[str, Any]) -> dict[str, Any]:
        seen, unresolved = list(a.get("seen") or []), int(a.get("unresolved") or 0)
        b = await self.d.places.baseline(
            uid(), str(a.get("place")), seen=seen, unresolved=unresolved
        )
        return {
            "status": "done",
            "seen": len(b.seen),
            "unresolved": b.unresolved,
            "places_without_baseline": len(b.without_baseline),
        }


def _schema_edit() -> dict[str, Any]:
    s, b, i = {"type": "string"}, {"type": "boolean"}, {"type": "integer"}
    arr = {"type": "array", "items": s}
    props: dict[str, Any] = {"piece": PIECE, "query": QUERY, "pair_with": PIECE}
    props["place"] = {"type": "string", "description": "A place he named"}
    props["features"] = {"type": "object"}
    props["set_parts"] = {"type": "array", "items": {"type": "object"}}
    props |= dict.fromkeys(("type", "label", "colour", "second", "pattern", "size", "brand"), s)
    props |= dict.fromkeys(("label_code", "set_label"), s)
    props |= dict.fromkeys(("occasions", "weather", "fabric", "care", "verify", "lock"), arr)
    props |= dict.fromkeys(("unlock",), arr)
    props |= dict.fromkeys(("mess_ok", "delicate", "private", "read", "suggested", "unpair"), b)
    props["formality"] = i
    return {"type": "object", "properties": props}


def _schema_places() -> dict[str, Any]:
    acts = ["list", "add", "rename", "remove", "baseline"]
    props: dict[str, Any] = {"action": {"enum": acts}, "seen": {"type": "array"}}
    props |= dict.fromkeys(("place", "label", "kind"), {"type": "string"})
    props["unresolved"] = {"type": "integer"}
    return {"type": "object", "required": ["action"], "properties": props}


def _schema_add() -> dict[str, Any]:
    piece = {"type": "object", "properties": {k: {} for k in _NEW}, "required": ["type"]}
    pieces = {"type": "array", "items": piece}
    return {"type": "object", "properties": {"pieces": pieces}, "required": ["pieces"]}


def write_tools(desk: Any) -> list[Tool]:
    api = WriteTools(desk)
    r2 = ActionRisk.REVERSIBLE
    return [
        Tool(
            "wardrobe_add",
            "Add pieces to the owner's wardrobe: one record per physical piece (each sock and "
            "each shoe is its own piece; pair them with wardrobe_edit).",
            _schema_add(),
            r2,
            api.add,
            agent=AGENT,
            check=_check_add,
            summarize=_card_add,
            activity_words=ADDED,
        ),  # fmt: skip
        Tool(
            "wardrobe_edit",
            "Change one piece by its id: type, attributes, lock, a care or size field, private, "
            "its place, its QR label, its pair or set. Only a move may name the piece by his "
            "words (query + place).",
            _schema_edit(),
            r2,
            api.edit,
            agent=AGENT,
            check=_check_edit,
            preview=api.preview_edit,
            summarize=lambda a: "Change a piece in your wardrobe",
            activity_words=CHANGED,
        ),  # fmt: skip
        Tool(
            "wardrobe_places",
            "List, add, rename or remove the owner's wardrobe places, or record a baseline "
            "scan of one.",
            _schema_places(),
            r2,
            api.places,
            agent=AGENT,
            summarize=_card_places,
            activity_words=PLACED,
        ),  # fmt: skip
    ]


__all__ = ["ADDED", "CHANGED", "NOT_OWN", "PLACED", "WriteTools", "write_tools"]

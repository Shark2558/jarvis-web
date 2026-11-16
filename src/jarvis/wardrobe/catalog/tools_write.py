# src/jarvis/wardrobe/catalog/tools_write.py
"""Part A's write tools (docs/plans/r13-wardrobe.md "Tools", D1, D6, D10, D18): `wardrobe_add`,
`wardrobe_edit` and `wardrobe_places`, all R2 in the `wardrobe` row, through the gateway.

- Write tools take piece ids only (D10): "I put my watch in the travel bag" is `wardrobe_find`
  first, then `wardrobe_edit(piece=<id>, place=...)` (D6 as amended by review A-1, deviation 6),
  so his words never sit in a card's stored arguments.
- A card's words never carry his label: `summarize` and `preview` go through `redact.card_words`
  (the approvals store is clear JSON, printed on Telegram).
- His own words only: a label or a place name (by its words, not its id) proposed in a round
  that read other people's content is refused in `check`, before any card stores it; a label he
  types locks (it vouches), one he says does not.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from jarvis.belongings.tools import origin_of
from jarvis.core.guardrails import ActionRisk
from jarvis.tools.base import Preview, Tool
from jarvis.tools.context import require_tool_context
from jarvis.tools.taint import content_tainted
from jarvis.wardrobe.catalog.edits import Edit, NewPiece
from jarvis.wardrobe.catalog.labels import NOT_HIS
from jarvis.wardrobe.catalog.links import pair_refusal, set_refusal
from jarvis.wardrobe.catalog.places import resolve_place, unknown_place
from jarvis.wardrobe.catalog.store import WardrobeUnavailable
from jarvis.wardrobe.catalog.tools import AGENT, PIECE, failed, guarded, line, uid
from jarvis.wardrobe.model import PLACE_ID, PRIVATE_BY_DEFAULT, Piece, WardrobeView
from jarvis.wardrobe.ports import Refused
from jarvis.wardrobe.redact import card_words, fixed_words

ADDED, CHANGED, PLACED = "Added to your wardrobe", "Changed your wardrobe", "Changed your places"
NOT_OWN = "Saved without the label: labels and places are only ever your own words."
TAINTED = (
    "This round read other people's content, and labels and place names are only ever his own "
    "words: leave the label out and name places by their id, or he types it in Helpers, Wardrobe."
)
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


def _by_name(place: object) -> bool:
    """A place given by his words, not by its id."""
    return isinstance(place, str) and bool(place.strip()) and not PLACE_ID.match(place)


def _own_words(texts: Iterable[object], places: Iterable[object] = ()) -> None:
    """On a round that read other people's content his free text never enters a card's stored
    arguments (approvals are clear JSON, printed on Telegram; D10): refused before any card."""
    if not content_tainted():
        return
    if any(isinstance(t, str) and t.strip() for t in texts) or any(map(_by_name, places)):
        raise ValueError(TAINTED)


def _check_add(a: dict[str, Any]) -> None:
    pieces = a.get("pieces")
    if not isinstance(pieces, list) or not 1 <= len(pieces) <= 20:
        raise ValueError("pieces is a list of 1 to 20 pieces")
    if any(not isinstance(p, dict) or not isinstance(p.get("type"), str) for p in pieces):
        raise ValueError("every piece needs its type")
    if any(set(p) - set(_NEW) for p in pieces):
        raise ValueError(f"a piece has only {', '.join(_NEW)}")
    _own_words((p.get("label") for p in pieces), (p.get("place") for p in pieces))


def _check_edit(a: dict[str, Any]) -> None:
    if not isinstance(a.get("piece"), str):
        raise ValueError("piece is a piece id: find it with wardrobe_find first")
    parts = a.get("set_parts", [])
    if not isinstance(parts, list) or any(not isinstance(x, dict) for x in parts):
        raise ValueError("set_parts is a list of {piece, alone}")
    _own_words((a.get("label"), a.get("set_label")), (a.get("place"),))


def _check_places(a: dict[str, Any]) -> None:
    named = a.get("label") if a.get("action") in ("add", "rename") else None
    _own_words((named,), (a.get("place"),))


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
                        raise unknown_place(view)
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
        p = view.piece(str(a.get("piece")))
        if p is None or p.merged_into is not None:
            raise Refused("That piece isn't in your wardrobe.")
        return p

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
        args = {k: v for k, v in a.items() if not (origin == "outside" and k == "label")}

        async def work() -> Any:
            view = await self.d.store.view(uid())
            p = await self._piece(view, args)
            self._first(view, p, args)  # every part checked before the first commit (L8)
            change = _edit_of(args, origin == "typed")
            saved: list[str] = []
            try:
                if change is not None:
                    done = await self.d.service.edit(uid(), p.id, change)
                    if done.status == "ask":
                        return {"status": "ask", "question": done.question, "piece": p.id}
                    saved.append("fields")
                await self._links(p.id, args, saved)
            except (Refused, WardrobeUnavailable) as exc:
                if not saved:
                    raise
                return {"status": "partial", "saved": saved, "message": failed(exc)["message"]}
            fresh = await self.d.store.view(uid())
            shown = line(fresh, fresh.pieces[p.id], self.d.views.place_words)
            return {"status": "done", "piece": shown}

        return await guarded(work)

    def _first(self, view: WardrobeView, p: Piece, a: dict[str, Any]) -> None:
        """What would refuse a later step, refused before anything is written."""
        if a.get("place") and resolve_place(view, str(a["place"])) is None:
            raise unknown_place(view)
        code = str(a.get("label_code") or "")
        if code and code not in view.labels and self.d.labels.number_of(uid(), code) is None:
            raise Refused(NOT_HIS)
        freeing = p.id if a.get("unpair") else None
        if a.get("pair_with"):
            why = pair_refusal(view, p.id, str(a["pair_with"]), freeing=freeing)
            if why is not None:
                raise Refused(why)
        if a.get("set_parts"):
            why = set_refusal(view, [str(x.get("piece")) for x in a["set_parts"]])
            if why is not None:
                raise Refused(why)

    async def _links(self, pid: str, a: dict[str, Any], saved: list[str]) -> None:
        if a.get("place"):
            await self.d.service.move(uid(), pid, str(a["place"]))
            saved.append("place")
        if "label_code" in a:
            code = str(a["label_code"] or "")
            if code:
                await self.d.labels.assign(uid(), code, pid)
            elif (worn := (await self.d.store.view(uid())).pieces[pid].label_code) is not None:
                await self.d.labels.assign(uid(), worn, None)  # "" frees the label it wears
            saved.append("label")
        if a.get("unpair"):
            await self.d.links.unpair(uid(), pid)
            saved.append("pair")
        if a.get("pair_with"):
            await self.d.links.pair(uid(), pid, str(a["pair_with"]))
            saved.append("pair")
        if a.get("set_parts"):
            parts = [(str(x["piece"]), bool(x.get("alone"))) for x in a["set_parts"]]
            await self.d.links.make_set(uid(), parts, label=str(a.get("set_label") or ""))
            saved.append("set")

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
    props: dict[str, Any] = {"piece": PIECE, "pair_with": PIECE}
    props["place"] = {"type": "string", "description": "A place he named"}
    props["features"] = {"type": "object"}
    props["set_parts"] = {"type": "array", "items": {"type": "object"}}
    props |= dict.fromkeys(("type", "label", "colour", "second", "pattern", "size", "brand"), s)
    props |= dict.fromkeys(("label_code", "set_label"), s)
    props |= dict.fromkeys(("occasions", "weather", "fabric", "care", "verify", "lock"), arr)
    props |= dict.fromkeys(("unlock",), arr)
    props |= dict.fromkeys(("mess_ok", "delicate", "private", "read", "suggested", "unpair"), b)
    props["formality"] = i
    return {"type": "object", "required": ["piece"], "properties": props}


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
            "Change one piece by its id (find it with wardrobe_find first): type, attributes, "
            "lock, a care or size field, private, its place, its QR label, its pair or set.",
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
            check=_check_places,
            summarize=_card_places,
            activity_words=PLACED,
        ),  # fmt: skip
    ]


__all__ = ["ADDED", "CHANGED", "NOT_OWN", "PLACED", "TAINTED", "WriteTools", "write_tools"]

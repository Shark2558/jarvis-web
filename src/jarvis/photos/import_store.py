# src/jarvis/photos/import_store.py
"""Where a Google Photos import stands, and who may step it (R11.1 O6; plan D14; review C-code H2).

    {prefix}photo_imports/{uid}   {session_id, state, total, done, faces, known, skipped, over,
                                   todo: [Google item ids still to do], list_token, cursor,
                                   wrapped, people: [fp_ ids recognised], paused, stuck,
                                   stuck_tries, rate_mpps, holder, lease_until, updated_at}

Ids and counts only: never a picture, a link or a name.

Two instances (the clock and the panel at once, or two Cloud Run revisions during a deploy) must
never step one import together. So a step first CLAIMS the import in a transaction (`claim`: a
random `holder` and a `lease_until`; a live lease held by someone else means "busy", and the step
does nothing), every save checks in its own transaction that the claim is still the step's and
renews it (`put`; a lost claim raises `LeaseLost` and the step stops writing), and the claim is
given back at the end (`release`). A lease left by a step that died runs out by itself. A new pick
(`start`) and a stop (`delete`) win over any step in flight. `expire` never marks a finished
import expired and never touches another pick's document.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from jarvis.faces.ports import is_person_id
from jarvis.photos.picker import PICKER_MAX
from jarvis.storage.docs import Delete, Docs, DocTx, Set
from jarvis.undo.store import owner_ok

STATES = ("none", "picking", "listing", "reading", "done", "expired")
PAUSES = {
    "laptop": "laptop not reachable",
    "kit": "update the home kit on your laptop (Integrations -> Home)",
    "reader": "the face reader on your laptop isn't ready yet",
    "edge": "your laptop's answer couldn't be understood",
    "google": "Google Photos isn't answering",
}
ID_MAX = 200
TOKEN_MAX = 2000
MAX_PEOPLE = 30
HOLDER_MAX = 32
EXPIRED_WORDS = "the Google Photos session ended: pick again to continue"
CLOCK_STEP_S = 13.5  # what one 5-minute tick of the helpers' clock gives an import step
TICK_S = 300.0
FASTER = "keep the Connectors panel open to go faster"


class LeaseLost(RuntimeError):
    """This step no longer holds the import: a newer step, a new pick or a stop took it."""


@dataclass(frozen=True)
class ImportDoc:
    session_id: str = ""
    state: str = "none"
    total: int = 0
    done: int = 0
    faces: int = 0
    known: int = 0
    skipped: int = 0
    over: int = 0
    todo: tuple[str, ...] = ()
    list_token: str = ""
    cursor: str = ""
    wrapped: bool = False  # this pass of the list began at its first page and found nothing yet
    people: tuple[str, ...] = ()
    paused: str = ""
    stuck: str = ""  # a photo Google failed to hand over (5xx, 429, a timeout): tried again
    stuck_tries: int = 0  # steps in a row that photo failed in
    rate_mpps: int = 0  # photos per 1,000 seconds of step time, as last measured (for the pace)

    @property
    def unknown(self) -> int:
        return max(0, self.faces - self.known)


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _text(value: object, limit: int) -> str:
    return value if isinstance(value, str) and len(value) <= limit else ""


def _plural(n: int, one: str, many: str) -> str:
    return f"{n:,} {one if n == 1 else many}"


def pace(doc: ImportDoc) -> str:
    """'about 14 hours left' in the background, from the pace last measured; '' when unknown."""
    left = len(doc.todo)
    per_tick = doc.rate_mpps * CLOCK_STEP_S / 1000
    if doc.state != "reading" or not left or per_tick <= 0:
        return ""
    minutes = round(left / per_tick * TICK_S / 60)
    if minutes < 90:
        when = _plural(max(5, 5 * round(minutes / 5)), "minute", "minutes")
    else:
        when = _plural(round(minutes / 60), "hour", "hours")
    return f"about {when} left; {FASTER}"


def describe(doc: ImportDoc, limit: int = PICKER_MAX) -> str:
    """The import in plain words: "312 of 2,000 read · 41 faces found · paused: ..."."""
    pause = f"paused: {PAUSES[doc.paused]}" if doc.paused in PAUSES else ""
    if doc.state == "picking":
        return f"P{pause[1:]}." if pause else "Waiting for you to choose photos."
    if doc.state == "listing":
        listing = f"Reading the list of what you picked ({len(doc.todo):,} so far)"
        return f"{listing} · {pause}" if pause else f"{listing}."
    if doc.state not in ("reading", "done", "expired"):
        return ""
    parts = [f"{doc.done:,} of {doc.total:,} read", _plural(doc.faces, "face", "faces") + " found"]
    if doc.skipped:
        parts.append(f"{doc.skipped:,} could not be read")
    if doc.over:
        parts.append(f"{doc.over:,} more were picked than your limit of {limit:,}")
    if doc.state == "expired":
        parts.append(EXPIRED_WORDS)
    elif pause:
        parts.append(pause)
    elif pace(doc):
        parts.append(pace(doc))
    return " · ".join(parts)


def parse(raw: object) -> ImportDoc:
    if not isinstance(raw, dict):
        return ImportDoc()
    state, todo, people = raw.get("state"), raw.get("todo"), raw.get("people")
    ids = (
        [t for t in todo if isinstance(t, str) and 0 < len(t) <= ID_MAX]
        if isinstance(todo, list)
        else []
    )
    return ImportDoc(
        session_id=_text(raw.get("session_id"), ID_MAX),
        state=state if state in STATES else "none",
        total=_count(raw.get("total")),
        done=_count(raw.get("done")),
        faces=_count(raw.get("faces")),
        known=_count(raw.get("known")),
        skipped=_count(raw.get("skipped")),
        over=_count(raw.get("over")),
        todo=tuple(ids[:PICKER_MAX]),
        list_token=_text(raw.get("list_token"), TOKEN_MAX),
        cursor=_text(raw.get("cursor"), TOKEN_MAX),
        wrapped=raw.get("wrapped") is True,
        people=tuple(p for p in people if is_person_id(p))[:MAX_PEOPLE]
        if isinstance(people, list)
        else (),
        paused=_text(raw.get("paused"), 16) if raw.get("paused") in PAUSES else "",
        stuck=_text(raw.get("stuck"), ID_MAX),
        stuck_tries=_count(raw.get("stuck_tries")),
        rate_mpps=_count(raw.get("rate_mpps")),
    )


def body(doc: ImportDoc) -> dict[str, Any]:
    return {
        "session_id": doc.session_id,
        "state": doc.state,
        "total": doc.total,
        "done": doc.done,
        "faces": doc.faces,
        "known": doc.known,
        "skipped": doc.skipped,
        "over": doc.over,
        "todo": list(doc.todo),
        "list_token": doc.list_token,
        "cursor": doc.cursor,
        "wrapped": doc.wrapped,
        "people": list(doc.people),
        "paused": doc.paused,
        "stuck": doc.stuck,
        "stuck_tries": doc.stuck_tries,
        "rate_mpps": doc.rate_mpps,
        "updated_at": datetime.now(UTC).isoformat(),
    }


class ImportStore:
    """`{prefix}photo_imports/{uid}`: one import's progress, in plain fields (ids and counts)."""

    def __init__(
        self, docs: Docs, *, prefix: str = "jarvis_", now: Callable[[], float] = time.time
    ) -> None:
        self._d = docs
        self._col = f"{prefix}photo_imports"
        self._now = now

    def _path(self, uid: str) -> str:
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        return f"{self._col}/{uid}"

    async def get(self, uid: str) -> ImportDoc:
        return parse(await self._d.get(self._path(uid)))

    async def start(self, uid: str, doc: ImportDoc) -> None:
        """A new pick: whatever import (and whatever step of it) was running is replaced."""
        await self._d.write([Set(self._path(uid), body(doc))])

    async def delete(self, uid: str) -> None:
        await self._d.write([Delete(self._path(uid))])

    def _held_by_other(self, raw: dict[str, Any], holder: str) -> bool:
        other = raw.get("holder")
        until = raw.get("lease_until")
        if not other or other == holder or isinstance(until, bool):
            return False
        return isinstance(until, int | float) and until > self._now()

    async def claim(
        self, uid: str, session_id: str, holder: str, lease_s: float
    ) -> ImportDoc | None:
        """This step's claim on the import, or None when another live step holds it (or the
        document is another pick's)."""
        path = self._path(uid)

        async def tx(t: DocTx) -> ImportDoc | None:
            raw = await t.get(path)
            if isinstance(raw, dict):
                doc = parse(raw)
                if doc.session_id != session_id and doc.state != "none":
                    return None  # a newer pick: not this step's to touch
                if self._held_by_other(raw, holder):
                    return None
            if not isinstance(raw, dict) or parse(raw).session_id != session_id:
                doc = ImportDoc(session_id, "picking")
            claim = {"holder": holder[:HOLDER_MAX], "lease_until": self._now() + lease_s}
            t.set(path, {**body(doc), **claim})
            return doc

        return await self._d.transaction(tx)

    async def put(self, uid: str, doc: ImportDoc, holder: str, lease_s: float) -> None:
        """Save, only while this step still holds the import (and renew its claim)."""
        path = self._path(uid)

        async def tx(t: DocTx) -> None:
            raw = await t.get(path)
            mine = isinstance(raw, dict) and raw.get("holder") == holder
            if not mine or parse(raw).session_id != doc.session_id:
                raise LeaseLost()
            t.set(path, {**body(doc), "holder": holder, "lease_until": self._now() + lease_s})

        await self._d.transaction(tx)

    async def release(self, uid: str, holder: str) -> None:
        path = self._path(uid)

        async def tx(t: DocTx) -> None:
            raw = await t.get(path)
            if isinstance(raw, dict) and raw.get("holder") == holder:
                t.set(path, {**raw, "holder": "", "lease_until": 0})

        await self._d.transaction(tx)

    async def expire(self, uid: str, session_id: str, holder: str = "") -> ImportDoc:
        """Google's session is over: keep the counts, drop the ids that can't be read any more.
        A finished import stays finished; another pick's document, or one a live step of
        someone else holds, is left as it is."""
        path = self._path(uid)

        async def tx(t: DocTx) -> ImportDoc:
            raw = await t.get(path)
            doc = parse(raw)
            if isinstance(raw, dict):
                if doc.state == "done" or (doc.session_id != session_id and doc.state != "none"):
                    return doc
                if self._held_by_other(raw, holder):
                    return doc
            if doc.session_id != session_id:
                doc = ImportDoc(session_id, "picking")
            ended = replace(
                doc, state="expired", todo=(), list_token="", cursor="", paused="", stuck=""
            )
            ended = replace(ended, stuck_tries=0)
            held = raw if isinstance(raw, dict) else {}
            lease = {"holder": held.get("holder", ""), "lease_until": held.get("lease_until", 0)}
            t.set(path, {**body(ended), **lease})
            return ended

        return await self._d.transaction(tx)


__all__ = [
    "PAUSES",
    "ImportDoc",
    "ImportStore",
    "LeaseLost",
    "body",
    "describe",
    "pace",
    "parse",
]

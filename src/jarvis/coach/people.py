# src/jarvis/coach/people.py
"""R8 I0 seam S27 (docs/plans/r8-vision.md v8.0.3 D6, the owner's final words: "Keep everything
and save the results"): who a kept result is for.

    who = "me"                the owner
        | "fp_<12 hex>"       a person enrolled with consent in R3's Faces (never a name here)
        | "gst_<12 hex>"      a guest: someone JARVIS didn't know, "Guest N" of one session

A look's unknown body (`who` "" in the engine's Result) becomes a guest the first time its tally is
kept: one guest per (session, track), labelled "Guest 1", "Guest 2" ... in that session's order. He
can rename a guest (his words, letters only) or merge it into himself, an enrolled person or
another guest; a merged guest's results then count as the other's, and the registry remembers
where it went so a later kept tally follows it. The registry is one document per owner,
`{prefix}coach_people/{uid}`, sealed under the keyring's `coach` purpose (AAD
"coach_people/{uid}/v1"), at most `GUESTS_MAX` guests. No keyring: `CoachOff` (never in clear).
"""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from jarvis.integrations.vault import VaultError
from jarvis.keyring import KEY_ID, Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Doc, Docs, DocTx
from jarvis.storage.sessions import safe_id

log = get_logger(__name__)

COLLECTION = "coach_people"
PURPOSE = "coach"
ME = "me"
PERSON = re.compile(r"^fp_[0-9a-f]{12}$")
GUEST = re.compile(r"^gst_[0-9a-f]{12}$")
SESSION = re.compile(r"^cs_[0-9a-f]{12}$")
LABEL = re.compile(r"^[A-Za-z][A-Za-z .'-]{0,39}$")
GUESTS_MAX = 500
TRACK_MAX = 63


class CoachOff(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Coach results are off, Sir: JARVIS has no token key to keep them sealed.")


class PeopleRefused(ValueError):
    """A rename or merge that can't be done, in plain words."""


def is_who(value: object) -> bool:
    """A kept result's owner: me, an enrolled fp_ id or a guest id."""
    return isinstance(value, str) and (
        value == ME or bool(PERSON.match(value)) or bool(GUEST.match(value))
    )


def new_session() -> str:
    return "cs_" + secrets.token_hex(6)


@dataclass(frozen=True)
class Guest:
    id: str
    label: str
    session: str
    track: int
    made_at: str
    merged_into: str | None = None


def _uid(uid: str) -> str:
    if not isinstance(uid, str) or not safe_id(uid):
        raise ValueError("invalid user id")
    return uid


class PeopleStore:
    def __init__(
        self,
        docs: Docs,
        keyring: Keyring | None,
        *,
        prefix: str = "jarvis_",
        now: Callable[[], datetime],
    ) -> None:
        self._docs, self._ring, self._prefix, self._now = docs, keyring, prefix, now

    def _path(self, uid: str) -> str:
        return f"{self._prefix}{COLLECTION}/{_uid(uid)}"

    def _cipher(self) -> Keyring:
        if self._ring is None:
            raise CoachOff()
        return self._ring

    def _open(self, uid: str, doc: Doc | None) -> list[Guest]:
        if not doc:
            return []
        try:
            raw = (
                self._cipher()
                .cipher(PURPOSE)
                .decrypt(str(doc["blob"]), aad=f"{COLLECTION}/{uid}/v1")
            )
            return [Guest(**g) for g in json.loads(raw)["guests"]]
        except (KeyError, TypeError, ValueError, VaultError) as exc:
            log.error("the coach's people did not open", extra={"error": type(exc).__name__})
            raise CoachOff() from None

    def _doc(self, uid: str, guests: list[Guest]) -> Doc:
        plain = json.dumps({"guests": [g.__dict__ for g in guests]}, separators=(",", ":"))
        blob = self._cipher().cipher(PURPOSE).encrypt(plain.encode(), aad=f"{COLLECTION}/{uid}/v1")
        return {"uid": uid, "v": 1, "kid": KEY_ID, "n": len(guests), "blob": blob,
                "updated_at": self._now().isoformat()}  # fmt: skip

    async def guests(self, uid: str) -> list[Guest]:
        return self._open(uid, await self._docs.get(self._path(uid)))

    async def guest_for(self, uid: str, session: str, track: int) -> str:
        """The guest id of one unknown body of one session ("Guest N"), made on first use."""
        if not SESSION.match(str(session)) or not 0 <= int(track) <= TRACK_MAX:
            raise PeopleRefused("That session isn't one JARVIS knows.")
        path = self._path(uid)

        async def work(tx: DocTx) -> str:
            found = self._open(uid, await tx.get(path))
            for g in found:
                if g.session == session and g.track == track:
                    return g.id
            if len(found) >= GUESTS_MAX:
                raise PeopleRefused("You have too many guests, Sir. Merge or delete some first.")
            n = 1 + sum(1 for g in found if g.session == session)
            guest = Guest("gst_" + secrets.token_hex(6), f"Guest {n}", session, int(track),
                          self._now().isoformat())  # fmt: skip
            tx.set(path, self._doc(uid, [*found, guest]))
            return guest.id

        return await self._docs.transaction(work)

    async def resolve(self, uid: str, who: str) -> str:
        """Where a guest's results now count (it may have been merged, perhaps twice)."""
        if not GUEST.match(who):
            return who
        by_id = {g.id: g for g in await self.guests(uid)}
        seen: set[str] = set()
        while GUEST.match(who) and who in by_id and by_id[who].merged_into and who not in seen:
            seen.add(who)
            who = str(by_id[who].merged_into)
        return who

    async def rename(self, uid: str, guest: str, label: str) -> Guest:
        text = " ".join(str(label).split())
        if not LABEL.match(text):
            raise PeopleRefused("A guest's name is 1 to 40 letters, Sir.")
        return await self._change(uid, guest, lambda g: replace(g, label=text))

    async def merge(self, uid: str, guest: str, into: str) -> Guest:
        if not is_who(into) or into == guest:
            raise PeopleRefused(
                "Merge a guest into yourself, someone you enrolled, or another guest."
            )
        return await self._change(uid, guest, lambda g: replace(g, merged_into=into))

    async def _change(self, uid: str, guest: str, change: Callable[[Guest], Guest]) -> Guest:
        path = self._path(uid)

        async def work(tx: DocTx) -> Guest:
            found = self._open(uid, await tx.get(path))
            hit = next((g for g in found if g.id == guest), None)
            if hit is None:
                raise PeopleRefused("That guest isn't one JARVIS knows.")
            new = change(hit)
            tx.set(path, self._doc(uid, [new if g.id == guest else g for g in found]))
            return new

        return await self._docs.transaction(work)

    async def forget(self, uid: str, guest: str) -> bool:
        """The guest's entry (its results are deleted by the results store)."""
        path = self._path(uid)

        async def work(tx: DocTx) -> bool:
            found = self._open(uid, await tx.get(path))
            left = [g for g in found if g.id != guest]
            if len(left) == len(found):
                return False
            tx.set(path, self._doc(uid, left))
            return True

        return await self._docs.transaction(work)

    async def export(self, uid: str) -> dict[str, Any]:
        return {"guests": [g.__dict__ for g in await self.guests(uid)]}


__all__ = [
    "COLLECTION",
    "GUEST",
    "GUESTS_MAX",
    "ME",
    "PERSON",
    "SESSION",
    "CoachOff",
    "Guest",
    "PeopleRefused",
    "PeopleStore",
    "is_who",
    "new_session",
]

# src/jarvis/coach/store.py
"""R8 I0 seam S7 (docs/plans/r8-vision.md v8.0.3 section 4.4, ADR-51): the kept coach results
and his reference routines, sealed under the keyring's `coach` purpose.

    {prefix}coach_results/{uid}_{yyyymmdd}  uid, day, v, kid, n, updated_at, and blob =
                                            AES-GCM(JSON {day, items}), AAD "coach_results/{uid}/v1"
    {prefix}coach_routines/{uid}_{rid}      uid, rid, v, kid, updated_at, blob = AES-GCM(JSON
                                            {kind, angles}), AAD "coach_routines/{uid}/{rid}/v1"

An item is `{id: "ct_<12 hex>", kept_at, use, who, session, tally}`: `tally` fits its use case's
model (`jarvis.coach.usecases.parse_tally`, written as the model writes it) and `who` is "me",
an enrolled fp_ id or a guest id (`jarvis.coach.people`: the owner's D6, everyone's results are
saved). Anything else is `Dropped` and nothing is written. The same rules as
`jarvis.vision.store`: at most `PER_DAY_MAX` items a day, a day's blob under Firestore's 1 MiB,
the day inside the blob must match the document's, no keyring -> `CoachOff` (never in clear), a
day that won't open never blocks, hides or deletes the others, the daily sweep deletes days past
`keep_days` (the setting `coach_keep_days`, 90). A blood-pressure reading is kept the same way
under the use case `bp-reading`, only once he confirmed it (`jarvis.coach.bp.BpReading`).

A routine is his own reference (`dance`, `tai-chi`) or his posture calibration (`posture`):
joint angles only (degrees, at most `ANGLES_MAX` rows of `JOINTS_MAX` angles), never a point or
a picture. Logs carry class names and counts only.
"""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from jarvis.coach.bp import BpReading
from jarvis.coach.people import CoachOff, is_who
from jarvis.coach.usecases import parse_tally
from jarvis.integrations.vault import VaultError
from jarvis.keyring import KEY_ID, Keyring
from jarvis.logging import get_logger
from jarvis.notify.quiet import local
from jarvis.storage.docs import Delete, Doc, Docs, DocTx, Query
from jarvis.storage.sessions import safe_id

log = get_logger(__name__)

COLLECTION = "coach_results"
ROUTINES = "coach_routines"
PURPOSE = "coach"
VERSION = 1
PER_DAY_MAX = 200
KEEP_DAYS = 90
KEEP_DAYS_RANGE = (7, 365)
BP_USE = "bp-reading"
RESULT_ID = re.compile(r"^ct_[0-9a-f]{12}$")
ROUTINE_ID = re.compile(r"^(?:posture|dance-[1-9]|dance-1[0-9]|dance-20|tai-chi-[1-9])$")
SESSION = re.compile(r"^cs_[0-9a-f]{12}$")
ITEM_MAX = 20_000
BLOB_MAX = 900_000
ANGLES_MAX = 3_000  # rows (a 5-minute routine at 10 a second)
JOINTS_MAX = 16


class CoachUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Your coach results couldn't be read just now, Sir.")


class Dropped(ValueError):
    def __init__(self) -> None:
        super().__init__("That result doesn't fit its coach, so it was dropped.")


class DayFull(ValueError):
    def __init__(self) -> None:
        super().__init__("That day's coach results are full, Sir. Delete some first.")


Angle = Annotated[float, Field(ge=0.0, le=360.0)]


class Routine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["posture", "dance", "tai-chi"]
    angles: tuple[tuple[Angle, ...], ...] = Field(min_length=1, max_length=ANGLES_MAX)

    @model_validator(mode="after")
    def _rows(self) -> Routine:
        if any(not 1 <= len(row) <= JOINTS_MAX for row in self.angles):
            raise ValueError("a row holds 1 to 16 joint angles")
        return self


def _uid(uid: str) -> str:
    if not isinstance(uid, str) or not safe_id(uid):
        raise ValueError("invalid user id")
    return uid


def item_of(use: str, who: str, session: str, raw: object, kept_at: str) -> dict[str, Any]:
    """The stored form, or `Dropped`: the tally re-written by its model."""
    if not is_who(who) or not SESSION.match(str(session)):
        raise Dropped()
    if use == BP_USE:
        try:
            tally: dict[str, Any] = BpReading.model_validate(raw).model_dump(mode="json")
        except ValidationError:
            raise Dropped() from None
    else:
        found = parse_tally(use, raw)
        if found is None:
            raise Dropped()
        tally = found.model_dump(mode="json")
    item = {"id": "ct_" + secrets.token_hex(6), "kept_at": kept_at, "use": use, "who": who,
            "session": session, "tally": tally}  # fmt: skip
    if len(json.dumps(item, separators=(",", ":"))) > ITEM_MAX:
        raise Dropped()
    return item


class CoachStore:
    def __init__(
        self,
        docs: Docs,
        keyring: Keyring | None,
        *,
        prefix: str = "jarvis_",
        now: Callable[[], datetime],
        tz: str = "Asia/Kolkata",
        keep_days: int = KEEP_DAYS,
    ) -> None:
        self._docs, self._ring, self._prefix, self._now, self._tz = docs, keyring, prefix, now, tz
        self.keep_days = min(KEEP_DAYS_RANGE[1], max(KEEP_DAYS_RANGE[0], int(keep_days)))

    @property
    def sealed(self) -> bool:
        return self._ring is not None

    def _today(self) -> date:
        return local(self._now(), self._tz).date()

    def _first_kept_day(self) -> str:
        return (self._today() - timedelta(days=self.keep_days - 1)).isoformat()

    def _path(self, uid: str, day: str) -> str:
        return f"{self._prefix}{COLLECTION}/{_uid(uid)}_{day.replace('-', '')}"

    def _cipher(self) -> Keyring:
        if self._ring is None:
            raise CoachOff()
        return self._ring

    def _seal(self, uid: str, day: str, items: list[dict[str, Any]]) -> str:
        plain = json.dumps({"day": day, "items": items}, separators=(",", ":"))
        return self._cipher().cipher(PURPOSE).encrypt(plain.encode(), aad=f"{COLLECTION}/{uid}/v1")

    def _open(self, uid: str, doc: Doc) -> list[dict[str, Any]]:
        try:
            raw = (
                self._cipher()
                .cipher(PURPOSE)
                .decrypt(str(doc["blob"]), aad=f"{COLLECTION}/{uid}/v1")
            )
            data = json.loads(raw)
            items = data["items"] if isinstance(data, dict) else None
            if data.get("day") != doc.get("day") or not isinstance(items, list):
                raise ValueError("a coach day that moved or is not a list")
        except (KeyError, TypeError, ValueError, AttributeError, VaultError) as exc:
            log.error("a kept coach day did not open", extra={"error": type(exc).__name__})
            raise CoachUnavailable() from None
        return [i for i in items if isinstance(i, dict)]

    def _doc(self, uid: str, day: str, items: list[dict[str, Any]]) -> Doc:
        return {
            "uid": uid,
            "day": day,
            "v": VERSION,
            "kid": KEY_ID,
            "n": len(items),
            "blob": self._seal(uid, day, items),
            "updated_at": self._now().isoformat(),
        }

    async def _rows(self, uid: str) -> list[tuple[str, Doc]]:
        try:
            return await self._docs.query(
                Query(f"{self._prefix}{COLLECTION}", where=("uid", _uid(uid)))
            )
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001 - the store: plain words, the class in the log
            log.warning("kept coach days unreadable", extra={"error": type(exc).__name__})
            raise CoachUnavailable() from None

    async def keep(self, uid: str, use: str, who: str, session: str, raw: object) -> dict[str, Any]:
        """Keep one tally (or a confirmed reading); `Dropped` when it doesn't fit."""
        _uid(uid)
        self._cipher()
        item = item_of(use, who, session, raw, self._now().isoformat())
        day = self._today().isoformat()
        path = self._path(uid, day)

        async def work(tx: DocTx) -> dict[str, Any]:
            old = await tx.get(path)
            items = self._open(uid, old) if old else []
            if len(items) >= PER_DAY_MAX:
                raise DayFull()
            doc = self._doc(uid, day, [*items, item])
            if len(str(doc["blob"])) > BLOB_MAX:
                raise DayFull()
            tx.set(path, doc)
            return item

        return await self._docs.transaction(work)

    async def list(
        self, uid: str, *, days: int = 7, who: str | None = None
    ) -> list[dict[str, Any]]:
        """Newest first; a day that doesn't open is left out (and logged), never the others."""
        self._cipher()
        first = (
            self._today() - timedelta(days=max(1, min(int(days), self.keep_days)) - 1)
        ).isoformat()
        found: list[dict[str, Any]] = []
        unreadable = 0
        for _, doc in await self._rows(uid):
            if str(doc.get("day", "")) < first:
                continue
            try:
                found.extend(i for i in self._open(uid, doc) if who in (None, i.get("who")))
            except CoachUnavailable:
                unreadable += 1
        if unreadable and not found:
            raise CoachUnavailable()
        return sorted(found, key=lambda i: str(i.get("kept_at", "")), reverse=True)

    async def count(self, uid: str, *, who: Callable[[str], bool] | None = None) -> int:
        if not self.sealed:
            return 0
        items = await self.list(uid, days=self.keep_days)
        return sum(1 for i in items if who is None or who(str(i.get("who", ""))))

    async def delete(self, uid: str, rid: str) -> bool:
        if not isinstance(rid, str) or not RESULT_ID.match(rid):
            return False
        return await self._drop(uid, lambda i: i.get("id") == rid) > 0

    async def delete_who(self, uid: str, who: Callable[[str], bool]) -> int:
        """Every kept result of the people `who` picks (one person, a guest, every guest)."""
        return await self._drop(uid, lambda i: who(str(i.get("who", ""))))

    async def _drop(self, uid: str, gone: Callable[[dict[str, Any]], bool]) -> int:
        dropped = 0
        for _, doc in await self._rows(uid):
            day = str(doc.get("day", ""))
            try:
                if not any(gone(i) for i in self._open(uid, doc)):
                    continue
            except CoachUnavailable:
                continue  # that day stays as it is
            path = self._path(uid, day)

            async def work(tx: DocTx, path: str = path, day: str = day) -> int:
                old = await tx.get(path)
                items = self._open(uid, old) if old else []
                left = [i for i in items if not gone(i)]
                if left:
                    tx.set(path, self._doc(uid, day, left))
                else:
                    tx.delete(path)
                return len(items) - len(left)

            dropped += await self._docs.transaction(work)
        return dropped

    async def delete_all(self, uid: str) -> int:
        rows = await self._rows(uid)
        if rows:
            await self._docs.write([Delete(f"{self._prefix}{COLLECTION}/{i}") for i, _ in rows])
        return sum(int(d.get("n", 0)) for _, d in rows)

    async def sweep(self, uid: str) -> int:
        first = self._first_kept_day()
        old = [i for i, d in await self._rows(uid) if str(d.get("day", "")) < first]
        if old:
            await self._docs.write([Delete(f"{self._prefix}{COLLECTION}/{i}") for i in old])
        return len(old)

    async def export(self, uid: str, *, who: str | None = None) -> dict[str, Any]:
        if not self.sealed:
            return {"results": []}
        return {"results": await self.list(uid, days=self.keep_days, who=who)}


class RoutineStore:
    def __init__(self, docs: Docs, keyring: Keyring | None, *, prefix: str = "jarvis_",
                 now: Callable[[], datetime]) -> None:  # fmt: skip
        self._docs, self._ring, self._prefix, self._now = docs, keyring, prefix, now

    def _path(self, uid: str, rid: str) -> str:
        if not ROUTINE_ID.match(str(rid)):
            raise ValueError("not a routine id")
        return f"{self._prefix}{ROUTINES}/{_uid(uid)}_{rid}"

    def _cipher(self) -> Keyring:
        if self._ring is None:
            raise CoachOff()
        return self._ring

    async def put(self, uid: str, rid: str, raw: object) -> Routine:
        routine = Routine.model_validate(raw)
        aad = f"{ROUTINES}/{uid}/{rid}/v1"
        blob = self._cipher().cipher(PURPOSE).encrypt(routine.model_dump_json().encode(), aad=aad)
        doc = {
            "uid": uid,
            "rid": rid,
            "v": VERSION,
            "kid": KEY_ID,
            "blob": blob,
            "updated_at": self._now().isoformat(),
        }
        path = self._path(uid, rid)
        await self._docs.transaction(lambda tx: _set(tx, path, doc))
        return routine

    async def get(self, uid: str, rid: str) -> Routine | None:
        doc = await self._docs.get(self._path(uid, rid))
        if not doc:
            return None
        try:
            raw = (
                self._cipher()
                .cipher(PURPOSE)
                .decrypt(str(doc["blob"]), aad=f"{ROUTINES}/{uid}/{rid}/v1")
            )
            return Routine.model_validate_json(raw)
        except (KeyError, ValueError, VaultError) as exc:
            log.error("a coach routine did not open", extra={"error": type(exc).__name__})
            raise CoachUnavailable() from None

    async def delete(self, uid: str, rid: str) -> bool:
        path = self._path(uid, rid)
        if not await self._docs.get(path):
            return False
        await self._docs.write([Delete(path)])
        return True


async def _set(tx: DocTx, path: str, doc: Doc) -> None:
    tx.set(path, doc)


__all__ = [
    "BP_USE",
    "COLLECTION",
    "KEEP_DAYS",
    "PER_DAY_MAX",
    "PURPOSE",
    "RESULT_ID",
    "ROUTINES",
    "CoachStore",
    "CoachUnavailable",
    "DayFull",
    "Dropped",
    "Routine",
    "RoutineStore",
    "item_of",
]

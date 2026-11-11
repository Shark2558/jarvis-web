# src/jarvis/helpers/nudges/store.py
"""Part C's documents (docs/plans/r11-free-helpers.md data model; BRIEF-COMMON section 4).

- `nudges/{uid}`: his `NudgeSettings` (plain: on/off, windows, words, the free-time list).
- `nudges/{uid}_told`: the claims, `{day: [key, ...]}` for the last `KEEP_TOLD_DAYS` days. A key
  names a nudge and its due minute (or a planned activity's fingerprint), never words. A job
  claims in a transaction BEFORE it sends, and releases the claim when no channel took the message
  (`SendResult.retry`), so a restart or a second run never sends twice and a failed send is
  retried by the next run.
- `wellbeing/{uid}_{date}`: water glasses, stand-ups and activity check-ins, sealed with the keyring
  purpose `wellbeing` (AAD `wellbeing/{uid}/v1`; the day is inside the seal too and checked on
  read). Kept `KEEP_WELL_DAYS` days. No keyring: `WellbeingOff`, nothing is stored.
Errors carry plain words; logs carry class names only (never a count or a word he typed).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jarvis.helpers.nudges.models import NudgeSettings
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, DocTx, Query

log = get_logger(__name__)

KEEP_TOLD_DAYS = 3
KEEP_WELL_DAYS = 30
MAX_KEYS_A_DAY = 200
MAX_WATER = 40
MAX_STOOD = 60
MAX_CHECKINS = 20
PURPOSE = "wellbeing"
Outcome = Literal["asked", "done", "missed", "moved"]


class NudgesUnavailable(RuntimeError):
    """His nudge settings couldn't be read or saved (plain words)."""


class WellbeingOff(RuntimeError):
    """The water and activity log needs the keyring (JARVIS's token key)."""


OFF_WORDS = (
    "The water, stand-up and activity log is off: it needs JARVIS's token key, so nothing is kept."
)


class NudgeStore:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._docs = docs
        self._prefix = prefix

    def _path(self, uid: str) -> str:
        return f"{self._prefix}nudges/{uid}"

    def _told_path(self, uid: str) -> str:
        return f"{self._prefix}nudges/{uid}_told"

    async def settings(self, uid: str) -> NudgeSettings:
        try:
            raw = await self._docs.get(self._path(uid))
            return NudgeSettings.model_validate(raw.get("settings", {})) if raw else NudgeSettings()
        except Exception as exc:  # noqa: BLE001 - the clock skips him; the tab says so
            log.warning("nudge settings unreadable", extra={"error": type(exc).__name__})
            raise NudgesUnavailable("Your nudge settings couldn't be read just now.") from exc

    async def change(self, uid: str, fn: Callable[[NudgeSettings], NudgeSettings]) -> NudgeSettings:
        path = self._path(uid)

        async def run(tx: DocTx) -> NudgeSettings:
            raw = await tx.get(path)
            now = NudgeSettings.model_validate(raw.get("settings", {})) if raw else NudgeSettings()
            new = fn(now).model_copy(update={"rev": now.rev + 1})
            tx.set(path, {"uid": uid, "settings": new.model_dump(mode="json")})
            return new

        return await self._docs.transaction(run)

    async def claim(self, uid: str, day: str, key: str) -> bool:
        """True when this run may send `key` (nobody claimed it today); made in a transaction."""
        path = self._told_path(uid)

        async def run(tx: DocTx) -> bool:
            told = _told(await tx.get(path))
            keys = told.get(day, [])
            if key in keys or len(keys) >= MAX_KEYS_A_DAY:
                return False
            kept = {d: told[d] for d in sorted({*told, day})[-KEEP_TOLD_DAYS:] if d != day}
            tx.set(path, {"uid": uid, "told": {**kept, day: [*keys, key]}})
            return True

        return await self._docs.transaction(run)

    async def release(self, uid: str, day: str, key: str) -> None:
        path = self._told_path(uid)

        async def run(tx: DocTx) -> None:
            told = _told(await tx.get(path))
            if key in told.get(day, []):
                left = [k for k in told[day] if k != key]
                tx.set(path, {"uid": uid, "told": {**told, day: left}})

        await self._docs.transaction(run)

    async def told(self, uid: str) -> dict[str, list[str]]:
        return _told(await self._docs.get(self._told_path(uid)))

    async def delete_all(self, uid: str) -> int:
        paths = [p for p in (self._path(uid), self._told_path(uid)) if await self._docs.get(p)]
        if paths:
            await self._docs.write([Delete(p) for p in paths])
        return len(paths)


def _told(raw: dict[str, object] | None) -> dict[str, list[str]]:
    got = raw.get("told") if raw else None
    if not isinstance(got, dict):
        return {}
    return {str(d): [str(k) for k in v] for d, v in got.items() if isinstance(v, list)}


# ---- the sealed log ------------------------------------------------------------------------------
class Checkin(BaseModel):
    """One planned activity's check-in: his word, what happened, its planned start (HH:MM)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    w: str = Field(min_length=2, max_length=30)
    o: Outcome
    at: str = Field(default="", max_length=5)

    def did(self, outcome: Outcome) -> Checkin:
        return self.model_copy(update={"o": outcome})


class WellDay(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    day: str = ""
    water: int = Field(default=0, ge=0, le=MAX_WATER)
    stood: int = Field(default=0, ge=0, le=MAX_STOOD)
    checkins: dict[str, Checkin] = Field(default_factory=dict, max_length=MAX_CHECKINS)

    def plus_water(self, glasses: int) -> WellDay:
        if not 1 <= glasses <= 10 or self.water + glasses > MAX_WATER:
            raise ValueError(f"Log 1 to 10 glasses at a time, at most {MAX_WATER} a day.")
        return self.model_copy(update={"water": self.water + glasses})

    def plus_stood(self, times: int = 1) -> WellDay:
        if not 1 <= times <= 10 or self.stood + times > MAX_STOOD:
            raise ValueError(f"Log 1 to 10 stand-ups at a time, at most {MAX_STOOD} a day.")
        return self.model_copy(update={"stood": self.stood + times})

    def with_checkin(self, key: str, checkin: Checkin) -> WellDay:
        if key not in self.checkins and len(self.checkins) >= MAX_CHECKINS:
            raise ValueError("That's the most check-ins a day can hold.")
        return self.model_copy(update={"checkins": {**self.checkins, key: checkin}})


class WellbeingStore:
    def __init__(self, docs: Docs, keyring: Keyring | None, *, prefix: str = "jarvis_") -> None:
        self._docs = docs
        self._ring = keyring
        self._prefix = prefix

    @property
    def on(self) -> bool:
        return self._ring is not None

    def _path(self, uid: str, day: str) -> str:
        return f"{self._prefix}wellbeing/{uid}_{day}"

    @staticmethod
    def _aad(uid: str) -> str:
        return f"wellbeing/{uid}/v1"

    def _seal(self, uid: str, day: WellDay) -> str:
        assert self._ring is not None
        plain = json.dumps(day.model_dump(mode="json"), separators=(",", ":")).encode()
        return self._ring.cipher(PURPOSE).encrypt(plain, aad=self._aad(uid))

    def _open(self, uid: str, day: str, raw: dict[str, object] | None) -> WellDay:
        if not raw or self._ring is None or not isinstance(raw.get("blob"), str):
            return WellDay(day=day)
        try:
            plain = self._ring.cipher(PURPOSE).decrypt(str(raw["blob"]), aad=self._aad(uid))
            got = WellDay.model_validate(json.loads(plain))
        except Exception as exc:  # noqa: BLE001 - unreadable (another owner's, a bad key): empty
            log.warning("a wellbeing day is unreadable", extra={"error": type(exc).__name__})
            return WellDay(day=day)
        return got if got.day == day else WellDay(day=day)

    async def day(self, uid: str, day: str) -> WellDay:
        if self._ring is None:
            raise WellbeingOff(OFF_WORDS)
        return self._open(uid, day, await self._docs.get(self._path(uid, day)))

    async def change(self, uid: str, day: str, fn: Callable[[WellDay], WellDay]) -> WellDay:
        if self._ring is None:
            raise WellbeingOff(OFF_WORDS)
        path = self._path(uid, day)

        async def run(tx: DocTx) -> WellDay:
            new = fn(self._open(uid, day, await tx.get(path)))
            tx.set(path, {"uid": uid, "day": day, "blob": self._seal(uid, new)})
            return new

        return await self._docs.transaction(run)

    async def _rows(self, uid: str) -> list[tuple[str, dict[str, object]]]:
        rows = await self._docs.query(Query(f"{self._prefix}wellbeing", where=("uid", uid)))
        return sorted((str(d.get("day", "")), d) for _, d in rows)

    async def days(self, uid: str) -> list[tuple[str, WellDay]]:
        return [(day, self._open(uid, day, raw)) for day, raw in await self._rows(uid)]

    async def sweep(self, uid: str, today: str) -> int:
        cutoff = (date.fromisoformat(today) - timedelta(days=KEEP_WELL_DAYS)).isoformat()
        gone = [self._path(uid, day) for day, _ in await self._rows(uid) if day < cutoff]
        if gone:
            await self._docs.write([Delete(p) for p in gone])
        return len(gone)

    async def delete_all(self, uid: str) -> int:
        gone = [self._path(uid, day) for day, _ in await self._rows(uid)]
        if gone:
            await self._docs.write([Delete(p) for p in gone])
        return len(gone)


__all__ = [
    "KEEP_TOLD_DAYS",
    "KEEP_WELL_DAYS",
    "OFF_WORDS",
    "Checkin",
    "NudgeStore",
    "NudgesUnavailable",
    "Outcome",
    "WellDay",
    "WellbeingOff",
    "WellbeingStore",
]

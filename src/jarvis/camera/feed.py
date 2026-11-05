# src/jarvis/camera/feed.py
"""The home feed: the last 7 days of what the cameras reported and what was done (R3 D8, D10, D13).

    {prefix}home_feed/{uid}_{YYYYMMDD}   {uid, day, blob}
        blob = AES-GCM(JSON [FeedItem...]) under the `home_feed` key, AAD `home/feed/{uid}/{day}/v1`

A line holds ids and times only: the person is an `fp_` id and the score, never a name. Names are
looked up when the feed is VIEWED, through the face directory, so a deleted or low-score person is
"someone JARVIS didn't recognise" in every old line too. Camera labels are the owner's own words.
Days are local days (`Settings.user_timezone`) and expire after 7 days (`FeedSweepJob`).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from jarvis.camera.config import CameraConfigService
from jarvis.camera.models import FEED_KEEP_DAYS, MAX_FEED_PER_DAY, FeedItem, first_upper, spaced
from jarvis.camera.ports import CameraUnavailable, safe_resolve
from jarvis.faces.ports import UNKNOWN_PERSON as UNKNOWN_WORDS
from jarvis.faces.ports import FaceDirectory, Resolved
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, DocTx, Query
from jarvis.undo.store import owner_ok

log = get_logger(__name__)

UNAVAILABLE = "JARVIS couldn't open your home feed just now. Try again in a minute."


def _day_id(d: date) -> str:
    return d.strftime("%Y%m%d")


def camera_words(label: str | None, cam: str) -> str:
    return label or spaced(cam)


def describe(item: FeedItem, name: str | None, camera: str) -> str:
    """One feed line in plain words, from fixed templates and the owner's own labels."""
    who = name or UNKNOWN_WORDS
    if item.kind == "greeting":
        return f"{name or 'A person JARVIS recognised'} arrived at {camera}"
    if item.kind == "package":
        return f"A package was left at {camera}" + (" (a delivery)" if item.delivered else "")
    if item.kind == "intruder":
        first = f"{who} at {camera} while the alarm was on"
        return first_upper(first)
    return f"A {item.label or 'thing'} at {camera}"


class Feed:
    def __init__(
        self,
        docs: Docs,
        keyring: Keyring,
        *,
        faces: FaceDirectory,
        config: CameraConfigService,
        tz: str,
        clock: Callable[[], float] = time.time,
        prefix: str = "jarvis_",
        keep_days: int = FEED_KEEP_DAYS,
    ) -> None:
        self._d = docs
        self._ring = keyring
        self._faces = faces
        self._config = config
        self._tz = ZoneInfo(tz)
        self._clock = clock
        self._coll = f"{prefix}home_feed"
        self._keep = keep_days

    # ---- storage -----------------------------------------------------------------------------

    def _path(self, uid: str, day: str) -> str:
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        return f"{self._coll}/{uid}_{day}"

    def _aad(self, uid: str, day: str) -> str:
        return f"home/feed/{uid}/{day}/v1"

    def _open(self, uid: str, day: str, doc: dict[str, Any] | None) -> list[FeedItem]:
        if doc is None:
            return []
        blob = doc.get("blob")
        if not isinstance(blob, str):
            raise ValueError("envelope")
        raw = json.loads(self._ring.cipher("home_feed").decrypt(blob, aad=self._aad(uid, day)))
        if not isinstance(raw, list):
            raise ValueError("items")
        return [FeedItem.model_validate(x) for x in raw]

    def _seal(self, uid: str, day: str, items: Sequence[FeedItem]) -> dict[str, Any]:
        plain = json.dumps([i.model_dump(mode="json") for i in items]).encode()
        blob = self._ring.cipher("home_feed").encrypt(plain, aad=self._aad(uid, day))
        return {"uid": uid, "day": day, "blob": blob}

    def local_day(self, epoch: float) -> date:
        return datetime.fromtimestamp(epoch, UTC).astimezone(self._tz).date()

    async def day_items(self, uid: str, day: date) -> list[FeedItem]:
        key = _day_id(day)
        try:
            return self._open(uid, key, await self._d.get(self._path(uid, key)))
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("home feed unreadable", extra={"reason": type(exc).__name__})
            raise CameraUnavailable(UNAVAILABLE) from None

    async def add(self, uid: str, item: FeedItem) -> None:
        key = _day_id(self.local_day(item.at))
        path = self._path(uid, key)

        async def tx(t: DocTx) -> None:
            try:
                cur = self._open(uid, key, await t.get(path))
            except Exception as exc:  # noqa: BLE001
                log.warning("home feed corrupt; refusing", extra={"reason": type(exc).__name__})
                raise CameraUnavailable(UNAVAILABLE) from None
            items = [*cur, item][-MAX_FEED_PER_DAY:]
            t.set(path, self._seal(uid, key, items))

        try:
            await self._d.transaction(tx)
        except (CameraUnavailable, ValueError):
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("home feed not saved", extra={"reason": type(exc).__name__})
            raise CameraUnavailable(UNAVAILABLE) from None

    async def since(self, uid: str, start: float) -> list[FeedItem]:
        """Lines from `start` (epoch) until now, oldest first."""
        first, last = self.local_day(start), self.local_day(self._clock())
        out: list[FeedItem] = []
        day = first
        while day <= last:
            out.extend(i for i in await self.day_items(uid, day) if i.at >= start)
            day += timedelta(days=1)
        return sorted(out, key=lambda i: i.at)

    # ---- view --------------------------------------------------------------------------------

    async def _name(self, uid: str, item: FeedItem) -> Resolved:
        return await safe_resolve(self._faces, uid, item.person, item.score)

    async def line(self, uid: str, item: FeedItem, cams: dict[str, str]) -> dict[str, Any]:
        """A feed line as the console shows it (names are the owner's own, so shown to him)."""
        who = await self._name(uid, item)
        camera = camera_words(cams.get(item.camera), item.camera)
        shown_who: str | None = who.name or (UNKNOWN_WORDS if item.kind == "intruder" else None)
        at = datetime.fromtimestamp(item.at, UTC).astimezone(self._tz)
        return {
            "at": at.isoformat(timespec="minutes"),
            "words": describe(item, who.name, camera),
            "camera": camera,
            "zone": spaced(item.zone) if item.zone else None,
            "who": shown_who,
            "decision": item.decision,
            "sent": {"telegram": item.telegram, "push": item.push},
        }

    async def view(self, uid: str, day_word: str) -> list[dict[str, Any]]:
        today = self.local_day(self._clock())
        day = today - timedelta(days=1) if day_word == "yesterday" else today
        items = await self.day_items(uid, day)
        settings = await self._config.get(uid)
        cams = {cid: c.label for cid, c in settings.cameras.items()}
        return [await self.line(uid, i, cams) for i in reversed(items)]

    # ---- upkeep ------------------------------------------------------------------------------

    async def sweep(self, uid: str) -> int:
        """Delete the owner's days older than the keep window; returns how many days went."""
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        cutoff = _day_id(self.local_day(self._clock()) - timedelta(days=self._keep))
        rows = await self._d.query(Query(self._coll, where=("uid", uid)))
        old = [doc_id for doc_id, d in rows if str(d.get("day", "")) < cutoff]
        if old:
            await self._d.write([Delete(f"{self._coll}/{i}") for i in old])
        return len(old)

    async def count(self, uid: str) -> int:
        n = 0
        for doc_id, d in await self._d.query(Query(self._coll, where=("uid", uid))):
            n += len(self._open(uid, str(d.get("day", "")), d))
            del doc_id
        return n

    async def wipe(self, uid: str) -> int:
        """Delete every day (the privacy delete); returns how many lines went."""
        rows = await self._d.query(Query(self._coll, where=("uid", uid)))
        total = 0
        for _, d in rows:
            total += len(self._open(uid, str(d.get("day", "")), d))
        await self._d.write([Delete(f"{self._coll}/{i}") for i, _ in rows])
        return total

    async def export(self, uid: str) -> list[dict[str, Any]]:
        """Every line with ids and times; no name (names live in Faces)."""
        rows = await self._d.query(Query(self._coll, where=("uid", uid)))
        out: list[dict[str, Any]] = []
        for _, d in sorted(rows, key=lambda r: str(r[1].get("day", ""))):
            out.extend(i.model_dump(mode="json") for i in self._open(uid, str(d["day"]), d))
        return out


class FeedSweepJob:
    """Watchdog step: drop feed days older than 7 days."""

    name = "home_feed_sweep"
    budget_s = 20.0

    def __init__(self, feed: Feed) -> None:
        self._feed = feed

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        swept = failed = 0
        for uid in owners:
            try:
                swept += await self._feed.sweep(uid)
            except Exception as exc:  # noqa: BLE001
                log.warning("feed sweep failed", extra={"reason": type(exc).__name__})
                failed += 1
        return {"swept": swept, "failed": failed}


__all__ = ["UNAVAILABLE", "Feed", "FeedSweepJob", "camera_words", "describe"]

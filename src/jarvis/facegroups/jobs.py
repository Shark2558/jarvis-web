# src/jarvis/facegroups/jobs.py
"""R11.1 Part C's two jobs on the helpers' 5-minute clock (plan D14, D15; `ticks.TickJob`).

- `photos_import`: one step of each owner's running Google Photos import (at most
  `photos_import_batch` photos), inside what the clock has left. No import running: one document
  read and nothing else. The laptop known to be offline: nothing is downloaded, the import says
  "paused: laptop not reachable" and waits. A step that Google or the laptop stops is a pause,
  never a failure of the clock; only something unexpected counts under `failed`.
- `face_groups_poll`: retry the names and forgets that wait for the laptop, refresh the copy of
  its unnamed groups and say once when new ones are worth naming.
Both are idempotent: progress is saved after every photo and the laptop counts a picture once.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from jarvis.facegroups.service import FaceGroupsService
from jarvis.integrations.google import GoogleAPIError, GoogleNotConnected
from jarvis.logging import get_logger
from jarvis.photos.errors import PickerError
from jarvis.photos.picker import PhotosNotGranted
from jarvis.photos.service import NoSession, PhotosService
from jarvis.ticks import FAILED_COUNT, time_left

log = get_logger(__name__)

IMPORT_JOB = "photos_import"
POLL_JOB = "face_groups_poll"
MARGIN_S = 1.5
IDLE = frozenset({"no_session", "done", "expired"})
PAUSED = frozenset({"laptop_offline", "kit_old", "reader_off", "edge_error", "timed_out"})
_STOPPED = (GoogleAPIError, GoogleNotConnected, PhotosNotGranted, PickerError, NoSession)
Probe = Callable[[], Callable[[str], Awaitable[bool]] | None]


class PhotosImportJob:
    name = IMPORT_JOB
    budget_s = 15.0

    def __init__(
        self, photos: Callable[[], PhotosService | None], laptop_online: Probe | None = None
    ) -> None:
        self._photos = photos
        self._online = laptop_online

    async def _away(self, uid: str) -> bool:
        probe = self._online() if self._online is not None else None
        if probe is None:
            return False
        try:
            return not await probe(uid)
        except Exception as exc:  # noqa: BLE001 - unknown: let the step itself find out
            log.warning("laptop probe failed", extra={"error": type(exc).__name__})
            return False

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        out = {"steps": 0, "photos": 0, "paused": 0, FAILED_COUNT: 0}
        photos = self._photos()
        if photos is None:
            return out
        for uid in owners:
            try:
                before = await photos.progress(uid)
                if before.status in IDLE:
                    continue
                if before.status != "waiting" and await self._away(uid) and before.total:
                    out["paused"] += 1
                    continue  # nothing is downloaded for a laptop that is asleep
                left = time_left()
                budget = max(1.0, (left if left is not None else self.budget_s) - MARGIN_S)
                res = await photos.collect(uid, budget_s=budget)
            except _STOPPED as exc:
                log.info("photo import paused", extra={"why": type(exc).__name__})
                out["paused"] += 1
                continue
            except Exception as exc:  # noqa: BLE001 - one owner never stops the others
                log.error("photo import step failed", extra={"error": type(exc).__name__})
                out[FAILED_COUNT] += 1
                continue
            out["steps"] += 1
            out["photos"] += max(0, res.photos - before.photos)
            out["paused"] += 1 if res.status in PAUSED else 0
        return out


class FaceGroupsPollJob:
    name = POLL_JOB
    budget_s = 10.0

    def __init__(self, groups: FaceGroupsService) -> None:
        self._groups = groups

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        out = {"forgotten": 0, "named": 0, "told": 0, "away": 0, FAILED_COUNT: 0}
        for uid in owners:
            try:
                got = await self._groups.poll(uid)
            except Exception as exc:  # noqa: BLE001 - one owner never stops the others
                log.error("face groups poll failed", extra={"error": type(exc).__name__})
                out[FAILED_COUNT] += 1
                continue
            for key, value in got.items():
                out[key] = out.get(key, 0) + value
        return out


__all__ = ["IMPORT_JOB", "POLL_JOB", "FaceGroupsPollJob", "PhotosImportJob"]

# src/jarvis/camera/history.py
"""Camera history search through the bridge, no model (R3 D15).

"Who was at the gate yesterday?" becomes a question to Frigate's event list on the laptop
(`GET /bridge/v1/events`, `GET /bridge/v1/packages`). The reply is parsed strictly (`jarvis.home`
vocabulary only; unknown keys are dropped) and then EVERY word in the result is rebuilt from
cloud-side tables: the owner's camera labels, fixed words for what was seen, and names from the
consent registry through the face directory. Nothing the laptop sends can reach the model as free
text, so an injected string in a Frigate label or zone name has nowhere to go.

Thumbnails are never requested (`include_thumbnails=0`) and bounding boxes are not read. A person
the directory doesn't name is "someone JARVIS didn't recognise" - never "probably X".
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jarvis.camera.config import CameraConfigService
from jarvis.camera.feed import camera_words
from jarvis.camera.models import (
    MAX_LIMIT,
    MAX_SPAN_DAYS,
    WHAT_VALUES,
    HistoryItem,
    HistoryQuery,
    HistoryResult,
    spaced,
)
from jarvis.camera.ports import safe_resolve
from jarvis.faces.ports import FAMILY_CHILD, UNKNOWN_PERSON, FaceDirectory
from jarvis.home.ports import (
    LABEL_ID,
    LABELS,
    PERSON_ID,
    CameraId,
    Epoch,
    EventId,
    HomeCaller,
    HomeRefused,
    Label,
    PersonId,
    Score,
    ZoneId,
)

BRIDGE_FETCH = 100  # how many the cloud asks the laptop for before it filters by who
MAX_BRIDGE_ITEMS = 200
BAD_REPLY = "Your home laptop sent an answer JARVIS didn't understand."
WORDS = {
    "person": "a person",
    "car": "a car",
    "motorcycle": "a motorcycle",
    "bicycle": "a bicycle",
    "dog": "a dog",
    "cat": "a cat",
}


class HistoryRejected(ValueError):
    """The question can't be asked as it stands (plain words, shown to the owner and the model)."""


class _Wire(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class _Event(_Wire):
    id: EventId
    camera: CameraId
    zones: tuple[ZoneId, ...] = Field(default=(), max_length=8)
    label: Label
    start: Epoch
    end: Epoch | None = None
    person: PersonId | None = None
    score: Score | None = None


class _Change(_Wire):
    camera: CameraId
    zone: ZoneId
    state: str = Field(pattern=r"^(package|empty)$")
    at: Epoch
    delivered: bool = False


class _Events(_Wire):
    events: tuple[_Event, ...] = Field(default=(), max_length=MAX_BRIDGE_ITEMS)
    more: bool = False


class _Changes(_Wire):
    changes: tuple[_Change, ...] = Field(default=(), max_length=MAX_BRIDGE_ITEMS)
    more: bool = False


def _parse(model: type[_Events] | type[_Changes], raw: dict[str, Any]) -> Any:
    try:
        return model.model_validate(raw)
    except ValidationError:
        raise HomeRefused("bad_reply", BAD_REPLY) from None


class History:
    def __init__(
        self,
        *,
        caller: HomeCaller,
        config: CameraConfigService,
        faces: FaceDirectory,
        tz: str,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._caller = caller
        self._config = config
        self._faces = faces
        self._tz = ZoneInfo(tz)
        self._clock = clock

    # ---- the question ------------------------------------------------------------------------

    def _window(self, q: HistoryQuery, kept_days: int) -> tuple[float, float] | None:
        def epoch(d: datetime) -> float:
            return (d if d.tzinfo else d.replace(tzinfo=self._tz)).timestamp()

        start, end = epoch(q.start), epoch(q.end)
        if end <= start:
            raise HistoryRejected("The end of the time range has to be after its start.")
        if end - start > MAX_SPAN_DAYS * 86400:
            raise HistoryRejected(f"Ask for at most {MAX_SPAN_DAYS} days at a time.")
        now = self._clock()
        earliest = now - kept_days * 86400
        if end < earliest:
            return None
        return max(start, earliest), min(end, now + 60)

    def _check(self, q: HistoryQuery, cams: dict[str, set[str]]) -> None:
        if q.what not in WHAT_VALUES:
            raise HistoryRejected("What to look for has to be a person, car, package or any.")
        if not 1 <= q.limit <= MAX_LIMIT:
            raise HistoryRejected(f"Ask for between 1 and {MAX_LIMIT} results.")
        if q.camera is not None and q.camera not in cams:
            raise HistoryRejected("JARVIS doesn't know that camera. Name it in the Home panel.")
        if q.zone is not None:
            known = {z for zs in cams.values() for z in zs}
            if not re.fullmatch(LABEL_ID, q.zone) or q.zone not in known:
                raise HistoryRejected("JARVIS doesn't know that zone.")
        if q.who not in (None, "known", "unknown") and not re.fullmatch(PERSON_ID, q.who or ""):
            raise HistoryRejected("Who has to be known, unknown or a person JARVIS recognises.")

    # ---- the answer --------------------------------------------------------------------------

    async def search(
        self, uid: str, q: HistoryQuery, *, hide_children: bool = False
    ) -> HistoryResult:
        """Raises `HistoryRejected` for a bad question and `HomeUnavailable` (offline, refused,
        bad reply) when the laptop can't answer."""
        settings = await self._config.get(uid)
        cams = {
            cid: {*(c.alarm_zones), *([c.package_zone] if c.package_zone else [])}
            for cid, c in settings.cameras.items()
        }
        self._check(q, cams)
        kept = settings.retention_days
        window = self._window(q, kept)
        if window is None:
            return HistoryResult(
                count=0,
                items=(),
                more=False,
                kept_days=kept,
                note=f"That is longer ago than JARVIS keeps ({kept} days).",
            )
        after, before = window
        labels = {c: v.label for c, v in settings.cameras.items()}
        found: list[tuple[float, HistoryItem]] = []
        more = False
        if q.what != "package":
            events = await self._events(uid, q, after, before)
            more = events.more
            for ev in events.events:
                got = await self._event_item(uid, ev, q, labels, hide_children)
                if got is not None:
                    found.append(got)
        if q.what in ("package", "any") and q.who is None:
            changes = await self._changes(uid, q, after, before)
            more = more or changes.more
            found.extend(self._change_items(changes, labels))
        found.sort(key=lambda r: r[0], reverse=True)
        shown = [item for _, item in found[: q.limit]]
        return HistoryResult(
            count=len(shown),
            items=tuple(shown),
            more=more or len(found) > q.limit,
            kept_days=kept,
        )

    async def _events(self, uid: str, q: HistoryQuery, after: float, before: float) -> _Events:
        query = {
            "labels": q.what if q.what in LABELS else ",".join(LABELS),
            "after": str(int(after)),
            "before": str(int(before)),
            "limit": str(BRIDGE_FETCH),
            "include_thumbnails": "0",
        }
        if q.camera:
            query["cameras"] = q.camera
        if q.zone:
            query["zones"] = q.zone
        if q.who and q.who.startswith("fp_"):
            query["person"] = q.who
        raw = await self._caller.call(uid, "GET", "/bridge/v1/events", query=query)
        return _parse(_Events, raw)  # type: ignore[no-any-return]

    async def _changes(self, uid: str, q: HistoryQuery, after: float, before: float) -> _Changes:
        query = {"after": str(int(after)), "before": str(int(before)), "limit": str(BRIDGE_FETCH)}
        if q.camera:
            query["cameras"] = q.camera
        raw = await self._caller.call(uid, "GET", "/bridge/v1/packages", query=query)
        return _parse(_Changes, raw)  # type: ignore[no-any-return]

    def _when(self, epoch: float) -> str:
        at = datetime.fromtimestamp(epoch, UTC).astimezone(self._tz)
        return f"{at:%a} {at.day} {at:%b}, {at:%H:%M}"

    async def _event_item(
        self,
        uid: str,
        ev: _Event,
        q: HistoryQuery,
        labels: dict[str, str],
        hide_children: bool,
    ) -> tuple[float, HistoryItem] | None:
        who: str | None = None
        if ev.label == "person":
            res = await safe_resolve(self._faces, uid, ev.person, ev.score)
            who = FAMILY_CHILD if res.child and hide_children else (res.name or UNKNOWN_PERSON)
            if q.who == "known" and not res.named:
                return None
            if q.who == "unknown" and res.named:
                return None
            if q.who and q.who.startswith("fp_") and res.person != q.who:
                return None
        elif q.who is not None:
            return None
        if q.zone and q.zone not in ev.zones:
            return None
        seconds = None if ev.end is None else max(0, int(ev.end - ev.start))
        item = HistoryItem(
            at=self._when(ev.start),
            camera=camera_words(labels.get(ev.camera), ev.camera),
            zone=spaced(ev.zones[0]) if ev.zones else None,
            what=WORDS[ev.label],
            who=who,
            seconds=seconds,
        )
        return ev.start, item

    def _change_items(
        self, changes: _Changes, labels: dict[str, str]
    ) -> list[tuple[float, HistoryItem]]:
        out = []
        for c in changes.changes:
            what = "a package was left" if c.state == "package" else "the package was taken"
            if c.state == "package" and c.delivered:
                what = "a package was delivered"
            out.append(
                (
                    c.at,
                    HistoryItem(
                        at=self._when(c.at),
                        camera=camera_words(labels.get(c.camera), c.camera),
                        zone=spaced(c.zone),
                        what=what,
                        who=None,
                        seconds=None,
                    ),
                )
            )
        return out


__all__ = ["BAD_REPLY", "History", "HistoryRejected"]

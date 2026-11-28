# src/jarvis/coach/home/runtime.py
"""R8 row 216's home leg (docs/plans/r8-vision.md v8.0.4 section 4.5a; the owner's D3, D4, D6;
ADR-49; builder J): the home camera's coach loop on the home laptop. Ships in the home kit.

    the RTSP sub-stream -> one frame -> pose (and objects) -> tracks -> who -> one body's Result
      -> each switched-on home use case's state for that body -> summary(state) -> a CoachReport
      (views and tallies ONLY) -> the bridge's signed event channel

- **Frames never leave a step.** A frame is decoded, looked at (pose, objects, the face of a body
  not yet named) inside one call on a worker thread and dropped; what comes back is a `Look`:
  points, boxes and labels for the use cases on this laptop, never pixels. Points and boxes go to
  the home use cases (`jarvis.coach.home.REGISTRY`) and nowhere else.
- **One body at a time**, as the console's driver (`console-vision.js live()`): each body has a
  `track` that follows its torso centre from frame to frame; each use case keeps one state per
  body; a pose Result reaches it as `{..., data: {points}, track, who}`, an objects Result reaches
  every body's state. `who` is a consented person's id from R3's face library (`identify`), else
  "me" for a body that was alone in view and is not anyone else (as on his own devices; sticky for
  as long as its track lasts), else "" (a guest: the cloud saves it as "Guest N", D6 final). The
  tracking target (`CoachState.target`) picks the bodies: everyone, "me" or one person.
- **Only views and tallies leave**, and only after three checks: a view is the fixed widget kinds
  with scalar values (`clean_view`), a tally must fit its use case's model (`usecases.
  parse_tally`, dropped never repaired), and neither may hold a geometry key (`GEOMETRY`) or a copy
  of a coordinate of the bodies just seen (`needles`). The `CoachReport` model checks once more.
  A refused report is counted and dropped; nothing about it is logged but its use case's id.
- **Pacing.** A body's view goes up when it changed, at most every `VIEW_EVERY_S`, and at least
  every `VIEW_REFRESH_S`; at most `VIEWS_PER_MIN` views a minute in all (the cloud takes 60 signed
  messages a minute from a home). A tally goes up when a body's session ends (it left, its use
  case was switched off, "cameras off") and, for the all-day desk coaches, every 15 minutes.
- **Rate (D4, plan 4.8).** The highest rate the switched-on use cases ask for (posture 1 a second,
  seated 15, ...), at most 15; a slow laptop slows itself (the gap is at least twice a look's time).
- **Off.** No use case switched on for this camera, or "cameras off" (`all_off`, D11): the stream
  and the models are closed at once (a waiting read returns within one frame). The alarm and
  Frigate are never touched: this loop reads its own copy of the sub-stream.

Optional hooks a home use case may have, besides the I0 protocol (`jarvis.coach.home`):
`rate(state) -> float | None` (posture asks for 2 a second while a slouch is suspected) and
`kept(state) -> state` (called after a 15-minute tally of an all-day coach, to start a new window).
"""

from __future__ import annotations

import asyncio
import logging
import math
import secrets
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from jarvis.coach.home import HOME_USE_CASES, REGISTRY, HomeUseCase
from jarvis.coach.home.engines import (
    BODIES_MAX,
    READY,
    Frame,
    FrameSource,
    ObjectEngine,
    PoseEngine,
    SourceDown,
    quality_of,
)
from jarvis.coach.home.identify import Identifier, NoOne
from jarvis.coach.usecases import BY_ID, VIEW_KINDS, parse_tally
from jarvis.home.ports import (
    MAX_TALLY_KEYS,
    MAX_VIEW,
    CoachReport,
    CoachState,
    HomeVisionPart,
)

log = logging.getLogger(__name__)

LIVE_MAX_FPS = 15.0  # R7 D13's cap, kept (D4)
IDLE_S = 5.0
RETRY_S = 15.0
VIEW_EVERY_S = 2.0
VIEW_REFRESH_S = 30.0
TALLY_EVERY_S = 900.0  # plan 4.4: the all-day desk coaches keep a tally every 15 minutes
ALL_DAY = frozenset({"posture", "activity"})
VIEWS_PER_MIN = 20
TALLIES_PER_MIN = 20
LOST_S = 10.0  # a body not seen (or not picked) this long has left: its session ends
REUSE_S = 60.0  # a track number is not given to another body for this long
WHO_RETRY_S = 5.0  # an unknown body's face is looked at again this often
WHO_RECHECK_S = 60.0  # a named body's, this often
TRACK_MATCH = 0.25  # of the frame: how far a torso centre may move between two looks
TRACK_MAX = 63
ONE = 0  # the state key of a use case that asked for no pose (none of R8's home ones)
WORD_MAX = 120
KEY_MAX = 32
TORSO = (11, 12, 23, 24)
GEOMETRY = frozenset(
    {
        *("x", "y", "z", "w", "h", "width", "height", "left", "top", "right", "bottom"),
        *("point", "points", "landmark", "landmarks", "keypoints", "box", "boxes", "bbox"),
        *("visibility", "frame", "image", "picture", "pixels", "jpeg", "crop", "embedding"),
    }
)
Sink = Callable[[CoachReport], Awaitable[bool]]


def new_session() -> str:
    return "cs_" + secrets.token_hex(6)


# ---- tracks ------------------------------------------------------------------------------------


def _centre(points: Sequence[Mapping[str, float]]) -> tuple[float, float]:
    seen = [points[i] for i in TORSO if points[i]["visibility"] > 0.3] or list(points)
    return (sum(p["x"] for p in seen) / len(seen), sum(p["y"] for p in seen) / len(seen))


class Tracker:
    """A number per body that follows its torso centre from look to look (`track`, 0..63)."""

    def __init__(self, lost_s: float = LOST_S, reuse_s: float = REUSE_S) -> None:
        self._lost = lost_s
        self._reuse = reuse_s
        self._live: dict[int, tuple[float, float, float]] = {}  # track -> (x, y, last seen)
        self._retired: dict[int, float] = {}

    def assign(self, bodies: Sequence[Sequence[Mapping[str, float]]], now: float) -> list[int]:
        for track, (_, _, seen) in list(self._live.items()):
            if now - seen > self._lost:
                del self._live[track]
                self._retired[track] = now
        centres = [_centre(b) for b in bodies]
        pairs = sorted(
            (math.dist(c, (x, y)), i, t)
            for i, c in enumerate(centres)
            for t, (x, y, _) in self._live.items()
        )
        given: dict[int, int] = {}
        for d, i, t in pairs:
            if d <= TRACK_MATCH and i not in given and t not in given.values():
                given[i] = t
        for i in range(len(bodies)):
            if i not in given:
                given[i] = self._free(now, set(given.values()))
        for i, c in enumerate(centres):
            self._live[given[i]] = (c[0], c[1], now)
            self._retired.pop(given[i], None)
        return [given[i] for i in range(len(bodies))]

    def live(self) -> frozenset[int]:
        """The tracks still followed (seen within `lost_s` of the last look)."""
        return frozenset(self._live)

    def _free(self, now: float, taken: set[int]) -> int:
        busy = set(self._live) | taken
        cool = {t for t, at in self._retired.items() if now - at < self._reuse}
        for t in range(TRACK_MAX + 1):
            if t not in busy and t not in cool:
                return t
        spare = [t for t in range(TRACK_MAX + 1) if t not in busy]
        return min(spare, key=lambda t: self._retired.get(t, 0.0))


# ---- what leaves the laptop ---------------------------------------------------------------------


def _scalar(v: object) -> bool:
    if isinstance(v, bool):
        return True
    if isinstance(v, int):
        return abs(v) <= 10**9
    if isinstance(v, float):
        return math.isfinite(v)
    return isinstance(v, str) and len(v) <= WORD_MAX


def _geometric(obj: object) -> bool:
    if isinstance(obj, Mapping):
        return any(str(k).lower() in GEOMETRY or _geometric(v) for k, v in obj.items())
    if isinstance(obj, list | tuple):
        return any(_geometric(v) for v in obj)
    return False


def _floats(obj: object) -> list[float]:
    if isinstance(obj, float):
        return [obj]
    if isinstance(obj, Mapping):
        return [f for v in obj.values() for f in _floats(v)]
    if isinstance(obj, list | tuple):
        return [f for v in obj for f in _floats(v)]
    return []


def needles(
    bodies: Sequence[Sequence[Mapping[str, float]]], things: Sequence[Mapping[str, Any]] = ()
) -> frozenset[float]:
    """The bodies' x and y coordinates and the things' boxes that could only be copied, never
    computed by chance (more than three decimals)."""
    found = [v for b in bodies for p in b for v in (p["x"], p["y"])]
    found += [float(v) for t in things for v in dict(t.get("box") or {}).values()]
    return frozenset(v for v in found if isinstance(v, float) and round(v, 3) != v)


def clean_view(raw: object) -> tuple[dict[str, Any], ...] | None:
    """The fixed widget kinds with scalar values only (a widget that isn't one is left out, as
    the console's `tally()` does); None when any widget holds geometry (the report is refused)."""
    if not isinstance(raw, list | tuple):
        return ()
    out: list[dict[str, Any]] = []
    for widget in raw:
        if not isinstance(widget, Mapping) or widget.get("kind") not in VIEW_KINDS:
            continue
        if _geometric(widget):
            return None
        if len(widget) > MAX_TALLY_KEYS or not all(
            isinstance(k, str) and len(k) <= KEY_MAX and _scalar(v) for k, v in widget.items()
        ):
            continue
        out.append(dict(widget))
        if len(out) == MAX_VIEW:
            break
    return tuple(out)


def clean_tally(use: str, raw: object) -> dict[str, Any] | None:
    """The use case's tally as its model keeps it, else None."""
    if raw is None or _geometric(raw):
        return None
    model = parse_tally(use, raw)
    return None if model is None else model.model_dump(mode="json")


# ---- one body of one use case --------------------------------------------------------------------


@dataclass
class _Body:
    state: Any
    who: str
    started: float
    seen: float
    tally_at: float
    view: tuple[dict[str, Any], ...] | None = None
    view_at: float = -math.inf


@dataclass
class _Use:
    id: str
    case: HomeUseCase
    states: dict[int, _Body] = field(default_factory=dict)

    @property
    def tasks(self) -> tuple[str, ...]:
        return tuple(getattr(self.case, "tasks", ()) or ())

    def feed(self, key: int, result: dict[str, Any], who: str, now: float, *,
             seen: bool = True) -> None:  # fmt: skip
        """One Result into one body's state. Only a pose of that body counts as seeing it (a
        thing in view does not keep a body that left in the session)."""
        body = self.states.get(key)
        if body is None:
            if len(self.states) > BODIES_MAX:
                return
            body = self.states[key] = _Body(None, who, now, now, now)
        try:
            body.state = self.case.on_result(_copy(result), body.state)
        except Exception as exc:  # noqa: BLE001 - one use case's fault never stops the loop
            log.info("a home use case failed", extra={"use": self.id, "error": type(exc).__name__})
        body.who = who
        if seen:
            body.seen = now


def _copy(obj: Any) -> Any:
    if isinstance(obj, Mapping):
        return {k: _copy(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_copy(v) for v in obj]
    return obj


@dataclass(frozen=True)
class Look:
    """What one frame gave. Never pixels: points and boxes, for this laptop's use cases only."""

    at: float
    ms: int
    quality: dict[str, float]
    bodies: tuple[tuple[int, str, tuple[dict[str, float], ...]], ...]  # (track, who, points)
    objects: tuple[dict[str, Any], ...] | None


class _Window:
    def __init__(self, per_min: int) -> None:
        self._per = per_min
        self._times: deque[float] = deque()

    def take(self, now: float) -> bool:
        while self._times and now - self._times[0] >= 60.0:
            self._times.popleft()
        if len(self._times) >= self._per:
            return False
        self._times.append(now)
        return True

    def count(self, now: float) -> int:
        while self._times and now - self._times[0] >= 60.0:
            self._times.popleft()
        return len(self._times)


# ---- the loop ------------------------------------------------------------------------------------


class HomeRuntime:
    def __init__(
        self,
        camera: str,
        source: FrameSource,
        pose: PoseEngine,
        sink: Sink,
        *,
        objects: ObjectEngine | None = None,
        identifier: Identifier | None = None,
        registry: Mapping[str, Callable[[], HomeUseCase]] | None = None,
        wall: Callable[[], float] = time.time,
        mono: Callable[[], float] = time.monotonic,
        idle_s: float = IDLE_S,
        retry_s: float = RETRY_S,
    ) -> None:
        self.camera = camera
        self._idle_s = idle_s
        self._retry_s = retry_s
        self._source = source
        self._pose = pose
        self._objects = objects
        self._who_of = identifier or NoOne()
        self._registry = REGISTRY if registry is None else registry
        self._sink = sink
        self._wall = wall
        self._mono = mono
        self._coach: CoachState | None = None
        self._uses: dict[str, _Use] = {}
        self._tracker = Tracker()
        self._who: dict[int, tuple[str, float]] = {}
        self._needles: frozenset[float] = frozenset()
        self._session = new_session()
        self._was_wanted = False
        self._looking = False
        self._open = False
        self._next_at = 0.0
        self._looks: deque[float] = deque()
        self._views = _Window(VIEWS_PER_MIN)
        self._tallies = _Window(TALLIES_PER_MIN)
        self._stop = threading.Event()
        self._wake = asyncio.Event()
        self._inflight: asyncio.Future[Any] | None = None
        self.why = ""  # why it isn't looking, plain words (never the address)
        self.refused = 0  # reports refused by the checks above
        self.sent = 0

    # ---- the cloud's coach part ----------------------------------------------------------------

    def apply(self, coach: CoachState) -> None:
        """A newer coach part from the cloud. "Cameras off" or nothing switched on for this
        camera stops a waiting read at once."""
        if self._coach is not None and coach.rev <= self._coach.rev:
            return
        self._coach = coach
        if not self.wanted():
            self._stop.set()
        self._wake.set()

    def wanted(self) -> tuple[str, ...]:
        coach = self._coach
        if coach is None or coach.all_off:
            return ()
        asked = coach.uses.get(self.camera, ())
        return tuple(
            u for u in asked
            if u in HOME_USE_CASES and u in self._registry and BY_ID[u].source == "home"
        )  # fmt: skip

    def _picks(self, who: str) -> bool:
        coach = self._coach
        if coach is None or coach.target == "all":
            return True
        return who == ("me" if coach.target == "me" else coach.person)

    def part(self) -> HomeVisionPart:
        now = self._mono()
        while self._looks and now - self._looks[0] >= 60.0:
            self._looks.popleft()
        if not self._looking:
            return HomeVisionPart(running=False, uses=self.wanted()[:4])
        return HomeVisionPart(
            running=True,
            model=self._pose.model,
            fps=round(min(60.0, len(self._looks) / 60.0), 2),
            uses=self.wanted()[:4],
        )

    # ---- running -------------------------------------------------------------------------------

    async def run(self) -> None:
        try:
            while True:
                await self.step()
        finally:
            await self._wind_down()

    async def step(self) -> None:
        """One turn of the loop: one look, or one pause."""
        wanted = self.wanted()
        await self._sync(wanted)
        if wanted and not self._was_wanted:
            self._session = new_session()  # a look starts: its guests are this session's
        self._was_wanted = bool(wanted)
        if not wanted:
            await self._close_stream()
            await self._pause(self._idle_s)
            return
        if not await self._ready():
            await self._close_stream()
            await self._pause(self._retry_s)
            return
        self._stop.clear()
        if not self.wanted():  # "cameras off" came while the models were made ready
            return
        try:
            frame = await self._call(self._source.read, self._next_at, self._stop)
        except Exception as exc:  # noqa: BLE001 - SourceDown, or the decoder's own fault
            down = str(exc) if isinstance(exc, SourceDown) else "unreadable"
            self.why = f"the home camera's stream: {down}"
            log.warning("the home camera's stream is down", extra={"why": down})
            await self._close_stream()
            await self._pause(self._retry_s)
            return
        if frame is None or not self.wanted():
            return  # stopped, or switched off while the frame was read: it is not looked at
        try:
            look = await self._call(self._look, frame)
        except Exception as exc:  # noqa: BLE001 - one frame the models couldn't look at
            log.info("a frame could not be looked at", extra={"error": type(exc).__name__})
            return
        finally:
            del frame  # the only picture: gone before anything is reported
        await self._use(look)
        gap = max(1.0 / self._rate(), 2.0 * look.ms / 1000.0)
        self._next_at = self._mono() + gap

    async def _call(self, fn: Callable[..., Any], *args: Any) -> Any:
        """Blocking work on a worker thread; on cancel, the thread is told to stop and awaited
        before anything it uses is closed."""
        fut = asyncio.get_running_loop().run_in_executor(None, fn, *args)
        self._inflight = fut
        try:
            return await asyncio.shield(fut)
        finally:
            if fut.done():
                self._inflight = None

    async def _pause(self, seconds: float) -> None:
        self._wake.clear()
        try:
            await asyncio.wait_for(self._wake.wait(), seconds)
        except TimeoutError:
            pass

    async def _ready(self) -> bool:
        why = await self._call(self._pose.status)
        if why != READY:
            self.why = why
            return False
        if not self._open:
            try:
                await self._call(self._source.open)
            except SourceDown as down:
                self.why = f"the home camera's stream: {down}"
                return False
            self._open = True
        self._looking, self.why = True, ""
        return True

    async def _close_stream(self) -> None:
        if self._inflight is not None and not self._inflight.done():
            self._stop.set()
            await asyncio.wait({self._inflight}, timeout=10.0)
        if self._open or self._looking:
            self._source.close()
            self._pose.close()
            if self._objects is not None:
                self._objects.close()
        self._open = self._looking = False

    async def _wind_down(self) -> None:
        for use in list(self._uses.values()):
            await self._end_all(use)
        self._uses.clear()
        await self._close_stream()

    # ---- the use cases -------------------------------------------------------------------------

    async def _sync(self, wanted: tuple[str, ...]) -> None:
        for uid in [u for u in self._uses if u not in wanted]:
            await self._end_all(self._uses.pop(uid))
        for uid in wanted:
            if uid not in self._uses:
                try:
                    self._uses[uid] = _Use(uid, self._registry[uid]())
                except Exception as exc:  # noqa: BLE001
                    log.info("a home use case could not start", extra={"use": uid,
                             "error": type(exc).__name__})  # fmt: skip

    def _rate(self) -> float:
        rates = [BY_ID[u.id].rate for u in self._uses.values()]
        for use in self._uses.values():
            hint = getattr(use.case, "rate", None)
            if not callable(hint):
                continue
            for body in use.states.values():
                try:
                    asked = hint(body.state)
                except Exception:  # noqa: BLE001
                    continue
                if isinstance(asked, int | float) and not isinstance(asked, bool) and asked > 0:
                    rates.append(float(asked))
        return max(0.2, min(LIVE_MAX_FPS, max(rates, default=1.0)))

    def _look(self, frame: Frame) -> Look:
        """On the worker thread: the only code that touches the frame."""
        start = time.perf_counter()
        wants = {t for u in self._uses.values() for t in u.tasks}
        raw = self._pose.bodies(frame) if "pose" in wants else []
        tracks = self._tracker.assign(raw, frame.at)
        live = self._tracker.live()
        self._who = {t: v for t, v in self._who.items() if t in live}
        bodies = tuple(
            (t, self._name(frame, t, pts, len(raw)), tuple(pts))
            for t, pts in zip(tracks, raw, strict=True)
        )
        things: tuple[dict[str, Any], ...] | None = None
        if "objects" in wants and self._objects is not None and self._objects.status() == READY:
            things = tuple(self._objects.objects(frame))
        quality = quality_of(frame)
        ms = int((time.perf_counter() - start) * 1000)
        return Look(frame.at, ms, quality, bodies, things)

    def _name(self, frame: Frame, track: int, points: Sequence[Mapping[str, float]],
              n: int) -> str:  # fmt: skip
        """Who a body is: a consented id, else "me" for a body that came into view alone and is
        nobody else (kept while its track lasts), else "" (a guest). A body's face is looked at
        when it appears, then every few seconds until it is named, then once a minute."""
        entry = self._who.get(track)
        if entry is None:
            known = self._who_of.who(frame, points) or ("me" if n == 1 else "")
            self._who[track] = (known, frame.at)
            return known
        known, at = entry
        due = WHO_RECHECK_S if known.startswith("fp_") else WHO_RETRY_S
        if frame.at - at >= due:
            known = self._who_of.who(frame, points) or known  # a turned head keeps the name
            self._who[track] = (known, frame.at)
        return known

    async def _use(self, look: Look) -> None:
        now = look.at
        self._looks.append(self._mono())
        self._needles = needles([pts for _, _, pts in look.bodies], look.objects or ())
        base = {"at": int(now), "ms": look.ms, "device": "home", "ok": True,
                "quality": look.quality}  # fmt: skip
        picked = [(t, w, p) for t, w, p in look.bodies if self._picks(w)]
        for use in self._uses.values():
            if "pose" in use.tasks:
                for track, who, points in picked:
                    pose = {**base, "task": "pose", "v": 2, "data": {"points": list(points)},
                            "track": track, "who": who}  # fmt: skip
                    use.feed(track, pose, who, now)
            if look.objects is not None and "objects" in use.tasks:
                things = {**base, "task": "objects", "v": 1,
                          "data": {"objects": list(look.objects)}}  # fmt: skip
                keys = list(use.states) if "pose" in use.tasks else [ONE]
                for key in keys:
                    body = use.states.get(key)
                    use.feed(key, things, body.who if body else "", now,
                             seen="pose" not in use.tasks)  # fmt: skip
        for use in self._uses.values():
            for key, body in list(use.states.items()):
                if now - body.seen > LOST_S:
                    await self._end(use, key)
                    continue
                await self._report(use, key, body, now)

    def _summary(self, use: _Use, body: _Body) -> Mapping[str, Any]:
        try:
            out = use.case.summary(body.state)
        except Exception as exc:  # noqa: BLE001
            log.info("a home use case failed", extra={"use": use.id, "error": type(exc).__name__})
            return {}
        return out if isinstance(out, Mapping) else {}

    async def _report(self, use: _Use, key: int, body: _Body, now: float) -> None:
        out = self._summary(use, body)
        if use.id in ALL_DAY and now - body.tally_at >= TALLY_EVERY_S:
            body.tally_at = now
            if await self._send(use, key, body, out, now, with_tally=True):
                kept = getattr(use.case, "kept", None)
                if callable(kept):
                    try:
                        body.state = kept(body.state)
                    except Exception:  # noqa: BLE001
                        log.info("a home use case failed", extra={"use": use.id})
            return
        view = clean_view(out.get("view"))
        changed = view is not None and view != body.view
        due = now - body.view_at >= (VIEW_EVERY_S if changed else VIEW_REFRESH_S)
        if due and self._views.take(self._mono()):
            await self._send(use, key, body, out, now, with_tally=False)

    async def _end(self, use: _Use, key: int) -> None:
        body = use.states.pop(key, None)
        if body is not None:
            await self._send(use, key, body, self._summary(use, body), self._wall(),
                             with_tally=True)  # fmt: skip

    async def _end_all(self, use: _Use) -> None:
        for key in list(use.states):
            await self._end(use, key)

    async def _send(self, use: _Use, key: int, body: _Body, out: Mapping[str, Any], now: float,
                    *, with_tally: bool) -> bool:  # fmt: skip
        view = clean_view(out.get("view"))
        tally = clean_tally(use.id, out.get("tally")) if with_tally else None
        if with_tally and out.get("tally") is None:
            return False  # nothing to keep yet
        if with_tally and tally is None:
            view = None  # a tally that doesn't fit is dropped, and its report with it
        if view is None or any(f in self._needles for f in _floats([view, tally])):
            self.refused += 1
            log.warning("a home coach report was refused", extra={"use": use.id})
            return False
        if with_tally and tally is not None and not self._tallies.take(self._mono()):
            log.warning("too many home coach tallies: one was dropped", extra={"use": use.id})
            return False
        try:
            event = CoachReport(
                id="cr-" + secrets.token_hex(8),
                type="coach",
                at=float(now),
                camera=self.camera,
                use=use.id,
                session=self._session,
                track=max(0, min(TRACK_MAX, key)),
                who=body.who,
                view=view,
                tally=tally,
            )
        except ValidationError:
            self.refused += 1
            log.warning("a home coach report didn't fit", extra={"use": use.id})
            return False
        body.view, body.view_at = view, now
        try:
            ok = bool(await self._sink(event))
        except Exception as exc:  # noqa: BLE001 - the outbox retries; the loop goes on
            log.info("a home coach report was not sent", extra={"error": type(exc).__name__})
            return False
        self.sent += int(ok)
        return ok


__all__ = [
    "ALL_DAY",
    "GEOMETRY",
    "LIVE_MAX_FPS",
    "LOST_S",
    "TALLY_EVERY_S",
    "VIEWS_PER_MIN",
    "VIEW_EVERY_S",
    "VIEW_REFRESH_S",
    "HomeRuntime",
    "Look",
    "Tracker",
    "clean_tally",
    "clean_view",
    "needles",
    "new_session",
]

# src/jarvis/homebridge/activitywatch.py
"""R8 row 183 (docs/plans/r8-vision.md 4.7, D5, ADR-53; builder C): screen time.

ActivityWatch (MPL-2.0) is installed by the owner on the laptop, never shipped. This plugin reads
its local REST API (`AW_URL` in bridge.env, default http://host.docker.internal:5600) and serves

    GET /bridge/v1/screentime?day=yyyy-mm-dd&offset=<minutes east of UTC>

-> `{"state": "ok", "day", "active_minutes", "programs": [{"name", "minutes"}, ...]}` for that
local day: the minutes each program had the focus while he was at the keyboard (its window events
intersected with the "not-afk" periods), and the active minutes in all. **Window titles never
leave the laptop:** they are dropped as each event is read, never kept, logged or sent; a
program's name is cut to `NAME_MAX` characters ("chrome.exe" -> "chrome").

With no ActivityWatch it answers `{"state": "not_installed"}` (Vitals: "off until ActivityWatch
is installed"); when it answers oddly or too slowly, `{"state": "unreachable"}`. A bad query is
refused in plain words. Kit-safe: the standard library and httpx only.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from jarvis.home.ports import SCREENTIME_ROUTE, BridgeState, HeartbeatParts, HomeRefused
from jarvis.homebridge.plugins import BridgeContext, BridgePlugin, BridgeRoute, TaskFactory

log = logging.getLogger(__name__)

NAME = "activitywatch"
DEFAULT_URL = "http://host.docker.internal:5600"
TIMEOUT_S = 10.0
MAX_BYTES = 16 * 1024 * 1024  # a day's events
EVENT_LIMIT = 100_000
NAME_MAX = 40
PROGRAMS_MAX = 25
OFFSET_RANGE = (-720, 840)  # minutes east of UTC
WINDOW_TYPE, AFK_TYPE = "currentwindow", "afkstatus"
BAD_QUERY = "Screen time needs a day (yyyy-mm-dd) and its offset from UTC in minutes."
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EXE = re.compile(r"\.exe$", re.IGNORECASE)

Span = tuple[float, float]  # unix seconds, start and end


class Unreachable(RuntimeError):
    """ActivityWatch answered oddly, too slowly or too much (never its text)."""


class NotInstalled(RuntimeError):
    """Nothing listens at AW_URL, or it has no window watcher."""


def base_url(raw: str | None) -> str | None:
    """`AW_URL` as `scheme://host[:port]`, or None when it isn't a plain http(s) address."""
    url = (raw or "").strip() or DEFAULT_URL
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    if parts.username or parts.password or parts.query or parts.fragment:
        return None
    if parts.path not in ("", "/"):
        return None
    host = parts.hostname if ":" not in parts.hostname else f"[{parts.hostname}]"
    return f"{parts.scheme}://{host}" + (f":{port}" if port else "")


def day_window(day: str, offset: int) -> Span:
    """The local day `day` (at `offset` minutes east of UTC) as unix seconds."""
    d = date.fromisoformat(day)
    start = datetime(d.year, d.month, d.day, tzinfo=UTC) - timedelta(minutes=offset)
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


def program(raw: object) -> str:
    """A program's name as it may leave the laptop: printable, short, no ".exe"."""
    text = "".join(c for c in str(raw or "") if c.isprintable()).strip()
    text = _EXE.sub("", text).strip()[:NAME_MAX].strip()
    return text or "Unknown"


def _when(raw: object) -> float | None:
    if not isinstance(raw, str):
        return None
    try:
        at = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return (at if at.tzinfo else at.replace(tzinfo=UTC)).timestamp()


def _span(event: Mapping[str, Any], window: Span) -> Span | None:
    start = _when(event.get("timestamp"))
    dur = event.get("duration")
    if start is None or isinstance(dur, bool) or not isinstance(dur, int | float) or dur <= 0:
        return None
    lo, hi = max(start, window[0]), min(start + float(dur), window[1])
    return (lo, hi) if hi > lo else None


def union(spans: Iterable[Span]) -> list[Span]:
    out: list[Span] = []
    for lo, hi in sorted(spans):
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def overlap(span: Span, merged: Sequence[Span]) -> float:
    return sum(max(0.0, min(span[1], hi) - max(span[0], lo)) for lo, hi in merged)


def screen_time(
    window_events: Iterable[Mapping[str, Any]],
    afk_events: Iterable[Mapping[str, Any]] | None,
    window: Span,
) -> tuple[float, dict[str, float]]:
    """(active seconds, {program: seconds}). A window event's title is never read."""
    focus: list[tuple[str, Span]] = []
    for e in window_events:
        data = e.get("data")
        span = _span(e, window) if isinstance(data, Mapping) else None
        if span is not None and isinstance(data, Mapping):
            focus.append((program(data.get("app")), span))
    if afk_events is None:  # no AFK watcher: the window events are the active time
        active = union(s for _, s in focus)
    else:
        active = union(
            s
            for e in afk_events
            if isinstance(e.get("data"), Mapping)
            and e["data"].get("status") == "not-afk"
            and (s := _span(e, window)) is not None
        )
    seconds: dict[str, float] = {}
    for name, span in focus:
        got = overlap(span, active)
        if got > 0:
            seconds[name] = seconds.get(name, 0.0) + got
    return sum(hi - lo for lo, hi in active), seconds


class ActivityWatchPlugin:
    def __init__(self, ctx: BridgeContext, *, client: httpx.AsyncClient | None = None) -> None:
        self.name = NAME
        self._ctx = ctx
        self._url = base_url(ctx.env.get("AW_URL"))
        self._client = client or httpx.AsyncClient(
            timeout=TIMEOUT_S, follow_redirects=False, trust_env=False
        )
        self._routes = (BridgeRoute(SCREENTIME_ROUTE[0], SCREENTIME_ROUTE[1], self._serve),)  # type: ignore[arg-type]

    def routes(self) -> Sequence[BridgeRoute]:
        return self._routes

    def tasks(self) -> Sequence[TaskFactory]:
        return ()

    async def heartbeat_part(self) -> HeartbeatParts:
        return HeartbeatParts()

    async def apply_state(self, state: BridgeState) -> None:
        return None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _serve(
        self, query: Mapping[str, str], body: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        del body
        day, raw_offset = query.get("day", ""), query.get("offset", "")
        try:
            offset = int(raw_offset)
            if not _DAY.match(day) or not OFFSET_RANGE[0] <= offset <= OFFSET_RANGE[1]:
                raise ValueError("bad query")
            window = day_window(day, offset)
        except ValueError:
            raise HomeRefused("bad_request", BAD_QUERY) from None
        return await self.read(day, window)

    async def read(self, day: str, window: Span) -> dict[str, Any]:
        try:
            active, seconds = await self._screen(window)
        except NotInstalled:
            return {"state": "not_installed"}
        except Unreachable:
            return {"state": "unreachable"}
        top = sorted(seconds.items(), key=lambda p: (-p[1], p[0]))[:PROGRAMS_MAX]
        return {
            "state": "ok",
            "day": day,
            "active_minutes": round(active / 60, 1),
            "programs": [{"name": n, "minutes": round(s / 60, 1)} for n, s in top],
        }

    async def _screen(self, window: Span) -> tuple[float, dict[str, float]]:
        if self._url is None:
            log.warning("screen time: AW_URL is not a plain http address")
            raise Unreachable()
        buckets = await self._get("/api/0/buckets/", None)
        if not isinstance(buckets, Mapping):
            raise Unreachable()
        win = _newest(buckets, WINDOW_TYPE)
        if win is None:
            raise NotInstalled()
        afk = _newest(buckets, AFK_TYPE)
        params = {
            "start": datetime.fromtimestamp(window[0], UTC).isoformat(),
            "end": datetime.fromtimestamp(window[1], UTC).isoformat(),
            "limit": str(EVENT_LIMIT),
        }
        win_events = await self._events(win, params)
        afk_events = await self._events(afk, params) if afk is not None else None
        return screen_time(win_events, afk_events, window)

    async def _events(self, bucket: str, params: Mapping[str, str]) -> list[Mapping[str, Any]]:
        got = await self._get(f"/api/0/buckets/{quote(bucket, safe='')}/events", params)
        if not isinstance(got, list):
            raise Unreachable()
        return [e for e in got if isinstance(e, Mapping)]

    async def _get(self, path: str, params: Mapping[str, str] | None) -> Any:
        try:
            resp = await self._client.get(f"{self._url}{path}", params=params)
        except httpx.ConnectError:
            raise NotInstalled() from None
        except httpx.HTTPError as exc:
            log.warning(
                "screen time: ActivityWatch didn't answer", extra={"error": type(exc).__name__}
            )
            raise Unreachable() from None
        if resp.status_code != 200 or len(resp.content) > MAX_BYTES:
            log.warning(
                "screen time: ActivityWatch answered oddly", extra={"status": resp.status_code}
            )
            raise Unreachable()
        try:
            return resp.json()
        except ValueError:
            raise Unreachable() from None


def _newest(buckets: Mapping[str, Any], kind: str) -> str | None:
    """The bucket of `kind` updated last (one laptop has one of each)."""
    found = [
        (str(b.get("last_updated") or ""), str(bid))
        for bid, b in buckets.items()
        if isinstance(b, Mapping) and b.get("type") == kind and isinstance(bid, str)
    ]
    return max(found)[1] if found else None


def create_plugin(ctx: BridgeContext) -> BridgePlugin:
    return ActivityWatchPlugin(ctx)


__all__ = [
    "DEFAULT_URL",
    "NAME",
    "ActivityWatchPlugin",
    "base_url",
    "create_plugin",
    "day_window",
    "program",
    "screen_time",
    "union",
]

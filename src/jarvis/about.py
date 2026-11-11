# src/jarvis/about.py
"""R6.1 D4: which JARVIS this is — its version and the day its image was built, for the Vitals
"About JARVIS · v6.1.0 · built 11 Nov 2026" line (added to GET /v1/vitals, owner-only).

The version has ONE source, `jarvis.__version__` (pyproject.toml carries the same number; a test
pins that they agree). The build date is a build-time value, never the request time:

  1. `JARVIS_BUILD_DATE` (ISO 8601) when the environment sets it (another host, a test); else
  2. `BUILD_DATE`, package data the Dockerfile stamps with `date -u` at image build, before
     `pip install .` (git-ignored, so a checkout never carries a stale one); else
  3. "unknown" (a local checkout, or a value that isn't a date).

Shown as the owner writes dates ("11 Nov 2026": fixed month words, no locale) in the owner's time
zone (`settings.user_timezone`). Read once per process and zone: an image's build date can't change.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, date, datetime
from functools import lru_cache
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from types import MappingProxyType
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jarvis import __version__
from jarvis.logging import get_logger

log = get_logger(__name__)

BUILD_DATE_ENV = "JARVIS_BUILD_DATE"
STAMP_FILE = "BUILD_DATE"
UNKNOWN = "unknown"
DEFAULT_ZONE = "Asia/Kolkata"
VERSION_SHOWN = r"^v[0-9]+\.[0-9]+\.[0-9]+$"
STAMP_MAX = 64  # an ISO 8601 time is at most ~35 characters; anything longer isn't one
DATE_ONLY = 10  # "2026-11-11"
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

PACKAGED_STAMP: Traversable = files("jarvis") / STAMP_FILE


def version() -> str:
    """The version as "v6.1.0" — the PR titles', tags' and build book's form."""
    return f"v{__version__}"


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_ZONE)


def shown(day: date) -> str:
    """11 Nov 2026 (the plans', guide's and build book's form)."""
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


def parse_stamp(raw: str | None, zone: ZoneInfo) -> str | None:
    """A stamp as the owner reads it, or None when it isn't an ISO 8601 date or time. A bare date is
    taken as written; a time without an offset is UTC (the Dockerfile stamps `date -u`)."""
    text = (raw or "").strip()
    if not text or len(text) > STAMP_MAX:
        return None
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    if len(text) == DATE_ONLY:
        return shown(when.date())
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return shown(when.astimezone(zone).date())


def _read(stamp: Traversable | Path | None) -> str | None:
    if stamp is None:
        return None
    try:
        data = stamp.read_bytes()
    except OSError:
        return None  # no stamp: a local checkout, or an image built before R6.1
    if len(data) > STAMP_MAX:
        return None
    try:
        return data.decode("ascii")
    except UnicodeDecodeError:
        return None


def build_date(
    *,
    environ: Mapping[str, str] | None = None,
    stamp: Traversable | Path | None = PACKAGED_STAMP,
    zone: str = DEFAULT_ZONE,
) -> str:
    """The build day as "11 Nov 2026", or "unknown"; never raises, never reads the clock."""
    env = os.environ if environ is None else environ
    tz = _zone(zone)
    for source, raw in (("env", env.get(BUILD_DATE_ENV)), ("stamp", _read(stamp))):
        if raw is None:
            continue
        day = parse_stamp(raw, tz)
        if day is not None:
            return day
        log.warning("build date unreadable; trying the next source", extra={"source": source})
    return UNKNOWN


@lru_cache(maxsize=4)
def fields(zone: str = DEFAULT_ZONE) -> Mapping[str, str]:
    """The two fields GET /v1/vitals carries: {version, build_date} (read-only)."""
    day = build_date(stamp=PACKAGED_STAMP, zone=zone)  # the module's stamp, looked up now
    return MappingProxyType({"version": version(), "build_date": day})


__all__ = [
    "BUILD_DATE_ENV",
    "DEFAULT_ZONE",
    "PACKAGED_STAMP",
    "STAMP_FILE",
    "UNKNOWN",
    "VERSION_SHOWN",
    "build_date",
    "fields",
    "parse_stamp",
    "shown",
    "version",
]

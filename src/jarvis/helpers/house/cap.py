# src/jarvis/helpers/house/cap.py
"""Reading NDMA SACHET's CAP 1.2 messages safely (docs/plans/r11-free-helpers.md D13, D20).

- `parse_xml(raw, limit=)` (`xmlsafe`): strict UTF-8 bytes with no DTD, then an expat parser
  whose every DTD handler raises (two layers, security review M1). No new dependency.
- `parse_cap`: the CAP 1.2 alert (its namespace required): identifier, status, msgType, scope,
  references and ONE info block (English first: SACHET sends en-IN and the state's language)
  with its onset and areas (description, polygons, geocodes). Every text is outside data:
  cleaned, capped, and used only to decide; a headline or instruction is kept only for the panel
  (fenced there). An area's description is read up to `AREA_TEXT_MAX` (4 KB: IMD lists many
  districts in one area, code review M4) and is never shown; a polygon over `MAX_POINTS` points
  is rejected, never cut (security review L3).
- `kind_for` (D13): any non-Met category, or Met Extreme -> `disaster_alert` (urgent: it rings
  at night); Met Severe -> `weather_warning` (held at night); Met Moderate / Minor ->
  `weather_note`.
- `matches_place`: his district by the area's LGD code, by his point inside a polygon, or by
  name (the district's words in the description, and his state named or no other state named);
  a state-wide warning for his state matches too. `DISTRICT_FILTER` exists only so the eval's
  negative control can switch the filter off; it is read at call time and is True in the app.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime

from jarvis.alerts import AlertKind
from jarvis.helpers.house.models import OUTSIDE_TEXT_MAX, STATES, Place, clean_text
from jarvis.helpers.house.xmlsafe import UnsafeXml, parse_xml
from jarvis.helpers.sources import MAX_CAP_BYTES

DISTRICT_FILTER = True
NS = "urn:oasis:names:tc:emergency:cap:1.2"
MAX_INFOS, MAX_AREAS, MAX_POLYGONS, MAX_POINTS = 4, 20, 10, 2000
AREA_TEXT_MAX = 4096  # an area's description, for matching only (never shown)
RANK: dict[str, int] = {"weather_note": 0, "weather_warning": 1, "disaster_alert": 2}
_ID = re.compile(r"^[A-Za-z0-9._:\-]{1,120}$")
_STATES_NORM = tuple(" ".join(re.sub(r"[^a-z]+", " ", s.lower()).split()) for s in STATES)


@dataclass(frozen=True)
class Area:
    desc: str
    polygons: tuple[tuple[tuple[float, float], ...], ...]
    codes: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Info:
    language: str
    categories: tuple[str, ...]
    event: str
    urgency: str
    severity: str
    certainty: str
    expires: datetime | None
    headline: str
    instruction: str
    areas: tuple[Area, ...]
    onset: datetime | None = None  # its onset, else its effective time


@dataclass(frozen=True)
class Alert:
    identifier: str
    sent: datetime | None
    status: str
    msg_type: str
    scope: str
    references: tuple[str, ...]
    info: Info | None


def _q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def _text(el: ET.Element | None, tag: str, limit: int = 80) -> str:
    found = el.find(_q(tag)) if el is not None else None
    return clean_text(found.text or "", limit) if found is not None else ""


def _when(value: str) -> datetime | None:
    try:
        got = datetime.fromisoformat(value)
    except ValueError:
        return None
    return got if got.tzinfo is not None else None


def parse_polygon(value: str) -> tuple[tuple[float, float], ...]:
    """CAP's "lat,lon lat,lon ..." (WGS 84, closed); () when it isn't one."""
    pairs = value.split()
    if len(pairs) > MAX_POINTS:
        return ()  # never a cut (open, partial) shape
    points: list[tuple[float, float]] = []
    for pair in pairs:
        lat, sep, lon = pair.partition(",")
        try:
            p = (float(lat), float(lon))
        except ValueError:
            return ()
        if not sep or not (-90 <= p[0] <= 90 and -180 <= p[1] <= 180):
            return ()
        points.append(p)
    return tuple(points) if len(points) >= 4 else ()


def _area(el: ET.Element) -> Area:
    polys = tuple(
        p
        for p in (parse_polygon(x.text or "") for x in el.findall(_q("polygon"))[:MAX_POLYGONS])
        if p
    )
    codes = tuple(
        (_text(g, "valueName", 60), _text(g, "value", 60)) for g in el.findall(_q("geocode"))[:10]
    )
    return Area(_text(el, "areaDesc", AREA_TEXT_MAX), polys, codes)


def _info(el: ET.Element) -> Info:
    return Info(
        language=_text(el, "language", 20),
        categories=tuple(clean_text(c.text or "", 20) for c in el.findall(_q("category"))[:8]),
        event=_text(el, "event", 120),
        urgency=_text(el, "urgency", 20),
        severity=_text(el, "severity", 20),
        certainty=_text(el, "certainty", 20),
        expires=_when(_text(el, "expires", 40)),
        headline=_text(el, "headline", OUTSIDE_TEXT_MAX),
        instruction=_text(el, "instruction", OUTSIDE_TEXT_MAX),
        areas=tuple(_area(a) for a in el.findall(_q("area"))[:MAX_AREAS]),
        onset=_when(_text(el, "onset", 40)) or _when(_text(el, "effective", 40)),
    )


def _pick(infos: list[ET.Element]) -> Info | None:
    parsed = [_info(i) for i in infos[:MAX_INFOS]]
    english = [i for i in parsed if i.language.lower().startswith("en")]
    found = english or parsed
    return found[0] if found else None


def parse_cap(raw: bytes) -> Alert:
    root = parse_xml(raw, limit=MAX_CAP_BYTES)
    if root.tag != _q("alert"):
        raise ValueError("Not a CAP 1.2 alert.")
    ident = _text(root, "identifier", 200)
    if not _ID.match(ident):
        raise ValueError("A CAP alert needs a plain identifier.")
    refs = tuple(
        part.split(",")[1]
        for part in _text(root, "references", 2000).split()
        if part.count(",") == 2 and _ID.match(part.split(",")[1])
    )
    info = _pick(root.findall(_q("info")))
    if info is not None and not info.categories:
        raise ValueError("A CAP info block needs a category.")
    return Alert(
        identifier=ident,
        sent=_when(_text(root, "sent", 40)),
        status=_text(root, "status", 20),
        msg_type=_text(root, "msgType", 20),
        scope=_text(root, "scope", 20),
        references=refs[:20],
        info=info,
    )


def kind_for(info: Info) -> AlertKind:
    if set(info.categories) - {"Met"} or info.severity == "Extreme":
        return "disaster_alert"
    return "weather_warning" if info.severity == "Severe" else "weather_note"


def norm(text: str) -> str:
    """Lower-case letters and single spaces only (how names are compared)."""
    return " ".join(re.sub(r"[^a-z]+", " ", text.lower()).split())


def _inside(point: tuple[float, float], poly: tuple[tuple[float, float], ...]) -> bool:
    """Ray casting with latitude as y and longitude as x."""
    y, x = point
    inside = False
    for (y1, x1), (y2, x2) in zip(poly, poly[1:] + poly[:1], strict=True):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _by_name(desc: str, district: str, state: str) -> bool:
    padded = f" {desc} "
    if desc in (state, f"state of {state}", f"{state} state"):
        return True  # a warning for the whole of his state
    if f" {district} " not in padded:
        return False
    others = [s for s in _STATES_NORM if s != state and f" {s} " in padded]
    return f" {state} " in padded or not others


def matches_place(info: Info, place: Place) -> bool:
    if not DISTRICT_FILTER:  # the eval's negative control only
        return True
    district, state, point = norm(place.district), norm(place.state), place.point()
    for area in info.areas:
        if place.lgd and any(n.lower().startswith("lgd") and v == place.lgd for n, v in area.codes):
            return True
        if point is not None and any(_inside(point, p) for p in area.polygons):
            return True
        if district and _by_name(norm(area.desc), district, state):
            return True
    return False


__all__ = [
    "AREA_TEXT_MAX",
    "DISTRICT_FILTER",
    "MAX_POINTS",
    "NS",
    "RANK",
    "Alert",
    "Area",
    "Info",
    "UnsafeXml",
    "kind_for",
    "matches_place",
    "norm",
    "parse_cap",
    "parse_polygon",
    "parse_xml",
]

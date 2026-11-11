# src/jarvis/helpers/house/words.py
"""Part B's alert texts: fixed templates only (docs/plans/r11-free-helpers.md D4, D10-D14; C45).

Every message is built here from JARVIS's own words, his own labels (a chore, an upkeep item, his
district as he typed it), numbers JARVIS parsed and checked, and a fixed event word. Never from a
CAP headline or instruction, an RSS title or a mail subject. A rota member's label (a person) is
only in the `named` version, which the alert policy uses only when "names in alerts" is on.
"""

from __future__ import annotations

from datetime import date, datetime

from jarvis.helpers.sources import OPEN_METEO_ATTRIBUTION

OPEN_METEO_SHORT = "Weather data by Open-Meteo.com."
SACHET_SHORT = "(SACHET)"
OFFICIAL_FIRST = (
    "JARVIS is a second channel. The official SACHET app, SMS and cell broadcast warnings come "
    "first: keep them on."
)
ADULTS_ONLY = "Adults only: JARVIS keeps no children's data. Reminders go only to you."
BREACH_HOW = (
    "Sign up your own address at Have I Been Pwned's free 'Notify me' (and Mozilla Monitor if you "
    "like). JARVIS then watches your Gmail for their notices and sends your address nowhere."
)
HIBP_NOTIFY = "https://haveibeenpwned.com/NotifyMe"
# D13: the fixed event vocabulary (first match in the CAP `event` wins); anything else is
# "Disaster" (an urgent alert) or "Weather" (a Met one)
EVENT_WORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("tsunami",), "Tsunami"),
    (("cyclone", "cyclonic", "depression"), "Cyclone"),
    (("earthquake",), "Earthquake"),
    (("landslide", "land slide", "mudslide"), "Landslide"),
    (("flood", "inundation"), "Flood"),
    (("heavy rain", "heavy rainfall", "very heavy", "extremely heavy"), "Heavy rain"),
    (("thunder", "lightning"), "Thunderstorm"),
    (("heat wave", "heatwave", "heat-wave"), "Heat wave"),
    (("cold wave", "coldwave", "cold-wave"), "Cold wave"),
)


def event_word(event: str, kind: str) -> str:
    low = " ".join(event.lower().split())
    for needles, word in EVENT_WORDS:
        if any(n in low for n in needles):
            return word
    return "Disaster" if kind == "disaster_alert" else "Weather"


def _hhmm(at: datetime) -> str:
    return at.strftime("%H:%M")


def _when(at: datetime, today: date) -> str:
    return "today" if at.date() == today else "tomorrow" if at.date() > today else "earlier"


def chore(label: str) -> str:
    return f"Chore today: {label}. Open JARVIS to see whose turn it is."


def chore_named(label: str, member: str) -> str:
    return f"Chore today: {label}. It's {member}'s turn."


def upkeep_soon(label: str, due: date) -> str:
    return f"Home upkeep: {label} is due on {due.day} {due.strftime('%b')}."


def upkeep_due(label: str) -> str:
    return f"Home upkeep due today: {label}."


def weather(kind: str, at: datetime, value: float, today: date) -> str:
    """`at` local; `value` a number JARVIS parsed and bounded."""
    day = _when(at, today)
    if kind == "rain_hour":
        body = f"Heavy rain likely around {_hhmm(at)} {day}: about {value:.0f} mm in an hour."
    elif kind == "rain_day":
        body = f"Heavy rain likely {day}: about {value:.0f} mm in the day."
    elif kind == "heat":
        body = f"Very hot {day}: it will feel like {value:.0f} °C around {_hhmm(at)}."
    else:
        body = f"Strong winds likely around {_hhmm(at)} {day}: gusts up to {value:.0f} km/h."
    return f"{body} {OPEN_METEO_SHORT}"


def until(expires: datetime | None, now: datetime) -> str:
    """'until 18:00' today, 'until 12 Nov 18:00' on another day (both local)."""
    if expires is None:
        return "until further notice"
    if expires.date() == now.date():
        return f"until {_hhmm(expires)}"
    return f"until {expires.day} {expires.strftime('%b')} {_hhmm(expires)}"


def cap(kind: str, event: str, district: str, ends: str) -> str:
    if kind == "disaster_alert":
        return f"Urgent: {event} warning for {district} {ends} {SACHET_SHORT}. Open JARVIS."
    if kind == "weather_warning":
        return f"{event} warning for {district} {ends} {SACHET_SHORT}. Open JARVIS."
    return f"{event} advisory for {district} {ends} {SACHET_SHORT}."


def lifted(event: str, district: str) -> str:
    return f"{event} warning for {district} lifted {SACHET_SHORT}."


def breach(service: str) -> str:
    return (
        f"A breach notice from {service} arrived. Open it in Gmail and change that password, Sir."
    )


def brief_weather(t_max: float | None, rain_from: str | None) -> str:
    temp = f"up to {t_max:.0f} °C" if t_max is not None else "temperature unknown"
    rain = f"rain likely after {rain_from}" if rain_from else "no rain expected"
    return f"Weather: {temp}, {rain} · {OPEN_METEO_ATTRIBUTION}"


def brief_warning(kind: str, event: str, district: str, ends: str) -> str:
    word = "advisory" if kind == "weather_note" else "warning"
    urgent = "Urgent: " if kind == "disaster_alert" else ""
    return f"{urgent}{event} {word} for {district} {ends} (SACHET)."


def brief_outage(source: str, since: str) -> str:
    return f"Can't reach {source} since {since}: the official SACHET app and SMS still warn you."


__all__ = [
    "ADULTS_ONLY",
    "BREACH_HOW",
    "EVENT_WORDS",
    "HIBP_NOTIFY",
    "OFFICIAL_FIRST",
    "OPEN_METEO_SHORT",
    "breach",
    "brief_outage",
    "brief_warning",
    "brief_weather",
    "cap",
    "chore",
    "chore_named",
    "event_word",
    "lifted",
    "until",
    "upkeep_due",
    "upkeep_soon",
    "weather",
]

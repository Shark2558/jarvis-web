# src/jarvis/brief/home_overnight.py
"""The brief's "Home overnight" section (R3 D10, D16): what the home camera noted since 20:00 last
evening - burglar alerts, parcels, people JARVIS recognised - and how many alerts were held back for
quiet hours. Counts, local times and fixed words only: no name (a person is "a person JARVIS
recognised"), no picture. Deterministic and never part of the AI-summary input
(`brief.summarize` names its blocks one by one). Absent (None) when there is nothing to say.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, tzinfo

from jarvis.brief.models import HomeOvernightItem, HomeOvernightSection
from jarvis.camera.config import CameraConfigService
from jarvis.camera.feed import Feed, camera_words
from jarvis.camera.models import FeedItem, first_upper
from jarvis.faces.ports import RECOGNISED_PERSON

MAX_SHOWN = 5
SINCE_HOUR = 20  # yesterday evening


def words(item: FeedItem, camera: str) -> str | None:
    if item.kind == "intruder":
        return f"Burglar alert at {camera}"
    if item.kind == "package":
        return f"A package was left at {camera}"
    if item.kind == "greeting":
        return f"{first_upper(RECOGNISED_PERSON)} arrived at {camera}"
    return None  # a car or a dog while armed is in the feed, not in the brief


class HomeOvernightBrief:
    def __init__(self, feed: Feed, config: CameraConfigService) -> None:
        self._feed = feed
        self._config = config

    async def section(self, uid: str, tz: tzinfo, day: date) -> HomeOvernightSection | None:
        start = datetime.combine(day - timedelta(days=1), time(SINCE_HOUR), tzinfo=tz)
        lines = [i for i in await self._feed.since(uid, start.timestamp()) if i.kind != "other"]
        if not lines:
            return None
        cams = {c: v.label for c, v in (await self._config.get(uid)).cameras.items()}
        items = []
        for i in lines[:MAX_SHOWN]:
            text = words(i, camera_words(cams.get(i.camera), i.camera))
            if text:
                at = datetime.fromtimestamp(i.at, UTC).astimezone(tz)
                items.append(HomeOvernightItem(when=at.strftime("%H:%M"), words=text))
        return HomeOvernightSection(
            total=len(lines),
            held=sum(1 for i in lines if i.decision == "held"),
            items=tuple(items),
            state="ok",
        )


__all__ = ["MAX_SHOWN", "SINCE_HOUR", "HomeOvernightBrief", "words"]

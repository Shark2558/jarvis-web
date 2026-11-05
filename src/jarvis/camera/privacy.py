# src/jarvis/camera/privacy.py
"""Camera data in the privacy dashboard (R3 D14). Registered by I1 with `PrivacyRegistry.register`.

- `home_feed` (Home alerts and greetings, 7 days): count of lines, export of ids and times (no
  name: names live in Faces), delete with the passkey (it can't be brought back).
- `camera_home` (recordings, snapshots and face pictures): they live on the owner's laptop only, so
  the row explains that, has no count and cannot be deleted from here.
- `CameraData.wipe(uid)`: the arm state and camera settings, for A's unlink.
"""

from __future__ import annotations

import hashlib
from typing import Any

from jarvis.camera.alarm import Alarm
from jarvis.camera.config import CameraConfigService
from jarvis.camera.feed import Feed
from jarvis.privacy.ports import CategoryView

SECTION = "Home and camera"


class HomeFeedPrivacy:
    id = "home_feed"
    section = SECTION
    label = "Home alerts and greetings"

    def __init__(self, feed: Feed | None) -> None:
        self._feed = feed

    async def describe(self, uid: str) -> CategoryView:
        base: dict[str, Any] = {
            "id": self.id,
            "section": self.section,
            "label": self.label,
            "what": (
                "What the camera reported and what JARVIS did about it: burglar alerts, "
                "parcels and greetings. Times and places only - no pictures."
            ),
            "unit": "entries",
            "retention": "7 days",
            "where": "Firestore, encrypted by JARVIS",
        }
        if self._feed is None:
            return CategoryView(
                **base, count=0, note="Not available on this server (no encryption key)."
            )
        count = await self._feed.count(uid)
        fingerprint = hashlib.sha256(f"home_feed:{count}".encode()).hexdigest()[:16]
        return CategoryView(
            **base,
            count=count,
            encrypted_by_jarvis=True,
            export=True,
            delete="passkey" if count else "none",
            recoverable=False,
            rev=fingerprint,
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        if self._feed is None:
            return None
        return {"entries": await self._feed.export(uid)}

    async def delete(self, uid: str) -> int:
        return 0 if self._feed is None else await self._feed.wipe(uid)


class CameraHomePrivacy:
    id = "camera_home"
    section = SECTION
    label = "Recordings and pictures at home"

    async def describe(self, uid: str) -> CategoryView:
        return CategoryView(
            id=self.id,
            section=self.section,
            label=self.label,
            what="Recordings, snapshots and face pictures. They never leave your laptop.",
            count=None,
            unit="",
            retention="7 days (strangers' faces 72 hours; people you added until you delete them)",
            where="Your home laptop only",
            encrypted_by_jarvis=False,
            export=False,
            delete="none",
            note="Open Frigate on your laptop to see or delete them. People are deleted in Faces.",
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        return None

    async def delete(self, uid: str) -> int:
        return 0


class CameraData:
    """What B keeps per owner besides the feed: the arm state and the camera settings."""

    def __init__(self, alarm: Alarm, config: CameraConfigService) -> None:
        self._alarm = alarm
        self._config = config

    async def wipe(self, uid: str) -> None:
        await self._alarm.wipe(uid)
        await self._config.wipe(uid)

    async def export(self, uid: str) -> dict[str, Any]:
        rec = await self._alarm.record(uid)
        cams = await self._config.get(uid)
        return {
            "alarm": {"armed": rec.armed, "mode": rec.mode, "changed_by": rec.set_via},
            "cameras": {
                cid: {"label": c.label, "alarm_zones": list(c.alarm_zones)}
                for cid, c in cams.cameras.items()
            },
        }


__all__ = ["CameraData", "CameraHomePrivacy", "HomeFeedPrivacy"]

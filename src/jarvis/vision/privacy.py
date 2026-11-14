# src/jarvis/vision/privacy.py
"""R7 D25: the camera's two rows on the privacy dashboard (section "Home and camera"), registered
through the part (`MobilePart.privacy`, I0 seam 20), so no privacy file is edited.

- `vision_results` (delete: passkey; it can't be brought back): the results he pressed Keep on,
  sealed by JARVIS (`vision`), 90 days; export lists them (never the sealed blob).
- `vision_device`: what lives only in this browser (the camera-off switch): nothing on the server,
  nothing to delete here; each device switches its own camera.
Both say what is never kept: a camera frame or a picture.
"""

from __future__ import annotations

from typing import Any

from jarvis.privacy.ports import CategoryView
from jarvis.privacy.sources import OURS_ENC, CallbackSource, Look, Spec
from jarvis.vision.store import VisionStore

SECTION = "Home and camera"
RESULTS_ID = "vision_results"
DEVICE_ID = "vision_device"
OFF_NOTE = "Off: JARVIS has no token key, so no camera result is kept."
NEVER = (
    "Never kept: a camera frame or a picture. A picture you chose to send to the AI stays with its "
    "conversation."
)


def results_privacy(store: VisionStore) -> CallbackSource:
    async def look(uid: str) -> Look:
        if not store.sealed:
            return Look(0, deletable=False, note=OFF_NOTE)
        count = await store.count(uid)
        return Look(count, [count], deletable=count > 0)

    async def export(uid: str) -> dict[str, Any]:
        return await store.export(uid)

    return CallbackSource(
        Spec(
            RESULTS_ID,
            SECTION,
            "Camera results you kept",
            "What a look on your phone or browser found, only when you pressed Keep: the task, "
            "the time, numbers, labels from fixed lists and text that was read.",
            "results",
            f"{store.keep_days} days",
            OURS_ENC,
            encrypted_by_jarvis=True,
            delete="passkey",
            note=NEVER,
        ),
        look,
        export,
        store.delete_all,
    )


class DevicePrivacy:
    id = DEVICE_ID
    section = SECTION
    label = "Only on this device: the camera-off switch"

    async def describe(self, uid: str) -> CategoryView:
        del uid
        return CategoryView(
            id=self.id,
            section=self.section,
            label=self.label,
            what=(
                "Whether this device's camera is switched off for JARVIS. It never reaches the "
                "server, and switching it off never disarms the home camera."
            ),
            count=None,
            unit="",
            retention="Until you switch it on again",
            where="This browser only",
            note="Switch it in Camera, Cameras, on each device.",
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        return None

    async def delete(self, uid: str) -> int:
        return 0


__all__ = ["DEVICE_ID", "RESULTS_ID", "SECTION", "DevicePrivacy", "results_privacy"]

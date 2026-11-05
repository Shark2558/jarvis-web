# src/jarvis/camera/packages.py
"""Doorstep package changes (R3 D16): one alert per change, not per flicker.

Frigate's state classification says `package` or `empty` for the doorstep zone. `empty -> package`
is the only change that alerts; `package -> empty` is only remembered. A second `package` inside 10
minutes of the last alert (the model flapping) is the same change. Until the owner trains the model
the settings say so in plain words and the bridge sends nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.camera.config import CameraConfigService
from jarvis.camera.models import CameraSettings, CameraStatus, PackageMemo
from jarvis.home.ports import Package

FLAP_WINDOW_S = 600.0  # D10: package alerts at least 10 minutes apart
NO_MODEL_NOTE = "Train the doorstep model on your laptop (setup step 12)."


@dataclass(frozen=True)
class PackageChange:
    alert: bool = False
    delivered: bool = False
    reason: str = ""


def memo_key(camera: str, zone: str) -> str:
    return f"{camera}:{zone}"


def model_note(settings: CameraSettings) -> str | None:
    """Plain words when a doorstep zone is set but no doorstep model has been reported."""
    if settings.packages_on and settings.status.doorstep_model is not True:
        return NO_MODEL_NOTE
    return None


class Packages:
    def __init__(self, config: CameraConfigService) -> None:
        self._config = config

    async def on_state(self, uid: str, ev: Package) -> PackageChange:
        settings = await self._config.get(uid)
        cfg = settings.cameras.get(ev.camera)
        if cfg is None or cfg.package_zone != ev.zone:
            return PackageChange(reason="not_a_package_zone")
        key = memo_key(ev.camera, ev.zone)
        decided: list[PackageChange] = []

        def change(st: CameraStatus) -> CameraStatus:
            decided.clear()
            prev = st.packages.get(key)
            if ev.state == "empty":
                memo = PackageMemo(
                    state="empty",
                    changed_at=ev.at,
                    alerted_at=prev.alerted_at if prev else None,
                )
                decided.append(PackageChange(reason="logged"))
            elif prev is not None and prev.state == "package":
                decided.append(PackageChange(reason="same"))
                return st
            else:
                last = prev.alerted_at if prev else None
                flap = last is not None and ev.at - last < FLAP_WINDOW_S
                memo = PackageMemo(
                    state="package", changed_at=ev.at, alerted_at=last if flap else ev.at
                )
                decided.append(
                    PackageChange(
                        alert=not flap, delivered=ev.delivered, reason="flap" if flap else "new"
                    )
                )
            return st.model_copy(update={"packages": {**st.packages, key: memo}})

        await self._config.update_status(uid, change)
        return decided[0]


__all__ = ["FLAP_WINDOW_S", "NO_MODEL_NOTE", "PackageChange", "Packages", "memo_key", "model_note"]

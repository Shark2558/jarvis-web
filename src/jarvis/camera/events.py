# src/jarvis/camera/events.py
"""What the cloud does with the camera events the bridge sends (R3 D1, D8, D9, D12, D13, D16).

`CameraEvents` is a `HomeEventHandler` for detection | face_seen | package | heartbeat | ack. The
order that matters for the burglar alert (D9: 10 seconds from the camera to the phone):

    detection -> is the alarm armed? -> inside an alarm zone? -> who (face directory) ->
    ONE call to the notifier (policy, Telegram, Web Push) -> only then the feed line

- A detection that arrives while the cloud says disarmed is dropped and counted (D8); recognition
  never suppresses or softens an armed alert (a VIP, a family member at the gate still rings).
- A face lookup that fails counts as "not recognised" (`safe_resolve`). A detection whose alert
  could not be delivered (the notifier failed, or it said ring and no channel took it), or that
  failed for any other reason, is RAISED (`AlertNotSent` or the error): the webhook answers 503,
  gives the event id back and the bridge retries it.
- A heartbeat whose camera part says it is not receiving Frigate's events (`mqtt: false`) while
  armed raises one `home_arm_failed` alert per outage.
- If the arm record can't be read the alert goes out (a missed burglar is worse than a false one).
- Frigate's labels and zone ids are untrusted text: they have already passed the wire models
  (`jarvis.home.ports`), and the alert text uses only the owner's camera labels and fixed words.
- A child is never named in an alert; an adult only in `named_message`, which the notifier uses
  only when the owner switched names in alerts on. A snapshot goes to the notifier only after the
  owner's opt-in and is never stored (not in the feed, not in a log).
- No model call, no picture stored, nothing logged but ids and counts.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from jarvis.camera.alarm import Alarm
from jarvis.camera.config import CameraConfigService
from jarvis.camera.feed import Feed, camera_words
from jarvis.camera.models import CameraSettings, FeedItem, first_upper
from jarvis.camera.packages import Packages
from jarvis.camera.ports import NoSnapshots, SnapshotPolicy, safe_resolve
from jarvis.faces.directory import alert_words
from jarvis.faces.ports import FaceDirectory, Resolved
from jarvis.home.ports import (
    Ack,
    Detection,
    FaceSeen,
    Hazard,
    Heartbeat,
    HeartbeatParts,
    Package,
)
from jarvis.logging import get_logger
from jarvis.notify.ports import Delivery, Notifier, Signal

log = get_logger(__name__)

GREETING_EVERY_S = 1800.0  # D10: one greeting line per person per 30 minutes
ARM_ACK_PREFIX = "arm:"  # the bridge's arm ack carries this id prefix, so no other rev can confirm
NOTIFY_TRIES = 2


CAMERA_LINK_DOWN = (
    "Your home laptop is on, but it isn't getting the camera's events, so burglar alerts can't "
    "reach you. Check JARVIS Home on the laptop."
)


class AlertNotSent(RuntimeError):
    """A burglar alert could not be delivered. Raised out of `handle` so the webhook answers 503,
    gives the event id back and the bridge's retry (same id) tries again."""


Event = Heartbeat | Detection | FaceSeen | Package | Hazard | Ack


def unheard(delivery: Delivery) -> bool:
    """The policy let it out (ring or silent), but neither Telegram nor a browser took it."""
    return delivery.action in ("ring", "silent") and not (delivery.telegram or delivery.push)


def who_phrase(resolved: Resolved) -> str:
    """Who, for an alert that names nobody: C's `alert_words` with names off (I1: one rule for
    every channel; a child is never named, an adult's name goes only in `named_message`)."""
    return alert_words(resolved, say_names=False)


def intruder_text(place: str, when: str, who: str) -> str:
    return f"Burglar alert at {place} at {when}: {who}. Open Frigate on your laptop to see."


class CameraEvents:
    handles = frozenset({"heartbeat", "detection", "face_seen", "package", "ack"})

    def __init__(
        self,
        *,
        alarm: Alarm,
        config: CameraConfigService,
        feed: Feed,
        notifier: Notifier,
        faces: FaceDirectory,
        snapshots: SnapshotPolicy | None = None,
        packages: Packages | None = None,
        tz: str,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._alarm = alarm
        self._config = config
        self._feed = feed
        self._notifier = notifier
        self._faces = faces
        self._snapshots: SnapshotPolicy = snapshots or NoSnapshots()
        self._packages = packages or Packages(config)
        self._tz = ZoneInfo(tz)
        self._clock = clock
        self._greeted: dict[tuple[str, str], float] = {}
        self._link_down: set[str] = set()  # owners already told their camera link is down

    # ---- dispatch ----------------------------------------------------------------------------

    async def handle(self, uid: str, event: Event) -> None:
        try:
            if isinstance(event, Detection):
                await self._detection_or_retry(uid, event)
            elif isinstance(event, FaceSeen):
                await self._face_seen(uid, event)
            elif isinstance(event, Package):
                await self._package(uid, event)
            elif isinstance(event, Heartbeat):
                await self._camera_link(uid, event.parts)
                await self._config.record_heartbeat(uid, event.parts)
            elif isinstance(event, Ack):
                await self._ack(uid, event)
        except Exception as exc:  # noqa: BLE001 - one bad event never breaks the webhook
            if isinstance(event, Detection):
                raise  # ...except a detection: the bridge must retry it
            log.warning(
                "camera event failed",
                extra={"type": getattr(event, "type", "?"), "reason": type(exc).__name__},
            )

    async def _detection_or_retry(self, uid: str, ev: Detection) -> None:
        """A detection that can't be turned into an alert is raised, never swallowed: the bridge
        retries it (same id) instead of believing it was handled."""
        try:
            await self._detection(uid, ev)
        except AlertNotSent:
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("detection failed; asking for a retry", extra={"reason": type(exc).__name__})
            raise

    async def _ack(self, uid: str, ev: Ack) -> None:
        if ev.what == "state" and ev.rev is not None and ev.id.startswith(ARM_ACK_PREFIX):
            await self._alarm.ack(uid, ev.rev)

    async def _camera_link(self, uid: str, parts: HeartbeatParts) -> None:
        """Integrated review S1: the bridge says it is not receiving Frigate's events (its MQTT
        link is down, or the camera part never started) while the alarm is armed, so burglar
        alerts can't arrive. One alert per outage (a working link ends it); one that no channel
        took is tried again at the next heartbeat."""
        if parts.mqtt is None:
            return
        if parts.mqtt:
            self._link_down.discard(uid)
            return
        if uid in self._link_down or not await self._armed(uid):
            return
        signal = Signal(source="home", kind="home_arm_failed")
        delivery = await self._notify(uid, signal, CAMERA_LINK_DOWN)
        if delivery is not None and not unheard(delivery):
            self._link_down.add(uid)

    # ---- helpers -----------------------------------------------------------------------------

    async def _armed(self, uid: str) -> bool:
        """The cloud's arm state; unreadable counts as armed (the safe direction for an alarm)."""
        try:
            return (await self._alarm.record(uid)).armed
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "arm state unreadable; treating as armed", extra={"reason": type(exc).__name__}
            )
            return True

    async def _settings(self, uid: str) -> CameraSettings | None:
        try:
            return await self._config.get(uid)
        except Exception as exc:  # noqa: BLE001
            log.warning("camera settings unreadable", extra={"reason": type(exc).__name__})
            return None

    async def _who(self, uid: str, person: str | None, score: float | None) -> Resolved:
        return await safe_resolve(self._faces, uid, person, score)

    def _when(self, epoch: float) -> str:
        return datetime.fromtimestamp(epoch, UTC).astimezone(self._tz).strftime("%H:%M")

    @staticmethod
    def _place(settings: CameraSettings | None, camera: str) -> str:
        cfg = settings.cameras.get(camera) if settings else None
        return camera_words(cfg.label if cfg else None, camera)

    async def _notify(
        self,
        uid: str,
        signal: Signal,
        message: str,
        *,
        named: str | None = None,
        photo: bytes | None = None,
        must: bool = False,
    ) -> Delivery | None:
        for attempt in range(NOTIFY_TRIES):
            try:
                delivery = await self._notifier.notify(
                    uid, signal, message, named_message=named, photo=photo
                )
            except Exception as exc:  # noqa: BLE001 - try once more, then give up loudly
                log.error(
                    "alert not sent",
                    extra={"kind": signal.kind, "try": attempt + 1, "reason": type(exc).__name__},
                )
                continue
            if must and delivery.action == "ring" and unheard(delivery):
                # integrated review S3: the policy said ring but no channel took it (Telegram
                # down, no browser): raised, so the webhook answers 503 and the bridge retries
                log.error("alert reached no channel", extra={"kind": signal.kind})
                raise AlertNotSent("alert reached no channel")
            return delivery
        if must:
            raise AlertNotSent("alert not sent")
        return None

    async def _record(self, uid: str, item: FeedItem) -> None:
        try:
            await self._feed.add(uid, item)
        except Exception as exc:  # noqa: BLE001 - the feed never blocks or undoes an alert
            log.warning("feed line not saved", extra={"reason": type(exc).__name__})

    async def _touch(self, uid: str, camera: str, at: float) -> None:
        try:
            await self._config.touch_event(uid, camera, at)
        except Exception as exc:  # noqa: BLE001
            log.warning("last event not saved", extra={"reason": type(exc).__name__})

    @staticmethod
    def _sent(item: FeedItem, delivery: Delivery | None) -> FeedItem:
        if delivery is None:
            return item
        return item.model_copy(
            update={
                "decision": delivery.feed_decision,
                "telegram": delivery.telegram,
                "push": delivery.push,
                "photo_sent": delivery.photo_sent,
            }
        )

    # ---- detections --------------------------------------------------------------------------

    async def _detection(self, uid: str, ev: Detection) -> None:
        if not await self._armed(uid):
            await self._drop_disarmed(uid)
            return
        settings = await self._settings(uid)
        if settings is not None:
            cfg = settings.cameras.get(ev.camera)
            if cfg is None or not set(cfg.alarm_zones) & set(ev.zones):
                log.info("detection outside the alarm zones", extra={"camera": ev.camera})
                return
        zone = ev.zones[0] if ev.zones else None
        base = FeedItem(
            at=ev.start,
            kind="other",
            camera=ev.camera,
            zone=zone,
            label=ev.label,
            decision="dropped",
        )
        if ev.label != "person":
            await self._record(uid, base)
            await self._touch(uid, ev.camera, ev.start)
            return
        resolved = await self._who(uid, ev.face.person, ev.face.score) if ev.face else Resolved()
        place = self._place(settings, ev.camera)
        when = self._when(ev.start)
        text = intruder_text(place, when, who_phrase(resolved))
        named = (
            intruder_text(place, when, f"{resolved.name} (face matched)")
            if resolved.named and not resolved.child
            else None
        )
        photo = await self._photo(uid, ev)
        signal = Signal(
            source="home",
            kind="home_intruder",
            person_ref=resolved.person,
            vip=resolved.vip,
            child=resolved.child,
            camera=ev.camera,
        )
        try:
            delivery = await self._notify(uid, signal, text, named=named, photo=photo, must=True)
        except AlertNotSent:
            await self._record(
                uid, base.model_copy(update={"kind": "intruder", "decision": "failed"})
            )
            raise
        item = base.model_copy(
            update={
                "kind": "intruder",
                "person": ev.face.person if ev.face else None,
                "score": ev.face.score if ev.face else None,
            }
        )
        await self._record(uid, self._sent(item, delivery))
        await self._touch(uid, ev.camera, ev.start)

    async def _photo(self, uid: str, ev: Detection) -> bytes | None:
        """The opted-in snapshot, in memory only; None without the opt-in or on any trouble."""
        if ev.snapshot is None:
            return None
        try:
            if not await self._snapshots.snapshot_on(uid):
                return None
            return ev.snapshot_bytes()
        except Exception as exc:  # noqa: BLE001
            log.warning("snapshot dropped", extra={"reason": type(exc).__name__})
            return None

    async def _drop_disarmed(self, uid: str) -> None:
        try:
            await self._alarm.count_dropped(uid)
        except Exception as exc:  # noqa: BLE001
            log.warning("dropped detection not counted", extra={"reason": type(exc).__name__})

    # ---- faces and packages ------------------------------------------------------------------

    async def _face_seen(self, uid: str, ev: FaceSeen) -> None:
        resolved = await self._who(uid, ev.face.person, ev.face.score)
        if not resolved.named:
            return  # strangers while disarmed produce nothing (D1)
        armed = await self._armed(uid)
        settings = await self._settings(uid)
        if not armed and settings is not None and not settings.greetings:
            return
        key = (uid, ev.face.person)
        last = self._greeted.get(key)
        if last is not None and ev.at - last < GREETING_EVERY_S:
            return
        self._greeted[key] = ev.at
        item = FeedItem(
            at=ev.at,
            kind="greeting",
            camera=ev.camera,
            zone=ev.zones[0] if ev.zones else None,
            person=ev.face.person,
            score=ev.face.score,
            decision="silent",
        )
        delivery: Delivery | None = None
        if not armed:
            place = self._place(settings, ev.camera)
            plain = first_upper(who_phrase(resolved)) + f" arrived at {place}."
            named = None if resolved.child else f"{resolved.name} arrived at {place}."
            signal = Signal(
                source="home",
                kind="home_greeting",
                person_ref=resolved.person,
                vip=resolved.vip,
                child=resolved.child,
                camera=ev.camera,
            )
            delivery = await self._notify(uid, signal, plain, named=named)
        await self._record(uid, self._sent(item, delivery))

    async def _package(self, uid: str, ev: Package) -> None:
        change = await self._packages.on_state(uid, ev)
        if not change.alert:
            return
        settings = await self._settings(uid)
        place = self._place(settings, ev.camera)
        text = f"A package was left at {place}, {self._when(ev.at)}."
        signal = Signal(source="home", kind="home_package", camera=ev.camera)
        delivery = await self._notify(uid, signal, text)
        item = FeedItem(
            at=ev.at,
            kind="package",
            camera=ev.camera,
            zone=ev.zone,
            delivered=change.delivered,
            decision="silent",
        )
        await self._record(uid, self._sent(item, delivery))


__all__ = [
    "ARM_ACK_PREFIX",
    "CAMERA_LINK_DOWN",
    "GREETING_EVERY_S",
    "AlertNotSent",
    "CameraEvents",
    "intruder_text",
    "unheard",
    "who_phrase",
]

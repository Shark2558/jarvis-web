# src/jarvis/homebridge/camera.py
"""The bridge's camera plugin (R3 workstream B): Frigate -> detections, packages, history.

Registered by I1 in `homebridge/registry.py` (`PLUGINS = (core, camera_plugin, faces_plugin)`).

- MQTT: `frigate/events` -> `Detections.filter` -> optional small snapshot -> signed `Detection`;
  `frigate/tracked_object_update` (type face) -> `FaceSeen` for a consented id only;
  `frigate/<camera>/classification/doorstep` -> `Package` on a change.
- Routes (the signature is checked by the bridge app first): `GET /bridge/v1/events` (history from
  Frigate's event list, thumbnails never requested, only the vocabulary fields forwarded) and
  `GET /bridge/v1/packages` (the 7-day doorstep log).
- `apply_state`: takes the cloud's arm, camera settings and consented ids; an arm part at or above
  the local rev is acked with an `arm:<rev>:<nonce>` event id, which is the only ack the cloud
  counts as the alarm being confirmed.
- Heartbeat part: Frigate up, cameras producing frames, the doorstep model configured.

Bridge-kit module: standard library, pydantic, httpx, aiomqtt and `jarvis.home` /
`jarvis.homebridge` only.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import secrets
from collections.abc import Mapping, Sequence
from typing import Any

from jarvis.home.ports import (
    LABEL_ID,
    LABELS,
    MAX_CAMERAS,
    PERSON_ID,
    Ack,
    BridgeState,
    CameraPart,
    Detection,
    FaceMatch,
    FaceSeen,
    HeartbeatParts,
    HomeRefused,
    is_home_id,
)
from jarvis.homebridge.arm import ArmState
from jarvis.homebridge.detections import RECOGNITION_THRESHOLD, Detections, face_of
from jarvis.homebridge.frigate import DEFAULT_URL, FrigateClient
from jarvis.homebridge.mqtt import Connect, MqttConfig, MqttEvents, real_connect
from jarvis.homebridge.packages_log import PackagesLog, state_of
from jarvis.homebridge.plugins import BridgeContext, BridgeRoute, TaskFactory
from jarvis.homebridge.snapshot import small

log = logging.getLogger(__name__)

MAX_INFLIGHT = 32  # detections being sent at once; the rest wait for Frigate's next update
SNAPSHOT_WAIT_S = 2.0  # a photo never holds a burglar alert back for longer than this
MAX_QUERY_SPAN_S = 32 * 86400
FETCH_MAX = 100
CLASSIFICATION = re.compile(r"^frigate/([a-z0-9_]{1,24})/classification/doorstep$")
EVENT_ID = re.compile(r"^[A-Za-z0-9._:-]{1,50}$")


def _bad(words: str) -> HomeRefused:
    return HomeRefused("bad_query", words)


class CameraPlugin:
    name = "camera"

    def __init__(
        self,
        ctx: BridgeContext,
        *,
        frigate: FrigateClient | None = None,
        connect: Connect | None = None,
    ) -> None:
        self._ctx = ctx
        self.arm = ArmState(ctx.data_dir / "camera_state.json")
        self.detections = Detections(self.arm, self.face)
        self.packages = PackagesLog(ctx.data_dir / "packages.jsonl", ctx.now)
        self.frigate = frigate or FrigateClient(ctx.env.get("FRIGATE_URL") or DEFAULT_URL)
        cfg = MqttConfig.from_env(ctx.env)
        if not cfg.has_credentials:
            log.error("MQTT_USER / MQTT_PASSWORD are empty: the bridge will not connect to MQTT")
        self.mqtt = MqttEvents(connect or real_connect(cfg), self.on_message)
        self._faces_seen: set[str] = set()
        self._tasks: set[asyncio.Task[None]] = set()

    def face(self, sub_label: Any, label: object = "person") -> FaceMatch | None:
        """Frigate's face result -> a `FaceMatch`, or None (I1). C's face library decides when the
        faces plugin runs (a person being deleted stays unmatched until the laptop removed their
        pictures); without it, the consented ids the cloud synced to this plugin."""
        library = getattr(self._ctx.peers.get("faces"), "library", None)
        if library is None:
            return face_of(sub_label, self.arm.faces) if label == "person" else None
        if not (isinstance(sub_label, list | tuple) and len(sub_label) == 2):
            return None
        match = library.match(sub_label[0], sub_label[1], label)
        return match if isinstance(match, FaceMatch) else None

    # ---- plugin surface ----------------------------------------------------------------------

    def routes(self) -> Sequence[BridgeRoute]:
        return (
            BridgeRoute("GET", "/bridge/v1/events", self._events),
            BridgeRoute("GET", "/bridge/v1/packages", self._packages),
        )

    def tasks(self) -> Sequence[TaskFactory]:
        return (self.mqtt.run,)

    async def heartbeat_part(self) -> HeartbeatParts:
        up, online = await self.frigate.stats()
        cams = tuple(CameraPart(id=c, online=ok) for c, ok in list(online.items())[:MAX_CAMERAS])
        model = await self.frigate.has_doorstep_model() if up else None
        return HeartbeatParts(frigate=up, cameras=cams if up else None, doorstep_model=model)

    async def apply_state(self, state: BridgeState) -> None:
        home = self._home_id()
        if home is not None:
            self.arm.bind(home)
        rev = self.arm.apply(state)
        if rev is not None:
            ack = Ack(
                type="ack",
                id=f"arm:{rev}:{secrets.token_hex(3)}",
                at=float(self._ctx.now()),
                what="state",
                rev=rev,
            )
            await self._ctx.events.post_event(ack)

    def _home_id(self) -> str | None:
        """The home id of the current link (the bridge's own secret file); None when unreadable."""
        try:
            raw = json.loads((self._ctx.data_dir / "secret.json").read_text(encoding="utf-8"))
            home = raw.get("home_id") if isinstance(raw, dict) else None
        except (OSError, ValueError):
            return None
        return home if isinstance(home, str) and is_home_id(home) else None

    # ---- MQTT --------------------------------------------------------------------------------

    async def on_message(self, topic: str, payload: bytes) -> None:
        if topic == "frigate/events":
            await self._on_event(payload)
        elif topic == "frigate/tracked_object_update":
            await self._on_face(payload)
        elif (m := CLASSIFICATION.fullmatch(topic)) is not None:
            await self._on_package(m.group(1), payload)

    async def _on_event(self, payload: bytes) -> None:
        det = self.detections.filter(payload)
        if det is None:
            return
        if len(self._tasks) >= MAX_INFLIGHT:
            log.warning("too many detections in flight; this one is retried on its next update")
            self.detections.release(det.id.removeprefix("det:"))
            return
        task = asyncio.create_task(self._deliver(det))  # never awaited here: the MQTT loop goes on
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _deliver(self, det: Detection) -> None:
        ok = False
        try:
            settings = self.arm.settings
            if settings is not None and settings.snapshot and det.label == "person":
                det = await self._with_snapshot(det)
            ok = await self._ctx.events.post_event(det)
        except Exception as exc:  # noqa: BLE001 - a failed send is retried on the next update
            log.warning("detection not posted", extra={"reason": type(exc).__name__})
        if not ok:
            self.detections.release(det.id.removeprefix("det:"))

    async def drain(self) -> None:
        """Wait for the detections in flight (tests, shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def cancel(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await self.drain()

    async def _with_snapshot(self, det: Detection) -> Detection:
        frigate_id = det.id.removeprefix("det:")
        try:
            raw = await asyncio.wait_for(self.frigate.snapshot(frigate_id), SNAPSHOT_WAIT_S)
        except (TimeoutError, OSError):
            return det
        jpeg = None if raw is None else small(raw)
        if jpeg is None:
            return det
        return det.model_copy(update={"snapshot": base64.b64encode(jpeg).decode("ascii")})

    async def _on_face(self, payload: bytes) -> None:
        try:
            obj = json.loads(payload)
        except ValueError:
            return
        if not isinstance(obj, dict) or obj.get("type") != "face":
            return
        name, score = obj.get("name"), obj.get("score")
        event, camera = obj.get("id"), obj.get("camera")
        if not (isinstance(event, str) and EVENT_ID.fullmatch(event)):
            return
        if not (isinstance(camera, str) and re.fullmatch(LABEL_ID, camera)):
            return
        match = self.face([name, score])
        settings = self.arm.settings
        if match is None or settings is None or camera not in settings.cameras:
            return
        if not (self.arm.armed or settings.greetings):
            return
        key = f"{event}:{match.person}"
        if key in self._faces_seen:
            return
        self._faces_seen = {*list(self._faces_seen)[-200:], key}
        stamp = obj.get("timestamp")
        at = (
            float(stamp)
            if isinstance(stamp, int | float) and not isinstance(stamp, bool)
            else self._ctx.now()
        )
        await self._ctx.events.post_event(
            FaceSeen(
                type="face_seen",
                id=f"face:{event}"[:64],
                event=event,
                camera=camera,
                zones=(),
                at=at,
                face=FaceMatch(person=match.person, score=match.score),
            )
        )

    async def _on_package(self, camera: str, payload: bytes) -> None:
        settings = self.arm.settings
        if settings is None or not settings.packages:
            return
        cam = settings.cameras.get(camera)
        state = state_of(payload)
        if cam is None or cam.package_zone is None or state is None:
            return
        now = float(self._ctx.now())
        delivered = self.detections.person_seen_recently(camera, cam.package_zone, now)
        event = self.packages.on_state(camera, cam.package_zone, state, delivered=delivered, at=now)
        if event is not None:
            await self._ctx.events.post_event(event)

    # ---- routes ------------------------------------------------------------------------------

    @staticmethod
    def _csv(value: str | None, ok: Any, what: str) -> list[str]:
        items = [x for x in (value or "").split(",") if x]
        if len(items) > 8 or not all(ok(x) for x in items):
            raise _bad(f"That {what} isn't one the camera knows.")
        return items

    @staticmethod
    def _int(value: str | None, name: str, default: int | None = None) -> int:
        if value is None and default is not None:
            return default
        if value is None or not re.fullmatch(r"\d{1,12}", value):
            raise _bad(f"{name} has to be a number.")
        return int(value)

    def _window(self, query: Mapping[str, str]) -> tuple[int, int, int]:
        after, before = (
            self._int(query.get("after"), "after"),
            self._int(query.get("before"), "before"),
        )
        limit = self._int(query.get("limit"), "limit", FETCH_MAX)
        if before < after or before - after > MAX_QUERY_SPAN_S or not 1 <= limit <= FETCH_MAX:
            raise _bad("That time range or limit isn't allowed.")
        return after, before, limit

    async def _events(
        self, query: Mapping[str, str], body: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        after, before, limit = self._window(query)
        labels = self._csv(query.get("labels"), lambda x: x in LABELS, "kind of thing") or list(
            LABELS
        )
        cams = self._csv(query.get("cameras"), lambda x: re.fullmatch(LABEL_ID, x), "camera")
        zones = self._csv(query.get("zones"), lambda x: re.fullmatch(LABEL_ID, x), "zone")
        person = query.get("person")
        if person is not None and not re.fullmatch(PERSON_ID, person):
            raise _bad("That isn't a person JARVIS recognises.")
        rows = await self.frigate.events(
            labels=",".join(labels),
            cameras=",".join(cams) or None,
            zones=",".join(zones) or None,
            after=after,
            before=before,
            limit=limit,
        )
        out = []
        for row in rows:
            item = self._event_row(row)
            if item is None or (person is not None and item.get("person") != person):
                continue
            out.append(item)
        return {"events": out, "more": len(rows) >= limit}

    def _event_row(self, row: Mapping[str, Any]) -> dict[str, Any] | None:
        """Only the vocabulary fields of one Frigate event; no thumbnail, box or free text."""
        ident, cam, label = row.get("id"), row.get("camera"), row.get("label")
        start, end = row.get("start_time"), row.get("end_time")
        if not (isinstance(ident, str) and EVENT_ID.fullmatch(ident)):
            return None
        if not (isinstance(cam, str) and re.fullmatch(LABEL_ID, cam) and label in LABELS):
            return None
        if isinstance(start, bool) or not isinstance(start, int | float):
            return None
        zones = [
            z for z in row.get("zones", []) if isinstance(z, str) and re.fullmatch(LABEL_ID, z)
        ]
        item: dict[str, Any] = {
            "id": ident,
            "camera": cam,
            "zones": zones[:8],
            "label": label,
            "start": float(start),
        }
        if isinstance(end, int | float) and not isinstance(end, bool) and end >= start:
            item["end"] = float(end)
        match = self.face(row.get("sub_label"), label)
        if match is not None and match.score >= RECOGNITION_THRESHOLD:
            item["person"], item["score"] = match.person, match.score
        return item

    async def _packages(
        self, query: Mapping[str, str], body: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        after, before, limit = self._window(query)
        cams = self._csv(query.get("cameras"), lambda x: re.fullmatch(LABEL_ID, x), "camera")
        rows, more = self.packages.query(after, before, cams[0] if cams else None, limit)
        return {"changes": rows, "more": more}


def camera_plugin(ctx: BridgeContext) -> CameraPlugin:
    """The `PluginFactory` I1 puts in `homebridge/registry.PLUGINS`."""
    return CameraPlugin(ctx)


__all__ = ["CameraPlugin", "camera_plugin"]

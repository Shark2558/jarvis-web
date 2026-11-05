# src/jarvis/home/ports.py
"""The home wire and the cloud's home ports (R3 D1, D5, D6, D8; Layer 6 IoT).

Shared by the cloud and the home bridge (it ships in the home kit), so it imports only the
standard library and pydantic.

- The vocabulary (D1): camera and zone ids `[a-z0-9_]{1,24}`, labels from a fixed list, person ids
  `fp_<12 hex>` (never a name), times as UTC epoch seconds, scores 0..1 rounded to 2 places. Never
  coordinates, thumbnails, crops, clips, audio or Home Assistant attributes.
- `HomeEvent`: what the bridge may send up (heartbeat | detection | face_seen | package | hazard |
  ack), one per signed webhook, every model `extra="forbid"` with strict scalars. `parse_event`
  is the only parser, called AFTER the signature check (`jarvis.home.signing`): over 128 KB, or
  over 16 KB without an opted-in snapshot (D12), is `too_large`; anything else wrong is
  `invalid`. Neither error carries the input.
- `BridgeState`: what the cloud tells the bridge (D8): the arm state, the consented people, the
  exposed devices and the camera settings, each part with its own `rev`; a missing part means
  "unchanged".
- Cloud ports: `HomeEventHandler` (webhook dispatch by event type; several handlers may take one
  type), `HomeCaller` (cloud -> bridge calls, `HomeOffline` / `HomeRefused`), `ArmReader` and
  `StateSource` (parts of the bridge state other workstreams own).
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Mapping
from typing import Annotated, Any, Literal, Protocol, get_args, runtime_checkable

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_validator,
)

HOME_ID = r"^h_[0-9a-f]{8}$"
LABEL_ID = r"^[a-z0-9_]{1,24}$"  # camera and zone ids the owner types
PERSON_ID = r"^fp_[0-9a-f]{12}$"
EVENT_ID = r"^[A-Za-z0-9._:-]{1,64}$"
ENTITY_ID = r"^[a-z_]{1,32}\.[a-z0-9_]{1,64}$"
VERSION_RE = r"^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$"
B64_STD = r"^[A-Za-z0-9+/]+={0,2}$"

MAX_EPOCH = 4_102_444_800.0  # 2100-01-01
MAX_REV = 10**12
MAX_CAMERAS = 8
MAX_ZONES = 8
MAX_PEOPLE = 30  # D13
MAX_EXPOSED = 50  # D6
MAX_PICTURES = 200
MAX_EVENT_BYTES = 16 * 1024  # D5: any event without an opted-in snapshot
MAX_WEBHOOK_BYTES = 128 * 1024  # D5: the route's cap
MAX_SNAPSHOT_BYTES = 80 * 1024  # D12: one JPEG, <= 640 px on the long side
SNAPSHOT_B64_CHARS = 4 * -(-MAX_SNAPSHOT_BYTES // 3)
JPEG_MAGIC = b"\xff\xd8\xff"

WEBHOOK_PATH = "/home/webhook"
LINK_PATH = "/home/link"
BridgeMethod = Literal["GET", "POST"]
# D6: the bridge's signed API. Everything else is 404 at home and refused by the cloud's client.
BRIDGE_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/bridge/v1/health"),
        ("POST", "/bridge/v1/state"),
        ("GET", "/bridge/v1/devices"),
        ("POST", "/bridge/v1/devices/action"),
        ("GET", "/bridge/v1/events"),
        ("GET", "/bridge/v1/packages"),
        ("GET", "/bridge/v1/faces/summary"),
    }
)

Label = Literal["person", "car", "motorcycle", "bicycle", "dog", "cat"]
LABELS: tuple[str, ...] = get_args(Label)
HazardClass = Literal["smoke", "carbon_monoxide", "gas", "moisture", "safety"]
ArmMode = Literal["away", "night"]
DeviceTier = Literal["read", "everyday", "passkey", "always_passkey"]
# D6 "Never exposed": no tier makes these reachable, at either end.
NEVER_EXPOSED_DOMAINS = frozenset(
    {
        "script",
        "automation",
        "shell_command",
        "rest_command",
        "homeassistant",
        "hassio",
        "notify",
        "camera",
    }
)
EVENT_TYPES = ("heartbeat", "detection", "face_seen", "package", "hazard", "ack")


def _round2(v: float) -> float:
    return round(v, 2)


HomeId = Annotated[StrictStr, StringConstraints(pattern=HOME_ID)]
CameraId = Annotated[StrictStr, StringConstraints(pattern=LABEL_ID)]
ZoneId = Annotated[StrictStr, StringConstraints(pattern=LABEL_ID)]
PersonId = Annotated[StrictStr, StringConstraints(pattern=PERSON_ID)]
EventId = Annotated[StrictStr, StringConstraints(pattern=EVENT_ID)]
EntityId = Annotated[StrictStr, StringConstraints(pattern=ENTITY_ID)]
Version = Annotated[StrictStr, StringConstraints(pattern=VERSION_RE)]
Epoch = Annotated[StrictFloat, Field(ge=0, le=MAX_EPOCH, allow_inf_nan=False)]
Score = Annotated[StrictFloat, Field(ge=0, le=1, allow_inf_nan=False), AfterValidator(_round2)]
Rev = Annotated[StrictInt, Field(ge=0, le=MAX_REV)]
PictureCount = Annotated[StrictInt, Field(ge=0, le=MAX_PICTURES)]


def is_home_id(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(HOME_ID, value) is not None


def route_allowed(method: str, path: str) -> bool:
    return (method, path) in BRIDGE_ROUTES


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---- home -> cloud events ----------------------------------------------------------------------


class FaceMatch(_Wire):
    """Frigate's recognition of an enrolled face: the person's id, never a name (D13)."""

    person: PersonId
    score: Score


class CameraPart(_Wire):
    id: CameraId
    online: StrictBool


class HeartbeatParts(_Wire):
    """What each part of the bridge reports in a heartbeat; None = that part didn't say."""

    ha: StrictBool | None = None  # A: Home Assistant answers with the token
    frigate: StrictBool | None = None  # A / B: Frigate answers
    cameras: tuple[CameraPart, ...] | None = Field(default=None, max_length=MAX_CAMERAS)
    doorstep_model: StrictBool | None = None  # B (D16): the doorstep state model exists
    faces: dict[PersonId, PictureCount] | None = Field(default=None, max_length=MAX_PEOPLE)  # C

    def merged(self, other: HeartbeatParts) -> HeartbeatParts:
        """These parts with every part `other` reported laid over them."""
        said = {k: getattr(other, k) for k in type(other).model_fields}
        return self.model_copy(update={k: v for k, v in said.items() if v is not None})


class _Event(_Wire):
    id: EventId


class Heartbeat(_Event):
    type: Literal["heartbeat"]
    at: Epoch
    bridge_version: Version
    state_rev: Rev  # the newest BridgeState rev the bridge applied (arm acks ride on it too)
    parts: HeartbeatParts = HeartbeatParts()


def _jpeg(text: str) -> bytes:
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("snapshot is not base64") from None
    if len(raw) > MAX_SNAPSHOT_BYTES or not raw.startswith(JPEG_MAGIC):
        raise ValueError("snapshot must be one small JPEG")
    return raw


class Detection(_Event):
    """A tracked object Frigate confirmed in a camera's zones (D7). While disarmed the bridge
    sends no person detections at all (D1, D8)."""

    type: Literal["detection"]
    camera: CameraId
    zones: tuple[ZoneId, ...] = Field(default=(), max_length=MAX_ZONES)
    label: Label
    start: Epoch
    end: Epoch | None = None
    score: Score
    face: FaceMatch | None = None
    # D12: base64 of one JPEG <= 80 KB, only for a person while armed and only after the owner
    # opted in. Passed through in memory; never stored, logged or audited.
    snapshot: str | None = Field(
        default=None, min_length=4, max_length=SNAPSHOT_B64_CHARS, pattern=B64_STD
    )

    @model_validator(mode="after")
    def _check(self) -> Detection:
        if self.end is not None and self.end < self.start:
            raise ValueError("an event can't end before it starts")
        if self.snapshot is not None:
            if self.label != "person":
                raise ValueError("a snapshot only comes with a person")
            _jpeg(self.snapshot)
        return self

    def snapshot_bytes(self) -> bytes | None:
        return None if self.snapshot is None else _jpeg(self.snapshot)


class FaceSeen(_Event):
    """A consented, enrolled person recognised (D13): greetings while disarmed, the face line
    while armed. Only for ids the cloud synced as consented, scored at Frigate's threshold."""

    type: Literal["face_seen"]
    event: EventId  # the Frigate event it belongs to
    camera: CameraId
    zones: tuple[ZoneId, ...] = Field(default=(), max_length=MAX_ZONES)
    at: Epoch
    face: FaceMatch


class Package(_Event):
    """A doorstep state change (D16)."""

    type: Literal["package"]
    camera: CameraId
    zone: ZoneId
    state: Literal["package", "empty"]
    at: Epoch
    delivered: StrictBool = False  # a person was in the zone in the 2 minutes before


class Hazard(_Event):
    """An exposed hazard sensor changed (D6)."""

    type: Literal["hazard"]
    entity: EntityId
    device_class: HazardClass
    state: Literal["on", "off"]
    at: Epoch


class Ack(_Event):
    """The bridge applied a state rev, or deleted a person's pictures (D13)."""

    type: Literal["ack"]
    at: Epoch
    what: Literal["state", "face_deleted"]
    rev: Rev | None = None
    person: PersonId | None = None

    @model_validator(mode="after")
    def _check(self) -> Ack:
        if self.what == "state" and (self.rev is None or self.person is not None):
            raise ValueError("a state ack names a rev")
        if self.what == "face_deleted" and self.person is None:
            raise ValueError("a delete ack names the person")
        return self


HomeEvent = Annotated[
    Heartbeat | Detection | FaceSeen | Package | Hazard | Ack, Field(discriminator="type")
]
_EVENTS: TypeAdapter[Any] = TypeAdapter(HomeEvent)


class EventRejected(ValueError):
    """`code` is "too_large" (413) or "invalid" (422); the message is the code, never the input."""

    def __init__(self, code: Literal["too_large", "invalid"]) -> None:
        super().__init__(code)
        self.code = code


def parse_event(raw: bytes) -> Heartbeat | Detection | FaceSeen | Package | Hazard | Ack:
    """The one parser for a webhook body, called only after its signature verified."""
    if len(raw) > MAX_WEBHOOK_BYTES:
        raise EventRejected("too_large")
    try:
        event = _EVENTS.validate_json(raw)
    except ValidationError:
        raise EventRejected("invalid") from None
    snap = len(event.snapshot) if isinstance(event, Detection) and event.snapshot else 0
    if len(raw) - snap > MAX_EVENT_BYTES:
        raise EventRejected("too_large")
    return event  # type: ignore[no-any-return]


# ---- cloud -> home state -----------------------------------------------------------------------


class ArmState(_Wire):
    armed: StrictBool
    mode: ArmMode = "away"
    rev: Rev


class FacesState(_Wire):
    rev: Rev
    people: tuple[PersonId, ...] = Field(default=(), max_length=MAX_PEOPLE)  # consented ids
    deleting: tuple[PersonId, ...] = Field(default=(), max_length=MAX_PEOPLE)


class ExposedDevice(_Wire):
    entity_id: EntityId
    tier: DeviceTier

    @model_validator(mode="after")
    def _check(self) -> ExposedDevice:
        if self.entity_id.split(".", 1)[0] in NEVER_EXPOSED_DOMAINS:
            raise ValueError("that kind of entity is never exposed")
        return self


class DevicesState(_Wire):
    rev: Rev
    exposed: tuple[ExposedDevice, ...] = Field(default=(), max_length=MAX_EXPOSED)


class CameraSetting(_Wire):
    alarm_zones: tuple[ZoneId, ...] = Field(default=(), max_length=MAX_ZONES)
    package_zone: ZoneId | None = None


class SettingsState(_Wire):
    rev: Rev
    cameras: dict[CameraId, CameraSetting] = Field(default_factory=dict, max_length=MAX_CAMERAS)
    retention_days: Annotated[StrictInt, Field(ge=1, le=30)] = 7  # D7
    greetings: StrictBool = False  # face_seen while disarmed (the cloud sends its setting)
    packages: StrictBool = False  # package events (D16)
    snapshot: StrictBool = False  # D12: off unless the owner opted in
    heartbeat_s: Annotated[StrictInt, Field(ge=60, le=600)] = 120


class BridgeState(_Wire):
    arm: ArmState | None = None
    faces: FacesState | None = None
    devices: DevicesState | None = None
    settings: SettingsState | None = None

    def merged(self, other: BridgeState) -> BridgeState:
        """This state with every part `other` carries laid over it."""
        return BridgeState(
            arm=other.arm if other.arm is not None else self.arm,
            faces=other.faces if other.faces is not None else self.faces,
            devices=other.devices if other.devices is not None else self.devices,
            settings=other.settings if other.settings is not None else self.settings,
        )


# ---- cloud ports -------------------------------------------------------------------------------

HOME_OFFLINE = "Your home laptop is off, asleep or offline, so I can't reach your home right now."
HOME_NOT_LINKED = "Your home laptop isn't linked yet: link it in Integrations -> Home."


class HomeUnavailable(Exception):
    """The home can't be used right now. `code` is a short word; the message is plain words for
    the owner and the model (never vendor text)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class HomeOffline(HomeUnavailable):
    """The laptop didn't answer (off, asleep, offline, Funnel down, timed out)."""

    def __init__(self, message: str = HOME_OFFLINE) -> None:
        super().__init__("offline", message)


class HomeRefused(HomeUnavailable):
    """The bridge, or the cloud's own allow-list, said no (`not_linked`, `not_allowed`,
    `bad_reply`, ...)."""


class ArmView(BaseModel):
    """The cloud's arm state as the owner sees it (D8): `confirmed` once the bridge acked `rev`."""

    model_config = ConfigDict(frozen=True)

    armed: bool
    mode: ArmMode
    rev: int = Field(ge=0)
    confirmed: bool
    pending_since: float | None = None


@runtime_checkable
class HomeEventHandler(Protocol):
    handles: frozenset[str]  # the event types it takes (EVENT_TYPES)

    async def handle(
        self, uid: str, event: Heartbeat | Detection | FaceSeen | Package | Hazard | Ack
    ) -> None: ...


@runtime_checkable
class HomeCaller(Protocol):
    async def call(
        self,
        uid: str,
        method: BridgeMethod,
        path: str,
        body: Mapping[str, Any] | None = None,
        *,
        query: Mapping[str, str] | None = None,
    ) -> dict[str, Any]: ...


@runtime_checkable
class ArmReader(Protocol):
    async def view(self, uid: str) -> ArmView: ...


@runtime_checkable
class StateSource(Protocol):
    """A workstream's part of the bridge state (B: arm and settings, C: faces, A: devices)."""

    async def state_part(self, uid: str) -> BridgeState: ...


__all__ = [
    "BRIDGE_ROUTES",
    "ENTITY_ID",
    "EVENT_ID",
    "EVENT_TYPES",
    "HOME_ID",
    "HOME_NOT_LINKED",
    "HOME_OFFLINE",
    "LABELS",
    "LABEL_ID",
    "LINK_PATH",
    "MAX_EVENT_BYTES",
    "MAX_SNAPSHOT_BYTES",
    "MAX_WEBHOOK_BYTES",
    "NEVER_EXPOSED_DOMAINS",
    "PERSON_ID",
    "WEBHOOK_PATH",
    "Ack",
    "ArmMode",
    "ArmReader",
    "ArmState",
    "ArmView",
    "BridgeMethod",
    "BridgeState",
    "CameraPart",
    "CameraSetting",
    "Detection",
    "DeviceTier",
    "DevicesState",
    "EventRejected",
    "ExposedDevice",
    "FaceMatch",
    "FaceSeen",
    "FacesState",
    "Hazard",
    "Heartbeat",
    "HeartbeatParts",
    "HomeCaller",
    "HomeEvent",
    "HomeEventHandler",
    "HomeOffline",
    "HomeRefused",
    "HomeUnavailable",
    "Label",
    "Package",
    "SettingsState",
    "StateSource",
    "is_home_id",
    "parse_event",
    "route_allowed",
]

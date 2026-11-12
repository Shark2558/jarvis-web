# src/jarvis/photos/edge.py
"""The home edge for photos and face groups (R4 D8, R11.1 O7; R3 homebridge). Pictures are sent
to the owner's home laptop, where the faces engine runs; it answers with ids and counts only (an
`fp_` id for a consented, named face, or an unnamed `c_` group id): never a name, a crop or an
embedding. Every answer is parsed strictly here: one field too many (a picture, say) and the
whole answer is refused (`EdgeBadReply`), so nothing but ids and counts can reach the cloud.

`BridgeHomeEdge` uses the signed R3 `HomeCaller` over five bridge routes (kit 0.2.0 and later):

    GET  /bridge/v1/health                 the kit's version: an older kit can't read photos
    POST /bridge/v1/faces/photos           one picture -> the faces in it
    POST /bridge/v1/faces/enrol            a group now belongs to a consented person
    GET  /bridge/v1/faces/groups           the unnamed groups worth naming
    POST /bridge/v1/faces/groups/forget    forget some, or all, unnamed groups

What the laptop says no to arrives as a short code: an unreachable or unlinked laptop is
`EdgeOffline`; a face reader that can't run (or an older kit) is `EdgeNotReady`; a picture or a
request it refuses is `EdgeRefused(code)`. The feature never fails open.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jarvis.home.ports import MAX_EPOCH, PERSON_ID, HomeCaller, HomeRefused, HomeUnavailable
from jarvis.homebridge.config import PHOTOS_SINCE
from jarvis.logging import get_logger
from jarvis.photos.models import CLUSTER_ID, FaceHit, Forgot, GroupAtHome, GroupsAtHome

log = get_logger(__name__)

HEALTH_PATH = "/bridge/v1/health"
PHOTOS_PATH = "/bridge/v1/faces/photos"
ENROL_PATH = "/bridge/v1/faces/enrol"
GROUPS_PATH = "/bridge/v1/faces/groups"
FORGET_PATH = "/bridge/v1/faces/groups/forget"
MAX_FACES_PER_PHOTO = 20
MAX_GROUPS = 100
MAX_COUNT = 10_000_000
READY = "ready"
KIT_OLD = "kit_old"
OFFLINE = "Your home laptop isn't reachable, so JARVIS can't look at the photos now."
BAD_REPLY = "Your home laptop's answer couldn't be understood, so JARVIS ignored it."
NOT_READY = "The face reader on your home laptop isn't ready yet: update the home kit."
OLD_KIT = (
    "Your home laptop runs an older home kit that can't read photos: download the kit again "
    "in Integrations -> Home and run setup-windows.ps1 -Update."
)
# the bridge's refusal codes that mean "this one thing was refused", not "the laptop is away"
REFUSALS = frozenset({"bad_image", "bad_request", "no_consent", "unknown_group", "already_named"})


class EdgeOffline(RuntimeError):
    def __init__(self, message: str = OFFLINE) -> None:
        super().__init__(message)


class EdgeBadReply(RuntimeError):
    """The laptop answered, but not in the agreed shape (distinct from being offline)."""

    def __init__(self, message: str = BAD_REPLY) -> None:
        super().__init__(message)


class EdgeNotReady(RuntimeError):
    """The laptop is there but its face reader can't run (no models yet, or an older kit)."""

    def __init__(self, message: str = NOT_READY) -> None:
        super().__init__(message)


class EdgeRefused(RuntimeError):
    """The laptop said no to this one request (`code` is the bridge's short word)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class HomeEdge(Protocol):
    async def ready(self, uid: str) -> str: ...

    async def analyse(
        self, uid: str, images: Sequence[bytes]
    ) -> tuple[tuple[FaceHit, ...], ...]: ...

    async def enrol(self, uid: str, cluster: str, person_id: str) -> int: ...

    async def groups(self, uid: str) -> GroupsAtHome: ...

    async def forget(self, uid: str, groups: Sequence[str] | None) -> Forgot: ...


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class EdgeFace(_Strict):
    cluster: str = Field(pattern=CLUSTER_ID.pattern)
    person: str | None = Field(pattern=PERSON_ID)
    score: float = Field(ge=0, le=1, allow_inf_nan=False)


class EdgeReply(_Strict):
    faces: list[EdgeFace] = Field(max_length=MAX_FACES_PER_PHOTO)


class EdgeGroup(_Strict):
    id: str = Field(pattern=CLUSTER_ID.pattern)
    n: int = Field(ge=0, le=MAX_COUNT)
    photos: int = Field(ge=0, le=MAX_COUNT)
    first: int = Field(ge=0, le=int(MAX_EPOCH))
    last: int = Field(ge=0, le=int(MAX_EPOCH))


class EdgeGroups(_Strict):
    groups: list[EdgeGroup] = Field(max_length=MAX_GROUPS)
    more: int = Field(ge=0, le=MAX_COUNT)
    strays: int = Field(ge=0, le=MAX_COUNT)
    named: int = Field(ge=0, le=MAX_COUNT)
    engine: Literal["ready", "off"]
    folder: Literal["off", "on", "unreadable"]
    read: int = Field(ge=0, le=MAX_COUNT)
    keep_days: int = Field(ge=1, le=3650)


class EdgeForgot(_Strict):
    forgotten: int = Field(ge=0, le=MAX_COUNT)
    left: int = Field(ge=0, le=MAX_COUNT)


class EdgeEnrolled(_Strict):
    pictures: int = Field(ge=0, le=200)
    camera: Literal["copied", "waiting"]


def _parse(model: type[Any], reply: Any) -> Any:
    """Strict: anything off-shape is `EdgeBadReply` as a whole, never partly trusted (logged by
    exception type only: a bad reply may hold anything)."""
    try:
        return model.model_validate(reply)
    except ValidationError as exc:
        log.warning("home edge reply rejected", extra={"reason": type(exc).__name__})
        raise EdgeBadReply() from None


def parse_faces(reply: Any) -> tuple[FaceHit, ...]:
    """The faces in one photo's reply."""
    parsed = _parse(EdgeReply, reply)
    return tuple(FaceHit(f.cluster, f.person, float(f.score)) for f in parsed.faces)


def _older(version: object, than: str) -> bool:
    def parts(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in v.split("."))

    try:
        return parts(str(version)) < parts(than)
    except ValueError:
        return True  # no readable version: treat it as a kit that can't


class BridgeHomeEdge:
    def __init__(self, home: HomeCaller) -> None:
        self._home = home

    async def ready(self, uid: str) -> str:
        """`ready`, or `kit_old` when the laptop runs a kit from before the photo routes.
        Raises `EdgeOffline` when it can't be reached (one cheap call, before anything is
        downloaded for it)."""
        reply = await self._call(uid, "GET", HEALTH_PATH, None)
        return KIT_OLD if _older(reply.get("version"), PHOTOS_SINCE) else READY

    async def analyse(self, uid: str, images: Sequence[bytes]) -> tuple[tuple[FaceHit, ...], ...]:
        out = []
        for image in images:
            body = {"image": base64.b64encode(image).decode("ascii")}
            out.append(parse_faces(await self._call(uid, "POST", PHOTOS_PATH, body)))
        return tuple(out)

    async def enrol(self, uid: str, cluster: str, person_id: str) -> int:
        """Tell the laptop a group is a consented person. Returns how many face pictures of
        them it now holds (a count)."""
        body = {"cluster": cluster, "person": person_id}
        reply = await self._call(uid, "POST", ENROL_PATH, body)
        return int(_parse(EdgeEnrolled, reply).pictures)

    async def groups(self, uid: str) -> GroupsAtHome:
        g = _parse(EdgeGroups, await self._call(uid, "GET", GROUPS_PATH, None))
        rows = tuple(GroupAtHome(r.id, r.n, r.photos, r.first, r.last) for r in g.groups)
        return GroupsAtHome(
            rows, g.more, g.strays, g.named, g.engine == "ready", g.folder, g.read, g.keep_days
        )

    async def forget(self, uid: str, groups: Sequence[str] | None) -> Forgot:
        """Forget these unnamed groups (None: all of them). The answer is the laptop's own
        confirmation: how many went and how many are left."""
        body: dict[str, Any] = {"all": True} if groups is None else {"groups": list(groups)}
        done = _parse(EdgeForgot, await self._call(uid, "POST", FORGET_PATH, body))
        return Forgot(done.forgotten, done.left)

    async def _call(
        self, uid: str, method: Literal["GET", "POST"], path: str, body: dict[str, Any] | None
    ) -> dict[str, Any]:
        try:
            return await self._home.call(uid, method, path, body)
        except HomeRefused as exc:
            if exc.code == "no_engine":
                raise EdgeNotReady() from None
            if exc.code in REFUSALS:
                raise EdgeRefused(exc.code, exc.message) from None
            log.warning("home edge unavailable", extra={"reason": exc.code})
            raise EdgeOffline() from None  # not linked, an older kit's 404, an untrusted answer
        except HomeUnavailable as exc:
            log.warning("home edge unavailable", extra={"reason": type(exc).__name__})
            raise EdgeOffline() from None


__all__ = [
    "ENROL_PATH",
    "FORGET_PATH",
    "GROUPS_PATH",
    "KIT_OLD",
    "OLD_KIT",
    "PHOTOS_PATH",
    "READY",
    "BridgeHomeEdge",
    "EdgeBadReply",
    "EdgeNotReady",
    "EdgeOffline",
    "EdgeRefused",
    "HomeEdge",
    "parse_faces",
]

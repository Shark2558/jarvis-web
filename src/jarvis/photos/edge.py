# src/jarvis/photos/edge.py
"""The home edge for picked photos (R4 D8; R3 homebridge). Pictures are sent to the owner's home
laptop, where the faces engine already runs; it answers with face ids only (an `fp_` id for an
enrolled face, or an unnamed `c_` cluster id), never a name, crop or embedding.

`BridgeHomeEdge` uses the signed R3 `HomeCaller`. Two bridge routes are needed that the R3 kit
does not have yet (see INTEGRATION.md): `POST /bridge/v1/faces/photos` and
`POST /bridge/v1/faces/enrol`. Until the integrator adds them to `home.ports.BRIDGE_ROUTES`
(with a per-route size cap for one picture), `HomeClient` refuses the call and the edge
reports `EdgeOffline`: the feature stays OFF, it never fails open.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jarvis.home.ports import PERSON_ID, HomeCaller, HomeUnavailable
from jarvis.logging import get_logger
from jarvis.photos.models import CLUSTER_ID, FaceHit

log = get_logger(__name__)

PHOTOS_PATH = "/bridge/v1/faces/photos"
ENROL_PATH = "/bridge/v1/faces/enrol"
MAX_FACES_PER_PHOTO = 20
OFFLINE = "Your home laptop isn't reachable, so JARVIS can't look at the photos now."
BAD_REPLY = "Your home laptop's answer couldn't be understood, so JARVIS ignored it."


class EdgeOffline(RuntimeError):
    def __init__(self, message: str = OFFLINE) -> None:
        super().__init__(message)


class HomeEdge(Protocol):
    async def analyse(
        self, uid: str, images: Sequence[bytes]
    ) -> tuple[tuple[FaceHit, ...], ...]: ...

    async def enrol(self, uid: str, cluster: str, person_id: str) -> None: ...


class EdgeBadReply(RuntimeError):
    """The laptop answered, but not in the agreed shape (distinct from being offline)."""

    def __init__(self, message: str = BAD_REPLY) -> None:
        super().__init__(message)


class EdgeFace(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    cluster: str = Field(pattern=CLUSTER_ID.pattern)
    person: str | None = Field(pattern=PERSON_ID)
    score: float = Field(ge=0, le=1, allow_inf_nan=False)


class EdgeReply(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    faces: list[EdgeFace] = Field(max_length=MAX_FACES_PER_PHOTO)


def parse_faces(reply: Any) -> tuple[FaceHit, ...]:
    """The faces in one photo's reply. Strict: anything off-shape is `EdgeBadReply` as a whole,
    never partly trusted (logged by exception type only: the reply may hold names)."""
    try:
        parsed = EdgeReply.model_validate(reply)
    except ValidationError as exc:
        log.warning("home edge reply rejected", extra={"reason": type(exc).__name__})
        raise EdgeBadReply() from None
    return tuple(FaceHit(f.cluster, f.person, float(f.score)) for f in parsed.faces)


class BridgeHomeEdge:
    def __init__(self, home: HomeCaller) -> None:
        self._home = home

    async def analyse(self, uid: str, images: Sequence[bytes]) -> tuple[tuple[FaceHit, ...], ...]:
        out = []
        for image in images:
            body = {"image": base64.b64encode(image).decode("ascii")}
            out.append(parse_faces(await self._call(uid, PHOTOS_PATH, body)))
        return tuple(out)

    async def enrol(self, uid: str, cluster: str, person_id: str) -> None:
        await self._call(uid, ENROL_PATH, {"cluster": cluster, "person": person_id})

    async def _call(self, uid: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self._home.call(uid, "POST", path, body)
        except HomeUnavailable as exc:
            log.warning("home edge unavailable", extra={"reason": type(exc).__name__})
            raise EdgeOffline() from None


__all__ = [
    "ENROL_PATH",
    "PHOTOS_PATH",
    "BridgeHomeEdge",
    "EdgeBadReply",
    "EdgeOffline",
    "HomeEdge",
    "parse_faces",
]

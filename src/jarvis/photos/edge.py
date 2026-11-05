# src/jarvis/photos/edge.py
"""The home edge for picked photos (R4 D8; R3 homebridge). Pictures are sent to the owner's home
laptop, where the faces engine already runs; it answers with face ids only (an `fp_` id for an
enrolled face, or an unnamed `c_` cluster id), never a name, crop or embedding.

`BridgeHomeEdge` uses the signed R3 `HomeCaller`. Two bridge routes are needed that the R3 kit
does not have yet (see INTEGRATION.md): `POST /bridge/v1/faces/photos` and
`POST /bridge/v1/faces/enrol`. Until the integrator adds them to `home.ports.BRIDGE_ROUTES`
(and raises `MAX_REQUEST_BYTES` for one picture), `HomeClient` refuses the call and the edge
reports `EdgeOffline`: the feature stays OFF, it never fails open.
"""

from __future__ import annotations

import base64
import math
from collections.abc import Sequence
from typing import Any, Protocol

from jarvis.faces.ports import is_person_id
from jarvis.home.ports import HomeCaller, HomeUnavailable
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


def parse_faces(reply: Any) -> tuple[FaceHit, ...]:
    """The faces in one photo's reply; anything malformed is dropped, never guessed."""
    rows = reply.get("faces") if isinstance(reply, dict) else None
    if not isinstance(rows, list):
        raise EdgeOffline(BAD_REPLY)
    out: list[FaceHit] = []
    for r in rows[:MAX_FACES_PER_PHOTO]:
        if not isinstance(r, dict):
            continue
        cluster, person, score = r.get("cluster"), r.get("person"), r.get("score")
        if not isinstance(cluster, str) or not CLUSTER_ID.fullmatch(cluster):
            continue
        if isinstance(score, bool) or not isinstance(score, int | float):
            continue
        if not math.isfinite(score) or not 0 <= score <= 1:
            continue
        out.append(FaceHit(cluster, person if is_person_id(person) else None, float(score)))
    return tuple(out)


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


__all__ = ["ENROL_PATH", "PHOTOS_PATH", "BridgeHomeEdge", "EdgeOffline", "HomeEdge", "parse_faces"]

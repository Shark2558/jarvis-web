# src/jarvis/homebridge/homevision.py
"""R8 row 216's home leg (docs/plans/r8-vision.md v8.0.4 4.5a, the owner's D3 and D4, ADR-49;
builder J): vision on the home laptop for the home camera. Ships in the home kit.

It reads the home camera's RTSP sub-stream (`HOMEVISION_RTSP_URL` in bridge.env: the address and
the camera's password stay on the laptop and are never logged; `HOMEVISION_CAMERA` is its id in
the camera setup), looks at about 1 frame a second (2 while a slouch is suspected, up to 15
during a seated session), runs MediaPipe's pose landmarker there (`HOMEVISION_MODELS_DIR`, default
/models: the pinned files, SHA-256 checked; full if the laptop keeps 15 frames a second, else
lite), names enrolled people through the face groups' named faces and the faces plugin's consent
(`BridgeContext.peers["faces"]`, read when a body appears, the owner's D6), and runs the home use
cases' rules (`jarvis.coach.home.REGISTRY`) one body at a time (`jarvis.coach.home.runtime`).

Up go only `CoachReport` events (views and tallies; never a frame, a point or a box) and its
heartbeat part (`HomeVisionPart`: running, which model, frames a second, which coaches). It obeys
the coach part of the state push (`CoachState`: which use cases on which camera, the target,
"cameras off"), from the push, every heartbeat's reply and, after a restart, the state the bridge
saved; it never touches Frigate or the alarm. No signed route: nothing can ask it for anything.

Not set up (no address or camera id; the owner's step when the camera arrives), or set up wrong (an
address that is not `rtsp://` to a home-network IP, a camera id that is not one): no task runs and
the heartbeat says `running: false`; the bridge itself is never stopped by it.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from jarvis.coach.home.engines import MediaPipeObjects, MediaPipePose, OpenCvSource, rtsp_url_ok
from jarvis.coach.home.identify import LaptopFaces
from jarvis.coach.home.runtime import HomeRuntime
from jarvis.home.ports import LABEL_ID, BridgeState, HeartbeatParts, HomeVisionPart
from jarvis.homebridge.face_store import DEFAULT_MATCH
from jarvis.homebridge.face_types import setting_float
from jarvis.homebridge.plugins import BridgeContext, BridgeRoute, TaskFactory
from jarvis.homebridge.state import STATE

log = logging.getLogger(__name__)

NAME = "homevision"
DEFAULT_MODELS_DIR = "/models"
# what the home rules look for (row 182: a phone, a cup or bowl; row 262: a chair and a table),
# from the vision contract's COCO labels (jarvis.vision.results.OBJECT_LABELS)
HOME_OBJECTS = (
    *("person", "cell_phone", "cup", "bowl", "bottle", "wine_glass", "fork", "spoon"),
    *("dining_table", "chair", "couch", "laptop", "keyboard", "book"),
)
NOT_SET = "the home camera isn't set up for the coaches yet"
BAD_ADDRESS = "HOMEVISION_RTSP_URL is not an rtsp:// address on the home network"
BAD_CAMERA = "HOMEVISION_CAMERA is not a camera id (a-z, 0-9 and _, up to 24)"


def settings_problem(env: dict[str, str] | Any) -> str:
    """ "" when the plugin can run, else why not (plain words, never the address)."""
    url = str(env.get("HOMEVISION_RTSP_URL", "") or "").strip()
    camera = str(env.get("HOMEVISION_CAMERA", "") or "").strip()
    if not url and not camera:
        return NOT_SET
    if not rtsp_url_ok(url):
        return BAD_ADDRESS
    if re.fullmatch(LABEL_ID, camera) is None:
        return BAD_CAMERA
    return ""


class HomeVisionPlugin:
    name = NAME

    def __init__(self, ctx: BridgeContext, *, runtime: HomeRuntime | None = None) -> None:
        self._ctx = ctx
        self.why = "" if runtime is not None else settings_problem(ctx.env)
        if self.why and self.why != NOT_SET:
            log.warning("the home camera's coaches are off", extra={"why": self.why})
        self.runtime = runtime if runtime is not None or self.why else self._build()
        if self.runtime is not None:
            saved = self._saved()
            if saved is not None and saved.coach is not None:
                self.runtime.apply(saved.coach)

    def _build(self) -> HomeRuntime:
        env = self._ctx.env
        models = Path(env.get("HOMEVISION_MODELS_DIR") or DEFAULT_MODELS_DIR)
        faces = LaptopFaces(
            Path(env.get("FACE_MODELS_DIR") or DEFAULT_MODELS_DIR),
            self._ctx.data_dir / "facegroups" / "groups.db",
            self._consented,
            match=setting_float(env.get("FACE_MATCH_SCORE"), DEFAULT_MATCH, 0.30, 0.80),
        )
        return HomeRuntime(
            str(env["HOMEVISION_CAMERA"]).strip(),
            OpenCvSource(str(env["HOMEVISION_RTSP_URL"]).strip()),
            MediaPipePose(models),
            self._ctx.events.post_event,
            objects=MediaPipeObjects(models, HOME_OBJECTS),
            identifier=faces,
            wall=self._ctx.now,
        )

    def _consented(self, person: str) -> bool:
        library = getattr(self._ctx.peers.get("faces"), "library", None)
        return bool(library is not None and library.consented(person))

    def _saved(self) -> BridgeState | None:
        """The state the bridge kept, so a restart without the internet keeps the switches."""
        try:
            raw = (self._ctx.data_dir / STATE).read_text("utf-8")
            return BridgeState.model_validate_json(raw)
        except (OSError, ValueError, ValidationError):
            return None

    def routes(self) -> Sequence[BridgeRoute]:
        return ()

    def tasks(self) -> Sequence[TaskFactory]:
        return () if self.runtime is None else (self.runtime.run,)

    async def heartbeat_part(self) -> HeartbeatParts:
        part = self.runtime.part() if self.runtime is not None else HomeVisionPart(running=False)
        return HeartbeatParts(homevision=part)

    async def apply_state(self, state: BridgeState) -> None:
        if self.runtime is not None and state.coach is not None:
            self.runtime.apply(state.coach)

    async def on_reply(self, state: BridgeState) -> None:
        await self.apply_state(state)  # the runtime takes only a newer rev


def create_plugin(ctx: BridgeContext) -> HomeVisionPlugin:
    return HomeVisionPlugin(ctx)


__all__ = ["HOME_OBJECTS", "NAME", "HomeVisionPlugin", "create_plugin", "settings_problem"]

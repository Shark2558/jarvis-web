# src/jarvis/homebridge/face_groups.py
"""The bridge's face-groups plugin (R11.1 O7; plan D15, D21-C). Ships in the home kit.

The laptop looks at still pictures: one photo JARVIS sends from Google Photos at a time, and the
owner's watched photo folder. Faces are grouped by likeness on this laptop (`face_store`), and the
signed answers carry group ids and counts only: never a picture, a crop or an embedding.

    POST /bridge/v1/faces/photos         {"image": base64 JPEG} -> {"faces": [{"cluster":
                                         "c_<12 hex>", "person": "fp_<12 hex>" | null, "score"}]}
    POST /bridge/v1/faces/enrol          {"cluster", "person"} -> {"pictures", "camera"}
    GET  /bridge/v1/faces/groups         -> {"groups": [{"id", "n", "photos", "first", "last"}],
                                         "more", "strays", "named", "engine", "folder", "read",
                                         "skipped", "keep_days"}
    POST /bridge/v1/faces/groups/forget  {"groups": [ids]} | {"all": true} -> {"forgotten", "left"}

- `person` is only ever an id the cloud synced as consented (the faces plugin's `FaceLibrary`
  decides; no consent here means nobody is named, whatever the store says). `score` is the
  laptop's likeness on the wire's scale: 0.9 (the cloud's bar) exactly at this laptop's threshold.
- `enrol` names a group for a consented id and copies its best crops into the camera's face
  library under that id, so the camera recognises the person too. If Frigate is down the copy is
  done later (`copy_to_camera`, every minute); photos are recognised by this laptop meanwhile.
- An unnamed group and a stray face are forgotten `FACE_GROUPS_KEEP_DAYS` (default 90) after they
  were first seen; a deleted person's groups go before the faces plugin acknowledges the delete.
- A plugin that can't run its engine answers `no_engine`; one whose store can't be opened (a
  locked, read-only or full disk: review C-code H4) answers `no_store`, says so in the groups
  view (`engine: "no_store"`) and tries to open it again every minute. Neither raises at start:
  a photos fault must not make the camera look broken.
- One bad picture is one refusal (`bad_image`), whatever went wrong with it: never a 500 that
  the cloud would read as "laptop not reachable" (review C-code H3).
- Consent is checked twice when a group is named: once when the message arrives and again
  inside the store's own lock, right before the write (review C-sec M2); and before each crop is
  copied to the camera.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import functools
import hashlib
import logging
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from jarvis.home.ports import BridgeState, HeartbeatParts, HomeRefused
from jarvis.homebridge.face_db import set_aside_files
from jarvis.homebridge.face_engine import (
    READY,
    EngineOff,
    FaceEngine,
    OpenCvEngine,
    reduction,
)
from jarvis.homebridge.face_folder import DEFAULT_PER_MINUTE, FolderScanner
from jarvis.homebridge.face_store import DEFAULT_MATCH, FaceStore, NoConsent
from jarvis.homebridge.face_types import GROUP, AlreadyNamed, Placed, UnknownGroup
from jarvis.homebridge.faces import FaceRefused
from jarvis.homebridge.jpeg import PictureRefused, jpeg_size
from jarvis.homebridge.plugins import BridgeContext, BridgeRoute, TaskFactory

log = logging.getLogger(__name__)

DEFAULT_KEEP_DAYS = 90
DEFAULT_MODELS_DIR = "/models"
DEFAULT_MOUNT = "/photos"
RECOGNISED = 0.9  # the cloud's bar for a name (faces.ports.RECOGNITION_THRESHOLD)
MAX_LISTED = 100
MAX_FORGET = 100
SWEEP_S = 3600.0
COPY_S = 60.0
NO_ENGINE = "The face reader on this laptop isn't ready."
NO_STORE = "The face store on this laptop can't be opened right now."


def confidence(cosine: float, match: float) -> float:
    """The laptop's likeness on the wire's 0..1 scale: exactly 0.9 at this laptop's threshold."""
    c = max(0.0, min(1.0, float(cosine)))
    if c >= match:
        return round(min(1.0, RECOGNISED + (1 - RECOGNISED) * (c - match) / (1 - match)), 4)
    return round(RECOGNISED * c / match, 4)


def _whole(text: object, default: int, low: int, high: int) -> int:
    value = str(text or "").strip()
    return int(value) if value.isdigit() and low <= int(value) <= high else default


def _part(text: object, default: float, low: float, high: float) -> float:
    try:
        value = float(str(text or ""))
    except ValueError:
        return default
    return value if low <= value <= high else default


class FaceGroupsPlugin:
    name = "facegroups"

    def __init__(self, ctx: BridgeContext, *, engine: FaceEngine | None = None) -> None:
        env = ctx.env
        self._ctx = ctx
        self.keep_days = _whole(env.get("FACE_GROUPS_KEEP_DAYS"), DEFAULT_KEEP_DAYS, 1, 3650)
        self.match = _part(env.get("FACE_MATCH_SCORE"), DEFAULT_MATCH, 0.30, 0.80)
        self.engine: FaceEngine = engine or OpenCvEngine(
            Path(env.get("FACE_MODELS_DIR") or DEFAULT_MODELS_DIR)
        )
        self.store: FaceStore | None = None
        self._open_store()
        mount = Path(env.get("PHOTOS_MOUNT") or DEFAULT_MOUNT) if env.get("PHOTOS_DIR") else None
        self.folder = FolderScanner(
            mount,
            self._look_own,
            self.store,
            per_minute=_whole(env.get("PHOTOS_PER_MINUTE"), DEFAULT_PER_MINUTE, 1, 30),
        )
        self._lock = asyncio.Lock()

    def _open_store(self) -> bool:
        """Open the store if it is not open (at start, then every minute while it can't be)."""
        if self.store is not None:
            return True
        try:
            self.store = FaceStore(
                self._ctx.data_dir / "facegroups", match=self.match, now=self._ctx.now
            )
        except (OSError, sqlite3.Error) as exc:
            log.error(
                "face groups are OFF: the store can't be opened",
                extra={"error": type(exc).__name__},
            )
            return False
        if getattr(self, "folder", None) is not None:
            self.folder.attach(self.store)
        return True

    def _need_store(self) -> FaceStore:
        if self.store is None and not self._open_store():
            raise HomeRefused("no_store", NO_STORE)
        assert self.store is not None
        return self.store

    # ---- consent lives with the faces plugin (read when a message arrives) ---------------------

    def _library(self) -> Any:
        return getattr(self._ctx.peers.get("faces"), "library", None)

    def _consented(self, person: object) -> bool:
        library = self._library()
        return bool(library is not None and library.consented(person))

    # ---- looking at one picture ----------------------------------------------------------------

    async def look(self, jpeg: bytes, *, own_file: bool = False) -> tuple[str, list[Placed]]:
        """(the picture's key, where its faces went). One picture at a time, off the event loop."""
        if self.store is None:
            raise EngineOff(NO_STORE)
        reduction(*jpeg_size(jpeg), own_file=own_file)  # the caps, before any engine sees it
        pic = hashlib.sha256(jpeg).hexdigest()[:32]
        async with self._lock:
            known = await asyncio.to_thread(self.store.known, pic)
            if known is not None:
                return pic, known
            why = await asyncio.to_thread(self.engine.status)
            if why != READY:
                raise EngineOff(why)
            faces = await asyncio.to_thread(
                functools.partial(self.engine.faces, jpeg, own_file=own_file)
            )
            return pic, await asyncio.to_thread(self.store.place, pic, faces)

    async def _look_own(self, jpeg: bytes) -> str:
        pic, _ = await self.look(jpeg, own_file=True)
        return pic

    def _wire(self, placed: Placed) -> dict[str, Any]:
        named = placed.person is not None and self._consented(placed.person)
        score = confidence(placed.cosine, self.match) if placed.cosine > 0 else 0.0
        return {
            "cluster": placed.group,
            "person": placed.person if named else None,
            "score": float(score),
        }

    # ---- the signed routes ---------------------------------------------------------------------

    def routes(self) -> Sequence[BridgeRoute]:
        return (
            BridgeRoute("POST", "/bridge/v1/faces/photos", self._photos),
            BridgeRoute("POST", "/bridge/v1/faces/enrol", self._enrol),
            BridgeRoute("GET", "/bridge/v1/faces/groups", self._groups),
            BridgeRoute("POST", "/bridge/v1/faces/groups/forget", self._forget),
        )

    async def _photos(
        self, query: Mapping[str, str], body: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        image = (body or {}).get("image")
        if set(body or {}) != {"image"} or not isinstance(image, str):
            raise HomeRefused("bad_request", "One picture a request.")
        try:
            jpeg = base64.b64decode(image, validate=True)
        except (binascii.Error, ValueError):
            raise HomeRefused("bad_image", "That isn't a picture.") from None
        self._need_store()
        try:
            _, placed = await self.look(jpeg)
        except EngineOff:
            raise HomeRefused("no_engine", NO_ENGINE) from None
        except sqlite3.Error as exc:
            log.error("the face store failed", extra={"error": type(exc).__name__})
            raise HomeRefused("no_store", NO_STORE) from None
        except Exception as exc:  # noqa: BLE001 - this one picture, never "laptop not reachable"
            if not isinstance(exc, PictureRefused | ValueError):
                log.warning("a picture could not be read", extra={"error": type(exc).__name__})
            raise HomeRefused("bad_image", "That picture can't be read here.") from None
        return {"faces": [self._wire(p) for p in placed]}

    async def _enrol(
        self, query: Mapping[str, str], body: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        data = body or {}
        cluster, person = data.get("cluster"), data.get("person")
        store = self._need_store()
        if not isinstance(cluster, str) or not GROUP.fullmatch(cluster):
            raise HomeRefused("unknown_group", "There is no such group on this laptop.")
        if not self._consented(person):  # the one door: an id without consent is never named
            raise HomeRefused("no_consent", "That person has no consent recorded.")
        name = functools.partial(store.name, cluster, str(person), consented=self._consented)
        try:
            kept = await asyncio.to_thread(name)  # consent asked again inside the store's lock
        except NoConsent:
            raise HomeRefused("no_consent", "That person has no consent recorded.") from None
        except UnknownGroup:
            raise HomeRefused("unknown_group", "There is no such group on this laptop.") from None
        except AlreadyNamed:
            raise HomeRefused("already_named", "That group is someone else already.") from None
        copied = await self._copy_group(cluster, str(person))
        return {"pictures": kept, "camera": "copied" if copied else "waiting"}

    async def _groups(
        self, query: Mapping[str, str], body: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        self._open_store()
        return await asyncio.to_thread(self.groups_view)

    async def _forget(
        self, query: Mapping[str, str], body: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        data = body or {}
        ids, everything = data.get("groups"), data.get("all")
        if (ids is None) == (everything is None) or set(data) - {"groups", "all"}:
            raise HomeRefused("bad_request", "Say which groups, or all.")
        self._need_store()  # "nothing left" is never said for a store that can't be read
        if everything is not None:
            if everything is not True:
                raise HomeRefused("bad_request", "Say which groups, or all.")
            return await self.forget(None)
        if not isinstance(ids, list) or not 0 < len(ids) <= MAX_FORGET:
            raise HomeRefused("bad_request", "Say which groups, or all.")
        if not all(isinstance(i, str) for i in ids):
            raise HomeRefused("bad_request", "Say which groups, or all.")
        return await self.forget([str(i) for i in ids])

    # ---- what the routes, the laptop's page and the faces plugin use ---------------------------

    def groups_view(self) -> dict[str, Any]:
        """Unnamed groups worth naming, as ids and counts (never a crop or an embedding)."""
        view: dict[str, Any] = {
            "groups": [],
            "more": 0,
            "strays": 0,
            "named": 0,
            "engine": "off",
            "folder": self.folder.state,
            "read": 0,
            "skipped": 0,
            "keep_days": self.keep_days,
        }
        if self.store is None:
            view["engine"] = "no_store"
            return view
        rows, counts = self.store.groups(), self.store.counts()
        view["groups"] = [
            {
                "id": r.id,
                "n": r.n or 0,
                "photos": r.pics,
                "first": int(r.first),
                "last": int(r.last),
            }
            for r in rows[:MAX_LISTED]
        ]
        view.update(
            more=max(0, len(rows) - MAX_LISTED),
            strays=counts.strays,
            named=counts.named,
            engine="ready" if self.engine.status() == READY else "off",
            read=self.store.files_read(),
            skipped=self.store.marks.skipped(),
        )
        return view

    def page_view(self) -> dict[str, Any]:
        """For the laptop's own page only (never a signed answer): the groups, how many crops
        each can show, and how the watched folder is doing."""
        view = self.groups_view()
        if self.store is not None:
            for group in view["groups"]:
                group["crops"] = len(self.store.crops(group["id"]))
        view.update(waiting=self.folder.waiting)
        folder = self.store.folder if self.store is not None else self._ctx.data_dir / "facegroups"
        view["set_aside"] = set_aside_files(folder)  # damaged files kept for the owner to delete
        return view

    def crop(self, group: str, index: int) -> bytes | None:
        """One face picture of a group, for the laptop's own page. None when there is none."""
        if self.store is None or not GROUP.fullmatch(group) or index < 0:
            return None
        crops = self.store.crops(group)
        return crops[index] if index < len(crops) else None

    async def forget(self, groups: list[str] | None) -> dict[str, int]:
        """Forget these unnamed groups (None: every unnamed group and stray). Counts only."""
        if self.store is None:
            return {"forgotten": 0, "left": 0}
        store = self.store
        if groups is None:
            gone = await asyncio.to_thread(store.forget_all)
        else:
            gone = await asyncio.to_thread(store.forget, groups)
        counts = await asyncio.to_thread(store.counts)
        return {"forgotten": gone, "left": counts.groups + counts.strays}

    async def expire(self) -> int:
        if self.store is None:
            return 0
        return await asyncio.to_thread(self.store.expire, self.keep_days)

    async def rescan(self) -> None:
        if self.store is not None:
            await asyncio.to_thread(self.store.rescan)

    def person_pictures(self) -> dict[str, int]:
        return self.store.person_pictures() if self.store is not None else {}

    async def forget_person(self, person: str) -> bool:
        """A person is being deleted: their groups go. True when nothing of them is left here."""
        if self.store is None and not self._open_store():
            return False  # the store can't be read: the delete waits, never "done"
        assert self.store is not None
        await asyncio.to_thread(self.store.forget_person, person)
        return not await asyncio.to_thread(self.store.holds, person)

    async def _copy_group(self, group: str, person: str) -> bool:
        """The group's crops into the camera's face library, under the person's id."""
        library = self._library()
        if library is None or self.store is None:
            return False
        for crop in await asyncio.to_thread(self.store.crops, group):
            if not self._consented(person):
                return False  # the person's delete began: nothing more is copied (C-sec M2)
            try:
                await library.enrol(person, crop)
            except FaceRefused as exc:
                if exc.code == "too_many":
                    break  # the camera has all the pictures of this person it takes
                return False
        await asyncio.to_thread(self.store.copied, group)
        return True

    async def copy_to_camera(self) -> int:
        """Finish copies that waited for Frigate. Returns how many groups were copied."""
        if self.store is None and not self._open_store():
            return 0
        assert self.store is not None
        done = 0
        for group, person in await asyncio.to_thread(self.store.uncopied):
            if self._consented(person) and await self._copy_group(group, person):
                done += 1
        return done

    # ---- the plugin's other duties -------------------------------------------------------------

    def tasks(self) -> Sequence[TaskFactory]:
        loops: list[TaskFactory] = [self._expire_loop, self._copy_loop]
        if self.folder.mount is not None:  # it waits for the store if that can't open yet
            loops.append(self.folder.run)
        return tuple(loops)

    async def _expire_loop(self) -> None:
        while True:
            await self.expire()
            await asyncio.sleep(SWEEP_S)

    async def _copy_loop(self) -> None:
        while True:
            await self.copy_to_camera()
            await asyncio.sleep(COPY_S)

    async def heartbeat_part(self) -> HeartbeatParts:
        return HeartbeatParts()  # the faces plugin adds this plugin's picture counts to its own

    async def apply_state(self, state: BridgeState) -> None:
        return None  # consent is read from the faces plugin when a message arrives

    async def aclose(self) -> None:
        if self.store is not None:
            self.store.close()


def create_plugin(ctx: BridgeContext) -> FaceGroupsPlugin:
    """The registry factory (`homebridge/registry.PLUGINS`)."""
    return FaceGroupsPlugin(ctx)


__all__ = ["DEFAULT_KEEP_DAYS", "FaceGroupsPlugin", "confidence", "create_plugin"]

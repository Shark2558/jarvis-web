# src/jarvis/homebridge/faces.py
"""The bridge's faces plugin (R3 D13): Frigate's face library at home, driven by ids.

- The cloud tells the bridge which person ids have consent (`BridgeState.faces`: ids only, never
  names) and which to delete. A library entry is named by the id (`fp_<12 hex>`), never by a name.
- `FaceLibrary.enrol` refuses an id that has no consent here, one being deleted, a bad image
  (JPEG or PNG, <= 5 MB, <= 20 pictures a person) and anything else: a face without consent is
  never added.
- `FaceLibrary.match` is what the detection filter (B) asks: a recognition counts only for a
  consented id at Frigate's threshold on a `person`. A name someone typed in Frigate's UI, an
  unknown id or a low score gives None, so the cloud never even hears of it.
- A delete removes the library entry and the person's attempts, then acks to the cloud
  (`Ack(face_deleted)`) - only when none of their pictures is left on this laptop (a folder the
  bridge may not delete in, or a picture that could not be removed, is never "done"); until
  then it is retried (also when Frigate was down).
- Pictures and embeddings never leave this machine: heartbeats carry counts only.

Frigate's face-library HTTP endpoints below (`HttpFrigateFaces`) are written from its documented
API and NOT verified against the pinned version's `/api/docs` (no network at build time); the
tests use a fake library. Stdlib, pydantic and httpx only (home kit); nothing from the cloud app.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, TypeVar

import httpx

from jarvis.home.ports import (
    MAX_PEOPLE,
    MAX_PICTURES,
    PERSON_ID,
    Ack,
    BridgeState,
    FaceMatch,
    FacesState,
    HeartbeatParts,
)
from jarvis.homebridge.plugins import BridgeContext, BridgeRoute, TaskFactory
from jarvis.homebridge.retention import Retention

T = TypeVar("T")
log = logging.getLogger(__name__)
# Frigate's own folders, as the home kit mounts Frigate's media (compose: ./frigate/media is
# /media/frigate in Frigate; the bridge gets the same path). Overridable by env.
DEFAULT_ATTEMPTS_DIR = "/media/frigate/clips/faces/train"
DEFAULT_DOORSTEP_DIR = "/media/frigate/clips/doorstep/train"
RECOGNITION_THRESHOLD = 0.9
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PER_PERSON = 20
JPEG = b"\xff\xd8\xff"
PNG = b"\x89PNG\r\n\x1a\n"
FRIGATE_TIMEOUT_S = 8.0
RETRY_S = 60.0
SWEEP_S = 3600.0
RECENT_FILE = re.compile(r"^(?!\.+$)[A-Za-z0-9._-]{1,116}\.(?:webp|jpe?g|png)$", re.IGNORECASE)
PERSON = re.compile(PERSON_ID)


class FaceRefused(Exception):
    """A request the bridge will not carry out (`code` is a short word, `words` plain English)."""

    def __init__(self, code: str, words: str) -> None:
        super().__init__(words)
        self.code = code
        self.words = words


class FaceLibraryPort(Protocol):
    async def counts(self) -> dict[str, int]: ...

    async def register(self, name: str, image: bytes, content_type: str) -> None: ...

    async def delete(self, name: str) -> None: ...

    async def recent(self) -> list[str]: ...

    async def recent_image(self, file: str) -> bytes: ...

    async def classify(self, name: str, file: str) -> None: ...


class HttpFrigateFaces:
    """Frigate's face library over its internal API (endpoints unverified, see the module note)."""

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._c = client or httpx.AsyncClient(timeout=FRIGATE_TIMEOUT_S, follow_redirects=False)

    async def _json(self, method: str, path: str, **kw: Any) -> Any:
        r = await self._c.request(method, self._base + path, **kw)
        r.raise_for_status()
        return r.json() if r.content else {}

    async def counts(self) -> dict[str, int]:
        data = await self._json("GET", "/api/faces")
        if not isinstance(data, dict):
            raise ValueError("faces")
        return {k: len(v) for k, v in data.items() if k != "train" and isinstance(v, list)}

    async def register(self, name: str, image: bytes, content_type: str) -> None:
        await self._json(
            "POST", f"/api/faces/{name}/register", files={"file": ("face", image, content_type)}
        )

    async def delete(self, name: str) -> None:
        data = await self._json("GET", "/api/faces")
        files = data.get(name, []) if isinstance(data, dict) else []
        if files:
            await self._json("POST", f"/api/faces/{name}/delete", json={"ids": list(files)})

    async def recent(self) -> list[str]:
        data = await self._json("GET", "/api/faces")
        train = data.get("train", []) if isinstance(data, dict) else []
        return [f for f in train if isinstance(f, str) and RECENT_FILE.fullmatch(f)][:40]

    async def recent_image(self, file: str) -> bytes:
        if not RECENT_FILE.fullmatch(file):
            raise FaceRefused("bad_file", "That picture isn't one of the recent visitors.")
        r = await self._c.get(f"{self._base}/clips/faces/train/{file}")
        r.raise_for_status()
        return r.content[:MAX_IMAGE_BYTES]

    async def classify(self, name: str, file: str) -> None:
        await self._json("POST", f"/api/faces/train/{name}/classify", json={"training_file": file})

    async def aclose(self) -> None:
        await self._c.aclose()


class FaceLibrary:
    """What the bridge knows about faces: the synced ids (persisted in `faces.json`) and the
    library. All decisions about consent are here."""

    def __init__(
        self,
        library: FaceLibraryPort,
        data_dir: Path,
        retention: Retention,
        *,
        post_ack: Callable[[Ack], Any] | None = None,
        now: Callable[[], float] = time.time,
        also_delete: Callable[[str], Awaitable[bool]] | None = None,
    ) -> None:
        self._lib = library
        self._path = data_dir / "faces.json"
        self._retention = retention
        self._post_ack = post_ack
        self._now = now
        # R11.1 O7: whatever else on this laptop holds this person's face (their named face
        # groups) goes too; False means "something is left", so the delete is not acknowledged
        self._also_delete = also_delete
        self.rev = 0
        self.people: frozenset[str] = frozenset()
        self.deleting: frozenset[str] = frozenset()
        self._load()

    # ---- the synced state ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text())
            state = FacesState.model_validate(raw)
        except (OSError, ValueError):
            return  # nothing synced yet (or unreadable): nobody has consent here
        self.rev = state.rev
        self.people = frozenset(state.people)
        self.deleting = frozenset(state.deleting)

    def _save(self) -> None:
        state = FacesState(
            rev=self.rev, people=tuple(sorted(self.people)), deleting=tuple(sorted(self.deleting))
        )
        tmp = self._path.with_name(f".faces-{secrets.token_hex(4)}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(state.model_dump_json())
        os.replace(tmp, self._path)

    def apply(self, faces: FacesState) -> None:
        """A new faces part from the cloud. A person being deleted never counts as consented.
        An older rev (a push that arrived late) is ignored; a person once asked to be deleted
        stays so until the delete is done here (their id is never un-deleted by a later push)."""
        if faces.rev < self.rev:
            return
        self.rev = faces.rev
        self.deleting = frozenset(faces.deleting) | self.deleting
        self.people = frozenset(faces.people) - self.deleting
        self._save()

    @property
    def retention_on(self) -> bool:
        """Old visitors' pictures are being cleaned up and deletes can finish (the page says
        so when not)."""
        return self._retention.ready

    # ---- decisions -------------------------------------------------------------------------

    def consented(self, person: object) -> bool:
        return isinstance(person, str) and person in self.people and person not in self.deleting

    def match(
        self, sub_label: object, score: object, object_label: object = "person"
    ) -> FaceMatch | None:
        """Frigate's recognition -> the face field of an event, or None. Only a consented id on a
        person at or above the threshold; a typed name, a car's "face", an unknown id: None."""
        if object_label != "person" or not self.consented(sub_label):
            return None
        if isinstance(score, bool) or not isinstance(score, int | float):
            return None
        if not RECOGNITION_THRESHOLD <= score <= 1:
            return None
        return FaceMatch(person=str(sub_label), score=float(score))

    async def enrol(self, person: str, image: bytes) -> int:
        """Add one picture to a consented person. Returns how many pictures they now have."""
        if not isinstance(person, str) or not PERSON.fullmatch(person):
            raise FaceRefused("bad_person", "That isn't a person code.")
        if not self.consented(person):
            raise FaceRefused(
                "no_consent",
                "That person has no consent recorded. Add them in JARVIS -> Faces first.",
            )
        kind = self._kind(image)
        counts = await self._counts()
        if counts.get(person, 0) >= MAX_PER_PERSON:
            raise FaceRefused("too_many", f"At most {MAX_PER_PERSON} pictures a person.")
        await self._call(self._lib.register(person, image, kind))
        return counts.get(person, 0) + 1

    async def enrol_recent(self, person: str, file: str) -> None:
        if not self.consented(person):
            raise FaceRefused("no_consent", "That person has no consent recorded.")
        if not RECENT_FILE.fullmatch(file):
            raise FaceRefused("bad_file", "That picture isn't one of the recent visitors.")
        await self._call(self._lib.classify(person, file))

    @staticmethod
    def _kind(image: bytes) -> str:
        if len(image) > MAX_IMAGE_BYTES:
            raise FaceRefused("too_big", "Pictures can be at most 5 MB.")
        if image.startswith(JPEG):
            return "image/jpeg"
        if image.startswith(PNG):
            return "image/png"
        raise FaceRefused("bad_image", "Use a JPEG or PNG picture.")

    @staticmethod
    async def _call(coro: Awaitable[T]) -> T:
        try:
            async with asyncio.timeout(FRIGATE_TIMEOUT_S):
                return await coro
        except FaceRefused:
            raise
        except Exception:  # noqa: BLE001 - vendor text never leaves the bridge
            raise FaceRefused(
                "frigate_down", "Frigate didn't answer. Check it is running."
            ) from None

    async def _counts(self) -> dict[str, int]:
        return await self._call(self._lib.counts())

    # ---- reads -----------------------------------------------------------------------------

    async def summary(self) -> dict[str, int]:
        """Pictures per consented person (counts only), for the page and the heartbeat."""
        counts = await self._counts()
        return {p: min(counts.get(p, 0), 200) for p in sorted(self.people)[:MAX_PEOPLE]}

    async def recent(self) -> list[str]:
        return await self._call(self._lib.recent())

    async def recent_image(self, file: str) -> bytes:
        if not RECENT_FILE.fullmatch(file):
            raise FaceRefused("bad_file", "That picture isn't one of the recent visitors.")
        return await self._call(self._lib.recent_image(file))

    # ---- deleting --------------------------------------------------------------------------

    async def delete(self, person: str) -> bool:
        """Remove the library entry and every attempt crop of this person. True only when
        nothing of them is left on this laptop (review H4/S5): the folder is one the bridge may
        delete in, every unlink worked, and a fresh look finds none. The file work runs off the
        event loop."""
        if not PERSON.fullmatch(person):
            return False
        await self._call(self._lib.delete(person))
        _, failed = await asyncio.to_thread(self._retention.delete_for, person)
        if failed or not self._retention.ready:
            return False  # crops could remain where nothing is swept: never "done"
        left = await asyncio.to_thread(self._retention.remaining_for, person)
        if left != 0:
            return False
        return self._also_delete is None or await self._also_delete(person)

    async def finish_deletes(self) -> list[str]:
        """Delete every person the cloud asked to delete and ack each. Safe to repeat: the cloud
        keeps asking until it hears the ack. A person that fails stays for the next round."""
        done: list[str] = []
        for person in sorted(self.deleting):
            try:
                if not await self.delete(person):
                    continue
            except FaceRefused:
                continue
            if self._post_ack is not None:
                ack = Ack(
                    type="ack",
                    id=f"fd-{person[3:]}-{int(self._now())}",
                    at=float(self._now()),
                    what="face_deleted",
                    person=person,
                )
                await self._post_ack(ack)
            self.deleting = self.deleting - {person}
            self._save()
            done.append(person)
        return done


class FacesPlugin:
    """The bridge plugin: summary route, heartbeat part, state, and its background tasks."""

    name = "faces"

    def __init__(
        self,
        ctx: BridgeContext,
        library: FaceLibraryPort | None = None,
        *,
        serve: Callable[[FaceLibrary], Any] | None = None,
    ) -> None:
        env = ctx.env
        attempts = env.get("FACES_ATTEMPTS_DIR") or DEFAULT_ATTEMPTS_DIR
        doorstep = env.get("FACES_DOORSTEP_DIR") or DEFAULT_DOORSTEP_DIR
        self.retention = Retention(Path(attempts), Path(doorstep), now=ctx.now)
        if not self.retention.ready:
            log.warning(
                "Faces: the folder of Frigate's face attempts was not found, is wrong or the "
                "bridge may not delete in it, so old pictures of visitors are NOT being cleaned "
                "up and face deletes will wait. Run setup-wsl.sh configure again (it shares "
                "Frigate's face folders with the bridge)."
            )
        lib = library or HttpFrigateFaces(env.get("FRIGATE_URL", "http://frigate:5000"))
        self._lib = lib
        self.library = FaceLibrary(
            lib,
            ctx.data_dir,
            self.retention,
            post_ack=ctx.events.post_event,
            now=ctx.now,
            also_delete=self._forget_groups,
        )
        self._ctx = ctx
        self._serve = serve

    def routes(self) -> Sequence[BridgeRoute]:
        return (BridgeRoute("GET", "/bridge/v1/faces/summary", self._summary),)

    async def _summary(
        self, query: Mapping[str, str], body: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        try:
            people = await self.library.summary()
        except FaceRefused:
            people = {}
        return {"people": people, "retention": "on" if self.retention.ready else "off"}

    def tasks(self) -> Sequence[TaskFactory]:
        out: list[TaskFactory] = [self._deletions, self._retention_loop]
        if self._serve is not None:
            serve = self._serve
            out.append(lambda: serve(self.library))
        return tuple(out)

    async def _deletions(self) -> None:
        while True:
            await self.library.finish_deletes()
            await asyncio.sleep(RETRY_S)

    async def _retention_loop(self) -> None:
        while True:
            await asyncio.to_thread(self.retention.sweep)
            await asyncio.sleep(SWEEP_S)

    def _groups(self) -> Any:
        """The face-groups plugin (R11.1 O7), found when a message arrives; None without it."""
        return self._ctx.peers.get("facegroups")

    async def _forget_groups(self, person: str) -> bool:
        groups = self._groups()
        if groups is None:
            return True
        try:
            return bool(await groups.forget_person(person))
        except Exception as exc:  # noqa: BLE001 - not removed: the delete waits, never "done"
            log.warning("a person's face groups were not removed", exc_info=exc)
            return False

    def _group_pictures(self) -> dict[str, int]:
        """Face pictures the groups plugin keeps for consented people (counts only)."""
        groups = self._groups()
        if groups is None:
            return {}
        try:
            held = dict(groups.person_pictures())
        except Exception as exc:  # noqa: BLE001 - a count only: the heartbeat goes without it
            log.warning("face group counts unreadable", exc_info=exc)
            return {}
        return {p: min(int(n), MAX_PICTURES) for p, n in held.items() if self.library.consented(p)}

    async def heartbeat_part(self) -> HeartbeatParts:
        extra = self._group_pictures()
        try:
            counts = await self.library.summary()
        except FaceRefused:
            # Frigate silent: this part says only what the groups plugin itself holds
            return HeartbeatParts(faces=extra) if extra else HeartbeatParts()
        merged = {p: min(n + extra.get(p, 0), MAX_PICTURES) for p, n in counts.items()}
        return HeartbeatParts(faces=merged)

    async def apply_state(self, state: BridgeState) -> None:
        if state.faces is None:
            return
        self.library.apply(state.faces)
        await self.library.finish_deletes()

    async def aclose(self) -> None:
        """The bridge is stopping (review M10): close Frigate's client."""
        close = getattr(self._lib, "aclose", None)
        if close is not None:
            await close()


def create_plugin(ctx: BridgeContext) -> FacesPlugin:
    """The registry factory (I1 lists it in `homebridge/registry.PLUGINS`)."""
    from jarvis.homebridge.local_page import serve_local_page

    return FacesPlugin(ctx, serve=lambda lib: serve_local_page(lib, ctx))


__all__ = [
    "DEFAULT_ATTEMPTS_DIR",
    "DEFAULT_DOORSTEP_DIR",
    "MAX_IMAGE_BYTES",
    "MAX_PER_PERSON",
    "FaceLibrary",
    "FaceLibraryPort",
    "FaceRefused",
    "FacesPlugin",
    "HttpFrigateFaces",
    "create_plugin",
]

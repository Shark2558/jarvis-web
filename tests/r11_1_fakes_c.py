# tests/r11_1_fakes_c.py -- R11.1 Part C's fakes: hand-made JPEG bytes (never a photo of a real
# person), a face engine that "recognises" the made-up people written into a test picture, and a
# fake Frigate face library. Imported as a top-level module (`from r11_1_fakes_c import ...`).
from __future__ import annotations

import base64
import math
import re
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import home_fakes
import httpx
from faces_fakes import FakeAudit
from fastapi import FastAPI
from photos_fakes import FakePicker

from jarvis.api.home import install_home
from jarvis.facegroups.service import FaceGroupsService
from jarvis.facegroups.store import GroupsStore
from jarvis.faces.service import FacesService
from jarvis.faces.store import FacesStore
from jarvis.home.client import HomeClient
from jarvis.home.heartbeat import HeartbeatHandler
from jarvis.home.link import LinkService
from jarvis.home.store import HomeStore
from jarvis.home.webhook import HomeWebhook
from jarvis.homebridge.app import Bridge, create_bridge
from jarvis.homebridge.config import BridgeConfig
from jarvis.homebridge.face_groups import FaceGroupsPlugin
from jarvis.homebridge.face_types import DIM, SeenFace
from jarvis.homebridge.faces import FacesPlugin
from jarvis.homebridge.plugins import BridgeContext
from jarvis.keyring import Keyring
from jarvis.photos.edge import BridgeHomeEdge
from jarvis.photos.service import PhotosService, PhotosState
from jarvis.storage.docs import MemoryDocs

A = "fp_3a9c12ab34cd"
B = "fp_000000000001"
CROP_NEEDLE = b"CROP-NEEDLE-7f3a91"
PICTURE_NEEDLE = b"PICTURE-NEEDLE-91c2e4"
# sixteen or more numbers in a row: what a leaked embedding looks like in JSON or a log line
EMBEDDING = re.compile(r"(?:-?\d+\.\d+(?:e-?\d+)?\s*,\s*){16,}")


def jpeg_bytes(
    width: int = 8, height: int = 8, *, sof: int = 0xC0, tail: bytes = b"\x12\x34", app: bytes = b""
) -> bytes:
    """A structurally valid JPEG of the declared size (not decodable into a real picture)."""
    return (
        b"\xff\xd8"
        + app
        + b"\xff\xdb\x00\x43\x00"
        + bytes(64)
        + bytes([0xFF, sof])
        + struct.pack(">HBHHB", 11, 8, height, width, 1)
        + b"\x01\x11\x00"
        + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
        + tail
        + b"\xff\xd9"
    )


def vec(person: int, wobble: int = 0) -> tuple[float, ...]:
    """A unit vector: the same made-up person with another wobble is 0.96 alike, another ~0."""
    v = [0.0] * DIM
    v[person % DIM] = 1.0
    v[(person + 40 + wobble) % DIM] = 0.2
    n = math.sqrt(sum(x * x for x in v))
    return tuple(x / n for x in v)


def picture(*people: int, n: int = 0, needle: bool = False) -> bytes:
    """A test "photo": a valid JPEG whose scan data names the made-up people in it (by number)
    and which picture it is. `ScriptedEngine` reads them back."""
    who = ",".join(str(p) for p in people)
    tail = f"<people:{who};n:{n}>".encode() + (PICTURE_NEEDLE if needle else b"")
    return jpeg_bytes(64, 64, tail=tail)


class ScriptedEngine:
    """A face engine for tests: finds exactly the people `picture()` wrote into the bytes. Every
    crop carries CROP_NEEDLE, so a test can prove no crop ever crossed to the cloud."""

    def __init__(self, *, ready: str = "ready") -> None:
        self.ready = ready
        self.seen: list[bytes] = []
        self.own_files: list[bool] = []

    def status(self) -> str:
        return self.ready

    def faces(self, jpeg: bytes, *, own_file: bool = False) -> list[SeenFace]:
        self.seen.append(jpeg)
        self.own_files.append(own_file)
        start = jpeg.find(b"<people:")
        if start < 0:
            return []
        body = jpeg[start + 8 : jpeg.index(b">", start)].decode()
        who, n = body.split(";n:")
        out = []
        for p in (int(x) for x in who.split(",") if x):
            crop = b"\xff\xd8\xff" + CROP_NEEDLE + f"-{p}-{n}".encode()
            out.append(SeenFace(vec(p, int(n) % 30), 0.95, 120, crop))
        return out


class FakeLib:
    """Frigate's face library (`FaceLibraryPort`): pictures by library name; `down` = no answer."""

    def __init__(self) -> None:
        self.pictures: dict[str, list[bytes]] = {}
        self.down = False

    def _check(self) -> None:
        if self.down:
            raise RuntimeError("frigate 10.0.0.5 exploded")

    async def counts(self) -> dict[str, int]:
        self._check()
        return {k: len(v) for k, v in self.pictures.items()}

    async def register(self, name: str, image: bytes, content_type: str) -> None:
        self._check()
        self.pictures.setdefault(name, []).append(image)

    async def delete(self, name: str) -> None:
        self._check()
        self.pictures.pop(name, None)

    async def recent(self) -> list[str]:
        return []

    async def recent_image(self, file: str) -> bytes:
        return b""

    async def classify(self, name: str, file: str) -> None:
        return None


def _base64_forms(needle: bytes) -> list[str]:
    """The needle as it reads inside base64 text, at each of the three byte alignments."""
    out = []
    for lead in range(3):
        text = base64.b64encode(b"\0" * lead + needle).decode()
        out.append(text[(0, 2, 3)[lead] : -4])
    return out


def holds(blob: bytes | str, needle: bytes) -> bool:
    """Is `needle` in there, raw or inside base64 text (at any byte alignment)?"""
    text = blob.decode("latin-1") if isinstance(blob, bytes) else blob
    return needle.decode() in text or any(form in text for form in _base64_forms(needle))


def leaks(blob: bytes | str) -> list[str]:
    """What a cloud-side text must never hold: a picture's or a crop's bytes (raw or base64) or
    anything shaped like an embedding. Returns the kinds found (empty = clean)."""
    text = blob.decode("latin-1") if isinstance(blob, bytes) else blob
    found = [
        kind
        for kind, needle in (("crop", CROP_NEEDLE), ("picture", PICTURE_NEEDLE))
        if holds(text, needle)
    ]
    if EMBEDDING.search(text):
        found.append("embedding")
    return found


# ---- a cloud and a home bridge wired together in process (as tests/home_fakes.py does), with the
# faces and face-groups plugins, a scripted engine and a tap on everything that crosses ----------


class Tap(httpx.AsyncBaseTransport):
    """Records the bodies that cross a transport: `sent` (requests) and `got` (answers)."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner
        self.sent: list[bytes] = []
        self.got: list[bytes] = []
        self.calls: list[tuple[str, str]] = []  # (method, path) of every request

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        self.sent.append(await request.aread())
        response = await self._inner.handle_async_request(request)
        body = await response.aread()
        self.got.append(body)
        return httpx.Response(response.status_code, headers=response.headers, content=body)


@dataclass
class Home:
    """`down` taps cloud -> laptop calls (its `got` is what the laptop ANSWERED); `up` taps the
    laptop's webhook posts (its `sent` is what the laptop SENT). Together they are everything
    the cloud receives from the laptop."""

    clock: Any
    docs: MemoryDocs
    store: HomeStore
    notes: Any
    bridge: Bridge
    client: HomeClient
    webhook: HomeWebhook
    engine: ScriptedEngine
    lib: FakeLib
    down: Tap
    up: Tap
    link: LinkService
    cloud_app: FastAPI
    faces: FacesService  # the cloud's registry: names and consent, never a picture
    audit: FakeAudit
    online: bool = True

    @property
    def groups(self) -> Any:
        return next(p for p in self.bridge.plugins if p.name == "facegroups")

    @property
    def faces_plugin(self) -> Any:
        return next(p for p in self.bridge.plugins if p.name == "faces")

    async def link_up(self) -> str:
        code = (await self.link.code(home_fakes.UID)).code
        return str(await self.bridge.link.link(code, home_fakes.URL, bytes(range(40, 72))))

    def received_by_the_cloud(self) -> bytes:
        return b"\n".join([*self.down.got, *self.up.sent])

    async def beat(self) -> bool:
        assert self.bridge.heartbeat is not None
        return bool(await self.bridge.heartbeat.beat())

    async def aclose(self) -> None:
        await self.bridge.link.aclose()
        await self.bridge.ha.aclose()


class _Sleepy(httpx.AsyncBaseTransport):
    """The laptop asleep: every call fails to connect while `home.online` is False."""

    def __init__(self, inner: httpx.AsyncBaseTransport, home: dict[str, Any]) -> None:
        self._inner, self._home = inner, home

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if not self._home["h"].online:
            raise httpx.ConnectError("asleep")
        return await self._inner.handle_async_request(request)


def build_home(tmp: Path, *, env: dict[str, str] | None = None) -> Home:
    """The cloud's home doors, its Faces registry (acks, heartbeats and the consent state ride
    the real webhook) and the real bridge app with the faces and face-groups plugins."""
    clock = home_fakes.Clock()
    docs = MemoryDocs()
    ring = Keyring(home_fakes.ROOT)
    store = HomeStore(docs, ring, clock=clock)
    notes = home_fakes.Notes()
    app = FastAPI()
    install_home(app)
    up = Tap(httpx.ASGITransport(app=app))
    cfg = BridgeConfig(jarvis_url="https://cloud.test", data_dir=tmp / "data")
    engine, lib = ScriptedEngine(), FakeLib()
    (tmp / "att").mkdir(exist_ok=True)

    def faces_plugin(ctx: BridgeContext) -> FacesPlugin:
        return FacesPlugin(ctx, lib)

    def face_groups_plugin(ctx: BridgeContext) -> FaceGroupsPlugin:
        return FaceGroupsPlugin(ctx, engine=engine)

    bridge = create_bridge(
        cfg,
        (faces_plugin, face_groups_plugin),
        clock=clock,
        http=httpx.AsyncClient(transport=up, base_url="https://cloud.test"),
        ha_http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))),
        env={"FACES_ATTEMPTS_DIR": str(tmp / "att"), **(env or {})},
    )
    holder: dict[str, Any] = {}
    down = Tap(_Sleepy(httpx.ASGITransport(app=bridge.app), holder))
    client = HomeClient(store, clock=clock, resolver=home_fakes.public_resolver, inner=down)
    link = LinkService(store, client, clock=clock, resolver=home_fakes.public_resolver)
    audit = FakeAudit()
    faces = FacesService(
        FacesStore(docs, ring),
        client,
        audit=audit,
        clock=lambda: datetime.fromtimestamp(clock(), UTC),
    )
    handlers = [HeartbeatHandler(store, notes), home_fakes.CameraStandIn(), faces]
    webhook = HomeWebhook(store, handlers, [faces], clock=clock, per_minute=600)
    app.state.home_store = store
    app.state.home_link = link
    app.state.home_webhook = webhook
    home = Home(
        clock, docs, store, notes, bridge, client, webhook, engine, lib, down, up, link, app,
        faces, audit,
    )  # fmt: skip
    holder["h"] = home
    return home


# ---- the cloud's photos and face-groups services over that home --------------------------------


class PhotoPicker(FakePicker):
    """Google's Picker serving the test pictures given (made-up people, see `picture`)."""

    def __init__(self, photos: Sequence[bytes] = (), *, ready: bool = True) -> None:
        super().__init__(ready=ready, items=len(photos))
        self.photos = list(photos)

    async def download(self, uid: str, item: Any) -> bytes:
        self.events.append(f"download {item.id}")
        return self.photos[int(item.id[1:])]


@dataclass
class Cloud:
    home: Home
    picker: PhotoPicker
    photos: PhotosService
    groups: FaceGroupsService

    async def at_home(self, *people: int, n: int = 0, needle: bool = False) -> None:
        """A picture the laptop reads itself (its watched folder): it never passes the cloud."""
        await self.home.groups.look(picture(*people, n=n, needle=needle), own_file=True)

    async def group_of(self, person: int, pictures: int = 3, *, start: int = 0) -> str:
        for i in range(pictures):
            await self.at_home(person, n=start + i)
        view = await self.groups.view(home_fakes.UID)
        return view.groups[-1].id if len(view.groups) == 1 else self._newest(view.groups)

    @staticmethod
    def _newest(groups: Sequence[Any]) -> str:
        return str(max(groups, key=lambda g: g.n).id)

    async def import_all(self, photos: Sequence[bytes]) -> Any:
        """Pick these photos and run the import to its end; returns the last step's result."""
        self.picker.photos = list(photos)
        self.picker.items = PhotoPicker(photos).items
        await self.photos.begin(home_fakes.UID)
        res = await self.photos.collect(home_fakes.UID)
        while res.status == "reading":
            res = await self.photos.collect(home_fakes.UID)
        return res


async def build_cloud(tmp: Path, *, env: dict[str, str] | None = None) -> Cloud:
    home = build_home(tmp, env=env)
    await home.link_up()
    picker = PhotoPicker()
    photos = PhotosService(
        picker, BridgeHomeEdge(home.client), home.faces, None, PhotosState(home.docs)
    )

    async def online(uid: str) -> bool:
        return home.online

    groups = FaceGroupsService(
        lambda: photos,
        GroupsStore(home.docs),
        notifier=lambda: home.notes,
        audit=home.audit,
        laptop_online=lambda: online,
    )
    return Cloud(home, picker, photos, groups)


def consent(**over: Any) -> dict[str, Any]:
    """The Faces panel's consent fields for an adult who said yes."""
    args: dict[str, Any] = {
        "name": "Anjali",
        "relation": "friend",
        "child": False,
        "vip": False,
        "given_by": "self",
        "consent_version": "fc1",
        "confirm": True,
    }
    args.update(over)
    return args

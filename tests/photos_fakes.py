# tests/photos_fakes.py -- in-memory picker, home edge and contacts for the Photos tests (R4 C).
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from faces_fakes import Faces, faces

from jarvis.contacts.client import Contact, Found
from jarvis.photos.edge import EdgeOffline
from jarvis.photos.models import FaceHit, PickedItem, PickerSession
from jarvis.photos.service import PhotosService, PhotosState
from jarvis.storage.docs import MemoryDocs

JPEG = b"\xff\xd8\xff fake"
C1 = "c_0123456789ab"
C2 = "c_ba9876543210"


class FakePicker:
    def __init__(self, *, ready: bool = True, items: int = 2) -> None:
        self.ready = ready
        self.items = [
            PickedItem(f"m{i}", "image/jpeg", f"https://x.googleusercontent.com/{i}")
            for i in range(items)
        ]
        self.deleted: list[str] = []
        self.created = 0

    async def create_session(self, uid: str) -> PickerSession:
        self.created += 1
        return PickerSession("sess1", "https://photos.google.com/picker/x", False, "")

    async def get_session(self, uid: str, sid: str) -> PickerSession:
        return PickerSession(sid, "", self.ready, "")

    async def list_items(self, uid: str, sid: str) -> tuple[PickedItem, ...]:
        return tuple(self.items)

    async def download(self, uid: str, item: PickedItem) -> bytes:
        return JPEG

    async def delete_session(self, uid: str, sid: str) -> None:
        self.deleted.append(sid)


class FakeEdge:
    """The home edge: `script` is one tuple of FaceHit per photo, served in order."""

    def __init__(self, script: Sequence[tuple[FaceHit, ...]] = (), *, online: bool = True) -> None:
        self.script = list(script)
        self.online = online
        self.received: list[bytes] = []
        self.enrolled: list[tuple[str, str]] = []

    async def analyse(self, uid: str, images: Sequence[bytes]) -> tuple[tuple[FaceHit, ...], ...]:
        if not self.online:
            raise EdgeOffline()
        self.received.extend(images)
        return tuple(self.script.pop(0) if self.script else () for _ in images)

    async def enrol(self, uid: str, cluster: str, person_id: str) -> None:
        if not self.online:
            raise EdgeOffline()
        self.enrolled.append((cluster, person_id))


class FakeContacts:
    def __init__(self, names: Sequence[str] = ()) -> None:
        self.names = list(names)
        self.queries: list[str] = []

    async def require(self, uid: str) -> None:
        return None

    async def search(self, uid: str, name: str) -> Found:
        self.queries.append(name)
        hits = tuple(Contact(n) for n in self.names if name.lower() in n.lower())
        return Found(hits, False)


@dataclass
class Rig:
    f: Faces
    picker: FakePicker
    edge: FakeEdge
    contacts: FakeContacts
    state: PhotosState
    svc: PhotosService


def rig(
    script: Sequence[tuple[FaceHit, ...]] = (),
    *,
    ready: bool = True,
    online: bool = True,
    contacts: Sequence[str] = (),
    items: int = 2,
    docs: MemoryDocs | None = None,
) -> Rig:
    f = faces(docs)
    picker, edge, con = (
        FakePicker(ready=ready, items=items),
        FakeEdge(script, online=online),
        FakeContacts(contacts),
    )
    state = PhotosState(f.docs)
    return Rig(f, picker, edge, con, state, PhotosService(picker, edge, f.svc, con, state))  # type: ignore[arg-type]


def consent_args(**over: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "relation": "friend",
        "child": False,
        "vip": False,
        "given_by": "self",
        "consent_version": "fc1",
        "confirm": True,
    }
    args.update(over)
    return args

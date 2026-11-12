# tests/photos_fakes.py -- in-memory picker, home edge and contacts for the Photos tests (R4 C).
from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from faces_fakes import Faces, faces

from jarvis.contacts.client import Contact, Found
from jarvis.integrations.google import GoogleNotFound
from jarvis.photos.edge import EdgeBadReply, EdgeNotReady, EdgeOffline, EdgeRefused
from jarvis.photos.errors import PickerError
from jarvis.photos.models import FaceHit, Forgot, GroupsAtHome, PickedItem, PickerSession
from jarvis.photos.service import PhotosService, PhotosState
from jarvis.storage.docs import MemoryDocs

JPEG = b"\xff\xd8\xff fake"
URI = "https://photos.google.com/picker/x"
C1 = "c_0123456789ab"
C2 = "c_ba9876543210"


class FakePicker:
    """Google's Picker: `items` picked photos served a page at a time (as Google does), each page
    with fresh links. `gone=True` is a session Google has ended (404)."""

    PAGE = 100

    def __init__(self, *, ready: bool = True, items: int = 2) -> None:
        self.ready = ready
        self.items = [
            PickedItem(f"m{i}", "image/jpeg", f"https://x.googleusercontent.com/{i}")
            for i in range(items)
        ]
        self.deleted: list[str] = []
        self.created = 0
        self.max_items: list[int | None] = []
        self.events: list[str] = []
        self.pages = 0  # list calls made
        self.expires = "2999-01-01T00:00:00Z"
        self.slow = 0.0  # seconds each download takes
        self.fail: set[str] = set()  # item ids whose download raises PickerError
        self.gone = False

    async def create_session(self, uid: str, max_items: int | None = None) -> PickerSession:
        self.created += 1
        self.max_items.append(max_items)
        return PickerSession(f"sess{self.created}", URI, False, self.expires)

    async def get_session(self, uid: str, sid: str) -> PickerSession:
        if self.gone:
            raise GoogleNotFound("gone")
        return PickerSession(sid, URI, self.ready, self.expires)

    async def list_page(
        self, uid: str, sid: str, token: str = ""
    ) -> tuple[tuple[PickedItem, ...], str]:
        if self.gone:
            raise GoogleNotFound("gone")
        self.pages += 1
        start = int(token or 0)
        page = tuple(self.items[start : start + self.PAGE])
        nxt = start + self.PAGE
        return page, (str(nxt) if nxt < len(self.items) else "")

    async def download(self, uid: str, item: PickedItem) -> bytes:
        self.events.append(f"download {item.id}")
        if self.slow:
            await asyncio.sleep(self.slow)
        if item.id in self.fail:
            raise PickerError("One of the photos couldn't be read.")
        return JPEG + item.id.encode()

    async def delete_session(self, uid: str, sid: str) -> None:
        self.deleted.append(sid)


class FakeEdge:
    """The home edge: `script` is one tuple of FaceHit per photo, served in order. `kit` is what
    `ready` answers; `refuse` holds picture bytes the laptop won't read."""

    def __init__(self, script: Sequence[tuple[FaceHit, ...]] = (), *, online: bool = True) -> None:
        self.script = list(script)
        self.online = online
        self.received: list[bytes] = []
        self.enrolled: list[tuple[str, str]] = []
        self.events: list[str] = []
        self.bad = False
        self.kit = "ready"
        self.reader_off = False
        self.refuse: set[bytes] = set()
        self.pictures = 3  # what an enrol answers: face pictures now held for that person
        self.home_groups = GroupsAtHome()
        self.forgot: list[tuple[str, ...] | None] = []

    def _up(self) -> None:
        if not self.online:
            raise EdgeOffline()

    async def ready(self, uid: str) -> str:
        self._up()
        return self.kit

    async def analyse(self, uid: str, images: Sequence[bytes]) -> tuple[tuple[FaceHit, ...], ...]:
        self._up()
        if self.bad:
            raise EdgeBadReply()
        if self.reader_off:
            raise EdgeNotReady()
        if any(i in self.refuse for i in images):
            raise EdgeRefused("bad_image", "Your home laptop couldn't read that picture.")
        self.events.append(f"analyse {len(images)}")
        self.received.extend(images)
        return tuple(self.script.pop(0) if self.script else () for _ in images)

    async def enrol(self, uid: str, cluster: str, person_id: str) -> int:
        self._up()
        self.enrolled.append((cluster, person_id))
        return self.pictures

    async def groups(self, uid: str) -> GroupsAtHome:
        self._up()
        return self.home_groups

    async def forget(self, uid: str, groups: Sequence[str] | None) -> Forgot:
        self._up()
        self.forgot.append(None if groups is None else tuple(groups))
        kept = (
            ()
            if groups is None
            else tuple(g for g in self.home_groups.groups if g.id not in set(groups))
        )
        gone = len(self.home_groups.groups) - len(kept)
        self.home_groups = GroupsAtHome(kept, 0, 0 if groups is None else self.home_groups.strays)
        return Forgot(gone, len(kept) + self.home_groups.strays)


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
    edge.events = picker.events  # one timeline: download / analyse order
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

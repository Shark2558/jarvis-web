# tests/faces_fakes.py -- a Faces service over MemoryDocs, a real keyring, a fake home (R3 C).
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from jarvis.faces.directory import Directory
from jarvis.faces.service import FacesService
from jarvis.faces.store import FacesStore
from jarvis.home.ports import BridgeMethod, HomeOffline
from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs

UID = "u_owner"
OTHER = "u_other"
ROOT = bytes(range(1, 33))
T0 = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now = self.now + timedelta(**kw)


class FakeHome:
    """The cloud's `HomeCaller`: records what was pushed; `online=False` is a sleeping laptop."""

    def __init__(self, *, online: bool = True) -> None:
        self.online = online
        self.calls: list[tuple[str, str, Mapping[str, Any] | None]] = []

    async def call(
        self,
        uid: str,
        method: BridgeMethod,
        path: str,
        body: Mapping[str, Any] | None = None,
        *,
        query: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        if not self.online:
            raise HomeOffline()
        self.calls.append((method, path, body))
        return {}


class FakeAudit:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    async def append(self, **kw: Any) -> None:
        self.entries.append(kw)


@dataclass
class Faces:
    docs: MemoryDocs
    store: FacesStore
    home: FakeHome
    clock: Clock
    audit: FakeAudit
    svc: FacesService
    directory: Directory


def faces(docs: MemoryDocs | None = None, *, online: bool = True) -> Faces:
    docs = docs or MemoryDocs()
    clock = Clock()
    store = FacesStore(docs, Keyring(ROOT))
    home = FakeHome(online=online)
    audit = FakeAudit()
    svc = FacesService(store, home, audit=audit, clock=clock)
    return Faces(docs, store, home, clock, audit, svc, Directory(store))


async def add_adult(f: Faces, name: str = "Anjali", **kw: Any) -> Any:
    args: dict[str, Any] = {
        "name": name,
        "relation": "friend",
        "child": False,
        "vip": False,
        "given_by": "self",
        "consent_version": "fc1",
        "confirm": True,
    }
    args.update(kw)
    return await f.svc.add(UID, **args)


async def add_child(f: Faces, name: str = "Mini", **kw: Any) -> Any:
    args: dict[str, Any] = {
        "name": name,
        "relation": "family",
        "child": True,
        "vip": False,
        "given_by": "parent_guardian",
        "consent_version": "fc1",
        "confirm": True,
    }
    args.update(kw)
    return await f.svc.add(UID, **args)


async def enrol(f: Faces, person: Any, pictures: int = 5) -> None:
    """The bridge's heartbeat said this person has pictures at home."""
    await f.svc.apply_pictures(UID, {person.id: pictures})

# src/jarvis/drive/live.py
"""Is a chosen Drive folder still the owner's, and still readable? (slice 12 D1, review F2/F3)

    owned_by(folder, email)   the ownership test, the same for the Use switch and every re-check:
                              when Drive says who shared it with JARVIS (`sharingUser`), that must
                              be the owner's address; when it doesn't say (unverified for consumer
                              accounts), the owner's address must be among `owners`. A sharer who
                              is someone else never passes — even on a folder the owner owns (an
                              editor re-shared it after the owner un-shared it).
    problem(f, id, email)     "" when `f` may be a root; else a short reason: gone (Drive won't
                              show it), not_folder, trashed, not_owner.
    RootChecks                every tool call re-checks every switched-on root against the address
                              stored when the owner switched it on (≤ 60 s cache, per instance).
                              A root that fails is OFF for every tool, but stays in the store: the
                              owner sees "switched on, but JARVIS can't currently read it" and the
                              JARVIS switch stays the authority. The console's view asks Drive
                              afresh (and so teaches the tools at once).

Only a definite answer is cached (Drive answered, or said 404). Any other Drive error is raised:
the call fails, nothing is read (fail closed).
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Iterable

from jarvis.drive.client import DriveClient
from jarvis.drive.ports import DriveFile, DriveNotFound
from jarvis.drive.roots import Root
from jarvis.logging import get_logger

log = get_logger(__name__)

ROOT_CHECK_TTL_S = 60.0
CACHE_SIZE = 200

Owns = Callable[[DriveFile, str | None], bool]


def owned_by(f: DriveFile, email: str | None) -> bool:
    if not email:
        return False
    mine = email.strip().lower()
    if f.sharer is not None:
        return f.sharer == mine
    return mine in f.owners


def problem(f: DriveFile | None, root_id: str, email: str | None, owns: Owns = owned_by) -> str:
    if f is None or f.id != root_id:
        return "gone"
    if not f.is_folder:
        return "not_folder"
    if f.trashed:
        return "trashed"
    if not owns(f, email):
        return "not_owner"
    return ""


class RootChecks:
    def __init__(
        self,
        client: DriveClient,
        *,
        clock: Callable[[], float] = time.monotonic,
        owns: Owns = owned_by,
    ) -> None:
        self.client = client
        self.owns = owns
        self._clock = clock
        self._cache: OrderedDict[tuple[str, str | None], tuple[float, str]] = OrderedDict()

    def remember(self, root_id: str, email: str | None, f: DriveFile | None) -> str:
        """Record what Drive just said about a root (also from the Use switch); its problem."""
        why = problem(f, root_id, email, self.owns)
        key = (root_id, email)
        self._cache[key] = (self._clock() + ROOT_CHECK_TTL_S, why)
        self._cache.move_to_end(key)
        while len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return why

    def forget(self, root_id: str | None = None) -> None:
        if root_id is None:
            self._cache.clear()
            return
        for key in [k for k in self._cache if k[0] == root_id]:
            del self._cache[key]

    async def problem_of(self, root: Root, *, fresh: bool = False) -> str:
        """Why the root may not be read now ("" when it may). Raises other Drive errors."""
        key = (root.id, root.email)
        hit = self._cache.get(key)
        if not fresh and hit is not None and hit[0] > self._clock():
            return hit[1]
        try:
            f: DriveFile | None = await self.client.get(root.id)
        except DriveNotFound:
            f = None
        why = self.remember(root.id, root.email, f)
        if why:
            log.info("drive root is off", extra={"reason": why})  # never the id or the name
        return why

    async def live(self, roots: Iterable[Root]) -> list[Root]:
        """The roots that may be read now (each checked, from the cache when fresh)."""
        return [r for r in roots if not await self.problem_of(r)]


__all__ = ["ROOT_CHECK_TTL_S", "Owns", "RootChecks", "owned_by", "problem"]

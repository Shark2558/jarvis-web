# src/jarvis/drive/guard.py
"""The parents check (slice 12 D1): before ANY read, an item must sit inside a folder the owner
chose. Google already limits what JARVIS's account can see (what was shared with it); this keeps
JARVIS inside what the owner confirmed, whatever else lands in its account (anyone who knows the
address can share things with it) and whatever id a model — or a hostile document — asks for.

    check(id, roots) → the item's fresh metadata, or NotInRoots ("not in your chosen folders")

- No confirmed roots: refused without asking Drive anything. The roots given are the ones that
  passed their own re-check this call (`jarvis.drive.live`): a root that fails it is OFF.
- The item itself is always fetched fresh (trashed or moved shows at once); in the trash → no.
- Its ancestors are walked through `parents` (breadth-first, so a file with two parents needs
  one confirmed path), each folder's metadata cached 60 seconds, at most 12 levels and 40
  look-ups. A confirmed root id on the way → allowed. A trashed folder, a folder Drive won't show
  (404: above what was shared), a cycle, or the limits reached → that path ends.
- Any other Drive error is raised as is (the call fails; nothing is read): fail closed.

`deny` (R2 D9): ids a path may not pass through (the DigiLocker inbox). With a deny list the whole
ancestry is walked, so a file under the inbox is refused even when a chosen root is also above it;
a walk a limit cut short is a no. The inbox itself is refused too.

There is no switch to turn the check off: the eval's negative control injects a guard that
allows everything instead (and must then fail).
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Collection

from jarvis.drive.client import DriveClient, check_id
from jarvis.drive.ports import DriveFile, DriveNotFound, NotInRoots
from jarvis.logging import get_logger

log = get_logger(__name__)

CACHE_TTL_S = 60.0
MAX_DEPTH = 12
MAX_LOOKUPS = 40
CACHE_SIZE = 2_000
NOT_IN_ROOTS = (
    "Not in your chosen folders: JARVIS reads only Drive folders you switched on in "
    "Integrations (and what is inside them)."
)


class WalkBudget:
    """Drive look-ups several walks may still make together (one search's hits). `ran_out` is
    True once a walk was cut short by it (that hit's answer is "not shown", unchecked)."""

    def __init__(self, left: int) -> None:
        self.left = left
        self.ran_out = False

    def take(self) -> bool:
        if self.left <= 0:
            self.ran_out = True
            return False
        self.left -= 1
        return True


class ParentsGuard:
    def __init__(self, client: DriveClient, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.client = client
        self._clock = clock
        self._cache: OrderedDict[str, tuple[float, DriveFile | None]] = OrderedDict()

    def forget(self) -> None:
        self._cache.clear()

    def is_cached(self, fid: str) -> bool:
        """Is this folder's metadata cached and still fresh (a walk past it costs no call)?"""
        hit = self._cache.get(fid)
        return hit is not None and hit[0] > self._clock()

    async def _ancestor(self, fid: str) -> DriveFile | None:
        """A folder above the item: cached metadata, or None when Drive won't show it."""
        hit = self._cache.get(fid)
        now = self._clock()
        if hit is not None and hit[0] > now:
            self._cache.move_to_end(fid)
            return hit[1]
        try:
            f: DriveFile | None = await self.client.get(fid)
        except DriveNotFound:
            f = None
        self._cache[fid] = (now + CACHE_TTL_S, f)
        self._cache.move_to_end(fid)
        while len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return f

    async def inside(
        self,
        item: DriveFile,
        roots: Collection[str],
        budget: WalkBudget | None = None,
        deny: Collection[str] = (),
    ) -> bool:
        """Is the (fresh) `item` inside a confirmed root? `budget`: look-ups shared by several
        walks (one search); spent -> no (fail closed). `deny` (R2 D9, the DigiLocker inbox): ids
        no path may pass through; the whole ancestry is walked, and one denied id on it, or a walk
        cut short by a limit, is a no."""
        if not roots or item.trashed:
            return False
        if item.id in deny:
            return False
        if item.id in roots and not deny:
            return True
        seen = {item.id}
        level = list(item.parents)
        lookups = 0
        found = item.id in roots
        for _ in range(MAX_DEPTH):
            if not level:
                return found
            if any(p in deny for p in level):
                return False
            if any(p in roots for p in level):
                if not deny:
                    return True
                found = True
            nxt: list[str] = []
            for pid in level:
                if pid in seen:
                    continue  # a cycle (or a diamond already walked)
                seen.add(pid)
                lookups += 1
                if lookups > MAX_LOOKUPS:
                    log.warning("drive parents walk: too many look-ups")
                    return False
                if budget is not None and not self.is_cached(pid) and not budget.take():
                    return False
                parent = await self._ancestor(pid)
                if parent is None or parent.trashed:
                    continue
                nxt.extend(p for p in parent.parents if p not in seen)
            level = nxt
        return False  # a root (or a walk's end) beyond MAX_DEPTH levels does not count

    async def check(
        self, file_id: str, roots: Collection[str], *, deny: Collection[str] = ()
    ) -> DriveFile:
        """The item's fresh metadata when it is inside a confirmed root (and under no `deny` id);
        else NotInRoots."""
        fid = check_id(file_id)
        if not roots:
            raise NotInRoots(NOT_IN_ROOTS)
        try:
            item = await self.client.get(fid)
        except DriveNotFound:
            raise NotInRoots(NOT_IN_ROOTS) from None
        # `deny` is passed only when there is one: a guard that overrides `inside` (the evals'
        # negative control) keeps the older signature
        inside = await (self.inside(item, roots, deny=deny) if deny else self.inside(item, roots))
        if not inside:
            raise NotInRoots(NOT_IN_ROOTS)
        return item


__all__ = [
    "CACHE_TTL_S",
    "MAX_DEPTH",
    "NOT_IN_ROOTS",
    "ParentsGuard",
    "WalkBudget",
]

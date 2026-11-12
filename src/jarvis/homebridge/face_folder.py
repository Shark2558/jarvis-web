# src/jarvis/homebridge/face_folder.py
"""The watched photo folder (R11.1 O7; plan D15). Ships in the home kit.

OFF until the owner sets `PHOTOS_DIR` in bridge.env: the kit then mounts that folder READ-ONLY at
`/photos` in the bridge's container. New pictures are read a few a minute (`PHOTOS_PER_MINUTE`,
default 6) and given to the face engine as the owner's own files; nothing in the folder is ever
changed, moved or deleted, and nothing read from it leaves the laptop.

- Only regular `.jpg` / `.jpeg` files (1 KB to 40 MB), at most 8 folders deep; folders whose name
  starts with a dot and every symbolic link are skipped.
- A file is "read" by a hash of its path, size and time (`face_db.FileMarks`), so an unchanged
  file is opened once; a picture the engine refuses is marked "could not be read" at once.
- A file still being written is left for a later pass: it is read only once neither its
  contents nor its details changed for `SETTLE_S` (review C-code M4: a half-copied photo is not
  read as a picture and then again as another).
- A try is counted BEFORE the picture is decoded and kept on disk (review C-sec H2): a file that
  makes the reader fail in any way (or takes the bridge down with it) is tried at most
  `MAX_TRIES` times, then marked "could not be read". A file that can't be opened right now (a
  sync client holds it) is not marked: it is tried again on a later pass, within the same limit.
- One file never stops the scan: whatever goes wrong with it is logged by its kind and the next
  file is read (review C-code H3).
- While the engine can't run, nothing is marked and no try is counted: the folder is read when
  it can.
Standard library only.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path

from jarvis.homebridge.face_db import MAX_TRIES, SKIPPED
from jarvis.homebridge.face_engine import EngineOff
from jarvis.homebridge.face_store import FaceStore
from jarvis.homebridge.jpeg import PictureRefused

log = logging.getLogger(__name__)

SUFFIXES = (".jpg", ".jpeg")
MIN_FILE_BYTES = 1024
MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_DEPTH = 8
MAX_PER_PASS = 2000
RESCAN_S = 600.0
DEFAULT_PER_MINUTE = 6
SETTLE_S = 60.0  # a file must have stayed unchanged this long before it is read
Look = Callable[[bytes], Awaitable[str]]  # the picture's key once the engine has looked at it


class FolderScanner:
    def __init__(
        self,
        root: Path | None,
        look: Look,
        store: FaceStore | None,
        *,
        per_minute: int = DEFAULT_PER_MINUTE,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self.mount = root  # where PHOTOS_DIR is mounted (None: the folder is off)
        self.root = root if store is not None else None
        self._look = look
        self._store = store
        self._pause = 60.0 / max(1, per_minute)
        self._sleep = sleep
        self._wall = wall  # the files' own clock (their mtime), not the bridge's corrected one
        self.settle_s = SETTLE_S
        self.waiting = 0  # pictures found on the last walk that were not read yet

    def attach(self, store: FaceStore) -> None:
        """The store could be opened after all (it was locked or the disk was full at start)."""
        self._store = store
        self.root = self.mount

    @property
    def skipped(self) -> int:
        """Files that could not be read as pictures (kept on disk, a count only)."""
        return self._store.marks.skipped() if self._store is not None else 0

    @property
    def state(self) -> str:
        """off (no folder set) | on | unreadable (set, but the bridge can't list it)."""
        if self.root is None:
            return "off"
        ok = self.root.is_dir() and os.access(self.root, os.R_OK | os.X_OK)
        return "on" if ok else "unreadable"

    # ---- the walk (in a thread) ----------------------------------------------------------------

    def _pictures(self, folder: Path, depth: int = 0) -> Iterator[tuple[Path, int, int, float]]:
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name)
        except OSError:
            return
        for entry in entries:
            try:
                if entry.is_symlink() or entry.name.startswith("."):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if depth < MAX_DEPTH:
                        yield from self._pictures(Path(entry.path), depth + 1)
                elif entry.is_file(follow_symlinks=False):
                    stat = entry.stat(follow_symlinks=False)
                    if (
                        entry.name.lower().endswith(SUFFIXES)
                        and MIN_FILE_BYTES <= stat.st_size <= MAX_FILE_BYTES
                    ):
                        changed = max(stat.st_mtime, stat.st_ctime)
                        yield Path(entry.path), stat.st_size, stat.st_mtime_ns, changed
            except OSError:
                continue

    def _unread(self) -> list[tuple[Path, str]]:
        assert self.root is not None and self._store is not None
        todo: list[tuple[Path, str]] = []
        waiting = 0
        now = self._wall()
        for path, size, mtime, changed in self._pictures(self.root):
            rel = path.relative_to(self.root).as_posix()
            key = hashlib.sha256(f"{rel}\0{size}\0{mtime}".encode()).hexdigest()[:32]
            if self._store.file_seen(key):
                continue
            waiting += 1
            if now - changed < self.settle_s:
                continue  # still being written (or just copied in): a later pass reads it
            if len(todo) < MAX_PER_PASS:
                todo.append((path, key))
        self.waiting = waiting
        return todo

    @staticmethod
    def _read(path: Path) -> bytes | None:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as fh:
                data = fh.read(MAX_FILE_BYTES + 1)
        except OSError:
            return None  # held by another program, or gone: tried again later
        return data if MIN_FILE_BYTES <= len(data) <= MAX_FILE_BYTES else None

    # ---- reading -------------------------------------------------------------------------------

    async def pass_once(self) -> int:
        """Walk the folder once and read what is new, at the set pace. Returns how many files
        were dealt with (0: nothing new, the folder is off, or the engine can't run yet)."""
        if self.state != "on" or self._store is None:
            return 0
        done = 0
        for path, key in await asyncio.to_thread(self._unread):
            try:
                finished = await self._one(path, key)
            except EngineOff:
                return done  # nothing is marked: read again when the engine can run
            except Exception as exc:  # noqa: BLE001 - one file never stops the scan (C-code H3)
                log.warning(
                    "a photo of the folder could not be read", extra={"error": type(exc).__name__}
                )
                finished = True  # its try is counted: after MAX_TRIES it is marked unreadable
            if not finished:
                continue
            done += 1
            self.waiting = max(0, self.waiting - 1)
            await self._sleep(self._pause)
        return done

    async def _one(self, path: Path, key: str) -> bool:
        """One file. True when it was dealt with (read, refused or tried); False when it could
        not be opened right now and waits for a later pass."""
        assert self._store is not None
        marks = self._store.marks
        if await asyncio.to_thread(marks.tries, key) >= MAX_TRIES:
            await asyncio.to_thread(marks.mark, key, SKIPPED)  # skipped: could not be read
            return True
        await asyncio.to_thread(marks.tried, key)  # BEFORE the decoder sees a byte of it
        data = await asyncio.to_thread(self._read, path)
        if data is None:
            return False
        try:
            pic = await self._look(data)
        except EngineOff:
            await asyncio.to_thread(marks.untried, key)
            raise
        except PictureRefused:
            pic = SKIPPED
        await asyncio.to_thread(marks.mark, key, pic)
        return True

    async def run(self) -> None:
        """The bridge task: read what is new, then look again every ten minutes."""
        while True:
            if await self.pass_once() == 0:
                await self._sleep(RESCAN_S)


__all__ = ["DEFAULT_PER_MINUTE", "MAX_FILE_BYTES", "FolderScanner"]

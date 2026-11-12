# src/jarvis/homebridge/face_folder.py
"""The watched photo folder (R11.1 O7; plan D15). Ships in the home kit.

OFF until the owner sets `PHOTOS_DIR` in bridge.env: the kit then mounts that folder READ-ONLY at
`/photos` in the bridge's container. New pictures are read a few a minute (`PHOTOS_PER_MINUTE`,
default 6) and given to the face engine as the owner's own files; nothing in the folder is ever
changed, moved or deleted, and nothing read from it leaves the laptop.

- Only regular `.jpg` / `.jpeg` files (1 KB to 40 MB), at most 8 folders deep; folders whose name
  starts with a dot and every symbolic link are skipped.
- A file is "read" by a hash of its path, size and time (`face_store.files`), so an unchanged
  file is opened once; a picture the engine refuses is marked too, so it is not tried for ever.
- While the engine can't run, nothing is marked: the folder is read when it can.
Standard library only.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path

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
    ) -> None:
        self.root = root if store is not None else None
        self._look = look
        self._store = store
        self._pause = 60.0 / max(1, per_minute)
        self._sleep = sleep
        self.waiting = 0  # pictures found on the last walk that were not read yet
        self.skipped = 0  # files that could not be read as pictures

    @property
    def state(self) -> str:
        """off (no folder set) | on | unreadable (set, but the bridge can't list it)."""
        if self.root is None:
            return "off"
        ok = self.root.is_dir() and os.access(self.root, os.R_OK | os.X_OK)
        return "on" if ok else "unreadable"

    # ---- the walk (in a thread) ----------------------------------------------------------------

    def _pictures(self, folder: Path, depth: int = 0) -> Iterator[tuple[Path, int, int]]:
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
                        yield Path(entry.path), stat.st_size, stat.st_mtime_ns
            except OSError:
                continue

    def _unread(self) -> list[tuple[Path, str]]:
        assert self.root is not None and self._store is not None
        todo: list[tuple[Path, str]] = []
        waiting = 0
        for path, size, mtime in self._pictures(self.root):
            rel = path.relative_to(self.root).as_posix()
            key = hashlib.sha256(f"{rel}\0{size}\0{mtime}".encode()).hexdigest()[:32]
            if self._store.file_seen(key):
                continue
            waiting += 1
            if len(todo) < MAX_PER_PASS:
                todo.append((path, key))
        self.waiting = waiting
        return todo

    @staticmethod
    def _read(path: Path) -> bytes | None:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            return None
        with os.fdopen(fd, "rb") as fh:
            data = fh.read(MAX_FILE_BYTES + 1)
        return data if MIN_FILE_BYTES <= len(data) <= MAX_FILE_BYTES else None

    # ---- reading -------------------------------------------------------------------------------

    async def pass_once(self) -> int:
        """Walk the folder once and read what is new, at the set pace. Returns how many files
        were dealt with (0: nothing new, the folder is off, or the engine can't run yet)."""
        if self.state != "on" or self._store is None:
            return 0
        done = 0
        for path, key in await asyncio.to_thread(self._unread):
            data = await asyncio.to_thread(self._read, path)
            pic = ""
            if data is not None:
                try:
                    pic = await self._look(data)
                except EngineOff:
                    return done  # nothing is marked: read again when the engine can run
                except PictureRefused:
                    pic = ""
            if not pic:
                self.skipped += 1
            await asyncio.to_thread(self._store.mark_file, key, pic)
            done += 1
            self.waiting = max(0, self.waiting - 1)
            await self._sleep(self._pause)
        return done

    async def run(self) -> None:
        """The bridge task: read what is new, then look again every ten minutes."""
        while True:
            if await self.pass_once() == 0:
                await self._sleep(RESCAN_S)


__all__ = ["DEFAULT_PER_MINUTE", "MAX_FILE_BYTES", "FolderScanner"]

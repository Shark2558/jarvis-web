# src/jarvis/homebridge/face_db.py
"""The face groups' SQLite file and the watched folder's bookkeeping (R11.1 O7; plan D15).
Ships in the home kit; standard library only.

`open_db(folder)` opens `{folder}/groups.db` (folder 0700, file 0600, `secure_delete` on). Only
REAL corruption counts as corrupt (review C-code H4): SQLite's "not a database" and "malformed"
answers. Such a file may still hold faces, so it is never unlinked: it is moved aside as
`groups.db.bad-<UTC time>` (with its journal), the laptop's page says so, and a fresh file is
started. Anything else (the file is locked, the disk is read-only or full, an I/O error) is NOT
corruption: it is raised as it is, the face groups are reported unavailable, and nothing on disk
is touched; the plugin tries again later.

`FileMarks` is the watched folder's memory, keyed by a hash of a file's path, size and time:
`files` holds what was read (and `pic = ""` for a file that could not be read), `file_tries`
how often a file was tried. A try is counted BEFORE the picture is decoded (review C-sec H2), so
a file that takes the bridge down with it is skipped after `MAX_TRIES` tries, not tried forever.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

DB = "groups.db"
SET_ASIDE = ".bad-"
BUSY_TIMEOUT_S = 5.0
MAX_TRIES = 3
SKIPPED = ""  # `files.pic` of a file that could not be read
_CORRUPT = frozenset({11, 26})  # SQLITE_CORRUPT, SQLITE_NOTADB (primary result codes)
_SIDECARS = ("", "-journal", "-wal", "-shm")
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS groups (
  id TEXT PRIMARY KEY, n INTEGER, person TEXT, first REAL NOT NULL, last REAL NOT NULL,
  pics INTEGER NOT NULL, faces INTEGER NOT NULL, samples INTEGER NOT NULL, vec BLOB NOT NULL,
  copied INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS crops (
  grp TEXT NOT NULL, slot INTEGER NOT NULL, quality REAL NOT NULL, jpeg BLOB NOT NULL,
  PRIMARY KEY (grp, slot));
CREATE TABLE IF NOT EXISTS pics (key TEXT PRIMARY KEY, at REAL NOT NULL, faces INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS pic_faces (
  pic TEXT NOT NULL, grp TEXT NOT NULL, cosine REAL NOT NULL, PRIMARY KEY (pic, grp));
CREATE INDEX IF NOT EXISTS pic_faces_grp ON pic_faces (grp);
CREATE TABLE IF NOT EXISTS files (key TEXT PRIMARY KEY, pic TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS file_tries (
  key TEXT PRIMARY KEY, tries INTEGER NOT NULL, at REAL NOT NULL);
"""


def is_corrupt(exc: sqlite3.Error) -> bool:
    """True only for a file SQLite says is not a database, or is malformed."""
    code = getattr(exc, "sqlite_errorcode", None)
    if isinstance(code, int):
        return (code & 0xFF) in _CORRUPT
    return isinstance(exc, sqlite3.DatabaseError) and not isinstance(exc, sqlite3.OperationalError)


def _connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600))
    db = sqlite3.connect(path, check_same_thread=False, timeout=BUSY_TIMEOUT_S)
    try:
        db.execute("PRAGMA secure_delete = ON")  # a forgotten face is wiped, not only unlinked
        db.executescript(SCHEMA)
        db.execute("SELECT count(*) FROM groups").fetchone()
    except BaseException:
        db.close()
        raise
    return db


def _set_aside(path: Path) -> str:
    """Move a corrupt file (and its journal) aside, never deleting it. Returns the new name."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    aside = f"{path.name}{SET_ASIDE}{stamp}"
    for extra in _SIDECARS:
        src = Path(f"{path}{extra}")
        if src.exists():
            dst = path.with_name(f"{aside}{extra}")
            os.replace(src, dst)
            os.chmod(dst, 0o600)
    return aside


def open_db(folder: Path) -> sqlite3.Connection:
    """The groups file, opened (and made if new). Raises `sqlite3.Error` unless it is corrupt."""
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    path = folder / DB
    try:
        return _connect(path)
    except sqlite3.Error as exc:
        if not is_corrupt(exc):
            raise  # locked, read-only, full, I/O: report it, touch nothing
        aside = _set_aside(path)
        log.warning("the face groups file was damaged: it was set aside", extra={"file": aside})
        return _connect(path)


def set_aside_files(folder: Path) -> int:
    """How many damaged groups files wait in the folder for the owner to delete them."""
    try:
        names = [p.name for p in folder.iterdir() if p.name.startswith(DB + SET_ASIDE)]
    except OSError:
        return 0
    return sum(1 for n in names if not n.endswith(_SIDECARS[1:]))


class FileMarks:
    """What the watched folder's scanner has read, refused, and tried (ids and counts)."""

    def __init__(
        self, db: sqlite3.Connection, lock: threading.RLock, now: Callable[[], float] = time.time
    ) -> None:
        self._db = db
        self._lock = lock
        self._now = now

    def seen(self, key: str) -> bool:
        with self._lock:
            row = self._db.execute("SELECT 1 FROM files WHERE key = ?", (key,)).fetchone()
        return row is not None

    def tries(self, key: str) -> int:
        with self._lock:
            row = self._db.execute("SELECT tries FROM file_tries WHERE key = ?", (key,)).fetchone()
        return int(row[0]) if row else 0

    def tried(self, key: str) -> int:
        """Count one more try BEFORE the file is decoded (committed at once). Returns it."""
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO file_tries (key, tries, at) VALUES (?, 1, ?) "
                "ON CONFLICT(key) DO UPDATE SET tries = tries + 1, at = excluded.at",
                (key, float(self._now())),
            )
        return self.tries(key)

    def untried(self, key: str) -> None:
        """Give a try back: the engine could not run, which is not the file's fault."""
        with self._lock, self._db:
            self._db.execute(
                "UPDATE file_tries SET tries = MAX(0, tries - 1) WHERE key = ?", (key,)
            )

    def mark(self, key: str, pic: str) -> None:
        """Read (`pic` is the picture's key) or could not be read (`SKIPPED`): done for good."""
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO files (key, pic, at) VALUES (?, ?, ?)",
                (key, pic, float(self._now())),
            )
            self._db.execute("DELETE FROM file_tries WHERE key = ?", (key,))

    def read(self) -> int:
        with self._lock:
            return int(self._db.execute("SELECT COUNT(*) FROM files").fetchone()[0])

    def skipped(self) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) FROM files WHERE pic = ?", (SKIPPED,)
            ).fetchone()
        return int(row[0])

    def forget_all(self) -> None:
        """Rescan: every file may be read again, from its first try."""
        self._db.execute("DELETE FROM files")
        self._db.execute("DELETE FROM file_tries")


__all__ = [
    "BUSY_TIMEOUT_S",
    "DB",
    "MAX_TRIES",
    "SCHEMA",
    "SKIPPED",
    "FileMarks",
    "is_corrupt",
    "open_db",
    "set_aside_files",
]

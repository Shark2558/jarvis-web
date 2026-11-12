# src/jarvis/homebridge/face_store.py
"""The laptop's store of face groups (R11.1 O7; plan D15, D21-C). Ships in the home kit.

Faces found in still pictures (photos JARVIS sends from Google Photos, the watched photo folder)
are grouped here by likeness: a face joins the group it is most like (cosine with the group's
average at least `match`), else it starts a new one. A group seen in `MIN_GROUP_PICS` pictures is
"worth naming" and gets a short number (Group 4). Naming is the cloud's job, after its consent
check; here a group only ever carries a person's id (`fp_<12 hex>`), never a name.

    {data}/facegroups/groups.db   SQLite, folder 0700, file 0600, `secure_delete` on
        groups     id, n, person, first, last, pics, faces, samples, vec (the sum of the unit
                   embeddings), copied (its crops are in the camera's face library)
        crops      the best few small face pictures of a group (shown only on the laptop's page)
        pics       a picture already looked at (a hash of its bytes), so it counts once
        pic_faces  which groups a picture's faces joined
        files      a file of the watched folder already read (a hash of path, size and time)

Nothing here leaves the laptop: the bridge's signed answers carry group ids and counts only. An
unnamed group, and a stray face seen in fewer pictures, is forgotten `keep_days` after it was
FIRST seen (`expire`); "forget" and a person's delete wipe the embeddings, the crops and the
picture rows in one transaction. A forgotten picture is looked at again only after `rescan()`.
"""

from __future__ import annotations

import logging
import os
import secrets
import sqlite3
import struct
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from jarvis.homebridge.face_types import (
    DIM,
    GROUP,
    JPEG,
    MIN_GROUP_PICS,
    PERSON,
    AlreadyNamed,
    Counts,
    GroupRow,
    Placed,
    SeenFace,
    UnknownGroup,
    dot,
    unit,
)

log = logging.getLogger(__name__)

MAX_CROPS = 5
MAX_SAMPLES = 50  # embeddings a group's average is made of; later faces only count
MAX_UNNAMED = 5000
MAX_FACES_PER_PICTURE = 20
MAX_CROP_BYTES = 64 * 1024
DEFAULT_MATCH = 0.42
DAY_S = 86_400.0
DB = "groups.db"
_PACK = struct.Struct(f"<{DIM}f")
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
"""


class FaceStore:
    def __init__(
        self,
        folder: Path,
        *,
        match: float = DEFAULT_MATCH,
        now: Callable[[], float] = time.time,
        max_unnamed: int = MAX_UNNAMED,
    ) -> None:
        self.match = match
        self._now = now
        self._max_unnamed = max_unnamed
        self._lock = threading.RLock()
        self._path = folder / DB
        folder.mkdir(parents=True, exist_ok=True)
        os.chmod(folder, 0o700)
        self._db = self._open()
        self._index: dict[str, tuple[list[float], str | None]] = {}
        for gid, person, vec in self._db.execute("SELECT id, person, vec FROM groups"):
            self._index[gid] = (unit(_PACK.unpack(vec)), person)

    # ---- the file ------------------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if not self._path.exists():
            os.close(os.open(self._path, os.O_WRONLY | os.O_CREAT, 0o600))
        db = sqlite3.connect(self._path, check_same_thread=False)
        db.execute("PRAGMA secure_delete = ON")  # a forgotten face is wiped, not only unlinked
        db.executescript(SCHEMA)
        db.execute("SELECT count(*) FROM groups").fetchone()
        return db

    def _open(self) -> sqlite3.Connection:
        try:
            return self._connect()
        except sqlite3.DatabaseError as exc:
            # unreadable: it may still hold faces, so it is removed (never kept beside the new one)
            log.warning("the face groups file was unreadable and was started again", exc_info=exc)
            for extra in ("", "-journal", "-wal", "-shm"):
                Path(f"{self._path}{extra}").unlink(missing_ok=True)
            return self._connect()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ---- reading -------------------------------------------------------------------------------

    def known(self, pic: str) -> list[Placed] | None:
        """Where a picture's faces went, when it was looked at before; None for a new picture."""
        with self._lock:
            if self._db.execute("SELECT 1 FROM pics WHERE key = ?", (pic,)).fetchone() is None:
                return None
            rows = self._db.execute(
                "SELECT f.grp, g.person, f.cosine FROM pic_faces f JOIN groups g ON g.id = f.grp "
                "WHERE f.pic = ? ORDER BY f.rowid",
                (pic,),
            ).fetchall()
        return [Placed(g, p, float(c)) for g, p, c in rows]

    def groups(self) -> list[GroupRow]:
        """Unnamed groups worth naming, the most pictures first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id, n, person, pics, first, last FROM groups "
                "WHERE person IS NULL AND pics >= ? ORDER BY pics DESC, last DESC, id",
                (MIN_GROUP_PICS,),
            ).fetchall()
        return [GroupRow(*r) for r in rows]

    def counts(self) -> Counts:
        with self._lock:
            groups, strays, named = self._db.execute(
                "SELECT COALESCE(SUM(person IS NULL AND pics >= ?), 0), "
                "COALESCE(SUM(person IS NULL AND pics < ?), 0), "
                "COALESCE(SUM(person IS NOT NULL), 0) FROM groups",
                (MIN_GROUP_PICS, MIN_GROUP_PICS),
            ).fetchone()
        return Counts(int(groups), int(strays), int(named))

    def crops(self, group: str) -> list[bytes]:
        """A group's face pictures, the best first. Only the laptop's own page shows them."""
        with self._lock:
            rows = self._db.execute(
                "SELECT jpeg FROM crops WHERE grp = ? ORDER BY quality DESC, slot", (group,)
            ).fetchall()
        return [bytes(r[0]) for r in rows]

    def person_pictures(self) -> dict[str, int]:
        """Face pictures kept per named person (counts only; the heartbeat carries them)."""
        with self._lock:
            rows = self._db.execute(
                "SELECT g.person, COUNT(*) FROM crops c JOIN groups g ON g.id = c.grp "
                "WHERE g.person IS NOT NULL GROUP BY g.person"
            ).fetchall()
        return {str(p): int(n) for p, n in rows}

    def file_seen(self, key: str) -> bool:
        with self._lock:
            row = self._db.execute("SELECT 1 FROM files WHERE key = ?", (key,)).fetchone()
        return row is not None

    def files_read(self) -> int:
        with self._lock:
            return int(self._db.execute("SELECT COUNT(*) FROM files").fetchone()[0])

    def uncopied(self) -> list[tuple[str, str]]:
        """Named groups whose crops are not in the camera's face library yet."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id, person FROM groups WHERE person IS NOT NULL AND copied = 0 ORDER BY id"
            ).fetchall()
        return [(str(g), str(p)) for g, p in rows]

    # ---- writing -------------------------------------------------------------------------------

    def place(self, pic: str, faces: Sequence[SeenFace]) -> list[Placed]:
        """One picture's faces into their groups, in the order given. A picture seen before is
        answered from the record and counts nothing twice."""
        faces = list(faces)[:MAX_FACES_PER_PICTURE]
        vectors = [unit(f.vector) for f in faces]  # refuse a bad picture before storing anything
        with self._lock:
            before = self.known(pic)
            if before is not None and len(before) >= len(faces):
                return before
            now = float(self._now())
            placed: dict[int, Placed] = {}
            with self._db:
                taken: set[str] = set()
                for i in sorted(range(len(faces)), key=lambda k: -faces[k].quality):
                    found = self._settle(pic, faces[i], vectors[i], taken, now)
                    if found is not None:
                        placed[i] = found
                        taken.add(found.group)
                self._db.execute(
                    "INSERT INTO pics (key, at, faces) VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET at = excluded.at, faces = excluded.faces",
                    (pic, now, len(faces)),
                )
            return [placed[i] for i in sorted(placed)]

    def _settle(
        self, pic: str, face: SeenFace, vector: list[float], taken: set[str], now: float
    ) -> Placed | None:
        gid, cosine = self._best(vector, taken)
        if gid is None:
            gid, cosine = self._start(vector, now), 0.0
            if gid is None:
                return None  # the store is full of groups worth keeping: this face is not kept
        else:
            self._join(gid, vector, now)
        fresh = self._db.execute(
            "INSERT OR IGNORE INTO pic_faces (pic, grp, cosine) VALUES (?, ?, ?)",
            (pic, gid, cosine),
        ).rowcount
        if fresh:
            self._db.execute("UPDATE groups SET pics = pics + 1 WHERE id = ?", (gid,))
            self._number(gid)
        self._keep_crop(gid, face)
        return Placed(gid, self._index[gid][1], cosine)

    def _best(self, vector: list[float], taken: set[str]) -> tuple[str | None, float]:
        best, score = None, self.match
        for gid, (centre, _) in self._index.items():
            if gid in taken:
                continue
            cosine = dot(vector, centre)
            if cosine >= score:
                best, score = gid, cosine
        return best, (min(1.0, score) if best is not None else 0.0)

    def _start(self, vector: list[float], now: float) -> str | None:
        unnamed = sum(1 for _, person in self._index.values() if person is None)
        if unnamed >= self._max_unnamed:
            oldest = self._db.execute(
                "SELECT id FROM groups WHERE person IS NULL AND pics < ? ORDER BY last, id LIMIT 1",
                (MIN_GROUP_PICS,),
            ).fetchone()
            if oldest is None:
                return None
            self._drop([str(oldest[0])])
        gid = "c_" + secrets.token_hex(6)
        self._db.execute(
            "INSERT INTO groups (id, first, last, pics, faces, samples, vec) "
            "VALUES (?, ?, ?, 0, 1, 1, ?)",
            (gid, now, now, _PACK.pack(*vector)),
        )
        self._index[gid] = (vector, None)
        return gid

    def _join(self, gid: str, vector: list[float], now: float) -> None:
        samples, vec = self._db.execute(
            "SELECT samples, vec FROM groups WHERE id = ?", (gid,)
        ).fetchone()
        if samples < MAX_SAMPLES:
            total = [a + b for a, b in zip(_PACK.unpack(vec), vector, strict=True)]
            self._db.execute(
                "UPDATE groups SET samples = samples + 1, vec = ? WHERE id = ?",
                (_PACK.pack(*total), gid),
            )
            self._index[gid] = (unit(total), self._index[gid][1])
        self._db.execute("UPDATE groups SET faces = faces + 1, last = ? WHERE id = ?", (now, gid))

    def _number(self, gid: str) -> None:
        """Group 1, 2, 3...: given once, when a group becomes worth naming."""
        pics, n = self._db.execute("SELECT pics, n FROM groups WHERE id = ?", (gid,)).fetchone()
        if n is not None or pics < MIN_GROUP_PICS:
            return
        self._db.execute(
            "INSERT INTO meta (k, v) VALUES ('next_n', 1) ON CONFLICT(k) DO UPDATE SET v = v + 1"
        )
        (number,) = self._db.execute("SELECT v FROM meta WHERE k = 'next_n'").fetchone()
        self._db.execute("UPDATE groups SET n = ? WHERE id = ?", (number, gid))

    def _keep_crop(self, gid: str, face: SeenFace) -> None:
        if not face.crop.startswith(JPEG) or len(face.crop) > MAX_CROP_BYTES:
            return
        held = self._db.execute(
            "SELECT slot, quality FROM crops WHERE grp = ? ORDER BY quality, slot", (gid,)
        ).fetchall()
        if len(held) < MAX_CROPS:
            slot = min(set(range(MAX_CROPS)) - {s for s, _ in held})
        elif face.quality > held[0][1]:
            slot = held[0][0]
        else:
            return
        self._db.execute(
            "INSERT OR REPLACE INTO crops (grp, slot, quality, jpeg) VALUES (?, ?, ?, ?)",
            (gid, slot, face.quality, face.crop),
        )

    def name(self, group: str, person: str) -> int:
        """Give a group a consented person's id. Returns how many face pictures it holds."""
        if not isinstance(group, str) or not GROUP.fullmatch(group):
            raise UnknownGroup(group)
        if not isinstance(person, str) or not PERSON.fullmatch(person):
            raise ValueError("a person is named by an fp_ id only")
        with self._lock, self._db:
            row = self._db.execute("SELECT person FROM groups WHERE id = ?", (group,)).fetchone()
            if row is None:
                raise UnknownGroup(group)
            if row[0] is not None and row[0] != person:
                raise AlreadyNamed(group)
            if row[0] is None:
                self._db.execute(
                    "UPDATE groups SET person = ?, copied = 0 WHERE id = ?", (person, group)
                )
                self._index[group] = (self._index[group][0], person)
            (kept,) = self._db.execute(
                "SELECT COUNT(*) FROM crops WHERE grp = ?", (group,)
            ).fetchone()
        return int(kept)

    def copied(self, group: str) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE groups SET copied = 1 WHERE id = ?", (group,))

    def mark_file(self, key: str, pic: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO files (key, pic, at) VALUES (?, ?, ?)",
                (key, pic, float(self._now())),
            )

    # ---- forgetting ----------------------------------------------------------------------------

    def _drop(self, ids: Iterable[str]) -> int:
        gone = 0
        for gid in ids:
            self._db.execute(
                "DELETE FROM pics WHERE key IN (SELECT pic FROM pic_faces WHERE grp = ?) AND "
                "NOT EXISTS (SELECT 1 FROM pic_faces o WHERE o.pic = pics.key AND o.grp <> ?)",
                (gid, gid),
            )
            self._db.execute("DELETE FROM pic_faces WHERE grp = ?", (gid,))
            self._db.execute("DELETE FROM crops WHERE grp = ?", (gid,))
            gone += self._db.execute("DELETE FROM groups WHERE id = ?", (gid,)).rowcount
            self._index.pop(gid, None)
        return gone

    def _ids(self, where: str, args: tuple[object, ...] = ()) -> list[str]:
        return [str(r[0]) for r in self._db.execute(f"SELECT id FROM groups WHERE {where}", args)]

    def forget(self, groups: Sequence[str]) -> int:
        """Forget these UNNAMED groups (a named one goes with its person). Returns how many."""
        wanted = [g for g in groups if isinstance(g, str) and GROUP.fullmatch(g)]
        with self._lock, self._db:
            unnamed = set(self._ids("person IS NULL"))
            return self._drop([g for g in dict.fromkeys(wanted) if g in unnamed])

    def forget_all(self) -> int:
        """Every unnamed group and every stray face."""
        with self._lock, self._db:
            return self._drop(self._ids("person IS NULL"))

    def forget_person(self, person: str) -> int:
        if not isinstance(person, str) or not PERSON.fullmatch(person):
            return 0
        with self._lock, self._db:
            return self._drop(self._ids("person = ?", (person,)))

    def expire(self, keep_days: int) -> int:
        """Unnamed groups and strays FIRST seen more than `keep_days` ago (plan D21-C)."""
        cutoff = float(self._now()) - keep_days * DAY_S
        with self._lock, self._db:
            return self._drop(self._ids("person IS NULL AND first < ?", (cutoff,)))

    def rescan(self) -> None:
        """Let the watched folder be read again from the start (a deliberate act on the laptop):
        the "already read" marks go, and so does every picture with a forgotten face."""
        with self._lock, self._db:
            self._db.execute("DELETE FROM files")
            self._db.execute(
                "DELETE FROM pics WHERE faces > "
                "(SELECT COUNT(*) FROM pic_faces f WHERE f.pic = pics.key)"
            )


__all__ = ["DEFAULT_MATCH", "MAX_CROPS", "MAX_FACES_PER_PICTURE", "FaceStore"]

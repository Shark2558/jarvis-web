# tests/test_r11_1_c_face_store_safety.py -- the laptop's face store under trouble (reviews C-code
# H4, M2, M5, M8 and C-sec M2, H2). A locked, read-only or full disk is NOT corruption: nothing is
# touched and the error is reported; a write that fails leaves the in-memory index exactly as the
# database (rolled back) is; the nearest-group search is one matrix product; a copied group's
# pictures are counted once; the consent check runs inside the store's own lock; a file of the
# watched folder is counted as tried before it is decoded.
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from jarvis.homebridge import face_db
from jarvis.homebridge.face_index import CentreIndex
from jarvis.homebridge.face_store import FaceStore, NoConsent
from jarvis.homebridge.face_types import DIM, SeenFace

A = "fp_3a9c12ab34cd"


def vec(person: int, wobble: int = 0) -> tuple[float, ...]:
    v = [0.0] * DIM
    v[person % DIM] = 1.0
    v[(person + 40 + wobble) % DIM] = 0.2
    n = sum(x * x for x in v) ** 0.5
    return tuple(x / n for x in v)


def face(person: int, wobble: int = 0) -> SeenFace:
    return SeenFace(vec(person, wobble), 0.95, 120, b"\xff\xd8\xffCROP-%d-%d" % (person, wobble))


def see(s: FaceStore, person: int, pictures: int) -> str:
    placed = [s.place(f"pic-{person}-{i}", [face(person, i)])[0] for i in range(pictures)]
    return placed[0].group


def yes(person: str) -> bool:
    return True


# ---- H4: only real corruption is corruption ------------------------------------------------------


def test_a_locked_file_is_reported_and_left_exactly_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = FaceStore(tmp_path / "facegroups")
    gid = see(s, 1, 3)
    s.name(gid, A, consented=yes)
    s.close()
    path = tmp_path / "facegroups" / "groups.db"
    before = path.read_bytes()
    monkeypatch.setattr(face_db, "BUSY_TIMEOUT_S", 0.05)
    holder = sqlite3.connect(path)
    holder.execute("BEGIN EXCLUSIVE")  # another process holds the file
    try:
        with pytest.raises(sqlite3.OperationalError):
            FaceStore(tmp_path / "facegroups")
    finally:
        holder.rollback()
        holder.close()
    assert path.read_bytes() == before
    assert not [p for p in path.parent.iterdir() if ".bad-" in p.name]
    again = FaceStore(tmp_path / "facegroups")  # tried again later: everything is still there
    assert again.counts().named == 1


@pytest.mark.parametrize(
    "error",
    [
        sqlite3.OperationalError("database or disk is full"),
        sqlite3.OperationalError("attempt to write a readonly database"),
        sqlite3.OperationalError("disk I/O error"),
    ],
)
def test_an_operational_error_is_never_taken_for_corruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: sqlite3.Error
) -> None:
    s = FaceStore(tmp_path / "facegroups")
    see(s, 1, 3)
    s.close()
    path = tmp_path / "facegroups" / "groups.db"
    before = path.read_bytes()

    def fails(*args: object, **kw: object) -> sqlite3.Connection:
        raise error

    monkeypatch.setattr(face_db.sqlite3, "connect", fails)
    with pytest.raises(sqlite3.OperationalError):
        FaceStore(tmp_path / "facegroups")
    assert path.read_bytes() == before and len(list(path.parent.iterdir())) == 1


def test_only_not_a_database_and_malformed_count_as_corrupt() -> None:
    corrupt = sqlite3.DatabaseError("file is not a database")
    corrupt.sqlite_errorcode = 26  # type: ignore[attr-defined]
    malformed = sqlite3.DatabaseError("database disk image is malformed")
    malformed.sqlite_errorcode = 11  # type: ignore[attr-defined]
    locked = sqlite3.OperationalError("database is locked")
    locked.sqlite_errorcode = 5  # type: ignore[attr-defined]
    full = sqlite3.OperationalError("database or disk is full")
    full.sqlite_errorcode = 13  # type: ignore[attr-defined]
    assert face_db.is_corrupt(corrupt) and face_db.is_corrupt(malformed)
    assert not face_db.is_corrupt(locked) and not face_db.is_corrupt(full)
    assert not face_db.is_corrupt(sqlite3.OperationalError("no code"))


# ---- M2: a failed write leaves no phantom group in memory ---------------------------------------


def test_a_write_that_fails_half_way_leaves_the_index_as_the_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = FaceStore(tmp_path / "facegroups")
    kept = see(s, 1, 3)

    def broken(*args: object) -> None:
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(s, "_keep_crop", broken)
    with pytest.raises(sqlite3.OperationalError):
        s.place("pic-new", [face(7)])  # a new group started in memory, then the write failed
    assert len(s._index) == 1 and kept in s._index  # noqa: SLF001 - the point of the test
    monkeypatch.undo()
    (p,) = s.place("pic-new", [face(7)])  # and the next face goes where it should, no TypeError
    assert p.group != kept and p.cosine == 0.0
    (q,) = s.place("pic-1-later", [face(1, 5)])
    assert q.group == kept


def test_a_failed_forget_keeps_every_group_in_the_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = FaceStore(tmp_path / "facegroups")
    g1, g2 = see(s, 1, 3), see(s, 2, 3)
    db = s._db  # noqa: SLF001

    class Breaks:
        """The connection, except that deleting crops fails: half-way through the drop."""

        def __getattr__(self, name: str) -> object:
            return getattr(db, name)

        def execute(self, sql: str, args: object = ()) -> object:
            if sql.startswith("DELETE FROM crops"):
                raise sqlite3.OperationalError("disk I/O error")
            return db.execute(sql, args)  # type: ignore[arg-type]

        def __enter__(self) -> object:
            return db.__enter__()

        def __exit__(self, *exc: object) -> object:
            return db.__exit__(*exc)  # type: ignore[arg-type]

    monkeypatch.setattr(s, "_db", Breaks())
    with pytest.raises(sqlite3.OperationalError):
        s.forget_all()
    monkeypatch.setattr(s, "_db", db)
    assert {g1, g2} <= {g.id for g in s.groups()}
    assert g1 in s._index and g2 in s._index  # noqa: SLF001


# ---- M5: the nearest-group search is vectorised -------------------------------------------------


def test_the_search_over_five_thousand_groups_is_one_matrix_product() -> None:
    np = pytest.importorskip("numpy")
    index = CentreIndex(np)
    rng = np.random.default_rng(7)
    centres = rng.standard_normal((5_000, DIM)).astype(np.float32)
    centres /= np.linalg.norm(centres, axis=1, keepdims=True)
    for i, c in enumerate(centres):
        index.put(f"c_{i:012x}", c.tolist(), None)
    probe = centres[1234].tolist()
    started = time.perf_counter()
    for _ in range(200):
        gid, cosine = index.best(probe, set(), 0.42)
    took = time.perf_counter() - started
    assert gid == f"c_{1234:012x}" and cosine == pytest.approx(1.0, abs=1e-5)
    assert took < 2.0  # about a millisecond per face; the Python loop needs seconds for this
    # taken groups are passed over, and the plain-Python search agrees with NumPy's
    plain = CentreIndex(None)
    for i, c in enumerate(centres):
        plain.put(f"c_{i:012x}", c.tolist(), None)
    near = (centres[10] + 0.05 * centres[11]).tolist()
    assert index.best(near, set(), 0.42)[0] == plain.best(near, set(), 0.42)[0] == f"c_{10:012x}"
    assert index.best(near, {f"c_{10:012x}"}, 0.42) == plain.best(near, {f"c_{10:012x}"}, 0.42)
    assert index.best(near, {f"c_{10:012x}"}, -1.0)[0] not in (None, f"c_{10:012x}")


def test_dropping_a_group_keeps_every_other_centre_where_it_was() -> None:
    np = pytest.importorskip("numpy")
    for lib in (np, None):
        index = CentreIndex(lib)
        for p in range(40):
            index.put(f"c_{p:012x}", list(vec(p)), None)
        index.drop(f"c_{3:012x}")
        index.drop(f"c_{39:012x}")
        for p in (0, 4, 38):
            assert index.best(list(vec(p, 9)), set(), 0.42)[0] == f"c_{p:012x}"
        assert index.best(list(vec(3, 9)), set(), 0.42)[0] is None and len(index) == 38


# ---- M8: a copied group is counted once ---------------------------------------------------------


def test_a_group_copied_to_the_camera_is_no_longer_counted_here(tmp_path: Path) -> None:
    s = FaceStore(tmp_path / "facegroups")
    g1, g2 = see(s, 1, 3), see(s, 2, 3)
    s.name(g1, A, consented=yes)
    s.name(g2, A, consented=yes)
    assert s.person_pictures() == {A: 6}
    s.copied(g1)  # its crops are in Frigate's library now: Frigate counts them
    assert s.person_pictures() == {A: 3}
    s.copied(g2)
    assert s.person_pictures() == {} and s.holds(A)  # still held here, counted by Frigate
    s.forget_person(A)
    assert not s.holds(A)


# ---- C-sec M2: the consent check runs inside the store's lock -----------------------------------


def test_naming_asks_for_consent_inside_the_lock_and_writes_nothing_without_it(
    tmp_path: Path,
) -> None:
    s = FaceStore(tmp_path / "facegroups")
    gid = see(s, 1, 3)
    held: list[bool] = []

    def gone(person: str) -> bool:
        held.append(s._lock._is_owned())  # type: ignore[attr-defined]  # noqa: SLF001
        return False

    with pytest.raises(NoConsent):
        s.name(gid, A, consented=gone)
    assert held == [True]
    assert s.counts().named == 0 and s.groups()[0].id == gid


def test_a_delete_that_starts_while_a_name_waits_leaves_no_group_named(tmp_path: Path) -> None:
    """The interleaving: the cloud's name passed the plugin's first look at consent; then the
    person's delete starts (consent gone) and runs `forget_person`; only then does the name
    reach the store. The store's own check refuses it, so nothing named survives."""
    s = FaceStore(tmp_path / "facegroups")
    gid = see(s, 1, 3)
    consent = {A}
    entered, release = threading.Event(), threading.Event()
    result: list[object] = []

    def slow_check(person: str) -> bool:
        entered.set()
        release.wait(5)
        return person in consent

    def naming() -> None:
        try:
            result.append(s.name(gid, A, consented=slow_check))
        except NoConsent as exc:
            result.append(exc)

    worker = threading.Thread(target=naming)
    worker.start()
    assert entered.wait(5)
    consent.discard(A)  # the delete begins while the name holds the lock
    deleter = threading.Thread(target=s.forget_person, args=(A,))
    deleter.start()
    release.set()
    worker.join(5)
    deleter.join(5)
    assert isinstance(result[0], NoConsent)
    assert not s.holds(A) and s.counts().named == 0


# ---- C-sec H2: a file is counted as tried before it is decoded ----------------------------------


def test_a_try_is_counted_before_decoding_and_cleared_when_marked(tmp_path: Path) -> None:
    s = FaceStore(tmp_path / "facegroups")
    assert s.marks.tried("file-1") == 1
    assert s.marks.tried("file-1") == 2
    s.close()
    again = FaceStore(tmp_path / "facegroups")  # it survives the bridge going down mid-decode
    assert again.marks.tries("file-1") == 2
    again.marks.untried("file-1")
    assert again.marks.tries("file-1") == 1
    again.marks.mark("file-1", face_db.SKIPPED)
    assert again.marks.tries("file-1") == 0 and again.marks.skipped() == 1
    again.rescan()
    assert again.marks.skipped() == 0 and not again.file_seen("file-1")

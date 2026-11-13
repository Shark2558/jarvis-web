# tests/test_r11_1_c_face_store.py -- R11.1 O7 (plan D15, D21-C): the laptop's store of face
# groups. A face seen in 3 pictures is a group worth naming; the same picture counts once; a named
# group makes later faces that person; an unnamed group and a stray face expire; "forget" removes
# the embeddings, the crops and the picture rows; everything is private on disk.
from __future__ import annotations

import math
import sqlite3
import stat
from pathlib import Path

import pytest

from jarvis.homebridge.face_db import set_aside_files
from jarvis.homebridge.face_store import FaceStore
from jarvis.homebridge.face_types import (
    DIM,
    MIN_GROUP_PICS,
    AlreadyNamed,
    SeenFace,
    UnknownGroup,
)

A = "fp_3a9c12ab34cd"
B = "fp_000000000001"
DAY = 86_400.0


def YES(person: str) -> bool:  # noqa: N802 - reads as the answer it is
    """The consent check, as the faces plugin answers it for a person who agreed."""
    return True


class Clock:
    def __init__(self, t: float = 1_800_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def vec(person: int, wobble: int = 0) -> tuple[float, ...]:
    """A unit vector: the same person with another wobble is 0.96 alike, another person ~0."""
    v = [0.0] * DIM
    v[person] = 1.0
    v[(person + 40 + wobble) % DIM] = 0.2
    n = math.sqrt(sum(x * x for x in v))
    return tuple(x / n for x in v)


def face(person: int, wobble: int = 0, *, score: float = 0.95, size: int = 120) -> SeenFace:
    return SeenFace(vec(person, wobble), score, size, b"\xff\xd8\xffCROP-%d-%d" % (person, wobble))


def store(tmp_path: Path, clock: Clock | None = None, **kw: object) -> FaceStore:
    return FaceStore(tmp_path / "facegroups", now=clock or Clock(), **kw)  # type: ignore[arg-type]


def see(s: FaceStore, person: int, pictures: int, *, start: int = 0) -> str:
    """The same person in `pictures` different pictures; returns the group id."""
    placed = [s.place(f"pic-{person}-{start + i}", [face(person, i)])[0] for i in range(pictures)]
    assert len({p.group for p in placed}) == 1
    return placed[0].group


def test_a_face_seen_in_three_pictures_becomes_a_group_worth_naming(tmp_path: Path) -> None:
    s = store(tmp_path)
    assert MIN_GROUP_PICS == 3
    gid = see(s, 1, 2)
    assert s.groups() == [] and s.counts().strays == 1  # two pictures: not yet worth naming
    assert see(s, 1, 1, start=2) == gid
    (row,) = s.groups()
    assert (row.id, row.n, row.pics, row.person) == (gid, 1, 3, None)
    assert s.counts().groups == 1 and s.counts().strays == 0


def test_the_same_picture_twice_counts_once(tmp_path: Path) -> None:
    s = store(tmp_path)
    assert s.known("pic-x") is None
    first = s.place("pic-x", [face(1)])
    again = s.place("pic-x", [face(1)])
    assert [p.group for p in again] == [p.group for p in first]
    assert s.known("pic-x") is not None and len(s.known("pic-x") or []) == 1
    see(s, 1, 2, start=10)
    (row,) = s.groups()
    assert row.pics == 3  # pic-x once, plus two more


def test_a_picture_with_no_face_is_remembered_as_seen(tmp_path: Path) -> None:
    s = store(tmp_path)
    assert s.place("pic-empty", []) == []
    assert s.known("pic-empty") == []


def test_two_people_in_one_picture_never_share_a_group(tmp_path: Path) -> None:
    s = store(tmp_path)
    one, two = s.place("pic-1", [face(1), face(1, 1)])  # two near-identical faces, one picture
    assert one.group != two.group
    a, b = s.place("pic-2", [face(1, 2), face(2)])
    assert a.group in {one.group, two.group} and b.group not in {one.group, two.group}


def test_naming_a_group_makes_later_faces_that_person(tmp_path: Path) -> None:
    s = store(tmp_path)
    gid = see(s, 1, 3)
    other = see(s, 2, 3)
    assert s.name(gid, A, consented=YES) == 3  # three crops are kept for that person
    (later,) = s.place("pic-new", [face(1, 9)])
    assert later.group == gid and later.person == A and later.cosine >= s.match
    (stranger,) = s.place("pic-new-2", [face(2, 9)])
    assert stranger.group == other and stranger.person is None
    assert [g.id for g in s.groups()] == [other]  # a named group is no longer "to name"
    assert s.person_pictures() == {A: 4} and s.counts().named == 1
    assert all(c.startswith(b"\xff\xd8\xff") for c in s.crops(gid)) and len(s.crops(gid)) == 4


def test_a_group_takes_one_name_only_and_an_unknown_group_none(tmp_path: Path) -> None:
    s = store(tmp_path)
    gid = see(s, 1, 3)
    s.name(gid, A, consented=YES)
    assert s.name(gid, A, consented=YES) == 3  # the same name again: nothing changes
    with pytest.raises(AlreadyNamed):
        s.name(gid, B, consented=YES)
    with pytest.raises(UnknownGroup):
        s.name("c_0123456789ab", A, consented=YES)
    for bad in ("", "c_xyz", "../x", "fp_3a9c12ab34cd"):
        with pytest.raises(UnknownGroup):
            s.name(bad, A, consented=YES)
    with pytest.raises(ValueError):
        s.name(see(s, 3, 3), "Anjali", consented=YES)  # a name is never an id


def test_only_the_best_few_crops_are_kept(tmp_path: Path) -> None:
    s = store(tmp_path)
    for i in range(8):
        s.place(f"p{i}", [face(1, i, score=0.80 + i / 100, size=100 + i)])
    (row,) = s.groups()
    crops = s.crops(row.id)
    assert len(crops) == 5
    assert b"CROP-1-7" in crops[0] and all(b"CROP-1-0" not in c for c in crops)  # best first


def test_an_unnamed_group_and_a_stray_expire_and_a_named_group_does_not(tmp_path: Path) -> None:
    clock = Clock()
    s = store(tmp_path, clock)
    named, unnamed = see(s, 1, 3), see(s, 2, 3)
    see(s, 3, 1)  # a stray: one picture only
    s.name(named, A, consented=YES)
    clock.t += 89 * DAY
    see(s, 2, 1, start=50)  # still being seen: the 90 days run from the FIRST sighting
    assert s.expire(90) == 0
    clock.t += 2 * DAY
    assert s.expire(90) == 2  # the unnamed group and the stray
    assert s.groups() == [] and s.counts().strays == 0 and s.counts().named == 1
    assert s.crops(unnamed) == [] and len(s.crops(named)) == 3
    (again,) = s.place("pic-after", [face(2, 7)])
    assert again.group != unnamed  # the embeddings are gone: the same face starts a new group


def test_forget_removes_embeddings_crops_and_picture_rows_of_unnamed_groups_only(
    tmp_path: Path,
) -> None:
    s = store(tmp_path)
    named, unnamed = see(s, 1, 3), see(s, 2, 3)
    s.name(named, A, consented=YES)
    assert s.forget([named, unnamed, "c_ffffffffffff", "bad"]) == 1
    assert s.crops(unnamed) == [] and s.known("pic-2-0") is None
    assert s.known("pic-1-0") is not None and len(s.crops(named)) == 3
    raw = (tmp_path / "facegroups" / "groups.db").read_bytes()
    assert (
        b"CROP-2-" not in raw and b"CROP-1-" in raw
    )  # deleted content is wiped, not just unlinked
    see(s, 4, 3)
    see(s, 5, 1)
    assert s.forget_all() == 2 and s.groups() == [] and s.counts().strays == 0
    assert s.counts().named == 1


def test_deleting_a_person_removes_their_groups(tmp_path: Path) -> None:
    s = store(tmp_path)
    g1, g2 = see(s, 1, 3), see(s, 2, 3)
    s.name(g1, A, consented=YES)
    s.name(
        g2, A, consented=YES
    )  # the same person, grouped twice (another angle): both carry the name
    assert s.person_pictures() == {A: 6}
    assert s.forget_person(A) == 2 and s.person_pictures() == {}
    assert s.crops(g1) == [] and s.crops(g2) == [] and s.forget_person(A) == 0
    assert s.forget_person("Anjali") == 0


def test_a_forgotten_group_comes_back_only_after_a_deliberate_rescan(tmp_path: Path) -> None:
    s = store(tmp_path)
    for i in range(3):
        s.place(f"pic-{i}", [face(1, i)])
        s.mark_file(f"file-{i}", f"pic-{i}")
    assert s.file_seen("file-0") and not s.file_seen("file-9")
    s.forget_all()
    assert s.file_seen(
        "file-0"
    )  # the folder's files stay "seen": nothing is grouped again by itself
    s.rescan()
    assert not s.file_seen("file-0") and s.known("pic-0") is None


def test_it_survives_a_restart_and_is_private_on_disk(tmp_path: Path) -> None:
    s = store(tmp_path)
    gid = see(s, 1, 3)
    s.name(gid, A, consented=YES)
    s.close()
    folder = tmp_path / "facegroups"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert stat.S_IMODE((folder / "groups.db").stat().st_mode) == 0o600
    again = store(tmp_path)
    (p,) = again.place("pic-later", [face(1, 5)])
    assert p.group == gid and p.person == A
    assert again.counts().named == 1


def test_the_number_of_unnamed_faces_is_capped_oldest_stray_first(tmp_path: Path) -> None:
    clock = Clock()
    s = store(tmp_path, clock, max_unnamed=3)
    keep = see(s, 1, 3)
    for person in (2, 3, 4):
        clock.t += 1
        see(s, person, 1)
    assert s.counts().groups == 1 and s.counts().strays == 2  # 3 unnamed in all; person 2 went
    assert s.known("pic-2-0") is None and s.groups()[0].id == keep


def test_a_bad_vector_is_refused(tmp_path: Path) -> None:
    s = store(tmp_path)
    for bad in ((1.0,) * 5, (float("nan"),) * DIM, (0.0,) * DIM):
        with pytest.raises(ValueError):
            s.place("pic", [SeenFace(bad, 0.9, 100, b"\xff\xd8\xff")])
    assert s.known("pic") is None


def test_an_unreadable_store_is_set_aside_never_deleted_and_started_again(tmp_path: Path) -> None:
    # review C-code H4: a damaged file may still hold faces: moved aside (timestamped), kept
    folder = tmp_path / "facegroups"
    folder.mkdir()
    damaged = b"not a database at all" * 50
    (folder / "groups.db").write_bytes(damaged)
    s = store(tmp_path)
    assert s.groups() == [] and see(s, 1, 3)
    (aside,) = [p for p in folder.iterdir() if p.name.startswith("groups.db.bad-")]
    assert aside.read_bytes() == damaged  # never unlinked: the owner decides
    assert stat.S_IMODE(aside.stat().st_mode) == 0o600
    assert set_aside_files(folder) == 1


def test_named_groups_wait_for_the_camera_copy(tmp_path: Path) -> None:
    s = store(tmp_path)
    gid = see(s, 1, 3)
    assert s.uncopied() == []
    s.name(gid, A, consented=YES)
    assert s.uncopied() == [(gid, A)]
    s.copied(gid)
    assert s.uncopied() == []
    s.close()
    with sqlite3.connect(tmp_path / "facegroups" / "groups.db") as db:  # ids only, never a name
        assert db.execute("SELECT person FROM groups").fetchall() == [(A,)]

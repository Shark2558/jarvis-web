# tests/test_homebridge_retention.py -- R3 D13/D7: unknown face attempts go after 72 h, recognised
# ones and doorstep attempts after 7 days, a deleted person's at once; nothing outside the folder
# is touched and links are never followed.
from __future__ import annotations

import os
from pathlib import Path

from jarvis.homebridge.retention import Retention

NOW = 1_800_000_000.0
H = 3600.0
A = "fp_3a9c12ab34cd"


def make(path: Path, age_h: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    t = NOW - age_h * H
    os.utime(path, (t, t))
    return path


def test_sweep_ages(tmp_path: Path) -> None:
    att, door = tmp_path / "attempts", tmp_path / "door"
    old_unknown = make(att / "1-unknown-0.5.webp", 73)
    new_unknown = make(att / "2-unknown-0.5.webp", 71)
    kept_new = make(att / f"3-{A}-0.95.webp", 100)
    kept_old = make(att / f"4-{A}-0.95.webp", 24 * 7 + 1)
    door_old = make(door / "d1.jpg", 24 * 7 + 1)
    door_new = make(door / "d2.jpg", 24 * 6)
    res = Retention(att, door, now=lambda: NOW).sweep()
    assert (res.unknown, res.kept, res.doorstep) == (1, 1, 1)
    assert not old_unknown.exists() and not kept_old.exists() and not door_old.exists()
    assert new_unknown.exists() and kept_new.exists() and door_new.exists()


def test_only_image_files_one_folder_deep_and_never_through_links(tmp_path: Path) -> None:
    att = tmp_path / "attempts"
    note = make(att / "readme.txt", 500)
    deep = make(att / "a" / "b" / "x.webp", 500)
    one = make(att / "a" / "y.webp", 500)
    outside = make(tmp_path / "outside" / "z.webp", 500)
    (att / "link").symlink_to(tmp_path / "outside")
    (att / "lnk.webp").symlink_to(outside)
    Retention(att, now=lambda: NOW).sweep()
    assert note.exists() and deep.exists() and outside.exists() and not one.exists()


def test_missing_or_linked_roots_are_quietly_nothing(tmp_path: Path) -> None:
    assert Retention(None, now=lambda: NOW).sweep().unknown == 0
    assert Retention(tmp_path / "nope", now=lambda: NOW).sweep().kept == 0
    real = tmp_path / "real"
    make(real / "q.webp", 500)
    (tmp_path / "ln").symlink_to(real)
    assert Retention(tmp_path / "ln", now=lambda: NOW).sweep().unknown == 0
    assert (real / "q.webp").exists()


def test_delete_for_removes_that_persons_crops_only(tmp_path: Path) -> None:
    att = tmp_path / "attempts"
    mine = make(att / f"1-{A}-0.9.webp", 1)
    other = make(att / "2-fp_000000000001-0.9.webp", 1)
    r = Retention(att, now=lambda: NOW)
    assert r.delete_for("Anjali") == 0 and r.delete_for("fp_*") == 0
    assert r.delete_for(A) == 1
    assert not mine.exists() and other.exists()

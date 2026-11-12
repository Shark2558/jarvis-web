# tests/test_r11_1_c_bridge_folder.py -- R11.1 O7 (plan D15): the watched photo folder on the
# laptop. Off until PHOTOS_DIR is set; new pictures are read a few a minute as the owner's own
# files and grouped; an unchanged file is read once; nothing in the folder is ever touched; what
# is not a plain picture file is skipped; a forgotten group comes back only after a rescan.
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from r11_1_fakes_c import ScriptedEngine, jpeg_bytes, picture

from jarvis.homebridge import face_folder
from jarvis.homebridge.face_groups import FaceGroupsPlugin
from jarvis.homebridge.plugins import BridgeContext


class Events:
    async def post_event(self, event: Any) -> bool:
        return True


class Naps:
    def __init__(self) -> None:
        self.taken: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.taken.append(seconds)


def photo(*people: int, n: int = 0) -> bytes:
    return picture(*people, n=n) + bytes(1100)  # over the 1 KB floor a real photo always clears


def plugin(tmp: Path, *, on: bool = True, **env: str) -> tuple[FaceGroupsPlugin, ScriptedEngine]:
    folder = tmp / "photos"
    folder.mkdir(exist_ok=True)
    settings = {"PHOTOS_MOUNT": str(folder), **env}
    if on:
        settings["PHOTOS_DIR"] = "/mnt/c/Users/someone/Pictures/JARVIS"  # the host's path: a label
    engine = ScriptedEngine()
    ctx = BridgeContext(env=settings, data_dir=tmp / "data", events=Events(), now=lambda: 5.0)
    built = FaceGroupsPlugin(ctx, engine=engine)
    built.folder._sleep = Naps()  # noqa: SLF001 - no real waiting in a test
    return built, engine


async def test_the_folder_is_off_until_photos_dir_is_set(tmp_path: Path) -> None:
    p, engine = plugin(tmp_path, on=False)
    (tmp_path / "photos" / "a.jpg").write_bytes(photo(1))
    assert p.folder.state == "off" and p.groups_view()["folder"] == "off"
    assert await p.folder.pass_once() == 0 and engine.seen == []
    assert len(p.tasks()) == 2  # no scanning task at all


async def test_new_pictures_are_read_as_the_owners_own_and_grouped(tmp_path: Path) -> None:
    p, engine = plugin(tmp_path)
    folder = tmp_path / "photos"
    (folder / "trip").mkdir()
    (folder / "a.jpg").write_bytes(photo(1, n=0))
    (folder / "b.JPG").write_bytes(photo(1, n=1))
    (folder / "trip" / "c.jpeg").write_bytes(photo(1, 2, n=2))
    assert p.folder.state == "on" and len(p.tasks()) == 3
    assert await p.folder.pass_once() == 3
    view = p.groups_view()
    assert [g["photos"] for g in view["groups"]] == [3] and view["strays"] == 1
    assert view["folder"] == "on" and view["read"] == 3
    assert engine.own_files == [True, True, True]  # larger caps, decoded smaller: never refused


async def test_an_unchanged_file_is_read_once_and_a_new_one_is_picked_up(tmp_path: Path) -> None:
    p, engine = plugin(tmp_path)
    folder = tmp_path / "photos"
    (folder / "a.jpg").write_bytes(photo(1, n=0))
    assert await p.folder.pass_once() == 1 and await p.folder.pass_once() == 0
    assert len(engine.seen) == 1
    (folder / "b.jpg").write_bytes(photo(1, n=1))
    assert await p.folder.pass_once() == 1 and len(engine.seen) == 2
    (folder / "a.jpg").write_bytes(photo(1, n=5))  # edited: another size and time, read again
    assert await p.folder.pass_once() == 1 and len(engine.seen) == 3


async def test_the_pace_is_a_few_pictures_a_minute(tmp_path: Path) -> None:
    p, _ = plugin(tmp_path, PHOTOS_PER_MINUTE="4")
    for i in range(3):
        (tmp_path / "photos" / f"{i}.jpg").write_bytes(photo(1, n=i))
    await p.folder.pass_once()
    assert p.folder._sleep.taken == [15.0, 15.0, 15.0]  # type: ignore[attr-defined]  # noqa: SLF001
    assert face_folder.DEFAULT_PER_MINUTE == 6


async def test_nothing_in_the_folder_is_ever_changed(tmp_path: Path) -> None:
    p, _ = plugin(tmp_path)
    folder = tmp_path / "photos"
    for i in range(3):
        (folder / f"{i}.jpg").write_bytes(photo(1, n=i))
    before = {f.name: (f.read_bytes(), f.stat().st_mtime_ns) for f in folder.iterdir()}
    await p.folder.pass_once()
    await p.forget(None)
    await p.expire()
    assert {f.name: (f.read_bytes(), f.stat().st_mtime_ns) for f in folder.iterdir()} == before


async def test_what_is_not_a_plain_picture_file_is_skipped(
    tmp_path: Path, monkeypatch: Any
) -> None:
    p, engine = plugin(tmp_path)
    folder = tmp_path / "photos"
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "secret.jpg").write_bytes(photo(9))
    (folder / "ok.jpg").write_bytes(photo(1))
    (folder / "notes.txt").write_bytes(photo(2))
    (folder / "phone.heic").write_bytes(photo(3))
    (folder / "tiny.jpg").write_bytes(jpeg_bytes())  # under 1 KB: an icon, not a photo
    (folder / ".hidden").mkdir()
    (folder / ".hidden" / "x.jpg").write_bytes(photo(4))
    os.symlink(outside / "secret.jpg", folder / "link.jpg")
    os.symlink(outside, folder / "linked-folder")
    monkeypatch.setattr(face_folder, "MAX_FILE_BYTES", 4000)
    (folder / "huge.jpg").write_bytes(photo(5) + bytes(5000))
    assert await p.folder.pass_once() == 1
    assert len(engine.seen) == 1 and b"<people:1;" in engine.seen[0]


async def test_a_file_the_engine_refuses_is_marked_and_not_tried_for_ever(tmp_path: Path) -> None:
    p, engine = plugin(tmp_path)
    folder = tmp_path / "photos"
    (folder / "broken.jpg").write_bytes(b"GIF89a" + bytes(2000))  # a .jpg that is not a JPEG
    (folder / "big.jpg").write_bytes(jpeg_bytes(30000, 100) + bytes(1100))  # an absurd size
    assert await p.folder.pass_once() == 2 and engine.seen == []
    assert p.folder.skipped == 2 and await p.folder.pass_once() == 0


async def test_while_the_engine_cannot_run_nothing_is_marked(tmp_path: Path) -> None:
    p, engine = plugin(tmp_path)
    (tmp_path / "photos" / "a.jpg").write_bytes(photo(1))
    engine.ready = "the face model files are not on this laptop yet"
    assert await p.folder.pass_once() == 0 and p.groups_view()["read"] == 0
    engine.ready = "ready"
    assert await p.folder.pass_once() == 1  # read as soon as it can


async def test_a_folder_that_cannot_be_listed_says_so(tmp_path: Path) -> None:
    p, _ = plugin(tmp_path, PHOTOS_MOUNT=str(tmp_path / "missing"))
    assert p.folder.state == "unreadable" and p.groups_view()["folder"] == "unreadable"
    assert await p.folder.pass_once() == 0


async def test_a_forgotten_group_comes_back_only_after_a_rescan(tmp_path: Path) -> None:
    p, engine = plugin(tmp_path)
    for i in range(3):
        (tmp_path / "photos" / f"{i}.jpg").write_bytes(photo(1, n=i))
    await p.folder.pass_once()
    assert len(p.groups_view()["groups"]) == 1
    await p.forget(None)
    assert await p.folder.pass_once() == 0 and p.groups_view()["groups"] == []
    await p.rescan()
    assert await p.folder.pass_once() == 3 and len(p.groups_view()["groups"]) == 1
    assert len(engine.seen) == 6

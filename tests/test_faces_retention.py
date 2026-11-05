# tests/test_faces_retention.py -- integrated review H4 / S5: a face delete is never acked while
# the person's pictures are still on the laptop (Frigate's files root-owned, a folder the bridge
# can't write, an unlink that failed), the file work runs off the event loop, and "retention off"
# is said on the laptop's Faces page.
from __future__ import annotations

import os
import pathlib
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from test_homebridge_faces import A, Acks, FakeLib, consent

from jarvis.homebridge import faces as faces_mod
from jarvis.homebridge.faces import FaceLibrary
from jarvis.homebridge.local_page import PORT, bind_host, create_local_app
from jarvis.homebridge.retention import Retention

CODE = "correct-horse-battery"


def _rig(tmp_path: Path) -> tuple[FaceLibrary, Acks, Path, Retention]:
    att = tmp_path / "train"
    att.mkdir()
    crop = att / f"1700000000-{A}-0.9.webp"
    crop.write_bytes(b"x")
    acks = Acks()
    retention = Retention(att)
    fl = FaceLibrary(FakeLib(), tmp_path, retention, post_ack=acks, now=lambda: 1000.0)
    consent(fl, deleting=(A,))
    return fl, acks, crop, retention


async def test_delete_for_unwritable_dir_is_not_ready_and_does_not_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S5: the bridge (uid 10001) can't write Frigate's folder: retention is off, nothing is
    deleted, no ack goes up, the person stays "deleting" (the tests run as root, so the folder's
    own mode can't show it; `os.access` is what the bridge asks)."""
    fl, acks, crop, retention = _rig(tmp_path)
    real = os.access

    def no_write(path: Any, mode: int, *a: Any, **k: Any) -> bool:
        if Path(path) == crop.parent and mode & os.W_OK:
            return False
        return real(path, mode, *a, **k)

    monkeypatch.setattr(os, "access", no_write)
    assert retention.ready is False
    assert await fl.finish_deletes() == []
    assert acks.sent == [] and A in fl.deleting


async def test_a_picture_that_could_not_be_unlinked_means_no_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H4: Frigate's root-owned file -> PermissionError -> counted as not deleted -> no ack."""
    fl, acks, crop, retention = _rig(tmp_path)

    def refuse(self: Path, *a: Any, **k: Any) -> None:
        raise PermissionError("root-owned file from Frigate")

    monkeypatch.setattr(pathlib.Path, "unlink", refuse)
    assert retention.delete_for(A) == (0, 1)
    assert await fl.finish_deletes() == []
    assert acks.sent == [] and A in fl.deleting and crop.exists()
    monkeypatch.undo()
    assert await fl.finish_deletes() == [A] and len(acks.sent) == 1 and not crop.exists()


async def test_a_delete_is_done_only_when_nothing_of_that_person_is_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S5: an unlink that "worked" but left the file (a racing Frigate write) is not done."""
    fl, acks, crop, _ = _rig(tmp_path)
    monkeypatch.setattr(pathlib.Path, "unlink", lambda self, *a, **k: None)
    assert await fl.finish_deletes() == []
    assert acks.sent == [] and crop.exists()


async def test_deletes_and_sweeps_run_off_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fl, _, _, _ = _rig(tmp_path)
    ran: list[str] = []
    real = faces_mod.asyncio.to_thread

    async def spy(fn: Any, *a: Any, **k: Any) -> Any:
        ran.append(getattr(fn, "__name__", "?"))
        return await real(fn, *a, **k)

    monkeypatch.setattr(faces_mod.asyncio, "to_thread", spy)
    assert await fl.finish_deletes() == [A]
    assert "delete_for" in ran


async def test_the_laptop_page_says_when_old_pictures_are_not_being_cleaned_up(
    tmp_path: Path,
) -> None:
    lib, acks = FakeLib(), Acks()
    fl = FaceLibrary(lib, tmp_path, Retention(None), post_ack=acks, now=lambda: 1000.0)
    consent(fl, A)
    app = create_local_app(fl, CODE)
    c = AsyncClient(transport=ASGITransport(app=app), base_url=f"http://localhost:{PORT}")
    assert (await c.post("/faces/api/login", json={"code": CODE})).status_code == 200
    got = (await c.get("/faces/api/people")).json()
    assert got["retention"] == "off"
    page = (Path(faces_mod.__file__).parent / "static" / "faces.js").read_text()
    assert "retention" in page and "not being cleaned up" in page


def test_the_page_binds_where_the_kit_says_inside_its_container() -> None:
    """H2: inside the container the page must listen on the container's address, or Docker's
    127.0.0.1:8098 publish reaches nothing; the Host check still allows only localhost."""
    assert bind_host({}) == "127.0.0.1"
    assert bind_host({"FACES_BIND": "0.0.0.0"}) == "0.0.0.0"
    for bad in ("", "example.com", "10.0.0.1; rm", "::"):
        assert bind_host({"FACES_BIND": bad}) == "127.0.0.1"

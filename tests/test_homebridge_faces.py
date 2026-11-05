# tests/test_homebridge_faces.py -- R3 D13 at home: the bridge refuses a face without consent, only
# a consented id at >= 0.9 on a person becomes a face match, deletes remove the library entry and
# the attempts and ack until heard, heartbeats carry counts only, state survives a restart.
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis.home.ports import Ack, BridgeState, FacesState
from jarvis.homebridge.faces import (
    FaceLibrary,
    FaceRefused,
    FacesPlugin,
    HttpFrigateFaces,
)
from jarvis.homebridge.plugins import BridgeContext, check_routes
from jarvis.homebridge.retention import Retention

A = "fp_3a9c12ab34cd"
B = "fp_000000000001"
JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 100


class FakeLib:
    def __init__(self) -> None:
        self.pictures: dict[str, list[bytes]] = {}
        self.train: list[str] = ["a.webp"]
        self.classified: list[tuple[str, str]] = []
        self.down = False

    def _check(self) -> None:
        if self.down:
            raise RuntimeError("frigate 10.0.0.5 exploded")

    async def counts(self) -> dict[str, int]:
        self._check()
        return {k: len(v) for k, v in self.pictures.items()}

    async def register(self, name: str, image: bytes, content_type: str) -> None:
        self._check()
        self.pictures.setdefault(name, []).append(image)

    async def delete(self, name: str) -> None:
        self._check()
        self.pictures.pop(name, None)

    async def recent(self) -> list[str]:
        self._check()
        return self.train

    async def recent_image(self, file: str) -> bytes:
        self._check()
        return JPEG

    async def classify(self, name: str, file: str) -> None:
        self._check()
        self.classified.append((name, file))


class Acks:
    def __init__(self) -> None:
        self.sent: list[Ack] = []

    async def __call__(self, ack: Ack) -> bool:
        self.sent.append(ack)
        return True


def rig(tmp_path: Path, **kw: Any) -> tuple[FaceLibrary, FakeLib, Acks]:
    lib, acks = FakeLib(), Acks()
    attempts = tmp_path / "attempts"
    attempts.mkdir(exist_ok=True)
    fl = FaceLibrary(lib, tmp_path, Retention(attempts), post_ack=acks, now=lambda: 1000.0, **kw)
    return fl, lib, acks


def consent(fl: FaceLibrary, *people: str, deleting: tuple[str, ...] = ()) -> None:
    fl.apply(FacesState(rev=1, people=people, deleting=deleting))


async def test_an_id_without_consent_is_refused_and_nothing_is_added(tmp_path: Path) -> None:
    fl, lib, _ = rig(tmp_path)
    with pytest.raises(FaceRefused) as err:
        await fl.enrol(A, JPEG)
    assert err.value.code == "no_consent" and lib.pictures == {}
    consent(fl, B)
    with pytest.raises(FaceRefused):
        await fl.enrol(A, JPEG)  # consent for someone else is not consent for A
    assert lib.pictures == {}


@pytest.mark.parametrize("bad", ["Anjali", "", "fp_xyz", "../x", "fp_3a9c12ab34cd/../b", None])
async def test_only_a_person_code_can_be_a_library_name(tmp_path: Path, bad: Any) -> None:
    fl, lib, _ = rig(tmp_path)
    consent(fl, A)
    with pytest.raises(FaceRefused):
        await fl.enrol(bad, JPEG)
    assert lib.pictures == {}


async def test_a_consented_person_takes_jpeg_and_png_under_the_library_id(tmp_path: Path) -> None:
    fl, lib, _ = rig(tmp_path)
    consent(fl, A)
    assert await fl.enrol(A, JPEG) == 1
    assert await fl.enrol(A, PNG) == 2
    assert list(lib.pictures) == [A]  # filed under the id, never a name


async def test_image_rules(tmp_path: Path) -> None:
    fl, lib, _ = rig(tmp_path)
    consent(fl, A)
    for data, code in (
        (b"GIF89a", "bad_image"),
        (JPEG + b"x" * (5 * 1024 * 1024), "too_big"),
        (b"", "bad_image"),
    ):
        with pytest.raises(FaceRefused) as err:
            await fl.enrol(A, data)
        assert err.value.code == code
    lib.pictures[A] = [JPEG] * 20
    with pytest.raises(FaceRefused) as err:
        await fl.enrol(A, JPEG)
    assert err.value.code == "too_many"


async def test_a_person_being_deleted_cannot_be_enrolled(tmp_path: Path) -> None:
    fl, _, _ = rig(tmp_path)
    consent(fl, A, deleting=(A,))
    with pytest.raises(FaceRefused):
        await fl.enrol(A, JPEG)
    assert fl.consented(A) is False


async def test_frigate_trouble_is_plain_words_without_vendor_text(tmp_path: Path) -> None:
    fl, lib, _ = rig(tmp_path)
    consent(fl, A)
    lib.down = True
    with pytest.raises(FaceRefused) as err:
        await fl.enrol(A, JPEG)
    assert err.value.code == "frigate_down" and "10.0.0.5" not in err.value.words


@pytest.mark.parametrize(
    ("label", "score", "obj", "ok"),
    [
        (A, 0.9, "person", True),
        (A, 0.95, "person", True),
        (A, 0.89, "person", False),
        (A, 1.2, "person", False),
        (A, True, "person", False),
        (A, None, "person", False),
        (A, 0.99, "car", False),
        ("Anjali", 0.99, "person", False),  # a name someone typed in Frigate's UI
        (B, 0.99, "person", False),  # an id the cloud never synced
        (None, 0.99, "person", False),
    ],
)
def test_match_only_a_consented_id_at_threshold_on_a_person(
    tmp_path: Path, label: Any, score: Any, obj: str, ok: bool
) -> None:
    fl, _, _ = rig(tmp_path)
    consent(fl, A)
    got = fl.match(label, score, obj)
    assert (got is not None) is ok
    if got is not None:
        assert got.person == A


async def test_delete_removes_library_and_attempts_then_acks(tmp_path: Path) -> None:
    fl, lib, acks = rig(tmp_path)
    consent(fl, A)
    await fl.enrol(A, JPEG)
    crop = tmp_path / "attempts" / f"100-{A}-0.95.webp"
    other = tmp_path / "attempts" / "100-stranger.webp"
    crop.write_bytes(b"x")
    other.write_bytes(b"x")
    consent(fl, deleting=(A,))
    assert await fl.finish_deletes() == [A]
    assert lib.pictures == {} and not crop.exists() and other.exists()
    (ack,) = acks.sent
    assert ack.what == "face_deleted" and ack.person == A


async def test_a_delete_with_frigate_down_is_retried_and_not_acked(tmp_path: Path) -> None:
    fl, lib, acks = rig(tmp_path)
    consent(fl, deleting=(A,))
    lib.down = True
    assert await fl.finish_deletes() == [] and acks.sent == []
    lib.down = False
    assert await fl.finish_deletes() == [A] and len(acks.sent) == 1


async def test_summary_counts_only_consented_people(tmp_path: Path) -> None:
    fl, lib, _ = rig(tmp_path)
    consent(fl, A)
    lib.pictures = {A: [JPEG] * 3, "Intruder": [JPEG] * 9}
    assert await fl.summary() == {A: 3}


async def test_state_survives_a_restart_and_unreadable_state_means_no_consent(
    tmp_path: Path,
) -> None:
    fl, lib, _ = rig(tmp_path)
    consent(fl, A)
    again = FaceLibrary(lib, tmp_path, Retention(None))
    assert again.consented(A) and again.rev == 1
    assert (tmp_path / "faces.json").stat().st_mode & 0o777 == 0o600
    (tmp_path / "faces.json").write_text("{not json")
    assert FaceLibrary(lib, tmp_path, Retention(None)).consented(A) is False


async def test_recent_visitors_can_be_assigned_only_to_a_consented_person(tmp_path: Path) -> None:
    fl, lib, _ = rig(tmp_path)
    consent(fl, A)
    assert await fl.recent() == ["a.webp"]
    await fl.enrol_recent(A, "a.webp")
    assert lib.classified == [(A, "a.webp")]
    with pytest.raises(FaceRefused):
        await fl.enrol_recent(B, "a.webp")
    with pytest.raises(FaceRefused):
        await fl.enrol_recent(A, "../etc/passwd")
    with pytest.raises(FaceRefused):
        await fl.recent_image("../x")


class Events:
    def __init__(self) -> None:
        self.posted: list[Any] = []

    async def post_event(self, event: Any) -> bool:
        self.posted.append(event)
        return True


async def test_the_plugin_serves_counts_heartbeats_state_and_deletes(tmp_path: Path) -> None:
    lib, events = FakeLib(), Events()
    ctx = BridgeContext(env={}, data_dir=tmp_path, events=events, now=lambda: 5.0)
    plugin = FacesPlugin(ctx, lib)
    check_routes([plugin])
    await plugin.apply_state(BridgeState())  # no faces part: unchanged
    await plugin.apply_state(BridgeState(faces=FacesState(rev=2, people=(A,))))
    await plugin.library.enrol(A, JPEG)
    (route,) = plugin.routes()
    assert (route.method, route.path) == ("GET", "/bridge/v1/faces/summary")
    assert await route.handler({}, None) == {"people": {A: 1}}
    assert (await plugin.heartbeat_part()).faces == {A: 1}
    await plugin.apply_state(BridgeState(faces=FacesState(rev=3, deleting=(A,))))
    assert lib.pictures == {} and [e.person for e in events.posted] == [A]
    lib.down = True
    assert (await plugin.heartbeat_part()).faces is None  # Frigate silent: says nothing
    assert await route.handler({}, None) == {"people": {}}
    assert len(plugin.tasks()) == 2


async def test_the_http_adapter_talks_to_frigates_documented_face_api(tmp_path: Path) -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path == "/api/faces":
            return httpx.Response(200, json={A: ["1.webp", "2.webp"], "train": ["t.webp", "../x"]})
        if request.url.path.startswith("/clips/faces/train/"):
            return httpx.Response(200, content=JPEG)
        return httpx.Response(200, json={"success": True})

    api = HttpFrigateFaces(
        "http://frigate:5000", httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    assert await api.counts() == {A: 2}
    assert await api.recent() == ["t.webp"]
    await api.register(A, JPEG, "image/jpeg")
    await api.delete(A)
    await api.classify(A, "t.webp")
    assert await api.recent_image("t.webp") == JPEG
    assert ("POST", f"/api/faces/{A}/register") in seen
    assert ("POST", f"/api/faces/{A}/delete") in seen
    assert ("POST", f"/api/faces/train/{A}/classify") in seen


def test_the_bridge_faces_files_import_nothing_from_the_cloud_app() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "homebridge"
    for name in ("faces.py", "retention.py", "local_page.py"):
        for node in ast.walk(ast.parse((root / name).read_text())):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else []
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods.append(node.module)
            for mod in mods:
                if mod.split(".")[0] == "jarvis":
                    assert mod in {"jarvis.home.ports", "jarvis.home.signing"} or mod.startswith(
                        "jarvis.homebridge."
                    ), (name, mod)

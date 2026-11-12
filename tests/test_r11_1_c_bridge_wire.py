# tests/test_r11_1_c_bridge_wire.py -- R11.1 O7: the photo routes through the REAL signed channel
# (the cloud's HomeClient and the bridge's app, in process). The bridge used to answer 404 here,
# which the cloud showed as "laptop not reachable". Pins: the three routes answer over the signed
# door with ids only; one photo fits (6 MB on that route only) and nothing else grows; a stranger
# cannot make the bridge buffer megabytes; the kit's version tells an old kit from a new one.
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest
from home_fakes import UID
from r11_1_fakes_c import A, build_home, jpeg_bytes, leaks, picture

from jarvis.home import kit, signing
from jarvis.home.client import MAX_REQUEST_BYTES_BY_ROUTE, request_limit
from jarvis.home.ports import BRIDGE_ROUTES, HomeRefused
from jarvis.homebridge import config as bridge_config
from jarvis.homebridge.app import body_limit

PHOTOS = "/bridge/v1/faces/photos"
ENROL = "/bridge/v1/faces/enrol"
GROUPS = "/bridge/v1/faces/groups"
FORGET = "/bridge/v1/faces/groups/forget"


def image(*people: int, n: int = 0, pad: int = 0) -> dict[str, str]:
    data = picture(*people, n=n)
    if pad:  # a bigger file: more scan data, the same 64 x 64 header
        data = jpeg_bytes(64, 64, tail=data[data.index(b"<people:") : -2] + b"A" * pad)
    return {"image": base64.b64encode(data).decode()}


async def test_the_four_routes_answer_over_the_signed_door_with_ids_only(tmp_path: Path) -> None:
    home = build_home(tmp_path)
    await home.link_up()
    ids = set()
    for n in range(3):
        reply = await home.client.call(UID, "POST", PHOTOS, image(1, n=n))
        ids.add(reply["faces"][0]["cluster"])
    assert len(ids) == 1
    listed = await home.client.call(UID, "GET", GROUPS)
    assert [g["photos"] for g in listed["groups"]] == [3] and listed["engine"] == "ready"
    with pytest.raises(HomeRefused) as err:  # nobody is consented yet: the bridge names nobody
        await home.client.call(UID, "POST", ENROL, {"cluster": ids.pop(), "person": A})
    assert err.value.code == "no_consent"
    gone = await home.client.call(UID, "POST", FORGET, {"all": True})
    assert gone == {"forgotten": 1, "left": 0}
    assert leaks(home.received_by_the_cloud()) == []
    await home.aclose()


async def test_the_route_list_is_exactly_these_eleven() -> None:
    assert BRIDGE_ROUTES == frozenset(
        {
            ("GET", "/bridge/v1/health"),
            ("POST", "/bridge/v1/state"),
            ("GET", "/bridge/v1/devices"),
            ("POST", "/bridge/v1/devices/action"),
            ("GET", "/bridge/v1/events"),
            ("GET", "/bridge/v1/packages"),
            ("GET", "/bridge/v1/faces/summary"),
            ("POST", PHOTOS),
            ("POST", ENROL),
            ("GET", GROUPS),
            ("POST", FORGET),
        }
    )


async def test_one_photo_fits_and_only_that_route_takes_more_than_64_kb(tmp_path: Path) -> None:
    six_mb = 6 * 1024 * 1024
    assert bridge_config.MAX_BODY_BYTES == 64 * 1024
    assert bridge_config.MAX_BODY_BYTES_BY_ROUTE == {("POST", PHOTOS): six_mb}
    assert body_limit("POST", PHOTOS) == six_mb == request_limit("POST", PHOTOS)
    assert MAX_REQUEST_BYTES_BY_ROUTE == {("POST", PHOTOS): six_mb}  # the cloud's side, unchanged
    for method, path in BRIDGE_ROUTES - {("POST", PHOTOS)}:
        assert body_limit(method, path) == 64 * 1024, path
    home = build_home(tmp_path)
    await home.link_up()
    reply = await home.client.call(UID, "POST", PHOTOS, image(1, pad=300_000))  # ~400 KB of JSON
    assert len(reply["faces"]) == 1
    await home.aclose()


class Upload:
    """A raw request to the bridge's app that counts how much of its body was asked for."""

    def __init__(self, path: str, headers: dict[str, str], chunks: list[bytes]) -> None:
        self.scope = {
            "type": "http",
            "method": "POST",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        }
        self._chunks = list(chunks)
        self.read = 0
        self.status = 0

    async def receive(self) -> dict[str, Any]:
        if not self._chunks:
            return {"type": "http.request", "body": b"", "more_body": False}
        chunk = self._chunks.pop(0)
        self.read += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": bool(self._chunks)}

    async def send(self, message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            self.status = message["status"]

    async def run(self, app: Any) -> int:
        await app(self.scope, self.receive, self.send)
        return self.status


async def test_a_stranger_cannot_make_the_bridge_read_megabytes(tmp_path: Path) -> None:
    home = build_home(tmp_path)
    await home.link_up()
    megabyte = [b"x" * 65_536] * 16
    now, nonce, mac = int(home.clock()), "A" * 22, "A" * 43
    home_id = (await home.store.status(UID)).home_id
    for headers in (
        {},  # no signature at all
        {signing.HEADER: "garbage"},
        {signing.HEADER: f"v1;h=h_00000000;t={now};n={nonce};s={mac}"},  # another home
        {signing.HEADER: f"v1;h={home_id};t={now - 3600};n={nonce};s={mac}"},  # an old time
    ):
        up = Upload(PHOTOS, headers, megabyte)
        assert await up.run(home.bridge.app) == 401 and up.read == 0, headers
    # this home's id and a fresh time but a forged signature: read (once, capped), then refused
    forged = Upload(PHOTOS, {signing.HEADER: f"v1;h={home_id};t={now};n={nonce};s={mac}"}, megabyte)
    assert await forged.run(home.bridge.app) == 401
    assert home.engine.seen == []  # nothing reached a handler
    # a small route never reads past its 64 KB, signed or not
    up = Upload(ENROL, {}, megabyte)
    assert await up.run(home.bridge.app) == 413 and up.read <= 2 * 65_536
    # and the photo route itself stops at 6 MB
    up = Upload(PHOTOS, {"content-length": str(7 * 1024 * 1024)}, megabyte)
    assert await up.run(home.bridge.app) == 413 and up.read == 0
    await home.aclose()


async def test_a_signed_photo_is_read_and_a_bad_one_refused_in_a_signed_answer(
    tmp_path: Path,
) -> None:
    home = build_home(tmp_path)
    await home.link_up()
    with pytest.raises(HomeRefused) as err:
        await home.client.call(UID, "POST", PHOTOS, {"image": "bm90IGEgcGljdHVyZQ=="})
    assert err.value.code == "bad_image"
    home.engine.ready = "no models"
    with pytest.raises(HomeRefused) as err:
        await home.client.call(UID, "POST", PHOTOS, image(1))
    assert err.value.code == "no_engine"
    assert "face reader" in str(err.value)  # the cloud's own words for that code
    await home.aclose()


def test_this_kit_is_version_two_and_an_older_bridge_is_out_of_date() -> None:
    assert bridge_config.BRIDGE_VERSION == "0.2.0" == kit.KIT_VERSION
    assert kit.outdated("0.1.0") and not kit.outdated("0.2.0")
    assert bridge_config.PHOTOS_SINCE == "0.2.0"


async def test_the_health_route_says_the_version_so_the_cloud_can_tell_an_old_kit(
    tmp_path: Path,
) -> None:
    home = build_home(tmp_path)
    await home.link_up()
    health = await home.client.call(UID, "GET", "/bridge/v1/health")
    assert health["version"] == "0.2.0"
    assert json.dumps(health).count("0.2.0") == 1
    await home.aclose()

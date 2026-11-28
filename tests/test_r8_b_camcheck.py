# tests/test_r8_b_camcheck.py -- R8 builder B, row 377 (docs/plans/r8-vision.md v8.0.4 section 4.6,
# ADR-49): the no-cloud camera check, against a FAKE camera in this file (standard library only: an
# asyncio ONVIF responder with WS-Security digest checking and an RTSP responder with digest login).
#   - only a private-range IPv4 address is checked (RFC 1918), and only that address is talked to,
#     whatever addresses the camera hands back
#   - the check passes only when ONVIF, Profile S (a main and a sub-stream), RTSP on both streams
#     and H.264 answer, AND they still answer after the camera's internet is blocked and it is
#     restarted; it fails in plain words naming the missing piece
#   - the camera's password stays on the laptop: never in a reply, a log line or the cloud's view;
#     the cloud's route refuses a public address before asking and a reply carrying anything more
# ruff: noqa: E501 -- the fake camera's SOAP, SDP and RTSP lines read best whole
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import stat
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jarvis.api.auth import require_auth
from jarvis.api.camera_spots import CheckView, build_camera_setup, router
from jarvis.api.identity import current_user
from jarvis.home.ports import HomeOffline, HomeRefused
from jarvis.homebridge import camcheck
from jarvis.homebridge.camcheck import (
    CamCheck,
    Login,
    LoginBook,
    Probe,
    private_ip,
)
from jarvis.homebridge.plugins import BridgeContext
from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs

IP = "192.168.1.40"
USER, PASSWORD = "admin", "L0cal-0nly-pass"  # the fake camera's own, never a real one
MAKER = "FakeCam Industries"
SDP = "v=0\r\no=- 1 1 IN IP4 0.0.0.0\r\ns=Fake\r\nm=video 0 RTP/AVP 96\r\na=rtpmap:96 {codec}/90000\r\n"


# ---- the fake camera -----------------------------------------------------------------------------
class FakeCamera:
    """An IP camera on 127.0.0.1: ONVIF on its "port 80", RTSP on its "port 554". `needs_cloud`
    cameras stop answering once restarted with their internet blocked."""

    def __init__(self, *, onvif: bool = True, profiles: int = 2, codecs: tuple[str, str] = ("H264", "H264"),
                 needs_cloud: bool = False, http_digest: bool = False) -> None:  # fmt: skip
        self.onvif, self.profiles, self.codecs = onvif, profiles, codecs
        self.needs_cloud, self.http_digest = needs_cloud, http_digest
        self.internet, self.dialed = True, []
        self.ports: dict[int, int] = {}
        self._servers: list[asyncio.base_events.Server] = []

    @property
    def answering(self) -> bool:
        return self.internet or not self.needs_cloud

    def restart(self, *, internet: bool) -> None:
        self.internet = internet

    def dial(self, ip: str, port: int) -> tuple[str, int]:
        self.dialed.append((ip, port))
        return "127.0.0.1", self.ports.get(port, 9)  # 9: nothing listens

    async def start(self) -> None:
        if self.onvif:
            s = await asyncio.start_server(self._http, "127.0.0.1", 0)
            self.ports[80] = s.sockets[0].getsockname()[1]
            self._servers.append(s)
        s = await asyncio.start_server(self._rtsp, "127.0.0.1", 0)
        self.ports[554] = s.sockets[0].getsockname()[1]
        self._servers.append(s)

    async def close(self) -> None:
        for s in self._servers:
            s.close()
            await s.wait_closed()

    # ONVIF
    def _wsse_ok(self, body: str) -> bool:
        got = {
            k: re.search(rf"<(?:\w+:)?{k}(?:\s[^>]*)?>([^<]*)<", body)
            for k in ("Username", "Password", "Nonce", "Created")
        }
        if not all(got.values()):
            return False
        user, digest, nonce, created = (m.group(1) for m in got.values() if m)
        want = base64.b64encode(
            hashlib.sha1(base64.b64decode(nonce) + created.encode() + PASSWORD.encode()).digest()
        ).decode()
        return user == USER and digest == want

    def _answer(self, body: str) -> str:
        tok = re.search(r"<ProfileToken>([^<]*)<", body)
        if "GetDeviceInformation" in body:
            return f"<tds:GetDeviceInformationResponse><tds:Manufacturer>{MAKER}</tds:Manufacturer></tds:GetDeviceInformationResponse>"
        if "GetCapabilities" in body:  # another host: the check must not follow it
            return "<tds:GetCapabilitiesResponse><tds:Capabilities><tt:Media><tt:XAddr>http://10.9.9.9/onvif/media</tt:XAddr></tt:Media></tds:Capabilities></tds:GetCapabilitiesResponse>"
        if "GetProfiles" in body:
            names = ["main", "sub"][: self.profiles]
            return (
                "<trt:GetProfilesResponse>"
                + "".join(
                    f'<trt:Profiles token="{n}" fixed="true"><tt:Name>{n}</tt:Name></trt:Profiles>'
                    for n in names
                )
                + "</trt:GetProfilesResponse>"
            )
        if "GetStreamUri" in body and tok:
            sub = 1 if tok.group(1) == "sub" else 0
            return f"<trt:GetStreamUriResponse><trt:MediaUri><tt:Uri>rtsp://10.9.9.9:554/cam/realmonitor?channel=1&amp;subtype={sub}</tt:Uri></trt:MediaUri></trt:GetStreamUriResponse>"
        return ""

    async def _http(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = (await reader.readuntil(b"\r\n\r\n")).decode("latin-1")
            size = int(re.search(r"(?i)content-length:\s*(\d+)", head).group(1))  # type: ignore[union-attr]
            body = (await reader.readexactly(size)).decode()
            if not self.answering:
                return  # its web server waits for its cloud: nothing comes back
            ns = ('xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tds="x" xmlns:trt="y" '
                  'xmlns:tt="z" xmlns:ter="http://www.onvif.org/ver10/error"')  # fmt: skip
            if self.http_digest and "authorization: digest" not in head.lower():
                out, status = (
                    b"",
                    '401 Unauthorized\r\nWWW-Authenticate: Digest realm="x", nonce="n", qop="auth"',
                )
            elif not self.http_digest and not self._wsse_ok(body):
                fault = "<s:Fault><s:Code><s:Value>s:Sender</s:Value><s:Subcode><s:Value>ter:NotAuthorized</s:Value></s:Subcode></s:Code></s:Fault>"
                out, status = (
                    f"<s:Envelope {ns}><s:Body>{fault}</s:Body></s:Envelope>".encode(),
                    "400 Bad Request",
                )
            else:
                out, status = (
                    f"<s:Envelope {ns}><s:Body>{self._answer(body)}</s:Body></s:Envelope>".encode(),
                    "200 OK",
                )
            writer.write(
                f"HTTP/1.1 {status}\r\nContent-Type: application/soap+xml\r\nContent-Length: {len(out)}\r\nConnection: close\r\n\r\n".encode()
                + out
            )
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    # RTSP
    async def _rtsp(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = (await reader.readuntil(b"\r\n\r\n")).decode("latin-1")
            if not self.answering:
                return
            line = head.split("\r\n")[0]
            uri = line.split(" ")[1]
            seq = re.search(r"CSeq: (\d+)", head).group(1)  # type: ignore[union-attr]
            auth = re.search(r"Authorization: Digest (.*)", head)
            ok = False
            if auth:
                f = dict(re.findall(r'(\w+)="([^"]*)"', auth.group(1)))
                ha1 = hashlib.md5(f"{f['username']}:Fake:{PASSWORD}".encode()).hexdigest()
                ha2 = hashlib.md5(f"DESCRIBE:{f['uri']}".encode()).hexdigest()
                ok = (
                    f["username"] == USER
                    and f["response"] == hashlib.md5(f"{ha1}:abc123:{ha2}".encode()).hexdigest()
                )
            if not ok:
                writer.write(
                    f'RTSP/1.0 401 Unauthorized\r\nCSeq: {seq}\r\nWWW-Authenticate: Digest realm="Fake", nonce="abc123"\r\n\r\n'.encode()
                )
            else:
                sdp = SDP.format(codec=self.codecs[1 if uri.endswith("subtype=1") else 0]).encode()
                writer.write(
                    f"RTSP/1.0 200 OK\r\nCSeq: {seq}\r\nContent-Type: application/sdp\r\nContent-Length: {len(sdp)}\r\n\r\n".encode()
                    + sdp
                )
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()


@asynccontextmanager
async def camera(**kw: Any) -> Any:
    cam = FakeCamera(**kw)
    await cam.start()
    try:
        yield cam
    finally:
        await cam.close()


LOGIN = Login(USER, PASSWORD)


def _ok(found: camcheck.Findings) -> dict[str, bool | None]:
    return {p.id: p.ok for p in found.pieces}


# ---- the address --------------------------------------------------------------------------------
@pytest.mark.parametrize("ip", ["192.168.1.40", "10.0.0.5", "172.16.0.1", "172.31.255.254"])
def test_a_home_network_address_is_checked(ip: str) -> None:
    assert private_ip(ip) == ip


@pytest.mark.parametrize(
    "ip",
    ["8.8.8.8", "172.32.0.1", "127.0.0.1", "169.254.1.1", "0.0.0.0", "100.64.0.1", "::1", "fd00::1",
     "camera.local", "192.168.001.040", "192.168.1", "", "192.168.1.40:554", "http://192.168.1.40"],
)  # fmt: skip
def test_anything_else_is_refused(ip: str) -> None:
    assert private_ip(ip) is None


async def test_the_probe_refuses_a_public_address_before_any_connection() -> None:
    async with camera() as cam:
        with pytest.raises(ValueError):
            await Probe(dial=cam.dial).run("8.8.8.8", LOGIN)
        assert cam.dialed == []


# ---- one look ------------------------------------------------------------------------------------
async def test_a_good_camera_answers_every_piece_and_only_its_address_is_dialed() -> None:
    async with camera() as cam:
        found = await Probe(dial=cam.dial).run(IP, LOGIN)
    assert found.ok and found.missing() == ""
    assert _ok(found) == {
        "onvif": True,
        "profiles": True,
        "rtsp_main": True,
        "rtsp_sub": True,
        "h264": True,
    }
    assert {ip for ip, _ in cam.dialed} == {IP}  # never 10.9.9.9, which the camera named


async def test_http_digest_onvif_is_answered_too() -> None:
    async with camera(http_digest=True) as cam:
        found = await Probe(dial=cam.dial).run(IP, LOGIN)
    assert _ok(found)["onvif"] is True and found.ok


@pytest.mark.parametrize(
    ("kw", "login", "missing"),
    [
        ({"onvif": False}, LOGIN, camcheck.W_ONVIF_NO),
        ({"profiles": 1}, LOGIN, camcheck.W_PROFILES_ONE),
        ({"profiles": 0}, LOGIN, camcheck.W_PROFILES_NONE),
        ({"codecs": ("H264", "H265")}, LOGIN, "The sub stream is H.265: set it to H.264 in the camera's own app."),
        ({"codecs": ("MJPEG", "H264")}, LOGIN, "The main stream is MJPEG: set it to H.264 in the camera's own app."),
        ({}, None, camcheck.W_LOGIN_NEED),
        ({}, Login(USER, "wrong"), camcheck.W_LOGIN_BAD),
    ],
)  # fmt: skip
async def test_a_missing_piece_fails_in_plain_words(
    kw: dict[str, Any], login: Login | None, missing: str
) -> None:
    async with camera(**kw) as cam:
        found = await Probe(dial=cam.dial, timeout_s=1.0).run(IP, login)
    assert not found.ok and found.missing() == missing
    assert "Traceback" not in missing and "Error" not in missing


async def test_a_camera_with_no_onvif_leaves_the_streams_unchecked_not_failed() -> None:
    async with camera(onvif=False) as cam:
        found = await Probe(dial=cam.dial, timeout_s=1.0).run(IP, LOGIN)
    assert _ok(found) == {"onvif": False, "rtsp_main": None, "rtsp_sub": None, "h264": None}


# ---- the two stages: "no cloud" ------------------------------------------------------------------
class Sink:
    async def post_event(self, event: Any) -> bool:
        return True


def _plugin(
    cam: FakeCamera, tmp: Path, env: dict[str, str] | None = None, now: list[float] | None = None
) -> CamCheck:
    clock = now if now is not None else [1_764_300_000.0]
    ctx = BridgeContext(env=env or {}, data_dir=tmp, events=Sink(), now=lambda: clock[0])
    book = LoginBook(tmp, env)
    if env is None:
        book.save(IP, USER, PASSWORD)
    return CamCheck(
        ctx,
        probe=Probe(dial=cam.dial, timeout_s=1.0),
        logins=book,
        rounds=3,
        gap_s=0.01,
        wait_s=5.0,
    )


async def _until_done(p: CamCheck, stage: str) -> dict[str, Any]:
    for _ in range(200):
        got = await p.handle({}, {"action": "status", "ip": IP, "stage": stage})
        if got["state"] == "done":
            return got
        await asyncio.sleep(0.02)
    raise AssertionError("the check never finished")


@pytest.mark.parametrize(("needs_cloud", "verdict"), [(False, "pass"), (True, "fail")])
async def test_it_passes_only_if_it_still_answers_with_its_internet_blocked(
    tmp_path: Path, needs_cloud: bool, verdict: str
) -> None:
    async with camera(needs_cloud=needs_cloud) as cam:
        p = _plugin(cam, tmp_path)
        first = await p.handle({}, {"action": "start", "ip": IP, "stage": "first"})
        assert first["state"] == "done" and first["verdict"] == "half"
        assert {c["id"]: c["ok"] for c in first["checks"]}["offline"] is None
        cam.restart(internet=False)  # his steps: block it at the router, restart it
        await p.handle({}, {"action": "start", "ip": IP, "stage": "offline"})
        done = await _until_done(p, "offline")
    assert done["verdict"] == verdict
    off = next(c for c in done["checks"] if c["id"] == "offline")
    if verdict == "pass":
        assert off["ok"] is True and done["rounds_done"] == 3 and done["missing"] == ""
    else:
        assert off["ok"] is False and done["missing"].startswith(
            "Stopped working once its internet was blocked: it needs its cloud service. "
            "ONVIF didn't answer."
        )
    CheckView.model_validate(done)  # exactly what the cloud takes


async def test_the_offline_stage_needs_the_first_one(tmp_path: Path) -> None:
    async with camera() as cam:
        p = _plugin(cam, tmp_path)
        got = await p.handle({}, {"action": "start", "ip": IP, "stage": "offline"})
        done = got if got["state"] == "done" else await _until_done(p, "offline")
    assert done["verdict"] == "fail" and done["missing"] == camcheck.W_OFF_FIRST


async def test_a_first_pass_counts_for_a_day(tmp_path: Path) -> None:
    clock = [1_764_300_000.0]
    async with camera() as cam:
        p = _plugin(cam, tmp_path, now=clock)
        await p.handle({}, {"action": "start", "ip": IP, "stage": "first"})
        clock[0] += 25 * 3600
        await p.handle({}, {"action": "start", "ip": IP, "stage": "offline"})
        done = await _until_done(p, "offline")
    assert done["missing"] == camcheck.W_OFF_FIRST


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"action": "start", "ip": "8.8.8.8"}, "not_private"),
        ({"action": "start", "ip": "127.0.0.1"}, "not_private"),
        ({"action": "start", "ip": IP, "url": "rtsp://x"}, "bad_request"),
        ({"action": "erase", "ip": IP}, "bad_request"),
        ({"action": "start", "ip": IP, "rtsp_port": 0}, "bad_request"),
    ],
)
async def test_the_bridge_route_refuses_in_plain_words(
    tmp_path: Path, body: dict[str, Any], code: str
) -> None:
    async with camera() as cam:
        with pytest.raises(HomeRefused) as got:
            await _plugin(cam, tmp_path).handle({}, body)
        assert cam.dialed == []
    assert got.value.code == code and "Traceback" not in got.value.message


async def test_a_status_for_an_address_never_checked_says_so(tmp_path: Path) -> None:
    async with camera() as cam:
        got = await _plugin(cam, tmp_path).handle({}, {"action": "status", "ip": IP})
    assert got["state"] == "none" and got["missing"] == "No check for that address yet."


# ---- the password stays on the laptop ------------------------------------------------------------
def _leaks(text: str) -> list[str]:
    return [
        x for x in (PASSWORD, "rtsp://", "realmonitor", MAKER, "10.9.9.9", USER + ":") if x in text
    ]


async def test_no_reply_or_log_line_carries_the_password_an_address_or_the_maker(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    async with camera(codecs=("H264", "H265")) as cam:
        p = _plugin(cam, tmp_path)
        bad = await p.handle({}, {"action": "start", "ip": IP, "stage": "first"})
        cam.codecs = ("H264", "H264")
        good = await p.handle({}, {"action": "start", "ip": IP, "stage": "first"})
    for reply in (bad, good):
        assert _leaks(json.dumps(reply)) == [], reply
    assert _leaks(caplog.text) == []
    assert PASSWORD not in repr(LOGIN) and "password" not in repr(LOGIN)


def test_the_login_book_is_the_laptops_own_file(tmp_path: Path) -> None:
    book = LoginBook(tmp_path)
    book.save(IP, USER, PASSWORD)
    path = tmp_path / "camcheck_logins.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert book.get(IP) == LOGIN and book.get("192.168.1.41") is None
    with pytest.raises(ValueError):
        book.save("8.8.8.8", USER, PASSWORD)
    assert book.forget(IP) and book.get(IP) is None


def test_the_home_cameras_own_address_lends_its_login(tmp_path: Path) -> None:
    env = {
        "HOMEVISION_RTSP_URL": f"rtsp://{USER}:L0cal%2D0nly-pass@{IP}:554/cam/realmonitor?subtype=1"
    }
    book = LoginBook(tmp_path, env)
    assert book.get(IP) == LOGIN and book.get("192.168.1.41") is None


async def test_the_login_from_bridge_env_passes_a_check(tmp_path: Path) -> None:
    env = {"HOMEVISION_RTSP_URL": f"rtsp://{USER}:{PASSWORD}@{IP}:554/x"}
    async with camera() as cam:
        got = await _plugin(cam, tmp_path, env=env).handle({}, {"action": "start", "ip": IP})
    assert got["verdict"] == "half"


def test_the_plugin_is_in_the_registry_and_serves_its_one_route(tmp_path: Path) -> None:
    from jarvis.homebridge.registry import PLUGINS

    assert camcheck.create_plugin in PLUGINS
    p = camcheck.create_plugin(BridgeContext(env={}, data_dir=tmp_path, events=Sink()))
    assert [(r.method, r.path) for r in p.routes()] == [("POST", "/bridge/v1/camera-check")]
    assert p.tasks() == ()


# ---- the cloud's route ----------------------------------------------------------------------------
class Kit:
    """The cloud's caller, straight to the plugin (signing is the bridge app's, tested there)."""

    def __init__(
        self,
        plugin: CamCheck | None = None,
        fail: Exception | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.plugin, self.fail, self.extra, self.calls = plugin, fail, extra or {}, []

    async def call(
        self, uid: str, method: str, path: str, body: Any = None, *, query: Any = None
    ) -> dict[str, Any]:
        self.calls.append((method, path, dict(body or {})))
        if self.fail is not None:
            raise self.fail
        assert self.plugin is not None
        return {**(await self.plugin.handle({}, body)), **self.extra}


def _client(kit: Kit | None) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[current_user] = lambda: "u_0123456789abcdef"
    app.state.camera_setup = build_camera_setup(
        MemoryDocs(), Keyring(bytes(range(61, 93))), caller=kit
    )
    return TestClient(app)


def test_the_cloud_refuses_a_public_address_without_asking_the_laptop() -> None:
    kit = Kit(fail=AssertionError("must not be called"))
    r = _client(kit).post("/v1/camera/check", json={"ip": "8.8.8.8"})
    assert r.status_code == 422 and r.json()["error"] == "not_private" and kit.calls == []
    assert "192.168." in r.json()["detail"]


@pytest.mark.parametrize(
    ("kit", "status", "code"),
    [
        (None, 409, "not_linked"),
        (Kit(fail=HomeOffline()), 503, "home_offline"),
        (Kit(fail=HomeRefused("busy", camcheck.W_BUSY)), 409, "busy"),
    ],
)
def test_the_cloud_says_plainly_when_the_laptop_cant_check(
    kit: Kit | None, status: int, code: str
) -> None:
    r = _client(kit).post("/v1/camera/check", json={"ip": IP})
    assert r.status_code == status and r.json()["error"] == code


def test_a_laptop_reply_carrying_more_than_the_view_is_refused() -> None:
    reply = {"ip": IP, "stage": "first", "state": "done", "verdict": "half", "checks": []}
    kit = Kit(extra={"uri": "rtsp://192.168.1.40/x"})
    kit.plugin = type("P", (), {"handle": staticmethod(lambda q, b: _const(reply))})()  # type: ignore[assignment]
    r = _client(kit).post("/v1/camera/check", json={"ip": IP})
    assert r.status_code == 422 and "rtsp" not in r.text
    ok = Kit()
    ok.plugin = kit.plugin
    good = _client(ok).post("/v1/camera/check", json={"ip": IP, "stage": "first"})
    assert good.status_code == 200 and good.json()["verdict"] == "half"
    assert ok.calls == [
        (
            "POST",
            "/bridge/v1/camera-check",
            {"action": "start", "ip": IP, "stage": "first", "onvif_port": 80, "rtsp_port": 554},
        )
    ]


async def _const(value: dict[str, Any]) -> dict[str, Any]:
    return value

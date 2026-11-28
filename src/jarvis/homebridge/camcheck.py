# src/jarvis/homebridge/camcheck.py
"""R8 row 377 (docs/plans/r8-vision.md v8.0.4 section 4.6, ADR-49; builder B): the no-cloud camera
check, on the home laptop. Kit-safe: the standard library, pydantic and httpx only.

`POST /bridge/v1/camera-check` {action: start|status, ip, stage: first|offline, onvif_port,
rtsp_port} takes a private-range IPv4 address only (RFC 1918: 10/8, 172.16/12, 192.168/16;
anything else, a name included, is refused), and checks, talking to that address alone:

1. ONVIF answers: `GetDeviceInformation` on the device service (WS-Security user token, or HTTP
   digest when the camera asks for it);
2. ONVIF Profile S: `GetCapabilities` (the media service), `GetProfiles` (at least two video
   profiles: main and sub) and `GetStreamUri` for the first two;
3. RTSP answers `DESCRIBE` on the main and the sub stream (digest or basic login);
4. both streams are H.264 (the SDP's `rtpmap`).

The host of every address the camera hands back is replaced by the address he typed, so the check
never talks to any other machine. The two stages make "no cloud": `first` with the camera as it is
(its internet on), then `offline` after he blocks its internet at the router and restarts it: it
passes only when every piece answers in every round for `ROUNDS` rounds `GAP_S` apart (about two
minutes) and the first stage passed in the last day. The laptop can't see the router, so the
blocking and the restart are his steps (the console asks him to confirm them).

The camera's user name and password stay on the laptop: from `LoginBook` (a 0600 file the laptop's
own page writes, `save`) or, for the camera the home vision plugin reads, the user and password in
`HOMEVISION_RTSP_URL` (bridge.env) when its host is the checked address. The reply to the cloud is
`CheckView`'s fields only: which pieces answered and the missing piece in plain words, never a
stream address, the camera's maker or model, or a password; nothing is logged but error classes.
The owner's camera is an Imou Ranger S2 (RTSP and ONVIF per its listing); nothing here names a
model.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import ipaddress
import json
import logging
import os
import re
import secrets
import xml.etree.ElementTree as ET  # noqa: S405 - size-capped, DOCTYPE refused before parsing
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import unquote, urlsplit
from xml.sax.saxutils import escape

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from jarvis.home.ports import CAMERA_CHECK_ROUTE, BridgeState, HeartbeatParts, HomeRefused
from jarvis.homebridge.plugins import BridgeContext, BridgeRoute, TaskFactory

log = logging.getLogger(__name__)

NAME = "camcheck"
PRIVATE_NETS = tuple(
    ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
PRIVATE_ONLY = (
    "JARVIS checks only a camera on your own Wi-Fi: an address that starts 192.168., 10. or "
    "172.16. to 172.31."
)
TIMEOUT_S = 4.0
MAX_REPLY = 256 * 1024
MAX_SDP = 64 * 1024
ROUNDS = 5  # the offline stage: every piece in every round ...
GAP_S = 30.0  # ... this far apart (two minutes in all)
FIRST_KEEP_S = 24 * 3600.0  # the first stage's pass counts for a day
WAIT_S = 5.0  # a start answers within this (the cloud's call waits 8 s)
MAX_JOBS = 2
LOGINS_FILE = "camcheck_logins.json"
USER_AGENT = "JARVIS camera check"
CheckId = Literal["onvif", "profiles", "rtsp_main", "rtsp_sub", "h264", "offline", "login"]
ORDER: tuple[CheckId, ...] = (
    "login",
    "onvif",
    "profiles",
    "rtsp_main",
    "rtsp_sub",
    "h264",
    "offline",
)
Dial = Callable[[str, int], tuple[str, int]]

W_ONVIF_OK = "JARVIS can find and name it (ONVIF)."
W_ONVIF_NO = "ONVIF didn't answer. Switch ONVIF on in the camera's own app, then check again."
W_LOGIN_NEED = (
    "It wants its user name and password: type them on your home laptop's camera check page "
    "(they stay on the laptop), then check again."
)
W_LOGIN_BAD = "It refused the user name and password the laptop has for it."
W_PROFILES_OK = "It offers a main and a smaller sub-stream (ONVIF Profile S)."
W_PROFILES_NONE = "ONVIF answered but lists no video stream (ONVIF Profile S is missing)."
W_PROFILES_ONE = "It has one video stream; JARVIS needs a second, smaller one (the sub-stream)."
W_RTSP_OK = "Sends video on your Wi-Fi (RTSP, {which} stream)."
W_RTSP_NO = "The {which} stream sent no video on your Wi-Fi (RTSP didn't answer)."
W_RTSP_SKIP = "Not checked: ONVIF didn't say where its video is."
W_SUB_NONE = "Not checked: it has no sub-stream."
W_H264_OK = "Its video is H.264."
W_H264_NO = "The {which} stream is {codec}: set it to H.264 in the camera's own app."
W_H264_SKIP = "Not checked: no video arrived."
W_OFF_WAIT = "Not checked yet: block its internet in your router, restart it, then check again."
W_OFF_OK = "Still works with its internet blocked (checked for two minutes)."
W_OFF_NO = "Stopped working once its internet was blocked: it needs its cloud service. {why}"
W_OFF_FIRST = "Run the first check with its internet on before blocking it."
W_BUSY = "Another camera is being checked. Try again in two minutes."
W_NONE = "No check for that address yet."

_SOAP = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Header>{head}</s:Header>'
    "<s:Body>{body}</s:Body></s:Envelope>"
)
_WSSE = (
    '<Security s:mustUnderstand="1" xmlns="http://docs.oasis-open.org/wss/2004/01/'
    'oasis-200401-wss-wssecurity-secext-1.0.xsd"><UsernameToken><Username>{user}</Username>'
    '<Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-'
    'profile-1.0#PasswordDigest">{digest}</Password><Nonce EncodingType="http://docs.oasis-open'
    '.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{nonce}</Nonce>'
    '<Created xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-'
    'utility-1.0.xsd">{created}</Created></UsernameToken></Security>'
)
DEVICE_NS = "http://www.onvif.org/ver10/device/wsdl"
MEDIA_NS = "http://www.onvif.org/ver10/media/wsdl"
SCHEMA_NS = "http://www.onvif.org/ver10/schema"
GET_INFO = f'<GetDeviceInformation xmlns="{DEVICE_NS}"/>'
GET_CAPS = f'<GetCapabilities xmlns="{DEVICE_NS}"><Category>Media</Category></GetCapabilities>'
GET_PROFILES = f'<GetProfiles xmlns="{MEDIA_NS}"/>'
GET_URI = (
    f'<GetStreamUri xmlns="{MEDIA_NS}"><StreamSetup><Stream xmlns="{SCHEMA_NS}">RTP-Unicast'
    f'</Stream><Transport xmlns="{SCHEMA_NS}"><Protocol>RTSP</Protocol></Transport>'
    "</StreamSetup><ProfileToken>{token}</ProfileToken></GetStreamUri>"
)


def private_ip(text: str) -> str | None:
    """The address as written, when it is a plain IPv4 address in RFC 1918's ranges; else None."""
    raw = text.strip() if isinstance(text, str) else ""
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return None
    if not isinstance(addr, ipaddress.IPv4Address) or str(addr) != raw:
        return None
    return raw if any(addr in net for net in PRIVATE_NETS) else None


def _direct(ip: str, port: int) -> tuple[str, int]:
    return ip, port


# ---- the camera's login, kept on the laptop ------------------------------------------------------
@dataclass(frozen=True)
class Login:
    user: str
    password: str = field(repr=False)


class LoginBook:
    """Logins by address: a 0600 file in the bridge's data folder (the laptop's page saves them),
    and the user and password in `HOMEVISION_RTSP_URL` for the camera at that URL's host."""

    def __init__(self, data_dir: Path, env: Mapping[str, str] | None = None) -> None:
        self._path = data_dir / LOGINS_FILE
        self._env = dict(env or {})

    def get(self, ip: str) -> Login | None:
        saved = self._read().get(ip)
        if isinstance(saved, dict) and isinstance(saved.get("user"), str):
            return Login(saved["user"], str(saved.get("password", "")))
        url = self._env.get("HOMEVISION_RTSP_URL", "")
        try:
            parts = urlsplit(url)
        except ValueError:
            return None
        if parts.scheme == "rtsp" and parts.hostname == ip and parts.username:
            return Login(unquote(parts.username), unquote(parts.password or ""))
        return None

    def save(self, ip: str, user: str, password: str) -> None:
        if private_ip(ip) is None or not 0 < len(user) <= 64 or len(password) > 128:
            raise ValueError("login")
        book = {**self._read(), ip: {"user": user, "password": password}}
        self._write(book)

    def forget(self, ip: str) -> bool:
        book = self._read()
        if ip not in book:
            return False
        del book[ip]
        self._write(book)
        return True

    def _read(self) -> dict[str, Any]:
        try:
            got = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return got if isinstance(got, dict) else {}

    def _write(self, book: Mapping[str, Any]) -> None:
        tmp = self._path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(book, fh)
        os.replace(tmp, self._path)


# ---- what one look at the camera found -----------------------------------------------------------
@dataclass(frozen=True)
class Piece:
    id: CheckId
    ok: bool | None  # None: not checked
    words: str


@dataclass(frozen=True)
class Findings:
    pieces: tuple[Piece, ...]

    @property
    def ok(self) -> bool:
        return all(p.ok is not False for p in self.pieces) and any(p.ok for p in self.pieces)

    def missing(self) -> str:
        for pid in ORDER:
            for p in self.pieces:
                if p.id == pid and p.ok is False:
                    return p.words
        return ""


class _Unauthorised(Exception):
    pass


class _NoAnswer(Exception):
    pass


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml(raw: bytes) -> ET.Element:
    if len(raw) > MAX_REPLY or b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise _NoAnswer("refused")
    try:
        return ET.fromstring(raw)  # noqa: S314 - capped, no DOCTYPE or ENTITY
    except ET.ParseError:
        raise _NoAnswer("not xml") from None


def _find(root: ET.Element, name: str) -> list[ET.Element]:
    return [e for e in root.iter() if _local(e.tag) == name]


def _fault_unauthorised(root: ET.Element) -> bool:
    text = " ".join((e.text or "") for f in _find(root, "Fault") for e in f.iter())
    return bool(re.search(r"NotAuthori[sz]ed", text))


def _wsse(login: Login) -> str:
    nonce = secrets.token_bytes(16)
    created = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = hashlib.sha1(nonce + created.encode() + login.password.encode()).digest()  # noqa: S324 - ONVIF's own scheme
    return _WSSE.format(
        user=escape(login.user),
        digest=base64.b64encode(digest).decode(),
        nonce=base64.b64encode(nonce).decode(),
        created=created,
    )


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()  # noqa: S324 - RTSP digest's own scheme


def _challenge(header: str) -> dict[str, str]:
    return {k.lower(): v for k, v in re.findall(r'(\w+)="?([^",]*)"?', header)}


def _rtsp_auth(header: str, login: Login, uri: str) -> str:
    """The Authorization line for DESCRIBE: digest (RFC 2617, qop auth when asked) or basic."""
    if header.lower().startswith("basic"):
        token = base64.b64encode(f"{login.user}:{login.password}".encode()).decode()
        return f"Basic {token}"
    c = _challenge(header[len("Digest") :])
    realm, nonce = c.get("realm", ""), c.get("nonce", "")
    ha1 = _md5(f"{login.user}:{realm}:{login.password}")
    ha2 = _md5(f"DESCRIBE:{uri}")
    line = f'Digest username="{login.user}", realm="{realm}", nonce="{nonce}", uri="{uri}"'
    if "auth" in c.get("qop", "").split(","):
        cnonce = secrets.token_hex(8)
        resp = _md5(f"{ha1}:{nonce}:00000001:{cnonce}:auth:{ha2}")
        return f'{line}, qop=auth, nc=00000001, cnonce="{cnonce}", response="{resp}"'
    return f'{line}, response="{_md5(f"{ha1}:{nonce}:{ha2}")}"'


def _codec(sdp: str) -> str:
    """The video codec the SDP names ("H264", "H265", ...); "" when it names none."""
    video = False
    for line in sdp.splitlines():
        if line.startswith("m="):
            video = line.startswith("m=video")
        elif video and (m := re.match(r"a=rtpmap:\d+\s+([A-Za-z0-9.-]+)/", line)):
            return m.group(1).upper()
    return ""


def _same_host(url: str, ip: str, default_port: int) -> tuple[int, str]:
    """(port, path) of an address the camera handed back; its host is always replaced by `ip`."""
    parts = urlsplit(url)
    port = parts.port or default_port
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    return port, path


class Probe:
    """One look at a camera; talks to the given private address only (`dial` maps it for tests)."""

    def __init__(self, *, dial: Dial = _direct, timeout_s: float = TIMEOUT_S) -> None:
        self._dial = dial
        self._timeout = timeout_s

    async def run(
        self, ip: str, login: Login | None, *, onvif_port: int = 80, rtsp_port: int = 554
    ) -> Findings:
        if private_ip(ip) is None:
            raise ValueError("not a private address")
        pieces: list[Piece] = []
        uris: list[str] = []
        try:
            uris = await self._onvif(ip, onvif_port, login, pieces)
        except _Unauthorised:
            pieces.append(Piece("login", False, W_LOGIN_BAD if login else W_LOGIN_NEED))
        except (_NoAnswer, httpx.HTTPError, OSError):
            answered = any(
                p.id == "onvif" for p in pieces
            )  # it answered, then stopped making sense
            pieces.append(Piece("profiles", False, W_PROFILES_NONE) if answered
                          else Piece("onvif", False, W_ONVIF_NO))  # fmt: skip
        await self._streams(ip, rtsp_port, login, uris, pieces)
        return Findings(tuple(pieces))

    # ---- ONVIF -----------------------------------------------------------------------------------
    async def _onvif(
        self, ip: str, port: int, login: Login | None, pieces: list[Piece]
    ) -> list[str]:
        async with httpx.AsyncClient(
            trust_env=False, follow_redirects=False, timeout=self._timeout
        ) as client:
            device = "/onvif/device_service"
            await self._soap(client, ip, port, device, GET_INFO, login)
            pieces.append(Piece("onvif", True, W_ONVIF_OK))
            caps = await self._soap(client, ip, port, device, GET_CAPS, login)
            media = next((x.text for m in _find(caps, "Media") for x in _find(m, "XAddr")), None)
            mport, mpath = _same_host(media, ip, port) if media else (port, "/onvif/media_service")
            got = await self._soap(client, ip, mport, mpath, GET_PROFILES, login)
            tokens = [p.get("token", "") for p in _find(got, "Profiles") if p.get("token")]
            if not tokens:
                pieces.append(Piece("profiles", False, W_PROFILES_NONE))
                return []
            ok = len(tokens) >= 2
            pieces.append(Piece("profiles", ok, W_PROFILES_OK if ok else W_PROFILES_ONE))
            uris: list[str] = []
            for token in tokens[:2]:
                body = GET_URI.format(token=escape(token[:64]))
                ans = await self._soap(client, ip, mport, mpath, body, login)
                uri = next((u.text for m in _find(ans, "MediaUri") for u in _find(m, "Uri")), "")
                uris.append((uri or "").strip())
            return uris

    async def _soap(
        self,
        client: httpx.AsyncClient,
        ip: str,
        port: int,
        path: str,
        body: str,
        login: Login | None,
    ) -> ET.Element:
        host, dport = self._dial(ip, port)
        url = f"http://{host}:{dport}{path}"
        headers = {
            "Content-Type": "application/soap+xml; charset=utf-8",
            "Host": ip if port == 80 else f"{ip}:{port}",
            "User-Agent": USER_AGENT,
        }
        envelope = _SOAP.format(head=_wsse(login) if login else "", body=body).encode()
        status, raw, challenge = await self._post(client, url, envelope, headers, None)
        if status == 401 and login is not None and challenge.lower().startswith("digest"):
            auth = httpx.DigestAuth(login.user, login.password)
            status, raw, challenge = await self._post(client, url, envelope, headers, auth)
        if status == 401:
            raise _Unauthorised
        root = _xml(raw)
        if _fault_unauthorised(root):
            raise _Unauthorised
        if status != 200 or _find(root, "Fault"):
            raise _NoAnswer(str(status))
        return root

    @staticmethod
    async def _post(
        client: httpx.AsyncClient,
        url: str,
        body: bytes,
        headers: Mapping[str, str],
        auth: httpx.Auth | None,
    ) -> tuple[int, bytes, str]:
        kw: dict[str, Any] = {"content": body, "headers": dict(headers)}
        if auth is not None:
            kw["auth"] = auth
        async with client.stream("POST", url, **kw) as r:
            buf = bytearray()
            async for chunk in r.aiter_bytes():
                buf += chunk
                if len(buf) > MAX_REPLY:
                    raise _NoAnswer("too big")
            return r.status_code, bytes(buf), r.headers.get("www-authenticate", "")

    # ---- RTSP ------------------------------------------------------------------------------------
    async def _streams(
        self, ip: str, rtsp_port: int, login: Login | None, uris: Sequence[str], pieces: list[Piece]
    ) -> None:
        codecs: list[tuple[str, str]] = []
        for which, i in (("main", 0), ("sub", 1)):
            pid: CheckId = "rtsp_main" if which == "main" else "rtsp_sub"
            uri = uris[i] if i < len(uris) else ""
            if not uri:
                pieces.append(Piece(pid, None, W_RTSP_SKIP if not uris else W_SUB_NONE))
                continue
            port, path = _same_host(uri, ip, rtsp_port)
            try:
                codec = await self._describe(ip, port, path, login)
            except _Unauthorised:
                if not any(p.id == "login" for p in pieces):
                    pieces.append(Piece("login", False, W_LOGIN_BAD if login else W_LOGIN_NEED))
                pieces.append(Piece(pid, False, W_RTSP_NO.format(which=which)))
                continue
            except (_NoAnswer, OSError, ValueError, asyncio.IncompleteReadError,
                    asyncio.LimitOverrunError):  # fmt: skip
                pieces.append(Piece(pid, False, W_RTSP_NO.format(which=which)))
                continue
            pieces.append(Piece(pid, True, W_RTSP_OK.format(which=which)))
            codecs.append((which, codec))
        if not codecs:
            pieces.append(Piece("h264", None, W_H264_SKIP))
            return
        bad = [(w, c) for w, c in codecs if c != "H264"]
        if bad:
            which, codec = bad[0]
            name = {"H265": "H.265", "": "an unknown kind"}.get(codec, codec)
            pieces.append(Piece("h264", False, W_H264_NO.format(which=which, codec=name)))
        else:
            pieces.append(Piece("h264", True, W_H264_OK))

    async def _describe(self, ip: str, port: int, path: str, login: Login | None) -> str:
        uri = f"rtsp://{ip}:{port}{path}"
        status, head, sdp = await self._rtsp(ip, port, uri, 1, None)
        challenge = head.get("www-authenticate", "")
        if status == 401 and login is not None and challenge:
            status, head, sdp = await self._rtsp(
                ip, port, uri, 2, _rtsp_auth(challenge, login, uri)
            )
        if status == 401:
            raise _Unauthorised
        if status != 200:
            raise _NoAnswer(str(status))
        return _codec(sdp)

    async def _rtsp(
        self, ip: str, port: int, uri: str, seq: int, auth: str | None
    ) -> tuple[int, dict[str, str], str]:
        host, dport = self._dial(ip, port)
        lines = [f"DESCRIBE {uri} RTSP/1.0", f"CSeq: {seq}", "Accept: application/sdp"]
        lines += [f"User-Agent: {USER_AGENT}"] + ([f"Authorization: {auth}"] if auth else [])
        async with asyncio.timeout(self._timeout):
            reader, writer = await asyncio.open_connection(host, dport)
            try:
                writer.write(("\r\n".join(lines) + "\r\n\r\n").encode())
                await writer.drain()
                raw = await reader.readuntil(b"\r\n\r\n")
                status_line, *rest = raw.decode("latin-1").split("\r\n")
                m = re.match(r"RTSP/1\.0 (\d{3})", status_line)
                if not m:
                    raise _NoAnswer("not rtsp")
                head = {
                    k.strip().lower(): v.strip()
                    for k, _, v in (h.partition(":") for h in rest if ":" in h)
                }
                size = int(head.get("content-length", "0") or 0)
                if size > MAX_SDP:
                    raise _NoAnswer("too big")
                body = await reader.readexactly(size) if size > 0 else b""
            finally:
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()
        return int(m.group(1)), head, body.decode("latin-1")


# ---- the plugin: one check per address, in two stages --------------------------------------------
class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal["start", "status"] = "start"
    ip: Annotated[str, StringConstraints(min_length=7, max_length=15)]
    stage: Literal["first", "offline"] = "first"
    onvif_port: Annotated[int, Field(ge=1, le=65535)] = 80
    rtsp_port: Annotated[int, Field(ge=1, le=65535)] = 554


@dataclass
class Job:
    ip: str
    stage: Literal["first", "offline"]
    rounds: int
    state: Literal["running", "done"] = "running"
    rounds_done: int = 0
    verdict: Literal["", "pass", "half", "fail"] = ""
    pieces: tuple[Piece, ...] = ()
    missing: str = ""
    task: asyncio.Task[None] | None = None


def view(job: Job | None, ip: str, stage: str = "first") -> dict[str, Any]:
    """The reply to the cloud: `jarvis.api.camera_spots.CheckView`'s fields, nothing else."""
    if job is None:
        return {"ip": ip, "stage": stage, "state": "none", "verdict": "", "checks": [],
                "missing": W_NONE, "rounds": 0, "rounds_done": 0}  # fmt: skip
    return {
        "ip": job.ip,
        "stage": job.stage,
        "state": job.state,
        "verdict": job.verdict,
        "checks": [{"id": p.id, "ok": p.ok, "words": p.words} for p in job.pieces],
        "missing": job.missing,
        "rounds": job.rounds,
        "rounds_done": job.rounds_done,
    }


class CamCheck:
    name = NAME

    def __init__(
        self,
        ctx: BridgeContext,
        *,
        probe: Probe | None = None,
        logins: LoginBook | None = None,
        rounds: int = ROUNDS,
        gap_s: float = GAP_S,
        wait_s: float = WAIT_S,
    ) -> None:
        self._ctx = ctx
        self._probe = probe or Probe()
        self.logins = logins or LoginBook(ctx.data_dir, ctx.env)
        self._rounds = rounds
        self._gap = gap_s
        self._wait = wait_s
        self._jobs: dict[str, Job] = {}
        self._first_ok: dict[str, float] = {}
        method, path = CAMERA_CHECK_ROUTE
        self._routes = (BridgeRoute(method, path, self.handle),)  # type: ignore[arg-type]

    def routes(self) -> Sequence[BridgeRoute]:
        return self._routes

    def tasks(self) -> Sequence[TaskFactory]:
        return ()

    async def heartbeat_part(self) -> HeartbeatParts:
        return HeartbeatParts()

    async def apply_state(self, state: BridgeState) -> None:
        return None

    async def aclose(self) -> None:
        for job in self._jobs.values():
            if job.task is not None and not job.task.done():
                job.task.cancel()

    async def handle(
        self, query: Mapping[str, str], body: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        try:
            req = CheckRequest.model_validate(dict(body or {}))
        except ValidationError:
            raise HomeRefused(
                "bad_request", "That check request isn't one the laptop takes."
            ) from None
        ip = private_ip(req.ip)
        if ip is None:
            raise HomeRefused("not_private", PRIVATE_ONLY)
        job = self._jobs.get(ip)
        if req.action == "status":
            return view(job, ip, req.stage)
        if job is not None and job.state == "running":
            return view(job, ip)
        if sum(j.state == "running" for j in self._jobs.values()) >= MAX_JOBS:
            raise HomeRefused("busy", W_BUSY)
        job = Job(ip=ip, stage=req.stage, rounds=1 if req.stage == "first" else self._rounds)
        self._jobs[ip] = job
        job.task = asyncio.create_task(self._run(job, req))
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(asyncio.shield(job.task), self._wait)
        return view(job, ip)

    async def _look(self, req: CheckRequest, ip: str) -> Findings:
        login = self.logins.get(ip)
        return await self._probe.run(ip, login, onvif_port=req.onvif_port, rtsp_port=req.rtsp_port)

    async def _run(self, job: Job, req: CheckRequest) -> None:
        try:
            if job.stage == "first":
                await self._first(job, req)
            else:
                await self._offline(job, req)
        except Exception as exc:  # noqa: BLE001 - the check fails in plain words, never a trace
            job.verdict, job.missing = "fail", W_ONVIF_NO
            log.warning("camera check failed: %s", type(exc).__name__)
        finally:
            job.state = "done"

    async def _first(self, job: Job, req: CheckRequest) -> None:
        found = await self._look(req, job.ip)
        job.rounds_done = 1
        job.pieces = (*found.pieces, Piece("offline", None, W_OFF_WAIT))
        if found.ok:
            self._first_ok[job.ip] = self._ctx.now()
            job.verdict, job.missing = "half", ""
        else:
            self._first_ok.pop(job.ip, None)
            job.verdict, job.missing = "fail", found.missing()

    async def _offline(self, job: Job, req: CheckRequest) -> None:
        passed = self._first_ok.get(job.ip)
        if passed is None or self._ctx.now() - passed > FIRST_KEEP_S:
            job.pieces = (Piece("offline", False, W_OFF_FIRST),)
            job.verdict, job.missing = "fail", W_OFF_FIRST
            return
        for n in range(job.rounds):
            if n:
                await asyncio.sleep(self._gap)
            found = await self._look(req, job.ip)
            job.rounds_done = n + 1
            if not found.ok:
                why = W_OFF_NO.format(why=found.missing())
                job.pieces = (*found.pieces, Piece("offline", False, why[:200]))
                job.verdict, job.missing = "fail", why[:300]
                return
            job.pieces = (*found.pieces, Piece("offline", None, f"Round {n + 1} of {job.rounds}."))
        job.pieces = (*job.pieces[:-1], Piece("offline", True, W_OFF_OK))
        job.verdict, job.missing = "pass", ""


def create_plugin(ctx: BridgeContext) -> CamCheck:
    return CamCheck(ctx)


__all__ = [
    "GAP_S",
    "NAME",
    "PRIVATE_ONLY",
    "ROUNDS",
    "CamCheck",
    "CheckRequest",
    "Findings",
    "Login",
    "LoginBook",
    "Piece",
    "Probe",
    "create_plugin",
    "private_ip",
    "view",
]

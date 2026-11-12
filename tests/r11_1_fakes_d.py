# tests/r11_1_fakes_d.py -- R11.1 Part D (People, pictures and Vitals): fakes shared by
# tests/test_r11_1_d_*.py and evals/r11_1/look.py. Imported bare: `from r11_1_fakes_d import ...`.
# Everything here is made up: no real person, no real picture, no real token.
from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import struct
import subprocess
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr
from r51b_fakes import Clock, OwnRig

from jarvis.core.guardrails import ConfirmationGate
from jarvis.home.heartbeat import HeartbeatHandler
from jarvis.home.ports import Heartbeat, HeartbeatParts
from jarvis.home.store import HomeStore
from jarvis.integrations.github import GithubClient, GithubStore
from jarvis.keyring import Keyring
from jarvis.llm.base import ImageBlock, ToolCall
from jarvis.people.research import PeopleService
from jarvis.people.tools import PeopleDeps, people_tools
from jarvis.picture.eyes import CantLook, Glance
from jarvis.picture.research import PictureResearch
from jarvis.picture.search import WebFinder
from jarvis.picture.tools import PICTURE_RESEARCH, picture_tools
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway, GatewayResult
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry
from jarvis.vitals.own import OwnSources
from jarvis.web.allowance import WebAllowance
from jarvis.web.ports import PageText, SearchHit, SearchPage
from jarvis.web.service import WebService
from jarvis.web.tools import web_tools

UID = "u_owner"
ROOT_KEY = bytes(range(1, 33))
HOME_ID = "h_0a1b2c3d"
BRIDGE_URL = "https://laptop.example.ts.net:8443"
GITHUB_TOKEN = "made-up-token-for-tests-0001"  # not a real token, and not shaped like one
GITHUB_LOGIN = "example-dev"
GITHUB_DOC = f"jarvis_connectors_github/{UID}"
DOM_JS = Path(__file__).resolve().parent / "fixtures" / "r11_1" / "d_dom.js"


# ---- O8 / D21-D: the People script run in Node on a small DOM, its buttons pressed ---------------
def run_people_dom(
    source: str, dossier: dict[str, Any] | None, *, presses: int = 0, offer: Any = None
) -> dict[str, Any]:
    """Run `source` (console-people.js, or a changed copy) on tests/fixtures/r11_1/d_dom.js with
    `dossier` as the last research; press "Open next" `presses` times; draw and press `offer` (a
    reply card) when given. Returns what it shows and what opened (followed links, window.open
    calls). Raises RuntimeError when Node is not installed."""
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is not installed")
    payload: dict[str, Any] = {"source": source, "dossier": dossier, "presses": presses}
    if offer is not None:
        payload["offer"] = offer
    done = subprocess.run(
        [node, str(DOM_JS)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    out: dict[str, Any] = json.loads(done.stdout)
    if "crashed" in out:
        raise RuntimeError(out["crashed"])
    return out


# ---- O10: a linked home whose laptop reports its parts ------------------------------------------
class HomeRig:
    """A real `HomeStore` over `MemoryDocs`, fed by the real heartbeat handler, read by a real
    Vitals board (`OwnRig`). `beat(frigate=False)` is one heartbeat from the laptop."""

    def __init__(self) -> None:
        self.clock = Clock()
        self.docs = MemoryDocs()
        self.store = HomeStore(self.docs, Keyring(ROOT_KEY), clock=lambda: self.clock().timestamp())
        self.handler = HeartbeatHandler(self.store, None)
        self.rig = OwnRig(OwnSources(home=self.store), clock=self.clock)
        self._n = 0

    async def link(self) -> None:
        await self.store.link(UID, HOME_ID, BRIDGE_URL, bytes(range(40, 72)))

    async def beat(self, **parts: Any) -> None:
        self._n += 1
        await self.handler.handle(
            UID,
            Heartbeat(
                type="heartbeat",
                id=f"hb-{self._n}",
                at=self.clock().timestamp(),
                bridge_version="0.1.0",
                state_rev=0,
                parts=HeartbeatParts(**parts),
            ),
        )

    async def row(self) -> Any:
        board = await self.rig.svc.board(UID)
        return next((v for v in board.items if v.provider.id == "home_link"), None)


# ---- O11: a connected GitHub token and a fake api.github.com ------------------------------------
def rate_headers(
    *, used: int = 12, limit: int = 5000, reset_in: float = 1800.0, now: float, expires: str = ""
) -> dict[str, str]:
    """What GitHub's own headers say about a token (the hourly limit; an expiry when it has one)."""
    out = {
        "x-ratelimit-limit": str(limit),
        "x-ratelimit-used": str(used),
        "x-ratelimit-reset": str(int(now + reset_in)),
    }
    if expires:
        out["github-authentication-token-expiration"] = expires
    return out


class FakeGithub:
    """api.github.com as an httpx transport: every request is recorded; `/rate_limit` and `/user`
    answer from what the test scripted (a list is served in order, the last one repeating).
    `hold()` makes the next answers wait (a slow GitHub); `stop_holding()` lets new requests
    through while the held ones still wait; `release()` lets every held one go."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.answers: dict[str, list[httpx.Response]] = {}
        self._gate: asyncio.Event | None = None
        self._held: list[asyncio.Event] = []

    def on(self, path: str, *responses: httpx.Response) -> None:
        self.answers[path] = list(responses)

    def hold(self) -> None:
        self._gate = asyncio.Event()
        self._held.append(self._gate)

    def stop_holding(self) -> None:
        self._gate = None

    def release(self) -> None:
        for gate in self._held:
            gate.set()
        self._held, self._gate = [], None

    def reads(self, path: str = "/rate_limit") -> int:
        return sum(1 for r in self.requests if r.method == "GET" and r.url.path == path)

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        gate = self._gate
        if gate is not None:
            await gate.wait()
        assert request.url.host == "api.github.com" and request.url.scheme == "https"
        queue = self.answers.get(request.url.path)
        if not queue:
            return httpx.Response(599, json={"message": "unscripted"})
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self._handle))


class GithubRig:
    """A real `GithubClient` and `GithubStore` over `MemoryDocs` and the fake API, read by a real
    Vitals board. `restart()` is a new process: the same documents, an empty memory."""

    def __init__(self) -> None:
        self.clock = Clock()
        self.docs = MemoryDocs()
        self.api = FakeGithub()
        self.client = self._client()
        self.rig = self._board()

    def _client(self) -> GithubClient:
        store = GithubStore(self.docs, Keyring(ROOT_KEY))
        return GithubClient(store, http=self.api.http(), clock=lambda: self.clock().timestamp())

    def _board(self) -> OwnRig:
        return OwnRig(OwnSources(github=self.client), clock=self.clock, docs=self.docs)

    @property
    def now(self) -> float:
        return self.clock().timestamp()

    def restart(self) -> None:
        self.client = self._client()
        self.rig = self._board()

    async def connected_without_facts(self) -> None:
        """A token saved before JARVIS kept GitHub's facts (or whose facts could not be saved)."""
        store = GithubStore(self.docs, Keyring(ROOT_KEY))
        await store.save(UID, SecretStr(GITHUB_TOKEN), GITHUB_LOGIN, None)

    async def connect(self) -> None:
        """An ordinary connect: `/user` answers and its headers are kept as the token's facts."""
        self.api.on(
            "/user",
            httpx.Response(200, json={"login": GITHUB_LOGIN}, headers=rate_headers(now=self.now)),
        )
        await self.client.connect(UID, SecretStr(GITHUB_TOKEN))

    def answers(self, status: int = 200, **kw: Any) -> None:
        headers = rate_headers(now=self.now, **kw) if status == 200 else {}
        self.api.on("/rate_limit", httpx.Response(status, json={"rate": {}}, headers=headers))

    async def stored(self) -> dict[str, Any]:
        doc = await self.docs.get(GITHUB_DOC)
        assert doc is not None
        return doc

    async def board(self) -> Any:
        return await self.rig.svc.board(UID)

    async def row(self) -> Any:
        items = (await self.board()).items
        return next((v for v in items if v.provider.id == "github_token"), None)


# ---- O9: pictures drawn in the test, and a fake pair of eyes that really reads them --------------
# A picture is a small PNG made here from plain shapes: coloured blocks, a drawn "person" (a head
# with two eyes over a body, in a colour nothing else uses) and lines of text set in a 5x7 dot
# font. Never a photograph, never a real person.
_FONT_ROWS = 7
_FONT = {
    ch: bytes.fromhex(rows)
    for ch, rows in {
        "A": "0e11111f111111", "B": "1e11111e11111e", "C": "0e11101010110e", "D": "1e11111111111e",
        "E": "1f10101e10101f", "F": "1f10101e101010", "G": "0e11101711110f", "H": "1111111f111111",
        "I": "0e04040404040e", "J": "0702020202120c", "K": "11121418141211", "L": "1010101010101f",
        "M": "111b1515111111", "N": "11191513111111", "O": "0e11111111110e", "P": "1e11111e101010",
        "Q": "0e11111115120d", "R": "1e11111e141211", "S": "0f10100e01011e", "T": "1f040404040404",
        "U": "1111111111110e", "V": "11111111110a04", "W": "1111111515150a", "X": "11110a040a1111",
        "Y": "11110a04040404", "Z": "1f01020408101f", "0": "0e11131519110e", "1": "040c040404040e",
        "2": "0e11010204081f", "3": "1f02040201110e", "4": "02060a121f0202", "5": "1f101e0101110e",
        "6": "0608101e11110e", "7": "1f010204080808", "8": "0e11110e11110e", "9": "0e11110f01020c",
        "-": "0000001f000000", ".": "00000000000c0c", " ": "00000000000000",
    }.items()
}  # fmt: skip
_GLYPH = {rows: ch for ch, rows in _FONT.items()}
_SCALE, _CELL, _LINE, _MARGIN = 2, 12, 18, 8
_INK, _PAPER, _SKIN = (10, 10, 10), (250, 250, 250), (223, 171, 104)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
Colour = tuple[int, int, int]


def _chunk(kind: bytes, body: bytes) -> bytes:
    crc = zlib.crc32(kind + body) & 0xFFFFFFFF
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)


def _png(pixels: list[list[Colour]]) -> bytes:
    height, width = len(pixels), len(pixels[0])
    raw = b"".join(b"\x00" + bytes(c for px in row for c in px) for row in pixels)
    head = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + _chunk(b"IHDR", head)
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def _pixels(png: bytes) -> list[list[Colour]]:
    """The pixels of a PNG made by `_png` (8-bit RGB, no filter): what the fake eyes look at."""
    assert png.startswith(PNG_SIGNATURE)
    width, height = struct.unpack(">II", png[16:24])
    start = png.index(b"IDAT") + 4
    size = struct.unpack(">I", png[start - 8 : start - 4])[0]
    raw = zlib.decompress(png[start : start + size])
    stride = 1 + 3 * width
    rows = []
    for y in range(height):
        line = raw[y * stride + 1 : (y + 1) * stride]
        rows.append([(line[i], line[i + 1], line[i + 2]) for i in range(0, 3 * width, 3)])
    return rows


def _block(px: list[list[Colour]], box: tuple[int, int, int, int], colour: Colour) -> None:
    x0, y0, x1, y1 = box
    for y in range(max(0, y0), min(len(px), y1)):
        for x in range(max(0, x0), min(len(px[0]), x1)):
            px[y][x] = colour


def _write(px: list[list[Colour]], line: int, text: str) -> None:
    top = _MARGIN + line * _LINE
    _block(px, (0, top - 2, len(px[0]), top + _FONT_ROWS * _SCALE + 2), _PAPER)
    for i, ch in enumerate(text.upper()):
        rows = _FONT[ch]
        for r in range(_FONT_ROWS):
            for c in range(5):
                if rows[r] >> (4 - c) & 1:
                    x, y = _MARGIN + i * _CELL + c * _SCALE, top + r * _SCALE
                    _block(px, (x, y, x + _SCALE, y + _SCALE), _INK)


def picture(
    *lines: str,
    person: bool = False,
    blocks: Sequence[tuple[tuple[int, int, int, int], Colour]] = (),
    size: tuple[int, int] = (360, 200),
) -> ImageBlock:
    """A picture drawn for a test: `blocks` of colour, a drawn person, and `lines` of text (A-Z,
    0-9, space, hyphen, full stop) set at the top. Returns the PNG as the block a brain is sent."""
    width, height = size
    px: list[list[Colour]] = [[(96, 148, 201)] * width for _ in range(height)]
    for box, colour in blocks:
        _block(px, box, colour)
    if person:  # a head with two eyes over a body, in the skin colour nothing else uses
        cx, top = width // 2, height // 2 - 20
        _block(px, (cx - 18, top, cx + 18, top + 40), _SKIN)
        _block(px, (cx - 10, top + 12, cx - 5, top + 17), _INK)
        _block(px, (cx + 5, top + 12, cx + 10, top + 17), _INK)
        _block(px, (cx - 30, top + 42, cx + 30, height), (40, 70, 160))
    for i, line in enumerate(lines):
        assert _MARGIN + len(line) * _CELL <= width, f"too long for the picture: {line!r}"
        _write(px, i, line)
    return ImageBlock(media_type="image/png", data=_png(px))


def read_text(block: ImageBlock) -> list[str]:
    """The lines of text really drawn in a test picture (the fake eyes' reading of the pixels)."""
    px = _pixels(block.data)
    lines = []
    for line in range((len(px) - _MARGIN) // _LINE):
        top = _MARGIN + line * _LINE
        chars = []
        for i in range((len(px[0]) - _MARGIN) // _CELL):
            rows = bytearray(_FONT_ROWS)
            for r in range(_FONT_ROWS):
                for c in range(5):
                    x, y = _MARGIN + i * _CELL + c * _SCALE, top + r * _SCALE
                    if px[y][x] == _INK:
                        rows[r] |= 1 << (4 - c)
            chars.append(_GLYPH.get(bytes(rows), "?"))
        text = "".join(chars).strip()
        if text and "?" not in text:
            lines.append(" ".join(text.split()))
    return lines


def shows_person(block: ImageBlock) -> bool:
    return any(_SKIN in row for row in _pixels(block.data))


def digest(block: ImageBlock) -> str:
    return hashlib.sha256(block.data).hexdigest()


@dataclass
class FakeEyes:
    """`jarvis.picture.eyes.Eyes` for tests and the eval: a seeing brain that answers the first
    look's JSON. It READS the picture it is handed: the text is what is really drawn in it and
    `has_person` is whether a person is drawn; `knows` adds what a real model would recognise
    (the scene and the things). `lies` replaces the whole answer for one picture: a brain that
    misbehaves (names a face, invents a caption, writes something that is not the schema)."""

    cant: CantLook | None = None  # the AI is off, no seeing brain, the limit, unreachable
    cost_usd: float = 0.0004
    known: dict[str, dict[str, Any]] = field(default_factory=dict)
    lied: dict[str, str] = field(default_factory=dict)
    looks: list[tuple[str, str, str, str]] = field(default_factory=list)  # uid, system, ask, digest

    def knows(self, block: ImageBlock, *, scene: str, subjects: Sequence[tuple[str, str]]) -> None:
        self.known[digest(block)] = {
            "scene": scene,
            "subjects": [{"kind": kind, "name": name} for kind, name in subjects],
        }

    def lies(self, block: ImageBlock, answer: Any) -> None:
        self.lied[digest(block)] = answer if isinstance(answer, str) else json.dumps(answer)

    async def state(self, uid: str) -> CantLook | None:
        return self.cant

    async def look(
        self, uid: str, system: str, ask: str, picture: ImageBlock, *, max_tokens: int
    ) -> Glance:
        if self.cant is not None:
            raise self.cant
        key = digest(picture)
        self.looks.append((uid, system, ask, key))
        if key in self.lied:
            return Glance(self.lied[key], self.cost_usd)
        known = self.known.get(key, {"scene": "A picture.", "subjects": []})
        answer = {
            "has_person": shows_person(picture),
            "scene": known["scene"],
            "text": read_text(picture),
            "subjects": known["subjects"],
            "named_in_text": "",
        }
        return Glance(json.dumps(answer), self.cost_usd)


class TurnPictures:
    """What `documents.pictures.turn_pictures` will answer once Part B fills it: the pictures of
    the latest owner turn of ONE conversation of ONE owner, newest first."""

    def __init__(self) -> None:
        self.by_turn: dict[tuple[str, str], list[ImageBlock]] = {}
        self.asked: list[tuple[str, str]] = []

    def attach(self, session_id: str, *blocks: ImageBlock, uid: str = UID) -> None:
        self.by_turn[(uid, session_id)] = list(blocks)

    async def __call__(self, uid: str, session_id: str) -> list[ImageBlock]:
        self.asked.append((uid, session_id))
        return list(self.by_turn.get((uid, session_id), []))


class FakeSearchVendor:
    """The web-search vendor (`jarvis.web.ports.SearchProvider`): records every query it is SENT
    (the tests' ground truth for "no search ran for the person") and answers from `pages`, whose
    keys are words a query must contain; anything else gets `default`."""

    name = "fake"

    def __init__(self) -> None:
        self.queries: list[str] = []
        self.pages: dict[str, list[SearchHit]] = {}
        self.default: list[SearchHit] = [
            SearchHit("An example page", "https://www.example.org/a", "About the thing."),
            SearchHit("Another example page", "https://example.com/b", "More about the thing."),
        ]
        self.fail = False

    async def search(
        self, query: str, *, max_results: int, topic: str, days: int | None
    ) -> SearchPage:
        self.queries.append(query)
        if self.fail:
            raise RuntimeError("vendor said: internal error 500")
        hits = next((h for k, h in self.pages.items() if k.lower() in query.lower()), self.default)
        return SearchPage(hits=list(hits[:max_results]), credits=1)

    async def extract(self, url: str) -> PageText:
        return PageText(url=url)

    async def aclose(self) -> None:
        return None


class FakeRows:
    """The owner's permission rows (`OwnerRules`): `web` is his "Search the web" choice."""

    def __init__(self, web: str = "allow", pictures: str = "allow") -> None:
        self.web, self.pictures, self.broken = web, pictures, False

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        if self.broken:
            raise RuntimeError("permissions unreadable")
        effects = {"allow": Effect.ALLOW, "ask": Effect.ASK, "never": Effect.DENY}
        return [
            PolicyRule(tool_pattern="web_*", effect=effects[self.web], source="owner"),
            PolicyRule(tool_pattern="picture_*", effect=effects[self.pictures], source="owner"),
        ]


class PictureRig:
    """Picture research end to end on fakes: the real tool through a real gateway (the owner's
    rows, the audit chain), the real service and guard, the real web allowance and the real
    people research behind its unchanged check; fake eyes, a fake search vendor and the fake
    `turn_pictures`. `guard=False` is the negative control."""

    def __init__(self, *, guard: bool = True, web: bool = True, enabled: bool = True) -> None:
        self.eyes = FakeEyes()
        self.turn = TurnPictures()
        self.vendor = FakeSearchVendor()
        self.docs = MemoryDocs()
        self.rows = FakeRows()
        self.web: WebService | None = (
            WebService(self.vendor, WebAllowance(self.docs)) if web else None
        )
        self.gateway: Gateway | None = None
        self.finder = WebFinder(lambda: self.web, lambda: self.gateway)
        self.svc = PictureResearch(self.eyes, self.turn, self.finder, enabled=enabled, guard=guard)
        registry = ToolRegistry()
        for tool in picture_tools(self.svc):
            registry.register(tool)
        if self.web is not None:
            for tool in web_tools(self.web):
                registry.register(tool)
        self.audit = AuditLog()
        self.gateway = Gateway(
            registry=registry,
            policy=Policy(),
            gate=ConfirmationGate(),
            audit=self.audit,
            rules=self.rows,
        )

    def add_people(self, service: PeopleService) -> None:
        assert self.gateway is not None
        for tool in people_tools(PeopleDeps(service)):
            self.gateway.registry.register(tool)

    async def call(self, tool: str, session: str = "sess_1", **args: Any) -> GatewayResult:
        assert self.gateway is not None
        call = ToolCall(id=f"t{len(self.vendor.queries)}", name=tool, arguments=dict(args))
        return await self.gateway.execute(call, scope=f"{UID}:{session}")

    async def research(self, session: str = "sess_1", **args: Any) -> GatewayResult:
        return await self.call(PICTURE_RESEARCH, session, **args)


__all__ = [
    "BRIDGE_URL",
    "DOM_JS",
    "GITHUB_DOC",
    "GITHUB_LOGIN",
    "GITHUB_TOKEN",
    "HOME_ID",
    "ROOT_KEY",
    "UID",
    "FakeEyes",
    "FakeGithub",
    "FakeRows",
    "FakeSearchVendor",
    "GithubRig",
    "HomeRig",
    "PictureRig",
    "TurnPictures",
    "digest",
    "picture",
    "rate_headers",
    "read_text",
    "run_people_dom",
    "shows_person",
]

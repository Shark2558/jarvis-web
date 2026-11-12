# tests/r11_1_fakes_d.py -- R11.1 Part D (People, pictures and Vitals): fakes shared by
# tests/test_r11_1_d_*.py and evals/r11_1/look.py. Imported bare: `from r11_1_fakes_d import ...`.
# Everything here is made up: no real person, no real picture, no real token.
from __future__ import annotations

import asyncio
from typing import Any

import httpx
from pydantic import SecretStr
from r51b_fakes import Clock, OwnRig

from jarvis.home.heartbeat import HeartbeatHandler
from jarvis.home.ports import Heartbeat, HeartbeatParts
from jarvis.home.store import HomeStore
from jarvis.integrations.github import GithubClient, GithubStore
from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs
from jarvis.vitals.own import OwnSources

UID = "u_owner"
ROOT_KEY = bytes(range(1, 33))
HOME_ID = "h_0a1b2c3d"
BRIDGE_URL = "https://laptop.example.ts.net:8443"
GITHUB_TOKEN = "made-up-token-for-tests-0001"  # not a real token, and not shaped like one
GITHUB_LOGIN = "example-dev"
GITHUB_DOC = f"jarvis_connectors_github/{UID}"


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


__all__ = [
    "BRIDGE_URL",
    "GITHUB_DOC",
    "GITHUB_LOGIN",
    "GITHUB_TOKEN",
    "HOME_ID",
    "ROOT_KEY",
    "UID",
    "FakeGithub",
    "GithubRig",
    "HomeRig",
    "rate_headers",
]

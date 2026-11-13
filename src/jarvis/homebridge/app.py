# src/jarvis/homebridge/app.py
"""The bridge's signed API (R3 D3, D5, D6). Ships in the home kit.

`create_bridge(cfg, factories)` builds the one web app on 127.0.0.1:8099 (Tailscale Funnel proxies
port 8443 to it). It serves ONLY `jarvis.home.ports.BRIDGE_ROUTES`; everything else is a bare 404.
For a fixed route the order is: a well-formed Content-Length (400) -> body <= 64 KB (413), read
within `BODY_READ_S` (408) -> signature (`BridgeAuth.check`, a bare 401 on any failure) -> JSON
parse -> the plugin's handler -> a signed answer. On the one large route (a photo, 6 MB) the
signature over the body hash the cloud declared is checked BEFORE a byte is read (review C-sec
M1), one upload at a time, and the hash of what was read must be the one declared. A handler
runs only after the signature, so an unauthenticated caller reaches no plugin code and no Home
Assistant call.

The core plugin (this module) serves health, state, devices and device actions; B's camera plugin
and C's faces plugin serve events, packages and faces/summary and are listed in
`registry.PLUGINS` (I1). Plugins are checked once: a route can't be served twice.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from pydantic import ValidationError

from jarvis.home import signing
from jarvis.home.ports import (
    BridgeState,
    HeartbeatParts,
    HomeRefused,
    route_allowed,
)
from jarvis.homebridge.auth import BridgeAuth
from jarvis.homebridge.cloud import CloudLink
from jarvis.homebridge.config import (
    BRIDGE_VERSION,
    MAX_BODY_BYTES,
    MAX_BODY_BYTES_BY_ROUTE,
    BridgeConfig,
)
from jarvis.homebridge.devices import DeviceBridge
from jarvis.homebridge.ha import HAClient
from jarvis.homebridge.heartbeat import HeartbeatLoop
from jarvis.homebridge.plugins import (
    BridgeContext,
    BridgePlugin,
    BridgeRoute,
    FatalTaskError,
    PluginFactory,
    TaskFactory,
    check_routes,
    plugin_env,
)
from jarvis.homebridge.state import BridgeStore

log = logging.getLogger(__name__)
RESTART_DELAY_S = 5.0
BODY_READ_S = 30.0  # a body that takes longer to arrive is not waited for (408)


class CorePlugin:
    """Health, state, devices and device actions (A)."""

    name = "core"

    def __init__(
        self,
        store: BridgeStore,
        ha: HAClient,
        devices: DeviceBridge,
        apply: Callable[[BridgeState], Any],
        broken: Callable[[], Sequence[str]] = tuple,
    ) -> None:
        self._store = store
        self._ha = ha
        self._devices = devices
        self._apply = apply
        self._broken = broken

    def routes(self) -> Sequence[BridgeRoute]:
        return (
            BridgeRoute("GET", "/bridge/v1/health", self._health),
            BridgeRoute("POST", "/bridge/v1/state", self._state),
            BridgeRoute("GET", "/bridge/v1/devices", self._list),
            BridgeRoute("POST", "/bridge/v1/devices/action", self._action),
        )

    def tasks(self) -> Sequence[TaskFactory]:
        return (self._devices.watch,)

    async def heartbeat_part(self) -> HeartbeatParts:
        ha = await self._ha.ping() if self._ha.linked else False
        # review M10: a part that could not start means the camera can't be trusted; a camera
        # plugin that did start reports its own MQTT state, laid over this one
        return HeartbeatParts(ha=ha, mqtt=False if self._broken() else None)

    async def apply_state(self, state: BridgeState) -> None:
        return None  # the core keeps no state of its own: devices read the store

    async def _health(
        self, query: Mapping[str, str], body: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        return {"ok": True, "version": BRIDGE_VERSION, "ha": self._ha.linked}

    async def _state(
        self, query: Mapping[str, str], body: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        try:
            state = BridgeState.model_validate(body or {})
        except ValidationError:
            raise HomeRefused("bad_state", "That state isn't valid.") from None
        await self._apply(state)
        return {"ok": True}

    async def _list(
        self, query: Mapping[str, str], body: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        if query.get("catalogue") == "1":
            return await self._devices.catalogue()
        return await self._devices.exposed_states()

    async def _action(
        self, query: Mapping[str, str], body: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        data = body or {}
        return await self._devices.act(data.get("entity_id"), data.get("action"), data.get("value"))


class Supervisor:
    """Runs each task and starts it again if it stops (a plugin crash must not end the bridge).
    Every stop is logged (review M10: never a silent restart); a task that raises
    `FatalTaskError` can never work as installed and is not started again."""

    def __init__(self, delay_s: float = RESTART_DELAY_S) -> None:
        self._delay = delay_s
        self._tasks: list[asyncio.Task[None]] = []

    def start(self, name: str, factory: TaskFactory) -> None:
        self._tasks.append(asyncio.create_task(self._loop(name, factory)))

    async def _loop(self, name: str, factory: TaskFactory) -> None:
        while True:
            try:
                await factory()
                log.warning("a bridge task ended; starting it again", extra={"task": name})
            except asyncio.CancelledError:
                raise
            except FatalTaskError:
                log.error("a bridge task can't run here and was stopped", extra={"task": name})
                return
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "a bridge task stopped", extra={"task": name, "error": type(exc).__name__}
                )
            await asyncio.sleep(self._delay)

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with suppress(asyncio.CancelledError, Exception):
                await task


def _bare(status: int) -> Response:
    return Response(status_code=status)


class Bridge:
    """The wired bridge: `app` plus the pieces tests and `__main__` need."""

    def __init__(
        self,
        cfg: BridgeConfig,
        factories: Sequence[PluginFactory] = (),
        *,
        clock: Callable[[], float] = time.time,
        http: httpx.AsyncClient | None = None,
        ha_http: httpx.AsyncClient | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.cfg = cfg
        self.store = BridgeStore(cfg.data_dir, clock=clock)
        self.auth = BridgeAuth(self.store, clock)
        self.link = CloudLink(cfg, self.store, self.auth, http=http, clock=clock, on_unlinked=None)
        self.ha = HAClient(cfg.ha_url, cfg.ha_token, http=ha_http)
        self.devices = DeviceBridge(
            self.ha,
            lambda: self.store.state.devices.exposed if self.store.state.devices else (),
            events=self.link,
            clock=clock,
        )
        # I1: each plugin reads its own keys from bridge.env (MQTT, Frigate, Faces; never the Home
        # Assistant token: `plugin_env`) and can find the plugins built before or after it by name
        # when a message arrives
        peers: dict[str, BridgePlugin] = {}
        ctx = BridgeContext(
            env=plugin_env(env), data_dir=cfg.data_dir, events=self.link, now=clock, peers=peers
        )
        self.heartbeat: HeartbeatLoop | None = None
        self.broken: tuple[str, ...] = ()
        core = CorePlugin(self.store, self.ha, self.devices, self._apply, lambda: self.broken)
        self.plugins: list[BridgePlugin] = [core, *self._build(factories, ctx)]
        peers.update({p.name: p for p in self.plugins})
        check_routes(self.plugins)
        self.heartbeat = HeartbeatLoop(self.store, self.link, self.plugins, clock=clock)
        self._routes: dict[tuple[str, str], BridgeRoute] = {
            (r.method, r.path): r for p in self.plugins for r in p.routes()
        }
        self.supervisor = Supervisor()
        self._large = asyncio.Lock()  # one large upload (a photo) is read at a time
        self.app = self._app()

    def _build(self, factories: Sequence[PluginFactory], ctx: BridgeContext) -> list[BridgePlugin]:
        """Each plugin from its factory. Review M10: one that raises is logged by name and
        skipped (the core and the others still start) and the heartbeat says so (`mqtt` false)."""
        built: list[BridgePlugin] = []
        broken: list[str] = []
        for factory in factories:
            name = str(getattr(factory, "__name__", "plugin"))
            try:
                built.append(factory(ctx))
            except Exception as exc:  # noqa: BLE001 - the bridge itself keeps running
                log.error(
                    "a bridge part could not start",
                    extra={"part": name, "error": type(exc).__name__},
                )
                broken.append(name)
        self.broken = tuple(broken)
        return built

    async def _apply(self, state: BridgeState) -> None:
        assert self.heartbeat is not None
        await self.heartbeat.apply(state)

    async def _close_plugins(self) -> None:
        for plugin in self.plugins:
            close = getattr(plugin, "aclose", None)
            if close is None:
                continue
            try:
                await close()
            except Exception as exc:  # noqa: BLE001 - every plugin gets its turn to close
                log.warning(
                    "a bridge part did not close",
                    extra={"part": plugin.name, "error": type(exc).__name__},
                )

    def _lifespan(self) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
        @asynccontextmanager
        async def lifespan(_: FastAPI) -> AsyncIterator[None]:
            assert self.heartbeat is not None
            self.supervisor.start("heartbeat", self.heartbeat.run)
            for plugin in self.plugins:
                for i, task in enumerate(plugin.tasks()):
                    self.supervisor.start(f"{plugin.name}-{i}", task)
            try:
                yield
            finally:
                await self.supervisor.stop()
                await self._close_plugins()
                await self.link.aclose()
                await self.ha.aclose()

        return lifespan

    def _app(self) -> FastAPI:
        app = FastAPI(lifespan=self._lifespan(), docs_url=None, redoc_url=None, openapi_url=None)

        @app.api_route(
            "/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
        )
        async def handle(request: Request, path: str) -> Response:
            return await self._serve(request)

        return app

    async def _read(self, request: Request, limit: int) -> bytes | int:
        """The body within the route's cap, or the status to answer with. Megabytes (R11.1 O7:
        one photo) are read only for a caller whose header could be this home's (the signature
        itself is checked afterwards, over the body), and one upload at a time."""
        declared = _declared(request)
        if declared == -1:
            return 400  # a Content-Length that is not a plain number: never a 500
        if declared is not None and declared > limit:
            return 413
        if limit <= MAX_BODY_BYTES:
            return await _read_in_time(request, limit)
        digest = request.headers.get(signing.BODY_HASH_HEADER)
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        header = request.headers.get(signing.HEADER)
        if not self.auth.precheck(header, method=request.method, target=target, digest=digest):
            return 401
        if self._large.locked():
            return 503
        async with self._large:
            body = await _read_in_time(request, limit)
        if isinstance(body, bytes) and signing.body_hash(body) != digest:
            return 401  # not the body that was signed
        return body

    async def _serve(self, request: Request) -> Response:
        method, path = request.method, request.url.path
        route = self._routes.get((method, path)) if route_allowed(method, path) else None
        if route is None:
            return _bare(404)
        raw_query = request.url.query
        target = path + (f"?{raw_query}" if raw_query else "")
        body = await self._read(request, body_limit(method, path))
        if isinstance(body, int):
            return _bare(body)
        try:
            who = self.auth.check(
                request.headers.get(signing.HEADER), method=method, target=target, body=body
            )
        except signing.SignatureError as exc:
            log.info("bridge request refused", extra={"check": exc.check})
            return _bare(401)
        status, data = 200, {}
        try:
            parsed: Mapping[str, Any] | None = None
            if method == "POST":
                loaded = json.loads(body) if body else {}
                if not isinstance(loaded, dict):
                    raise ValueError("body")
                parsed = loaded
            data = await route.handler(dict(request.query_params), parsed)
        except HomeRefused as exc:
            status, data = 400, {"code": exc.code}
        except ValueError:
            status, data = 422, {"code": "invalid"}
        except Exception as exc:  # noqa: BLE001 - never leak a cause
            log.error("bridge handler failed", extra={"error": type(exc).__name__})
            status, data = 500, {"code": "error"}
        raw = json.dumps(data, separators=(",", ":")).encode()
        header = self.auth.reply_header(who, status=status, method=method, target=target, body=raw)
        return Response(
            content=raw,
            status_code=status,
            media_type="application/json",
            headers={signing.HEADER: header, "Cache-Control": "no-store"},
        )


def body_limit(method: str, path: str) -> int:
    """The most bytes the bridge reads on one route: 64 KB, except one photo (R11.1 O7)."""
    return MAX_BODY_BYTES_BY_ROUTE.get((method, path), MAX_BODY_BYTES)


def _declared(request: Request) -> int | None:
    """The declared Content-Length; None when there is none; -1 when it is not a plain ASCII
    number (review C-sec L4: "²".isdigit() is True, int("²") raises)."""
    declared = request.headers.get("content-length")
    if declared is None:
        return None
    if not (declared.isascii() and declared.isdigit()) or len(declared) > 12:
        return -1
    return int(declared)


async def _read_in_time(request: Request, limit: int) -> bytes | int:
    """The body within its cap (413) and within `BODY_READ_S` (408): a caller that sends one
    byte a minute holds nothing for long."""
    try:
        async with asyncio.timeout(BODY_READ_S):
            body = await _read_capped(request, limit)
    except TimeoutError:
        return 408
    return 413 if body is None else body


async def _read_capped(request: Request, limit: int = MAX_BODY_BYTES) -> bytes | None:
    declared = _declared(request)
    if declared == -1 or (declared is not None and declared > limit):
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def create_bridge(cfg: BridgeConfig, factories: Sequence[PluginFactory] = (), **kw: Any) -> Bridge:
    return Bridge(cfg, factories, **kw)


__all__ = ["Bridge", "CorePlugin", "Supervisor", "body_limit", "create_bridge"]

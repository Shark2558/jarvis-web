# src/jarvis/homebridge/app.py
"""The bridge's signed API (R3 D3, D5, D6). Ships in the home kit.

`create_bridge(cfg, factories)` builds the one web app on 127.0.0.1:8099 (Tailscale Funnel proxies
port 8443 to it). It serves ONLY `jarvis.home.ports.BRIDGE_ROUTES`; everything else is a bare 404.
For a fixed route the order is: body <= 64 KB (413) -> signature (`BridgeAuth.check`, a bare 401 on
any failure) -> JSON parse -> the plugin's handler -> a signed answer. A handler runs only after the
signature, so an unauthenticated caller reaches no plugin code and no Home Assistant call.

The core plugin (this module) serves health, state, devices and device actions; B's camera plugin
and C's faces plugin serve events, packages and faces/summary and are listed in
`registry.PLUGINS` (I1). Plugins are checked once: a route can't be served twice.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import asynccontextmanager, suppress
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
from jarvis.homebridge.config import BRIDGE_VERSION, MAX_BODY_BYTES, BridgeConfig
from jarvis.homebridge.devices import DeviceBridge
from jarvis.homebridge.ha import HAClient
from jarvis.homebridge.heartbeat import HeartbeatLoop
from jarvis.homebridge.plugins import (
    BridgeContext,
    BridgePlugin,
    BridgeRoute,
    PluginFactory,
    TaskFactory,
    check_routes,
)
from jarvis.homebridge.state import BridgeStore

log = logging.getLogger(__name__)
RESTART_DELAY_S = 5.0


class CorePlugin:
    """Health, state, devices and device actions (A)."""

    name = "core"

    def __init__(
        self,
        store: BridgeStore,
        ha: HAClient,
        devices: DeviceBridge,
        apply: Callable[[BridgeState], Any],
    ) -> None:
        self._store = store
        self._ha = ha
        self._devices = devices
        self._apply = apply

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
        return HeartbeatParts(ha=await self._ha.ping() if self._ha.linked else False)

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
    """Runs each task and starts it again if it stops (a plugin crash must not end the bridge)."""

    def __init__(self, delay_s: float = RESTART_DELAY_S) -> None:
        self._delay = delay_s
        self._tasks: list[asyncio.Task[None]] = []

    def start(self, name: str, factory: TaskFactory) -> None:
        self._tasks.append(asyncio.create_task(self._loop(name, factory)))

    async def _loop(self, name: str, factory: TaskFactory) -> None:
        while True:
            try:
                await factory()
            except asyncio.CancelledError:
                raise
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
        ctx = BridgeContext(env={}, data_dir=cfg.data_dir, events=self.link, now=clock)
        self.heartbeat: HeartbeatLoop | None = None
        core = CorePlugin(self.store, self.ha, self.devices, self._apply)
        self.plugins: list[BridgePlugin] = [core, *(f(ctx) for f in factories)]
        check_routes(self.plugins)
        self.heartbeat = HeartbeatLoop(self.store, self.link, self.plugins, clock=clock)
        self._routes: dict[tuple[str, str], BridgeRoute] = {
            (r.method, r.path): r for p in self.plugins for r in p.routes()
        }
        self.supervisor = Supervisor()
        self.app = self._build()

    async def _apply(self, state: BridgeState) -> None:
        assert self.heartbeat is not None
        await self.heartbeat.apply(state)

    def _build(self) -> FastAPI:
        @asynccontextmanager
        async def lifespan(_: FastAPI):  # type: ignore[no-untyped-def]
            assert self.heartbeat is not None
            self.supervisor.start("heartbeat", self.heartbeat.run)
            for plugin in self.plugins:
                for i, task in enumerate(plugin.tasks()):
                    self.supervisor.start(f"{plugin.name}-{i}", task)
            try:
                yield
            finally:
                await self.supervisor.stop()
                await self.link.aclose()
                await self.ha.aclose()

        app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

        @app.api_route(
            "/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
        )
        async def handle(request: Request, path: str) -> Response:
            return await self._serve(request)

        return app

    async def _serve(self, request: Request) -> Response:
        method, path = request.method, request.url.path
        route = self._routes.get((method, path)) if route_allowed(method, path) else None
        if route is None:
            return _bare(404)
        raw_query = request.url.query
        target = path + (f"?{raw_query}" if raw_query else "")
        body = await _read_capped(request)
        if body is None:
            return _bare(413)
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


async def _read_capped(request: Request) -> bytes | None:
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > MAX_BODY_BYTES):
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def create_bridge(cfg: BridgeConfig, factories: Sequence[PluginFactory] = (), **kw: Any) -> Bridge:
    return Bridge(cfg, factories, **kw)


__all__ = ["Bridge", "CorePlugin", "Supervisor", "create_bridge"]

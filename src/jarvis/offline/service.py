# src/jarvis/offline/service.py
"""Offline mode (R1 D10-D12): the fallback brain on the owner's laptop.

`LocalFallback` is what `ModelRouter` calls when the cloud brain is unreachable (see
`jarvis.llm.fallback.FallbackBrain`). Ollama on the laptop speaks the OpenAI-compatible API behind a
Caddy bearer-key gate, published by Tailscale Funnel (TLS ends on the laptop). Per call it:

- reads the config (`LocalBrainStore`) and refuses unless it is switched on;
- re-checks that the tunnel name still resolves only to public addresses (a name that later points
  inward is refused: `config.ensure_public`);
- offers the laptop at most `OFFLINE_TOOLS`, adds the offline note, drops calls to anything else;
- marks the reply offline (`core.channel.mark_offline`, so `OfflineRules` makes every write ask)
  and meters it at zero;
- tells the owner (alerts port) when offline mode switches on or off, at most once per 30 minutes
  per kind; a failing alert never breaks an answer.

It also owns the status the console shows (Off / Standby / Active / Laptop not answering), the
settings (`configure`, `clear`) and the Test button. Nothing here logs the URL or the key; vendor
and server text never reaches the owner or the model.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from jarvis.alerts import AlertKind, AlertSink
from jarvis.config import Settings
from jarvis.core.channel import mark_offline
from jarvis.integrations.vault import TokenCipher
from jarvis.llm.base import (
    ChatMessage,
    Completion,
    Effort,
    LLMAuthError,
    LLMError,
    StreamUsage,
    ToolSpec,
)
from jarvis.llm.fallback import confine, offline_tools, offline_trailer
from jarvis.llm.local_provider import MAX_RESPONSE_BYTES, LocalBrainProvider
from jarvis.llm.router import ModelTier
from jarvis.logging import get_logger
from jarvis.offline.config import (
    PinnedTransport,
    Resolver,
    UrlRejected,
    check_url,
    ensure_public,
    system_resolver,
)
from jarvis.offline.prompt import OFFLINE_SYSTEM_PROMPT
from jarvis.offline.store import LocalBrainConfig, LocalBrainStore, valid_model
from jarvis.storage.docs import Docs

log = get_logger(__name__)

TEST_TIMEOUT_S = 5.0
ALERT_GAP_S = 30 * 60.0  # at most one alert of each kind per half hour
LAST_OK_WRITE_GAP_S = 60.0
ALERT_SEND_TIMEOUT_S = 5.0
KEY_MIN, KEY_MAX = 16, 200
MAX_LISTED_MODELS = 50

ALERT_TEXT: dict[str, str] = {
    "offline_on": (
        "JARVIS is in offline mode: Claude can't be reached, so your laptop is answering. "
        "Every change will ask first."
    ),
    "offline_off": "Claude is reachable again. JARVIS is out of offline mode.",
}


class OfflineRejected(Exception):
    """A settings change that can't be accepted; `detail` is plain words for the owner."""

    def __init__(self, code: str, detail: str, *, status: int = 422) -> None:
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _clean_key(raw: object) -> str:
    key = raw.strip() if isinstance(raw, str) else ""
    if not (KEY_MIN <= len(key) <= KEY_MAX) or not all(0x21 <= ord(c) <= 0x7E for c in key):
        raise OfflineRejected(
            "invalid_key",
            f"Paste the key the start script printed ({KEY_MIN}-{KEY_MAX} characters, no spaces).",
        )
    return key


def _model_listed(wanted: str, models: list[str]) -> bool:
    return wanted in models or (":" not in wanted and f"{wanted}:latest" in models)


def _failure_state(exc: Exception) -> str:
    return "refused" if isinstance(exc, LLMAuthError) else "unreachable"


class LocalFallback:
    def __init__(
        self,
        store: LocalBrainStore,
        *,
        alerts: AlertSink,
        timeout_s: float,
        resolver: Resolver = system_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._store = store
        self._alerts = alerts
        self._timeout = timeout_s
        self._resolver = resolver
        self._transport = transport
        self._clock = clock
        self._now = now
        self._active = False  # the laptop has been answering and the cloud has not come back
        self._failed: str | None = None  # 'unreachable' | 'refused' after a failed answer or Test
        self._last_used: datetime | None = None
        self._alert_at: dict[str, float] = {}
        self._ok_written_at: float | None = None

    @property
    def store(self) -> LocalBrainStore:
        """The laptop's stored address and key (R2: the privacy dashboard's `offline` row)."""
        return self._store

    # ---- FallbackBrain (called by ModelRouter) -------------------------------------------

    async def ready(self) -> bool:
        cfg = await self._store.get()
        return cfg is not None and cfg.enabled

    async def _open(self) -> tuple[LocalBrainConfig, LocalBrainProvider]:
        cfg = await self._store.get()
        if cfg is None or not cfg.enabled:
            raise LLMError("offline mode is off")
        host = urlsplit(cfg.url).hostname or ""
        try:
            await ensure_public(host, resolver=self._resolver)
        except UrlRejected as exc:
            raise LLMError("the laptop address is no longer a public Funnel address") from exc
        provider = LocalBrainProvider(
            cfg.url,
            api_key=cfg.key.get_secret_value(),
            timeout_s=self._timeout,
            transport=PinnedTransport(self._resolver, self._transport),
        )
        return cfg, provider

    async def complete(
        self,
        *,
        tier: ModelTier,
        system: str,
        system_dynamic: str | None,
        messages: list[ChatMessage],
        max_tokens: int,
        effort: Effort | None,
        tools: list[ToolSpec] | None,
    ) -> Completion:
        offered = offline_tools(tools)
        provider: LocalBrainProvider | None = None
        try:
            cfg, provider = await self._open()
            done = await provider.complete(
                system=OFFLINE_SYSTEM_PROMPT,
                system_dynamic=offline_trailer(system_dynamic),
                messages=messages,
                model=cfg.model,
                max_tokens=max_tokens,
                effort=effort,
                tools=offered,
            )
        except Exception as exc:
            self._failed = _failure_state(exc)
            raise
        finally:
            if provider is not None:
                await provider.aclose()
        mark_offline()
        await self._answered(cfg)
        return confine(done, offered)

    async def stream(
        self,
        *,
        tier: ModelTier,
        system: str,
        system_dynamic: str | None,
        messages: list[ChatMessage],
        max_tokens: int,
        effort: Effort | None,
        usage: StreamUsage | None,
    ) -> AsyncIterator[str]:
        provider: LocalBrainProvider | None = None
        try:
            cfg, provider = await self._open()
            first = True
            async for delta in provider.stream(
                system=OFFLINE_SYSTEM_PROMPT,
                system_dynamic=offline_trailer(system_dynamic),
                messages=messages,
                model=cfg.model,
                max_tokens=max_tokens,
                effort=effort,
                usage=usage,
            ):
                if first:
                    mark_offline()
                    first = False
                yield delta
        except Exception as exc:
            self._failed = _failure_state(exc)
            raise
        finally:
            if provider is not None:
                await provider.aclose()
        mark_offline()
        await self._answered(cfg)

    async def cloud_ok(self) -> None:
        if not self._active:
            return
        self._active = False
        await self._alert(await self._owner(), "offline_off")

    # ---- bookkeeping ---------------------------------------------------------------------

    async def _owner(self) -> str | None:
        cfg = await self._store.get()
        return cfg.set_by if cfg else None

    async def _answered(self, cfg: LocalBrainConfig) -> None:
        self._failed = None
        self._last_used = self._now()
        if (
            self._ok_written_at is None
            or self._clock() - self._ok_written_at >= LAST_OK_WRITE_GAP_S
        ):
            self._ok_written_at = self._clock()
            await self._safely(self._store.touch_ok(self._now()))
        if not self._active:
            self._active = True
            await self._alert(cfg.set_by, "offline_on")

    async def _safely(self, work: Any) -> None:
        try:
            await work
        except Exception as exc:  # noqa: BLE001 - bookkeeping never fails an answer
            log.warning("offline bookkeeping failed", extra={"error": type(exc).__name__})

    async def _alert(self, uid: str | None, kind: AlertKind) -> None:
        last = self._alert_at.get(kind)
        if uid is None or (last is not None and self._clock() - last < ALERT_GAP_S):
            return
        self._alert_at[kind] = self._clock()
        try:
            async with asyncio.timeout(ALERT_SEND_TIMEOUT_S):
                await self._alerts.send(uid, ALERT_TEXT[kind], kind=kind)
        except Exception as exc:  # noqa: BLE001 - an alert is a courtesy, never a failure
            log.warning("offline alert not sent", extra={"error": type(exc).__name__})

    # ---- status, settings, test (used by the API) ----------------------------------------

    async def status(self) -> dict[str, Any]:
        cfg = await self._store.get()
        if cfg is None:
            state = "off"
        elif not cfg.enabled:
            state = "off"
        elif self._failed:
            state = self._failed
        else:
            state = "active" if self._active else "standby"
        return {
            "available": True,
            "configured": cfg is not None,
            "enabled": bool(cfg and cfg.enabled),
            "host": urlsplit(cfg.url).hostname if cfg else None,
            "model": cfg.model if cfg else None,
            "state": state,
            "last_ok_at": cfg.last_ok_at.isoformat() if cfg and cfg.last_ok_at else None,
            "last_used_at": self._last_used.isoformat() if self._last_used else None,
        }

    async def configure(
        self,
        uid: str,
        *,
        url: str | None = None,
        key: str | None = None,
        model: str | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        cfg = await self._store.get()
        if cfg is None and (url is None or key is None or model is None):
            raise OfflineRejected("missing", "Fill in the address, the key and the model name.")
        new_url = cfg.url if cfg else ""
        if url is not None:
            try:
                new_url = (await check_url(url, resolver=self._resolver)).base
            except UrlRejected as exc:
                raise OfflineRejected("invalid_url", exc.reason) from None
        if key is None and cfg is not None and new_url != cfg.url:
            # the saved key is never sent to a different address unasked
            raise OfflineRejected("invalid_key", "You changed the address, so paste the key again.")
        new_key = SecretStr(_clean_key(key)) if key is not None else (cfg.key if cfg else None)
        new_model = model.strip() if isinstance(model, str) else (cfg.model if cfg else "")
        if not valid_model(new_model):
            raise OfflineRejected(
                "invalid_model", "Name the model you pulled in Ollama, for example qwen2.5:3b."
            )
        assert new_key is not None
        on = enabled if enabled is not None else (cfg.enabled if cfg else False)
        await self._store.put(url=new_url, key=new_key, model=new_model, enabled=on, set_by=uid)
        if not on:
            self._active = False
        self._failed = None
        return await self.status()

    async def clear(self, uid: str) -> dict[str, Any]:
        await self._store.delete()
        self._active = False
        self._failed = None
        self._last_used = None
        return await self.status()

    def _failure(self, detail: str, state: str = "unreachable") -> dict[str, Any]:
        self._failed = state
        return {"ok": False, "models": [], "detail": detail}

    async def test(self) -> dict[str, Any]:
        """`GET <url>/models` with the key, 5 s at most. Plain words for every outcome."""
        cfg = await self._store.get()
        if cfg is None:
            return {"ok": False, "models": [], "detail": "Offline mode isn't set up yet."}
        try:
            await ensure_public(urlsplit(cfg.url).hostname or "", resolver=self._resolver)
        except UrlRejected as exc:
            return self._failure(exc.reason)
        try:
            status, body = await self._get_models(cfg)
        except (httpx.HTTPError, TimeoutError, OSError):
            return self._failure(
                "Your laptop didn't answer. Is it awake, with Tailscale Funnel on?"
            )
        if status in (401, 403):
            return self._failure(
                "The laptop refused the key. Paste the new key in Integrations -> Offline mode.",
                "refused",
            )
        if status == 404:
            return self._failure(
                "Something answered, but it isn't the JARVIS gate. "
                "Check the address and that the start script is running."
            )
        if 300 <= status < 400:
            return self._failure("The address redirected somewhere else, which isn't allowed.")
        if status >= 500:
            return self._failure("The tunnel is up but Ollama isn't answering. Is Ollama running?")
        if status != 200:
            return self._failure("The laptop gave an answer JARVIS didn't expect.")
        models = self._model_ids(body)
        if models is None:
            return self._failure("The laptop gave an answer JARVIS didn't expect.")
        if not _model_listed(cfg.model, models):
            self._failed = "unreachable"
            return {
                "ok": False,
                "models": models,
                "detail": (
                    f"Your laptop answered, but the model {cfg.model} isn't installed there. "
                    f"Run: ollama pull {cfg.model}"
                ),
            }
        self._failed = None
        self._ok_written_at = self._clock()
        await self._safely(self._store.touch_ok(self._now()))
        return {
            "ok": True,
            "models": models,
            "detail": f"Your laptop answered (model {cfg.model}).",
        }

    async def _get_models(self, cfg: LocalBrainConfig) -> tuple[int, bytes]:
        async with asyncio.timeout(TEST_TIMEOUT_S):
            async with httpx.AsyncClient(
                timeout=TEST_TIMEOUT_S,
                follow_redirects=False,
                transport=PinnedTransport(self._resolver, self._transport),
            ) as client:
                async with client.stream(
                    "GET",
                    f"{cfg.url}/models",
                    headers={"authorization": f"Bearer {cfg.key.get_secret_value()}"},
                ) as resp:
                    buf = bytearray()
                    async for chunk in resp.aiter_bytes():
                        buf += chunk
                        if len(buf) > MAX_RESPONSE_BYTES:
                            return 0, b""
                    return resp.status_code, bytes(buf)

    @staticmethod
    def _model_ids(body: bytes) -> list[str] | None:
        try:
            data = json.loads(body)["data"]
            ids = [m["id"] for m in data if isinstance(m, dict) and valid_model(m.get("id"))]
        except (ValueError, KeyError, TypeError):
            return None
        return ids[:MAX_LISTED_MODELS]


def build_local_fallback(s: Settings, docs: Docs, alerts: AlertSink) -> LocalFallback | None:
    """The offline service, or None when there is no token key (the feature is off)."""
    key = s.token_key_bytes()
    if key is None:
        return None
    store = LocalBrainStore(docs, TokenCipher(key), prefix=s.firestore_prefix)
    return LocalFallback(store, alerts=alerts, timeout_s=s.local_brain_timeout_s)


__all__ = ["LocalFallback", "OfflineRejected", "build_local_fallback"]

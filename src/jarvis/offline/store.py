# src/jarvis/offline/store.py
"""The laptop-brain config document (R1 D10), deployment-wide: `<prefix>local_brain/config`.

    {blob: AES-GCM({url, key}), model, enabled, set_by, updated_at, last_ok_at}

URL and key are encrypted with the token key (`TokenCipher`, AAD "local_brain/config"); nothing else
in the document is secret. A document that can't be read (another token key, a tampered or hand
edited blob) reads as "not configured" and is logged; the feature then stays off.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import SecretStr

from jarvis.integrations.vault import TokenCipher, VaultError
from jarvis.logging import get_logger
from jarvis.storage.docs import Doc, Docs, DocTx

log = get_logger(__name__)

AAD = "local_brain/config"
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}")


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class LocalBrainConfig:
    url: str
    key: SecretStr
    model: str
    enabled: bool
    set_by: str
    updated_at: datetime
    last_ok_at: datetime | None = None


def valid_model(model: object) -> bool:
    return isinstance(model, str) and MODEL_RE.fullmatch(model) is not None


def _when(v: object) -> datetime | None:
    return datetime.fromisoformat(v) if isinstance(v, str) else None


class LocalBrainStore:
    def __init__(
        self,
        docs: Docs,
        cipher: TokenCipher,
        *,
        prefix: str = "jarvis_",
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._d = docs
        self._cipher = cipher
        self._path = f"{prefix}local_brain/config"
        self._now = now

    async def _raw(self) -> Doc | None:
        return await self._d.get(self._path)

    def _decode(self, raw: Doc) -> LocalBrainConfig | None:
        try:
            secret = json.loads(self._cipher.decrypt(raw["blob"], aad=AAD))
            model = raw["model"]
            if not valid_model(model) or not isinstance(secret["url"], str):
                raise ValueError("bad fields")
            return LocalBrainConfig(
                url=secret["url"],
                key=SecretStr(str(secret["key"])),
                model=model,
                enabled=raw["enabled"] is True,
                set_by=str(raw["set_by"]),
                updated_at=_when(raw["updated_at"]) or self._now(),
                last_ok_at=_when(raw.get("last_ok_at")),
            )
        except (VaultError, KeyError, TypeError, ValueError) as exc:
            log.warning("laptop brain config unreadable", extra={"reason": type(exc).__name__})
            return None

    async def get(self) -> LocalBrainConfig | None:
        raw = await self._raw()
        return None if raw is None else self._decode(raw)

    async def put(
        self, *, url: str, key: SecretStr, model: str, enabled: bool, set_by: str
    ) -> LocalBrainConfig:
        if not valid_model(model):
            raise ValueError("bad model name")
        blob = self._cipher.encrypt(
            json.dumps({"url": url, "key": key.get_secret_value()}).encode(), aad=AAD
        )
        now = self._now()

        async def work(tx: DocTx) -> LocalBrainConfig:
            raw = await tx.get(self._path)
            old = None if raw is None else self._decode(raw)
            same = (
                old is not None
                and old.url == url
                and old.key.get_secret_value() == key.get_secret_value()
            )
            last_ok = old.last_ok_at if same and old is not None else None
            tx.set(
                self._path,
                {
                    "blob": blob,
                    "model": model,
                    "enabled": bool(enabled),
                    "set_by": set_by,
                    "updated_at": now.isoformat(),
                    "last_ok_at": last_ok.isoformat() if last_ok else None,
                },
            )
            return LocalBrainConfig(url, key, model, bool(enabled), set_by, now, last_ok)

        return await self._d.transaction(work)

    async def _amend(self, changes: Doc) -> bool:
        """Read-modify-write in one transaction, so a Forget or a new key that lands in between
        is never undone (a plain get + set would write the old blob back). Never creates."""

        async def work(tx: DocTx) -> bool:
            raw = await tx.get(self._path)
            if raw is None:
                return False
            tx.set(self._path, {**raw, **changes})
            return True

        return await self._d.transaction(work)

    async def set_enabled(self, enabled: bool, *, by: str) -> bool:
        """Flip the switch only. False when nothing is stored."""
        return await self._amend(
            {"enabled": bool(enabled), "set_by": by, "updated_at": self._now().isoformat()}
        )

    async def touch_ok(self, when: datetime) -> None:
        """The laptop answered at `when`. Never creates the document."""
        await self._amend({"last_ok_at": when.isoformat()})

    async def delete(self) -> None:
        await self._d.transaction(_forget(self._path))


def _forget(path: str) -> Callable[[DocTx], Awaitable[None]]:
    async def work(tx: DocTx) -> None:
        tx.delete(path)

    return work

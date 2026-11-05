# src/jarvis/webpush/store.py
"""Browser subscriptions on the Docs port, encrypted by JARVIS (R3 D11, D14; Layer 7).

    {prefix}webpush/{uid}   {rev, v, kid, blob, updated_at}
        blob = AES-GCM(JSON [Device...]) under the `webpush` key, AAD `webpush/{uid}/v1`

At most 5 devices. The endpoint and keys are never in a Firestore field in clear. A document that
can't be read or decrypted is `PushUnavailable` and is never overwritten.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.notify.ports import MAX_PUSH_DEVICES
from jarvis.storage.docs import Delete, Docs, DocTx
from jarvis.undo.store import owner_ok

log = get_logger(__name__)
VERSION = 1
UNAVAILABLE = "JARVIS couldn't open your browser notification list just now. Try again in a minute."


class PushUnavailable(RuntimeError):
    """The list can't be read or saved (plain words)."""


class PushFull(RuntimeError):
    """Five devices already."""


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    endpoint: str
    p256dh: str
    auth: str
    added_at: str
    last_ok_at: str | None = None

    def view(self) -> dict[str, Any]:
        """What the console may see: no endpoint, no keys."""
        return {"id": self.id, "name": self.name, "added_at": self.added_at}


def _now() -> str:
    return datetime.now(UTC).isoformat()


class PushStore:
    def __init__(self, docs: Docs, keyring: Keyring, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._ring = keyring
        self._coll = f"{prefix}webpush"

    def _path(self, uid: str) -> str:
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        return f"{self._coll}/{uid}"

    def _open(self, uid: str, doc: dict[str, Any] | None) -> list[Device]:
        if doc is None:
            return []
        blob = doc.get("blob")
        if not isinstance(blob, str):
            raise ValueError("envelope")
        raw = json.loads(self._ring.cipher("webpush").decrypt(blob, aad=f"webpush/{uid}/v1"))
        out = [Device(**d) for d in raw]
        if len(out) > MAX_PUSH_DEVICES:
            raise ValueError("too many")
        return out

    def _seal(self, uid: str, devices: list[Device]) -> dict[str, Any]:
        plain = json.dumps([asdict(d) for d in devices]).encode()
        blob = self._ring.cipher("webpush").encrypt(plain, aad=f"webpush/{uid}/v1")
        return {"v": VERSION, "kid": self._ring.kid, "blob": blob, "updated_at": _now()}

    async def list(self, uid: str) -> list[Device]:
        try:
            return self._open(uid, await self._d.get(self._path(uid)))
        except Exception as exc:  # noqa: BLE001
            log.warning("push list unreadable", extra={"error": type(exc).__name__})
            raise PushUnavailable(UNAVAILABLE) from None

    async def _change(self, uid: str, fn: Any) -> Any:
        path = self._path(uid)

        async def tx_fn(tx: DocTx) -> Any:
            try:
                cur = self._open(uid, await tx.get(path))
            except Exception:  # noqa: BLE001
                raise PushUnavailable(UNAVAILABLE) from None
            new, result = fn(cur)
            if new is not None:
                tx.set(path, self._seal(uid, new))
            return result

        try:
            return await self._d.transaction(tx_fn)
        except (PushUnavailable, PushFull):
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("push list not saved", extra={"error": type(exc).__name__})
            raise PushUnavailable(UNAVAILABLE) from None

    async def add(self, uid: str, name: str, endpoint: str, p256dh: str, auth: str) -> Device:
        """A new device (the same endpoint replaces its old entry)."""
        dev = Device(
            id="w_" + secrets.token_hex(4),
            name=name,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            added_at=_now(),
        )

        def fn(cur: list[Device]) -> tuple[list[Device] | None, Device]:
            rest = [d for d in cur if d.endpoint != endpoint]
            if len(rest) >= MAX_PUSH_DEVICES:
                raise PushFull("Five devices are already set up. Remove one first.")
            return [*rest, dev], dev

        return await self._change(uid, fn)  # type: ignore[no-any-return]

    async def remove(self, uid: str, device_id: str) -> bool:
        def fn(cur: list[Device]) -> tuple[list[Device] | None, bool]:
            rest = [d for d in cur if d.id != device_id]
            return (rest, True) if len(rest) != len(cur) else (None, False)

        return await self._change(uid, fn)  # type: ignore[no-any-return]

    async def mark_ok(self, uid: str, device_id: str) -> None:
        def fn(cur: list[Device]) -> tuple[list[Device] | None, None]:
            if not any(d.id == device_id for d in cur):
                return None, None
            at = _now()
            return [
                Device(**{**asdict(d), "last_ok_at": at}) if d.id == device_id else d for d in cur
            ], None

        await self._change(uid, fn)

    async def clear(self, uid: str) -> None:
        await self._d.write([Delete(self._path(uid))])


__all__ = ["Device", "PushFull", "PushStore", "PushUnavailable"]

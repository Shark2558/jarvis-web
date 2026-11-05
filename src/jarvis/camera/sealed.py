# src/jarvis/camera/sealed.py
"""One encrypted JSON document per owner on the `Docs` port (R3; Layer 7).

The body is AES-GCM sealed by `Keyring.cipher(purpose)` with an AAD naming the document and the
owner; only `{blob, updated_at}` are visible in Firestore. A document that can't be read or
decrypted is `CameraUnavailable` and is never overwritten (fail closed); errors carry plain words,
never the cause.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel

from jarvis.camera.ports import CameraUnavailable
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, DocTx
from jarvis.undo.store import owner_ok

log = get_logger(__name__)

M = TypeVar("M", bound=BaseModel)
UNAVAILABLE = "JARVIS couldn't open your camera settings just now. Try again in a minute."


class SealedDoc(Generic[M]):  # noqa: UP046 - Python 3.11 keeps the classic form
    def __init__(
        self,
        docs: Docs,
        keyring: Keyring,
        *,
        collection: str,
        purpose: str,
        name: str,
        model: type[M],
    ) -> None:
        self._d = docs
        self._ring = keyring
        self._collection = collection
        self._purpose = purpose
        self._name = name
        self._model = model

    def _path(self, uid: str) -> str:
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        return f"{self._collection}/{uid}"

    def _aad(self, uid: str) -> str:
        return f"{self._name}/{uid}/v1"

    def _open(self, uid: str, doc: dict[str, object] | None) -> M:
        if doc is None:
            return self._model()
        blob = doc.get("blob")
        if not isinstance(blob, str):
            raise ValueError("envelope")
        raw = self._ring.cipher(self._purpose).decrypt(blob, aad=self._aad(uid))
        return self._model.model_validate_json(raw)

    def _seal(self, uid: str, value: M) -> dict[str, object]:
        blob = self._ring.cipher(self._purpose).encrypt(
            value.model_dump_json().encode(), aad=self._aad(uid)
        )
        return {"blob": blob, "updated_at": datetime.now(UTC).isoformat()}

    async def load(self, uid: str) -> M:
        try:
            return self._open(uid, await self._d.get(self._path(uid)))
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001 - storage or data trouble: read nothing
            log.warning("camera data unreadable", extra={"reason": type(exc).__name__})
            raise CameraUnavailable(UNAVAILABLE) from None

    async def update(self, uid: str, fn: Callable[[M], M | None]) -> M:
        """Read, let `fn` return the new value (None = unchanged), write: one transaction."""
        path = self._path(uid)

        async def tx(t: DocTx) -> M:
            try:
                current = self._open(uid, await t.get(path))
            except Exception as exc:  # noqa: BLE001
                log.warning("camera data corrupt; refusing", extra={"reason": type(exc).__name__})
                raise CameraUnavailable(UNAVAILABLE) from None
            new = fn(current)
            if new is None or new == current:
                return current
            t.set(path, self._seal(uid, new))
            return new

        try:
            return await self._d.transaction(tx)
        except CameraUnavailable:
            raise
        except (ValueError, LookupError, PermissionError):
            raise
        except Exception as exc:  # noqa: BLE001 - nothing changed
            log.warning("camera data not saved", extra={"reason": type(exc).__name__})
            raise CameraUnavailable(UNAVAILABLE) from None

    async def delete(self, uid: str) -> None:
        try:
            await self._d.write([Delete(self._path(uid))])
        except Exception as exc:  # noqa: BLE001
            log.warning("camera data not deleted", extra={"reason": type(exc).__name__})
            raise CameraUnavailable(UNAVAILABLE) from None


__all__ = ["UNAVAILABLE", "SealedDoc"]

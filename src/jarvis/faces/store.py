# src/jarvis/faces/store.py
"""The Faces registry on the `Docs` port, encrypted by JARVIS (R3 D13, D14; Layer 7).

    {prefix}faces/{uid}    {rev, v, kid, blob, updated_at}
        blob = AES-GCM(JSON {people: [Person...]}) under the `faces` key, AAD `faces/{uid}/v1`

No name, relation or consent date is ever in a Firestore field in clear, and no picture or
embedding is ever here. A document that can't be read or decrypted is `FacesUnavailable` and is
never overwritten; errors carry plain words and never the cause's text.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from jarvis.faces.models import MAX, Person, State
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, DocTx
from jarvis.undo.store import owner_ok

log = get_logger(__name__)

VERSION = 1
UNAVAILABLE = (
    "JARVIS couldn't open the list of people it recognises just now. Try again in a minute."
)
UNSAVED = "JARVIS couldn't save that just now. Try again in a minute."


class FacesUnavailable(RuntimeError):
    """The registry can't be read or saved right now (plain words)."""


class FacesStore:
    def __init__(self, docs: Docs, keyring: Keyring, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._ring = keyring
        self._col = f"{prefix}faces"

    def _path(self, uid: str) -> str:
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        return f"{self._col}/{uid}"

    @staticmethod
    def _aad(uid: str) -> str:
        return f"faces/{uid}/v1"

    def _seal(self, uid: str, state: State) -> dict[str, Any]:
        plain = json.dumps({"people": [p.to_json() for p in state.people]}, ensure_ascii=False)
        blob = self._ring.cipher("faces").encrypt(plain.encode(), aad=self._aad(uid))
        return {
            "rev": state.rev,
            "v": VERSION,
            "kid": self._ring.kid,
            "blob": blob,
            "updated_at": datetime.now(UTC).isoformat(),
        }

    def _open(self, uid: str, doc: dict[str, Any] | None) -> State:
        if doc is None:
            return State()
        rev, blob = doc.get("rev"), doc.get("blob")
        if not isinstance(rev, int) or isinstance(rev, bool) or not isinstance(blob, str):
            raise ValueError("envelope")
        raw = json.loads(self._ring.cipher("faces").decrypt(blob, aad=self._aad(uid)))
        people = tuple(Person.from_json(p) for p in raw["people"])
        if len(people) > MAX or len({p.id for p in people}) != len(people):
            raise ValueError("people")
        return State(rev, people)

    async def load(self, uid: str) -> State:
        path = self._path(uid)
        try:
            return self._open(uid, await self._d.get(path))
        except Exception as exc:  # noqa: BLE001 - storage or data trouble: read nothing
            log.warning("faces unreadable", extra={"reason": type(exc).__name__})
            raise FacesUnavailable(UNAVAILABLE) from None

    async def change(self, uid: str, fn: Callable[[State], State]) -> State:
        """Read, let `fn` return the new people, write with rev + 1 in one transaction. An error
        `fn` raises passes through unchanged; unreadable data is never overwritten."""
        path = self._path(uid)

        async def tx(t: DocTx) -> State:
            try:
                current = self._open(uid, await t.get(path))
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "faces corrupt; refusing to change", extra={"reason": type(exc).__name__}
                )
                raise FacesUnavailable(UNAVAILABLE) from None
            new = State(current.rev + 1, fn(current).people)
            t.set(path, self._seal(uid, new))
            return new

        try:
            return await self._d.transaction(tx)
        except (FacesUnavailable, ValueError, LookupError, PermissionError):
            raise
        except Exception as exc:  # noqa: BLE001 - nothing changed
            log.warning("faces change failed", extra={"reason": type(exc).__name__})
            raise FacesUnavailable(UNSAVED) from None

    async def wipe(self, uid: str) -> None:
        try:
            await self._d.write([Delete(self._path(uid))])
        except Exception as exc:  # noqa: BLE001
            log.warning("faces wipe failed", extra={"reason": type(exc).__name__})
            raise FacesUnavailable(UNSAVED) from None


__all__ = ["FacesStore", "FacesUnavailable"]

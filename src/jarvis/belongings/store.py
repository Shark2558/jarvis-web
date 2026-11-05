# src/jarvis/belongings/store.py
"""Where things are kept, on the `Docs` port, encrypted by JARVIS (R2 D2, D11; Layer 7).

    {prefix}belongings/{uid}                 {rev, v, kid, blob, updated_at}
        blob = AES-GCM(JSON {holders, things}) under the `belongings` key, AAD
        `belongings/index/{uid}/v1`
    {prefix}belongings_history/{uid}_{thing} {blob, updated_at}
        blob = AES-GCM(JSON [Move...]), AAD `belongings/history/{uid}/{thing}/v1`

Only `jarvis.keyring` derives keys and only `TokenCipher` encrypts. No name, place or note is ever
in a Firestore field in clear. A document that can't be read or decrypted is `ThingsUnavailable`
and is never overwritten; errors carry plain words and never the cause's text. Writes are
transactions: every read first, then the index and any history documents together.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from jarvis.belongings.models import MAX_HISTORY, Holder, Move, State, Thing
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, DocTx
from jarvis.undo.store import owner_ok

log = get_logger(__name__)

VERSION = 1
UNAVAILABLE = "JARVIS couldn't open your list of things just now. Try again in a minute."
UNSAVED = "JARVIS couldn't save that just now. Try again in a minute."


class ThingsUnavailable(RuntimeError):
    """The list can't be read or saved right now (plain words)."""


@dataclass(frozen=True)
class Change:
    """What a change wants written: the new state, moves to add to a thing's history, and things
    whose history goes (a purge)."""

    state: State
    moves: tuple[tuple[str, Move], ...] = ()
    drop_history: tuple[str, ...] = ()


def _now() -> str:
    return datetime.now(UTC).isoformat()


class BelongingsStore:
    def __init__(self, docs: Docs, keyring: Keyring, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._ring = keyring
        self._index = f"{prefix}belongings"
        self._hist = f"{prefix}belongings_history"

    # ---- paths and AAD ---------------------------------------------------------------------

    def _path(self, uid: str) -> str:
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        return f"{self._index}/{uid}"

    def _hpath(self, uid: str, thing_id: str) -> str:
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        return f"{self._hist}/{uid}_{thing_id}"

    @staticmethod
    def _aad_index(uid: str) -> str:
        return f"belongings/index/{uid}/v1"

    @staticmethod
    def _aad_hist(uid: str, thing_id: str) -> str:
        return f"belongings/history/{uid}/{thing_id}/v1"

    # ---- encode / decode -------------------------------------------------------------------

    def _seal_state(self, uid: str, state: State, rev: int) -> dict[str, Any]:
        plain = json.dumps(
            {
                "holders": [{"id": h.id, "label": h.label} for h in state.holders],
                "things": [t.to_json() for t in state.things],
            },
            ensure_ascii=False,
        ).encode()
        blob = self._ring.cipher("belongings").encrypt(plain, aad=self._aad_index(uid))
        return {"rev": rev, "v": VERSION, "kid": self._ring.kid, "blob": blob, "updated_at": _now()}

    def _open_state(self, uid: str, doc: dict[str, Any] | None) -> State:
        if doc is None:
            return State()
        rev, blob = doc.get("rev"), doc.get("blob")
        if not isinstance(rev, int) or isinstance(rev, bool) or not isinstance(blob, str):
            raise ValueError("envelope")
        raw = json.loads(self._ring.cipher("belongings").decrypt(blob, aad=self._aad_index(uid)))
        holders = tuple(Holder(str(h["id"]), str(h["label"])) for h in raw["holders"])
        return State(rev, holders, tuple(Thing.from_json(t) for t in raw["things"]))

    def _seal_moves(self, uid: str, thing_id: str, moves: list[Move]) -> dict[str, Any]:
        plain = json.dumps([m.to_json() for m in moves], ensure_ascii=False).encode()
        blob = self._ring.cipher("belongings").encrypt(plain, aad=self._aad_hist(uid, thing_id))
        return {"blob": blob, "updated_at": _now()}

    def _open_moves(self, uid: str, thing_id: str, doc: dict[str, Any] | None) -> list[Move]:
        if doc is None:
            return []
        blob = doc.get("blob")
        if not isinstance(blob, str):
            raise ValueError("envelope")
        raw = json.loads(
            self._ring.cipher("belongings").decrypt(blob, aad=self._aad_hist(uid, thing_id))
        )
        if not isinstance(raw, list):
            raise ValueError("moves")
        return [Move.from_json(m) for m in raw]

    # ---- reads -----------------------------------------------------------------------------

    async def load(self, uid: str) -> State:
        path = self._path(uid)
        try:
            return self._open_state(uid, await self._d.get(path))
        except Exception as exc:  # noqa: BLE001 - storage or data trouble: read nothing
            log.warning("belongings unreadable", extra={"reason": type(exc).__name__})
            raise ThingsUnavailable(UNAVAILABLE) from None

    async def history(self, uid: str, thing_id: str) -> list[Move]:
        path = self._hpath(uid, thing_id)
        try:
            return self._open_moves(uid, thing_id, await self._d.get(path))
        except Exception as exc:  # noqa: BLE001
            log.warning("belongings history unreadable", extra={"reason": type(exc).__name__})
            raise ThingsUnavailable(UNAVAILABLE) from None

    # ---- writes ----------------------------------------------------------------------------

    async def change(self, uid: str, fn: Callable[[State], Change]) -> State:
        """Read the list, let `fn` change it, write it (and the history it names) in one
        transaction. `fn` may raise its own errors (a full list): they pass through unchanged."""
        path = self._path(uid)

        async def tx(t: DocTx) -> State:
            try:
                current = self._open_state(uid, await t.get(path))
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "belongings corrupt; refusing to change", extra={"reason": type(exc).__name__}
                )
                raise ThingsUnavailable(UNAVAILABLE) from None
            change = fn(current)
            old: dict[str, list[Move]] = {}
            try:
                for tid in {tid for tid, _ in change.moves}:
                    old[tid] = self._open_moves(uid, tid, await t.get(self._hpath(uid, tid)))
            except Exception as exc:  # noqa: BLE001
                log.warning("belongings history corrupt", extra={"reason": type(exc).__name__})
                raise ThingsUnavailable(UNAVAILABLE) from None
            new_state = State(current.rev + 1, change.state.holders, change.state.things)
            t.set(path, self._seal_state(uid, new_state, new_state.rev))
            for tid, move in change.moves:
                old[tid] = [*old[tid], move][-MAX_HISTORY:]
            for tid, moves in old.items():
                t.set(self._hpath(uid, tid), self._seal_moves(uid, tid, moves))
            for tid in change.drop_history:
                t.delete(self._hpath(uid, tid))
            return new_state

        try:
            return await self._d.transaction(tx)
        except ThingsUnavailable:
            raise
        except (ValueError, LookupError, PermissionError):
            raise
        except Exception as exc:  # noqa: BLE001 - nothing changed
            log.warning("belongings change failed", extra={"reason": type(exc).__name__})
            raise ThingsUnavailable(UNSAVED) from None

    async def wipe(self, uid: str) -> int:
        """Delete the list and every history document; returns how many things went."""
        state = await self.load(uid)
        paths = [self._hpath(uid, t.id) for t in state.things]
        try:
            await self._d.write([Delete(p) for p in [*paths, self._path(uid)]])
        except Exception as exc:  # noqa: BLE001
            log.warning("belongings wipe failed", extra={"reason": type(exc).__name__})
            raise ThingsUnavailable(UNSAVED) from None
        return len(state.things)


__all__ = ["Change", "BelongingsStore", "ThingsUnavailable"]

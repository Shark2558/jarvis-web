# src/jarvis/backup/vault_probe.py
"""The restore drill's vault check (docs/plans/r14-hardening.md D4 "verifying" (3), review A2):
one owner's sealed vault in the throw-away copy opens with the LIVE key, through the vault store's
own read path (`VaultStore.load`, `VaultStore.chunk`, `VaultCrypto`), and matches live.

Both sides are read only (`ReadOnlyDocs`, handed to `VaultStore`, which reads with `get` alone; a
write would be an `AttributeError`). The plaintext is only hashed in memory, never kept, logged or
returned. Compared on the app's own fields, never Firestore's `update_time`:
- both vault documents carry the same `rev` and `updated_at`: every item is compared;
- otherwise (he changed his vault since the snapshot) each item whose own `updated_at` is the same
  on both sides;
- then one file of a compared item is opened whole on the copy's side and must give the SHA-256
  and size the vault recorded at upload (the vault service's own check), equal on both sides.
Outcomes: "opened" (with how many items and files were compared), "no_vault" (none on either
side, or one made after the snapshot: skipped, never a pass), or "failed" with a reason code:
`key` (the copy does not open with today's key), `vault_missing`, `vault_mismatch`, `vault_file`,
`live_unreadable`, `nothing_compared` (live has items and none could be compared). Never imports
the live store's SDK adapter nor the drill's log (D4 lock 3).
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from jarvis.backup.ports import ReadOnlyDocs
from jarvis.integrations.vault import VaultError
from jarvis.keyring import Keyring
from jarvis.vault.crypto import VaultCrypto
from jarvis.vault.models import FileRef, Item, VaultIndex, VaultUnavailable
from jarvis.vault.store import VaultStore

if TYPE_CHECKING:
    from jarvis.storage.docs import Doc, Docs

DocKey = Callable[["Doc"], object]
ItemKey = Callable[["Doc", Item], object]


def doc_version(doc: Doc) -> object:
    """The vault document's own version: (`rev`, `updated_at`)."""
    rev, at = doc.get("rev"), doc.get("updated_at")
    return None if rev is None or at is None else (rev, at)


def item_version(doc: Doc, item: Item) -> object:
    return item.updated_at


@dataclass(frozen=True)
class VaultCheck:
    outcome: Literal["opened", "no_vault", "failed"]
    reason: str | None = None
    items: int = 0
    files: int = 0


def _failed(reason: str) -> VaultCheck:
    return VaultCheck("failed", reason)


def _hash(item: Item) -> str:
    return hashlib.sha256(item.model_dump_json().encode()).hexdigest()


def _made_after(doc: Doc, snapshot: dt.datetime) -> bool:
    try:
        at = dt.datetime.fromisoformat(str(doc.get("updated_at")))
    except ValueError:
        return False
    return doc.get("rev") == 1 and (at if at.tzinfo else at.replace(tzinfo=dt.UTC)) > snapshot


def _pairs(
    raw: tuple[Doc, Doc], index: tuple[VaultIndex, VaultIndex], doc_key: DocKey, item_key: ItemKey
) -> list[tuple[Item, Item]]:
    (d_raw, l_raw), (d_index, l_index) = raw, index
    live = {i.id: i for i in l_index.items}
    same = doc_key(d_raw) is not None and doc_key(d_raw) == doc_key(l_raw)
    out: list[tuple[Item, Item]] = []
    for item in d_index.items:
        other = live.get(item.id)
        if other is None:
            continue
        stamp = item_key(d_raw, item)
        if same or (stamp is not None and stamp == item_key(l_raw, other)):
            out.append((item, other))
    return out


async def _file_opens(store: VaultStore, crypto: VaultCrypto, uid: str, item: Item) -> bool:
    ref: FileRef = item.files[0]
    try:
        dek = crypto.unwrap(uid, item.id, ref.fid, ref.dek)
        digest, total = hashlib.sha256(), 0
        for n in range(ref.chunks):
            blob = await store.chunk(uid, ref.fid, n)
            plain = crypto.open_chunk(dek, uid, item.id, ref.fid, n, ref.chunks, blob)
            digest.update(plain)  # hashed in memory only
            total += len(plain)
    except (VaultError, VaultUnavailable, ValueError):
        return False
    return digest.hexdigest() == ref.sha256 and total == ref.size


async def _opened(
    uid: str, drill: ReadOnlyDocs, live: ReadOnlyDocs, ring: Keyring, prefix: str
) -> tuple[VaultStore, VaultCrypto, VaultIndex, VaultIndex] | VaultCheck:
    crypto = VaultCrypto(ring)
    copy_store = VaultStore(cast("Docs", drill), crypto, prefix=prefix)
    live_store = VaultStore(cast("Docs", live), crypto, prefix=prefix)
    try:
        _, copy_index = await copy_store.load(uid)
    except VaultUnavailable:
        return _failed("key")
    try:
        _, live_index = await live_store.load(uid)
    except VaultUnavailable:
        return _failed("live_unreadable")
    return copy_store, crypto, copy_index, live_index


async def probe(
    uid: str,
    *,
    drill: ReadOnlyDocs,
    live: ReadOnlyDocs,
    ring: Keyring,
    prefix: str,
    snapshot: dt.datetime,
    doc_key: DocKey = doc_version,
    item_key: ItemKey = item_version,
) -> VaultCheck:
    path = f"{prefix}vault/{uid}"
    d_raw, l_raw = await drill.get(path), await live.get(path)
    if d_raw is None:
        if l_raw is None or _made_after(dict(l_raw), snapshot):
            return VaultCheck("no_vault")
        return _failed("vault_missing")
    opened = await _opened(uid, drill, live, ring, prefix)
    if isinstance(opened, VaultCheck):
        return opened
    store, crypto, d_index, l_index = opened
    if l_raw is None or not l_index.items:
        return VaultCheck("no_vault")  # nothing of his to compare with (the copy did open)
    pairs = _pairs((dict(d_raw), dict(l_raw)), (d_index, l_index), doc_key, item_key)
    if not pairs:
        return _failed("nothing_compared")
    if any(_hash(a) != _hash(b) for a, b in pairs):
        return _failed("vault_mismatch")
    with_file = next(((a, b) for a, b in pairs if a.files and b.files), None)
    if with_file is None:
        return VaultCheck("opened", items=len(pairs))
    item, other = with_file
    same_file = item.files[0].sha256 == other.files[0].sha256
    if not same_file or not await _file_opens(store, crypto, uid, item):
        return _failed("vault_file")
    return VaultCheck("opened", items=len(pairs), files=1)


__all__ = ["DocKey", "ItemKey", "VaultCheck", "doc_version", "item_version", "probe"]

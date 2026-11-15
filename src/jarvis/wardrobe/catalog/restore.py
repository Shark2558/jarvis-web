# src/jarvis/wardrobe/catalog/restore.py
"""Restoring the wardrobe's backup file, confirm before commit (docs/plans/r13-wardrobe.md D17,
OPS-06; plan review H3).

1. `check(uid, file)` opens every line (the seal, the line order, the schema, his id, today's key)
   and answers the counts (to add, already there, where his current record wins, in Recently
   deleted, purged since, events new to the logs) with a token: a MAC of his id, the file's
   SHA-256 and an expiry an hour on. It WRITES NOTHING (the token is stateless, so nothing about
   the file is kept either).
2. `apply(uid, file, token, include_purged)` checks the token against the same file and applies
   it in chunks of at most 50 pieces a transaction (each far under Firestore's 10 MiB): a piece in
   both keeps his current record and gains the file's events (unioned by event id and re-folded:
   the newer verified event wins, so a backup never undoes a later change); a piece missing now
   comes back only into an empty wardrobe or when he ticks it (purged since). Events are kept as
   they were stored (`as_stored`), so a restore cut after any chunk runs again and duplicates
   nothing. Photos and fingerprints come back only with the pieces that come back.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from jarvis.keyring import KEY_ID
from jarvis.storage.docs import DocTx, Op, Set
from jarvis.wardrobe.catalog.backup import MAGIC, VERSION, aad_line
from jarvis.wardrobe.catalog.photos import MAX_SHARDS, PhotoVault
from jarvis.wardrobe.catalog.store import CatalogStore
from jarvis.wardrobe.http import RestoreCheck, RestoreCounts, RestoreDone
from jarvis.wardrobe.model import PHOTO_ID, Event, Piece, WardrobeView
from jarvis.wardrobe.ports import Commit, Refused

CHUNK = 50
TOKEN_LIFE = timedelta(hours=1)
UNREADABLE = (
    "That file can't be opened: it isn't a wardrobe backup of yours from this JARVIS, or it was "
    "made before a key change."
)
EXPIRED = "That check has expired or was for another file: check the file again."


@dataclass(frozen=True)
class Parsed:
    view: WardrobeView
    logs: dict[str, list[Event]]
    photos: dict[str, dict[str, Any]] = field(default_factory=dict)
    prints: dict[int, dict[str, Any]] = field(default_factory=dict)
    has_photos: bool = False
    digest: str = ""


def _head(line: bytes) -> dict[str, Any]:
    import json  # noqa: PLC0415 - only the clear head is plain JSON

    if not line.startswith(MAGIC):
        raise ValueError("magic")
    head = json.loads(line[len(MAGIC) :])
    if head.get("v") != VERSION or head.get("kid") != KEY_ID:
        raise ValueError("version or key")
    return dict(head)


def parse(store: CatalogStore, uid: str, body: bytes) -> Parsed:
    try:
        lines = body.rstrip(b"\n").split(b"\n")
        head = _head(lines[0])
        rows = [store.sealer.open("wardrobe", aad_line(uid, n), ln.decode("ascii"))
                for n, ln in enumerate(lines[1:], start=1)]  # fmt: skip
        if not rows or rows[-1].get("t") != "end" or rows[-1]["d"]["lines"] != len(rows) - 1:
            raise ValueError("cut")
        view = WardrobeView.model_validate(rows[0]["d"])
        if rows[0]["t"] != "index" or view.uid != uid:
            raise ValueError("index")
        out = Parsed(view, {}, has_photos=bool(head.get("photos")))
        for row in rows[1:-1]:
            _take(out, row["t"], row["d"])
    except (ValueError, KeyError, TypeError, IndexError, UnicodeDecodeError):
        raise Refused(UNREADABLE) from None
    except Exception:  # noqa: BLE001 - a seal that doesn't open: the same plain words
        raise Refused(UNREADABLE) from None
    return Parsed(out.view, out.logs, out.photos, out.prints, out.has_photos,
                  hashlib.sha256(body).hexdigest())  # fmt: skip


def _take(out: Parsed, kind: str, d: Any) -> None:
    """One line of the file; a photo or a shard must be his, a shard number in range."""
    uid = out.view.uid
    if kind == "log":
        out.logs[str(d["p"])] = [Event.model_validate(e) for e in d["e"]]
    elif kind == "photo" and PHOTO_ID.match(str(d["id"])) and d["doc"].get("owner") == uid:
        out.photos[str(d["id"])] = dict(d["doc"])
    elif kind == "fp" and 0 <= int(d["n"]) < MAX_SHARDS and d["doc"].get("owner") == uid:
        out.prints[int(d["n"])] = dict(d["doc"])
    else:
        raise ValueError("line")


class Restore:
    def __init__(self, store: CatalogStore, vault: PhotoVault) -> None:
        self.store, self.vault = store, vault

    # ---- the token (stateless: the check writes nothing) --------------------------------------
    def _token(self, uid: str, digest: str, expires: int, empty: bool) -> str:
        """`empty`: the wardrobe was empty at the check, so every piece is added, also when a
        restore cut halfway runs again (decided once, carried under the MAC)."""
        mac = self.store.sealer.mac(f"restore/{uid}/{digest}/{expires}/{int(empty)}")
        return f"{expires:x}-{int(empty)}-{mac[:40]}"

    def _token_ok(self, uid: str, digest: str, token: str) -> bool | None:
        """The check's `empty`, or None when the token is not for this file or has expired."""
        head, _, rest = token.partition("-")
        try:
            expires, empty = int(head, 16), rest[:1] == "1"
        except ValueError:
            return None
        fresh = self.store.now().timestamp() < expires
        ok = hmac.compare_digest(self._token(uid, digest, expires, empty), token)
        return empty if fresh and ok else None

    # ---- check ---------------------------------------------------------------------------------
    async def check(self, uid: str, body: bytes) -> RestoreCheck:
        parsed = parse(self.store, uid, body)
        current = await self.store.view(uid)
        counts, purged = await self._counts(uid, parsed, current)
        expires = int((self.store.now() + TOKEN_LIFE).timestamp())
        words = (
            f"{counts.added} to add, {counts.already_there} already there, "
            f"{counts.events} new events; nothing is changed until you restore."
        )
        token = self._token(uid, parsed.digest, expires, not current.pieces)
        return RestoreCheck(token=token, counts=counts,
                            purged=purged, photos=parsed.has_photos, message=words)  # fmt: skip

    async def _counts(
        self, uid: str, parsed: Parsed, current: WardrobeView
    ) -> tuple[RestoreCounts, tuple[str, ...]]:
        both = [pid for pid in parsed.view.pieces if pid in current.pieces]
        missing = [pid for pid in parsed.view.pieces if pid not in current.pieces]
        empty = not current.pieces
        new_events = 0
        for pid, events in parsed.logs.items():
            known = {e.id for e in await self.store.events(uid, pid)} if pid in both else set()
            new_events += sum(e.id not in known for e in events)
        differ = sum(_attrs(current.pieces[p]) != _attrs(parsed.view.pieces[p]) for p in both)
        in_bin = sum(current.pieces[p].state == "archived" for p in both)
        counts = RestoreCounts(
            added=len(missing) if empty else 0, already_there=len(both), superseded=differ,
            back_from_bin=in_bin, purged_since=0 if empty else len(missing), events=new_events,
        )  # fmt: skip
        return counts, () if empty else tuple(missing)

    # ---- apply ---------------------------------------------------------------------------------
    async def apply(
        self, uid: str, body: bytes, token: str, include_purged: Sequence[str] = ()
    ) -> RestoreDone:
        parsed = parse(self.store, uid, body)
        empty = self._token_ok(uid, parsed.digest, token)
        if empty is None:
            raise Refused(EXPIRED)
        current, ticked = await self.store.view(uid), set(include_purged)
        ids = [p for p in parsed.view.pieces if p in current.pieces or empty or p in ticked]
        chunks = [ids[i : i + CHUNK] for i in range(0, len(ids), CHUNK)]
        added = there = events = 0
        for n, chunk in enumerate(chunks):
            got = await self._chunk(uid, parsed, chunk, first=n == 0)
            added, there = added + got[0], there + got[1]
            events += got[2]
        counts = RestoreCounts(added=added, already_there=there, superseded=0, back_from_bin=0,
                               purged_since=0, events=events)  # fmt: skip
        words = f"Restored: {added} added, {there} already there, {events} events."
        return RestoreDone(counts=counts, chunks=len(chunks), message=words)

    async def _chunk(
        self, uid: str, parsed: Parsed, chunk: list[str], *, first: bool
    ) -> tuple[int, int, int]:
        seen: list[int] = [0, 0]

        async def fn(view: WardrobeView, tx: DocTx) -> Commit:
            new = [pid for pid in chunk if pid not in view.pieces]
            seen[:] = [len(new), len(chunk) - len(new)]
            recs = tuple(_record(parsed, parsed.view.pieces[pid]) for pid in new)
            events = tuple(e for pid in chunk for e in parsed.logs.get(pid, []))
            extra = self._photo_ops(uid, parsed, recs, view, first)
            return Commit(events=events, records=recs, extra=extra)

        def links(fresh: WardrobeView) -> WardrobeView:
            return _links(fresh, parsed.view)

        got = await self.store.transact(uid, fn, index=links, as_stored=True)
        return seen[0], seen[1], sum(m != "known" for m in got.marks.values())

    def _photo_ops(
        self, uid: str, parsed: Parsed, recs: Sequence[Piece], view: WardrobeView, first: bool
    ) -> tuple[Op, ...]:
        if not parsed.has_photos:
            return ()
        ops: list[Op] = [Set(self.vault.path(uid, ph), parsed.photos[ph])
                         for p in recs for ph in p.photos if ph in parsed.photos]  # fmt: skip
        no_prints = not any(p.fp_model for p in view.pieces.values())
        if first and no_prints:
            ops += [Set(self.vault.prints.path(uid, n), doc) for n, doc in parsed.prints.items()]
        return tuple(ops)


def _attrs(p: Piece) -> dict[str, Any]:
    drop = {"state", "back_to", "place", "place_at", "hold", "expected_back", "wear", "wears"}
    drop |= {"last_worn", "events", "created_at", "updated_at"}
    return {k: v for k, v in p.model_dump().items() if k not in drop}


def _record(parsed: Parsed, p: Piece) -> Piece:
    if parsed.has_photos and not p.private:
        kept = tuple(ph for ph in p.photos if ph in parsed.photos)
        return p.model_copy(update={"photos": kept})
    return p.model_copy(update={"photos": (), "fp_model": None})


def _links(fresh: WardrobeView, old: WardrobeView) -> WardrobeView:
    have = set(fresh.pieces)
    pairs = {**{k: v for k, v in old.pairs.items() if set(v.pieces) <= have}, **fresh.pairs}
    sets = {**{k: v for k, v in old.sets.items() if {x.piece for x in v.parts} <= have},
            **fresh.sets}  # fmt: skip
    places = {**old.places, **fresh.places}
    labels = {**{k: v for k, v in old.labels.items() if v.piece in have or v.piece is None},
              **fresh.labels}  # fmt: skip
    return fresh.model_copy(update={"pairs": pairs, "sets": sets, "places": places,
                                    "labels": labels})  # fmt: skip


__all__ = ["CHUNK", "EXPIRED", "UNREADABLE", "Parsed", "Restore", "parse"]

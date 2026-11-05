# src/jarvis/home/store.py
"""Where the home link is kept, on the `Docs` port (R3 D4, D5, D9; Layer 7).

    {prefix}home/{uid}           {home_id, v, kid, blob, linked_at, state, last_seen_at, parts,
                                  bridge_version, dropped_disarmed, outage_alerted, rev}
        blob = AES-GCM(JSON {bridge_url, seed}) under the `home` key, AAD `home/config/{uid}/v1`
    {prefix}home_devices/{uid}   {rev, v, kid, blob}  blob = AES-GCM(JSON [entry...]), AAD
                                  `home/devices/{uid}/v1`  (entity ids and the owner's labels)
    {prefix}home_link/{uid}      {code_hash, expires_at, tries}      one pending code
    {prefix}home_claims/{uid}_{h32}  {at}                            create-only, swept after 48 h

Only `jarvis.keyring` derives keys and only `TokenCipher` encrypts. The bridge URL and the seed are
never in a clear field. A document that can't be read or decrypted is `HomeStoreUnavailable` and
is never overwritten by a write that did not mean to (fail closed). `last_seen` is kept in process
and written when empty or 5 minutes old, so an instance restart can't fake an outage (D9).
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
from typing import Any

from jarvis.home.models import (
    DevicesRecord,
    ExposedEntry,
    HomeRecord,
    HomeState,
    HomeStatus,
    Seen,
)
from jarvis.home.ports import is_home_id
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Create, Delete, DocExists, Docs, DocTx, Query, Set
from jarvis.undo.store import owner_ok

log = get_logger(__name__)

VERSION = 1
SEEN_WRITE_EVERY_S = 300.0
CLAIM_KEEP_S = 48 * 3600.0
MAX_CODE_TRIES = 5  # wrong tries per client in the window
MAX_CODE_TRIES_ALL = 50  # and across all clients
CODE_TRY_WINDOW_S = 300.0
WRONG_CLIENTS_MAX = 1000
UNKNOWN_IDS_MAX = 512  # forged home ids remembered (bounded, oldest out)
UNKNOWN_ID_TTL_S = 60.0
UNAVAILABLE = "JARVIS couldn't open your home link just now. Try again in a minute."
_STATES = ("linked", "online", "offline", "degraded")


class HomeStoreUnavailable(RuntimeError):
    """The home link can't be read or saved right now (plain words)."""


def _claim_hash(event_id: str) -> str:
    return hashlib.sha256(event_id.encode()).hexdigest()[:32]


class HomeStore:
    def __init__(
        self,
        docs: Docs,
        keyring: Keyring,
        *,
        prefix: str = "jarvis_",
        clock: Callable[[], float],
    ) -> None:
        self._d = docs
        self._ring = keyring
        self._home = f"{prefix}home"
        self._devices = f"{prefix}home_devices"
        self._codes = f"{prefix}home_link"
        self._claims = f"{prefix}home_claims"
        self._clock = clock
        self._seen: dict[str, tuple[float, str]] = {}  # uid -> (last seen, state), in process
        self._written: dict[str, float] = {}  # uid -> when last_seen_at was last written
        self._by_home: dict[str, str] = {}  # home id -> uid (verified on every use)
        self._wrong: dict[str, tuple[int, float]] = {}  # client -> (wrong tries, window start)
        self._wrong_all: tuple[int, float] = (0, 0.0)
        self._unknown: dict[str, float] = {}  # forged/unknown home id -> until (bounded, review H1)

    def now(self) -> float:
        return self._clock()

    # ---- paths ---------------------------------------------------------------------------------

    def _path(self, uid: str) -> str:
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        return f"{self._home}/{uid}"

    # ---- the record ----------------------------------------------------------------------------

    def _seal(self, uid: str, bridge_url: str, seed: bytes) -> str:
        plain = json.dumps(
            {"bridge_url": bridge_url, "seed": base64.b64encode(seed).decode("ascii")}
        ).encode()
        return self._ring.cipher("home").encrypt(plain, aad=f"home/config/{uid}/v1")

    def _open(self, uid: str, doc: dict[str, Any]) -> HomeRecord:
        home_id, blob = doc.get("home_id"), doc.get("blob")
        if not is_home_id(home_id) or not isinstance(blob, str):
            raise ValueError("envelope")
        raw = json.loads(self._ring.cipher("home").decrypt(blob, aad=f"home/config/{uid}/v1"))
        seed = base64.b64decode(raw["seed"], validate=True)
        if not isinstance(raw["bridge_url"], str) or len(seed) != 32:
            raise ValueError("record")
        return HomeRecord(home_id=str(home_id), bridge_url=raw["bridge_url"], seed=seed)

    async def _get(self, path: str) -> dict[str, Any] | None:
        try:
            return await self._d.get(path)
        except Exception as exc:  # noqa: BLE001 - plain words, never the cause
            log.error("home read failed", extra={"error": type(exc).__name__})
            raise HomeStoreUnavailable(UNAVAILABLE) from None

    async def load(self, uid: str) -> HomeRecord | None:
        """The owner's linked home, None when not linked. Unreadable -> HomeStoreUnavailable."""
        doc = await self._get(self._path(uid))
        if doc is None:
            return None
        try:
            return self._open(uid, doc)
        except Exception as exc:  # noqa: BLE001
            log.error("home record unreadable", extra={"error": type(exc).__name__})
            raise HomeStoreUnavailable(UNAVAILABLE) from None

    async def status(self, uid: str) -> HomeStatus | None:
        doc = await self._get(self._path(uid))
        if doc is None:
            return None
        try:
            state: HomeState = doc["state"] if doc.get("state") in _STATES else "linked"
            parts = doc.get("parts")
            return HomeStatus(
                home_id=str(doc["home_id"]),
                state=state,
                linked_at=float(doc.get("linked_at", 0.0)),
                last_seen_at=self._last_seen(uid, doc.get("last_seen_at")),
                parts=parts if isinstance(parts, dict) else {},
                bridge_version=doc.get("bridge_version")
                if isinstance(doc.get("bridge_version"), str)
                else None,
                dropped_disarmed=int(doc.get("dropped_disarmed", 0)),
                outage_alerted=bool(doc.get("outage_alerted", False)),
            )
        except (KeyError, TypeError, ValueError):
            raise HomeStoreUnavailable(UNAVAILABLE) from None

    def _last_seen(self, uid: str, stored: object) -> float | None:
        mine = self._seen.get(uid)
        theirs = float(stored) if isinstance(stored, int | float) else None
        if mine is None:
            return theirs
        return mine[0] if theirs is None else max(mine[0], theirs)

    async def find(self, home_id: str) -> tuple[str, HomeRecord] | None:
        """(uid, record) for a home id, None if unknown. The webhook's lookup, before any parse."""
        if not is_home_id(home_id):
            return None
        now = self._clock()
        if self._unknown.get(home_id, 0.0) > now:
            return None  # asked about a moment ago and not ours: no read for a stranger's guess
        uid = self._by_home.get(home_id)
        if uid is not None:
            rec = await self.load(uid)
            if rec is not None and rec.home_id == home_id:
                return uid, rec
            self._by_home.pop(home_id, None)
        rows = await self._query(Query(self._home, where=("home_id", home_id), limit=1))
        if not rows:
            self._remember_unknown(home_id, now)
            return None
        uid = rows[0][0]
        try:
            rec = self._open(uid, rows[0][1])
        except Exception:  # noqa: BLE001
            raise HomeStoreUnavailable(UNAVAILABLE) from None
        self._by_home[home_id] = uid
        return uid, rec

    def _remember_unknown(self, home_id: str, now: float) -> None:
        if len(self._unknown) >= UNKNOWN_IDS_MAX:
            self._unknown.pop(next(iter(self._unknown)))  # the oldest guess goes first
        self._unknown[home_id] = now + UNKNOWN_ID_TTL_S

    async def _query(self, q: Query) -> list[tuple[str, dict[str, Any]]]:
        try:
            return await self._d.query(q)
        except Exception as exc:  # noqa: BLE001
            log.error("home query failed", extra={"error": type(exc).__name__})
            raise HomeStoreUnavailable(UNAVAILABLE) from None

    async def linked_uids(self) -> list[str]:
        rows = await self._query(Query(self._home, limit=500))
        return [uid for uid, _ in rows]

    async def link(self, uid: str, home_id: str, bridge_url: str, seed: bytes) -> None:
        """Save a (new or re-made) link. A new seed replaces the old one at once."""
        path = self._path(uid)
        now = self._clock()
        old = await self._get(path)
        keep = int(old.get("dropped_disarmed", 0)) if isinstance(old, dict) else 0
        doc = {
            "home_id": home_id,
            "v": VERSION,
            "kid": self._ring.kid,
            "blob": self._seal(uid, bridge_url, seed),
            "linked_at": now,
            "state": "linked",
            "last_seen_at": None,
            "parts": {},
            "bridge_version": None,
            "dropped_disarmed": keep,
            "outage_alerted": False,
            "rev": int(old.get("rev", 0)) + 1 if isinstance(old, dict) else 1,
        }
        try:
            await self._d.write([Set(path, doc)])
        except Exception as exc:  # noqa: BLE001
            log.error("home save failed", extra={"error": type(exc).__name__})
            raise HomeStoreUnavailable(UNAVAILABLE) from None
        self._seen.pop(uid, None)
        self._written.pop(uid, None)
        self._by_home = {h: u for h, u in self._by_home.items() if u != uid}
        self._by_home[home_id] = uid
        self._unknown.pop(home_id, None)

    async def unlink(self, uid: str) -> bool:
        """Delete the link, the exposed devices and any pending code. True if there was one."""
        path = self._path(uid)
        had = await self._get(path) is not None
        try:
            await self._d.write(
                [
                    Delete(path),
                    Delete(f"{self._devices}/{uid}"),
                    Delete(f"{self._codes}/{uid}"),
                ]
            )
        except Exception as exc:  # noqa: BLE001
            log.error("home unlink failed", extra={"error": type(exc).__name__})
            raise HomeStoreUnavailable(UNAVAILABLE) from None
        self._seen.pop(uid, None)
        self._written.pop(uid, None)
        self._by_home = {h: u for h, u in self._by_home.items() if u != uid}
        return had

    # ---- heartbeat bookkeeping -----------------------------------------------------------------

    async def _update(self, uid: str, change: Callable[[dict[str, Any]], None]) -> bool:
        path = self._path(uid)

        async def tx_fn(tx: DocTx) -> bool:
            doc = await tx.get(path)
            if doc is None:
                return False
            change(doc)
            tx.set(path, doc)
            return True

        try:
            return await self._d.transaction(tx_fn)
        except Exception as exc:  # noqa: BLE001
            log.error("home update failed", extra={"error": type(exc).__name__})
            raise HomeStoreUnavailable(UNAVAILABLE) from None

    async def seen(
        self,
        uid: str,
        *,
        parts: dict[str, Any],
        bridge_version: str,
        degraded: bool = False,
    ) -> Seen | None:
        """A heartbeat arrived: remember it in process and write it when the state changed or the
        last write is 5 minutes old. None if the home is gone."""
        now = self._clock()
        status = await self.status(uid)
        if status is None:
            return None
        state: HomeState = "degraded" if degraded else "online"
        self._seen[uid] = (now, state)
        stale = now - self._written.get(uid, 0.0) >= SEEN_WRITE_EVERY_S
        changed = status.state != state or status.parts != parts or status.last_seen_at is None
        if stale or changed or status.bridge_version != bridge_version:

            def change(doc: dict[str, Any]) -> None:
                doc.update(
                    state=state,
                    last_seen_at=now,
                    parts=parts,
                    bridge_version=bridge_version,
                    outage_alerted=False,
                )

            if not await self._update(uid, change):
                return None
            self._written[uid] = now
        return Seen(previous=status.state, outage_alerted=status.outage_alerted)

    async def mark_offline(self, uid: str, *, alerted: bool) -> None:
        def change(doc: dict[str, Any]) -> None:
            doc.update(state="offline", outage_alerted=alerted)

        await self._update(uid, change)
        self._seen.pop(uid, None)

    async def add_dropped(self, uid: str) -> None:
        def change(doc: dict[str, Any]) -> None:
            doc["dropped_disarmed"] = int(doc.get("dropped_disarmed", 0)) + 1

        await self._update(uid, change)

    # ---- exposed devices -----------------------------------------------------------------------

    async def load_devices(self, uid: str) -> DevicesRecord:
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        doc = await self._get(f"{self._devices}/{uid}")
        if doc is None:
            return DevicesRecord()
        try:
            rev, blob = doc["rev"], doc["blob"]
            if not isinstance(rev, int) or isinstance(rev, bool) or not isinstance(blob, str):
                raise ValueError("envelope")
            raw = json.loads(self._ring.cipher("home").decrypt(blob, aad=f"home/devices/{uid}/v1"))
            entries = tuple(
                ExposedEntry(
                    entity_id=str(e["entity_id"]),
                    tier=str(e["tier"]),
                    device_class=e.get("device_class"),
                    label=e.get("label"),
                    name=e.get("name"),
                )
                for e in raw
            )
            return DevicesRecord(rev=rev, entries=entries)
        except Exception as exc:  # noqa: BLE001
            log.error("home devices unreadable", extra={"error": type(exc).__name__})
            raise HomeStoreUnavailable(UNAVAILABLE) from None

    async def save_devices(self, uid: str, entries: tuple[ExposedEntry, ...]) -> DevicesRecord:
        old = await self.load_devices(uid)  # unreadable -> refuses, never overwrites
        plain = json.dumps(
            [
                {
                    "entity_id": e.entity_id,
                    "tier": e.tier,
                    "device_class": e.device_class,
                    "label": e.label,
                    "name": e.name,
                }
                for e in entries
            ],
            ensure_ascii=False,
        ).encode()
        blob = self._ring.cipher("home").encrypt(plain, aad=f"home/devices/{uid}/v1")
        doc = {"rev": old.rev + 1, "v": VERSION, "kid": self._ring.kid, "blob": blob}
        try:
            await self._d.write([Set(f"{self._devices}/{uid}", doc)])
        except Exception as exc:  # noqa: BLE001
            log.error("home devices save failed", extra={"error": type(exc).__name__})
            raise HomeStoreUnavailable(UNAVAILABLE) from None
        return DevicesRecord(rev=old.rev + 1, entries=entries)

    # ---- event claims (D5) ---------------------------------------------------------------------

    async def claim(self, uid: str, event_id: str) -> bool:
        """Create-only. False = already claimed (a replay or a retry: a no-op)."""
        path = f"{self._claims}/{uid}_{_claim_hash(event_id)}"
        try:
            await self._d.write([Create(path, {"at": self._clock()})])
        except DocExists:
            return False
        except Exception as exc:  # noqa: BLE001
            log.error("home claim failed", extra={"error": type(exc).__name__})
            raise HomeStoreUnavailable(UNAVAILABLE) from None
        return True

    async def release(self, uid: str, event_id: str) -> None:
        """Give a claim back when the handler failed, so the bridge's retry is not a no-op."""
        try:
            await self._d.write([Delete(f"{self._claims}/{uid}_{_claim_hash(event_id)}")])
        except Exception as exc:  # noqa: BLE001
            log.error("home claim release failed", extra={"error": type(exc).__name__})

    async def sweep_claims(self) -> int:
        cutoff = self._clock() - CLAIM_KEEP_S
        rows = await self._query(Query(self._claims, order_by="at", limit=400))
        old = [i for i, d in rows if isinstance(d.get("at"), int | float) and d["at"] < cutoff]
        if old:
            await self._d.write([Delete(f"{self._claims}/{i}") for i in old])
        return len(old)

    # ---- link codes (D4) -----------------------------------------------------------------------

    async def put_code(self, uid: str, code_hash: str, expires_at: float) -> None:
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        doc = {"code_hash": code_hash, "expires_at": expires_at, "tries": 0}
        try:
            await self._d.write([Set(f"{self._codes}/{uid}", doc)])
        except Exception as exc:  # noqa: BLE001
            log.error("home code save failed", extra={"error": type(exc).__name__})
            raise HomeStoreUnavailable(UNAVAILABLE) from None

    def _guesses_exhausted(self, client: str, now: float) -> bool:
        """Wrong tries are counted per client (and under one small global ceiling), never against
        the owner's code: a stranger's guesses lock the stranger out, not the owner (review M1)."""
        mine = self._wrong.get(client)
        if mine is not None and now - mine[1] >= CODE_TRY_WINDOW_S:
            del self._wrong[client]
            mine = None
        if self._wrong_all[1] and now - self._wrong_all[1] >= CODE_TRY_WINDOW_S:
            self._wrong_all = (0, 0.0)
        return (mine is not None and mine[0] >= MAX_CODE_TRIES) or (
            self._wrong_all[0] >= MAX_CODE_TRIES_ALL
        )

    def _count_wrong(self, client: str, now: float) -> None:
        count, since = self._wrong.get(client, (0, now))
        if client not in self._wrong and len(self._wrong) >= WRONG_CLIENTS_MAX:
            self._wrong.pop(next(iter(self._wrong)))
        self._wrong[client] = (count + 1, since)
        total, started = self._wrong_all
        self._wrong_all = (total + 1, started or now)

    async def take_code(self, code_hash: str, client: str = "") -> str | None:
        """The uid whose live pending code this is, else None. A wrong code is counted against the
        client that sent it: five lock that client out for CODE_TRY_WINDOW_S (even with the right
        code), and a global ceiling stops a spread-out run. It never touches the codes themselves.
        Not spent here."""
        now = self._clock()
        if self._guesses_exhausted(client, now):
            return None
        rows = await self._query(Query(self._codes, limit=20))
        for uid, doc in rows:
            if float(doc.get("expires_at", 0)) > now and doc.get("code_hash") == code_hash:
                return uid
        self._count_wrong(client, now)
        return None

    async def spend_code(self, uid: str) -> None:
        await self._d.write([Delete(f"{self._codes}/{uid}")])

    async def sweep_codes(self) -> int:
        now = self._clock()
        rows = await self._query(Query(self._codes, limit=100))
        old = [u for u, d in rows if float(d.get("expires_at", 0)) <= now]
        if old:
            await self._d.write([Delete(f"{self._codes}/{u}") for u in old])
        return len(old)


__all__ = ["HomeStore", "HomeStoreUnavailable"]

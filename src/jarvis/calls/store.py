# src/jarvis/calls/store.py
"""The call store (R18; Layer 7 via the `Docs` port: `FirestoreDocs` in production, `MemoryDocs` in
tests), following the repository's store pattern (`jarvis.phone.store`, `jarvis.voice.settings`).

    {prefix}calls/{uid}/cards/{card_id}      a CallCard (number sealed)
    {prefix}calls/{uid}/records/{call_id}    a CallRecord (number sealed) + started_ts, delete_ts
    {prefix}calls/{uid}/days/{YYYY-MM-DD}    the limits' counters (IST day): calls, new_numbers,
                                             per_number {ref: n}, no_answer {ref: n}
    {prefix}calls/{uid}/months/{YYYY-MM}     {inr}: the month's calls spend (the ₹200 cap)
    {prefix}calls/{uid}/numbers/{ref}        a number called before: {first_at, last_at, calls}
    {prefix}call_settings/{uid}              the owner's settings (`jarvis.calls.settings`)
    {prefix}call_lang_check/{lang}_{option}  the language check's latest result per option

A number is never stored in clear: `number_sealed` (AES-GCM under the `calls` key, bound to the
owner) and `number_ref` (an HMAC under the `calls` MAC domain, 128 bits) for counters and "called
before". A document that does not read back (bad shape, a seal that does not open) raises
`CallStoreUnreadable`: never "no card". Counting a call and its limits check run in one transaction.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import re
import secrets
from datetime import UTC, date, datetime
from typing import Any

from pydantic import ValidationError

from jarvis.calls.models import CallCard, CallRecord, CallSettings, LanguageResult
from jarvis.calls.ports import CallStoreUnreadable, DayCounts, LimitCheck
from jarvis.calls.settings import CallSettingsStore, owner_key
from jarvis.integrations.vault import VaultError
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, DocTx, MemoryDocs, Query, Set

log = get_logger(__name__)

CALLS_COLL, LANG_COLL = "calls", "call_lang_check"
KEY_PURPOSE = "calls"
REF_HEX = 32
LIST_MAX = 200
WIPE_BATCH = 200  # documents a delete pass removes
WIPE_PASSES = 50  # at most 10,000 of one kind
PRIVACY_MAX = 1_000  # calls the Privacy panel counts (30 days of at most 10 a day: 300)
MONTH = re.compile(r"^20[0-9]{2}-(0[1-9]|1[0-2])$")


# ---- sealing the number --------------------------------------------------------------------------
class KeyringSealer:
    """The production sealer: `Keyring` purpose `calls` (cipher and MAC domain)."""

    def __init__(self, keyring: Keyring) -> None:
        self._k = keyring

    def __repr__(self) -> str:
        return "KeyringSealer(<hidden>)"

    def seal(self, uid: str, e164: str) -> str:
        return self._k.cipher(KEY_PURPOSE).encrypt(e164.encode(), aad=f"calls/number/{uid}")

    def open(self, uid: str, sealed: str) -> str:
        try:
            return self._k.cipher(KEY_PURPOSE).decrypt(sealed, aad=f"calls/number/{uid}").decode()
        except (VaultError, UnicodeDecodeError, ValueError):
            raise CallStoreUnreadable("a stored number does not open") from None

    def ref(self, uid: str, e164: str) -> str:
        return self._k.mac(KEY_PURPOSE, f"number/{uid}/{e164}")[:REF_HEX]


class MemorySealer:
    """Tests only: an opaque token per number, kept in this process; refs keyed per instance."""

    def __init__(self) -> None:
        self._key = secrets.token_bytes(32)
        self._sealed: dict[str, tuple[str, str]] = {}

    def seal(self, uid: str, e164: str) -> str:
        token = f"ms_{secrets.token_hex(12)}"
        self._sealed[token] = (uid, e164)
        return token

    def open(self, uid: str, sealed: str) -> str:
        found = self._sealed.get(sealed)
        if found is None or found[0] != uid:
            raise CallStoreUnreadable("a stored number does not open")
        return found[1]

    def ref(self, uid: str, e164: str) -> str:
        mac = hmac.new(self._key, f"number/{uid}/{e164}".encode(), hashlib.sha256)
        return mac.hexdigest()[:REF_HEX]


# ---- the store -----------------------------------------------------------------------------------
def _ts(at: datetime) -> float:
    return at.timestamp()


def _counts(day: date, raw: dict[str, Any] | None) -> DayCounts:
    if raw is None:
        return DayCounts(day)
    try:
        per = {str(k): int(v) for k, v in dict(raw.get("per_number") or {}).items()}
        miss = {str(k): int(v) for k, v in dict(raw.get("no_answer") or {}).items()}
        return DayCounts(day, int(raw.get("calls", 0)), int(raw.get("new_numbers", 0)), per, miss)
    except (TypeError, ValueError, AttributeError):
        raise CallStoreUnreadable("a day's call counters are not readable") from None


def _dump_counts(c: DayCounts) -> dict[str, Any]:
    return {
        "day": c.day.isoformat(),
        "calls": c.calls,
        "new_numbers": c.new_numbers,
        "per_number": dict(c.per_number),
        "no_answer": dict(c.no_answer),
    }


class DocCallStore:
    def __init__(
        self,
        docs: Docs,
        *,
        prefix: str = "jarvis_",
        sealer: KeyringSealer | MemorySealer,
        base: CallSettings | None = None,
    ) -> None:
        self.docs = docs
        self.sealer = sealer
        self._calls = f"{prefix}{CALLS_COLL}"
        self._lang = f"{prefix}{LANG_COLL}"
        self._settings = CallSettingsStore(docs, prefix=prefix, base=base)

    # ---- paths -------------------------------------------------------------------------------
    def _coll(self, uid: str, kind: str) -> str:
        return f"{self._calls}/{owner_key(uid)}/{kind}"

    def _doc(self, uid: str, kind: str, doc_id: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", doc_id):
            raise ValueError("not a document id")
        return f"{self._coll(uid, kind)}/{doc_id}"

    # ---- sealing -----------------------------------------------------------------------------
    def _sealed(self, uid: str, model: CallCard | CallRecord) -> dict[str, Any]:
        body = model.model_dump(mode="json", exclude={"number_e164"})
        body["number_sealed"] = self.sealer.seal(uid, model.number_e164)
        body["number_ref"] = self.sealer.ref(uid, model.number_e164)
        return body

    def _opened(self, uid: str, raw: dict[str, Any] | None, kind: type[Any]) -> Any:
        if raw is None:
            return None
        sealed = raw.get("number_sealed")
        if not isinstance(sealed, str):
            raise CallStoreUnreadable("a stored call has no number")
        body = {k: v for k, v in raw.items() if k not in ("number_sealed", "number_ref")}
        body = {k: v for k, v in body.items() if k not in ("started_ts", "delete_ts")}
        try:
            return kind.model_validate(body | {"number_e164": self.sealer.open(uid, sealed)})
        except ValidationError:
            raise CallStoreUnreadable("a stored call is not readable") from None

    # ---- cards -------------------------------------------------------------------------------
    async def put_card(self, uid: str, card: CallCard) -> None:
        await self.docs.write([Set(self._doc(uid, "cards", card.id), self._sealed(uid, card))])

    async def get_card(self, uid: str, card_id: str) -> CallCard | None:
        found: CallCard | None = self._opened(
            uid, await self.docs.get(self._doc(uid, "cards", card_id)), CallCard
        )
        return found

    async def delete_card(self, uid: str, card_id: str) -> None:
        await self.docs.write([Delete(self._doc(uid, "cards", card_id))])

    # ---- records -----------------------------------------------------------------------------
    def _record_doc(self, uid: str, record: CallRecord) -> dict[str, Any]:
        body = self._sealed(uid, record)
        body["started_ts"] = _ts(record.started_at)
        body["delete_ts"] = _ts(record.delete_after)
        return body

    async def put_record(self, uid: str, record: CallRecord) -> None:
        path = self._doc(uid, "records", record.id)
        await self.docs.write([Set(path, self._record_doc(uid, record))])

    async def get_record(self, uid: str, call_id: str) -> CallRecord | None:
        found: CallRecord | None = self._opened(
            uid, await self.docs.get(self._doc(uid, "records", call_id)), CallRecord
        )
        return found

    async def list_records(self, uid: str, *, limit: int = 50) -> list[CallRecord]:
        q = Query(
            self._coll(uid, "records"),
            order_by="started_ts",
            descending=True,
            limit=max(1, min(limit, LIST_MAX)),
        )
        return [self._opened(uid, raw, CallRecord) for _, raw in await self.docs.query(q)]

    async def delete_record(self, uid: str, call_id: str) -> bool:
        path = self._doc(uid, "records", call_id)

        async def work(tx: DocTx) -> bool:
            if await tx.get(path) is None:
                return False
            tx.delete(path)
            return True

        return await self.docs.transaction(work)

    async def set_keep(self, uid: str, call_id: str, keep: bool) -> CallRecord | None:
        path = self._doc(uid, "records", call_id)

        async def work(tx: DocTx) -> CallRecord | None:
            rec: CallRecord | None = self._opened(uid, await tx.get(path), CallRecord)
            if rec is None:
                return None
            new = rec.model_copy(update={"keep": keep})
            tx.set(path, self._record_doc(uid, new))
            return new

        return await self.docs.transaction(work)

    async def due_for_deletion(self, uid: str, now: datetime) -> list[CallRecord]:
        q = Query(self._coll(uid, "records"), order_by="delete_ts", limit=LIST_MAX)
        cut = _ts(now)
        out = []
        for _, raw in await self.docs.query(q):
            if float(raw.get("delete_ts", math.inf)) > cut:
                break
            rec: CallRecord = self._opened(uid, raw, CallRecord)
            if not rec.keep:
                out.append(rec)
        return out

    # ---- counters and numbers ----------------------------------------------------------------
    async def known_number(self, uid: str, e164: str) -> bool:
        ref = self.sealer.ref(uid, e164)
        return await self.docs.get(self._doc(uid, "numbers", ref)) is not None

    async def day_counts(self, uid: str, day: date) -> DayCounts:
        return _counts(day, await self.docs.get(self._doc(uid, "days", day.isoformat())))

    async def count_call(
        self, uid: str, day: date, e164: str, *, check: LimitCheck | None = None
    ) -> tuple[DayCounts, str | None]:
        """Count one placed call (the limits' check first, inside the same transaction)."""
        ref = self.sealer.ref(uid, e164)
        day_path = self._doc(uid, "days", day.isoformat())
        num_path = self._doc(uid, "numbers", ref)
        now = datetime.now(UTC).isoformat()

        async def work(tx: DocTx) -> tuple[DayCounts, str | None]:
            counts = _counts(day, await tx.get(day_path))
            number = await tx.get(num_path)
            new = number is None
            refused = check(counts, new) if check is not None else None
            if refused is not None:
                return counts, refused
            per = dict(counts.per_number) | {ref: counts.to_number(ref) + 1}
            after = DayCounts(
                day, counts.calls + 1, counts.new_numbers + int(new), per, dict(counts.no_answer)
            )
            tx.set(day_path, _dump_counts(after))
            calls = int((number or {}).get("calls", 0)) + 1
            first = (number or {}).get("first_at", now)
            tx.set(num_path, {"first_at": first, "last_at": now, "calls": calls})
            return after, None

        return await self.docs.transaction(work)

    async def count_no_answer(self, uid: str, day: date, e164: str) -> DayCounts:
        ref = self.sealer.ref(uid, e164)
        path = self._doc(uid, "days", day.isoformat())

        async def work(tx: DocTx) -> DayCounts:
            c = _counts(day, await tx.get(path))
            miss = dict(c.no_answer) | {ref: c.no_answer.get(ref, 0) + 1}
            after = DayCounts(day, c.calls, c.new_numbers, dict(c.per_number), miss)
            tx.set(path, _dump_counts(after))
            return after

        return await self.docs.transaction(work)

    def _month(self, uid: str, month: str) -> str:
        if not MONTH.fullmatch(month):
            raise ValueError("a month is YYYY-MM")
        return self._doc(uid, "months", month)

    async def month_spend(self, uid: str, month: str) -> float:
        raw = await self.docs.get(self._month(uid, month))
        try:
            return float((raw or {}).get("inr", 0.0))
        except (TypeError, ValueError):
            raise CallStoreUnreadable("the month's calls spend is not readable") from None

    async def add_spend(self, uid: str, month: str, inr: float) -> float:
        if not math.isfinite(inr) or inr < 0:
            raise ValueError("a spend is a finite amount of at least ₹0")
        path = self._month(uid, month)

        async def work(tx: DocTx) -> float:
            raw = await tx.get(path)
            total = round(float((raw or {}).get("inr", 0.0)) + inr, 4)
            tx.set(path, {"inr": total})
            return total

        return await self.docs.transaction(work)

    # ---- settings and the language table -----------------------------------------------------
    async def settings(self, uid: str) -> CallSettings:
        return await self._settings.get(uid)

    async def save_settings(self, uid: str, changes: dict[str, Any]) -> CallSettings:
        return await self._settings.save(uid, changes)

    async def put_language_result(self, result: LanguageResult) -> None:
        path = f"{self._lang}/{result.lang}_{result.option.value}"
        await self.docs.write([Set(path, result.model_dump(mode="json"))])

    # ---- the owner's data, for the Privacy panel (R18 review; `jarvis.calls.privacy`) ----------
    async def _ids(self, coll: str, limit: int = WIPE_BATCH) -> list[tuple[str, dict[str, Any]]]:
        return await self.docs.query(Query(coll, limit=limit))

    async def _wipe(self, coll: str) -> int:
        gone = 0
        for _ in range(WIPE_PASSES):
            rows = await self._ids(coll)
            if not rows:
                break
            await self.docs.write([Delete(f"{coll}/{doc_id}") for doc_id, _ in rows])
            gone += len(rows)
        return gone

    async def call_rows(self, uid: str) -> list[tuple[str, bool, float]]:
        """(call id, kept, delete time) of each record, unopened (a seal that doesn't open is
        still counted and still deleted)."""
        rows = await self._ids(self._coll(uid, "records"), limit=PRIVACY_MAX)
        return [
            (doc_id, raw.get("keep") is True, float(raw.get("delete_ts", 0.0) or 0.0))
            for doc_id, raw in rows
        ]

    async def wipe_calls(self, uid: str) -> int:
        """The owner's records, cards and numbers called before (the sealed parts are
        `SealedBlobs.wipe`'s). Today's counters and the months' ₹ stay: they keep the limits
        and the calls cap and hold no number. The records removed."""
        records = await self._wipe(self._coll(uid, "records"))
        for kind in ("cards", "numbers"):
            await self._wipe(self._coll(uid, kind))
        return records

    async def settings_saved(self, uid: str) -> bool:
        return await self._settings.saved(uid)

    async def reset_settings(self, uid: str) -> bool:
        """Back to the defaults (his saved settings deleted); False when none were saved."""
        return await self._settings.reset(uid)

    async def delete_language_results(self) -> int:
        return await self._wipe(self._lang)

    async def language_results(self) -> list[LanguageResult]:
        out = []
        for doc_id, raw in await self.docs.query(Query(self._lang)):
            try:
                out.append(LanguageResult.model_validate(raw))
            except ValidationError:  # not offered: a language is offered only once it passed
                log.warning("a language check result is not readable", extra={"doc": doc_id})
        return out


class MemoryCallStore(DocCallStore):
    """The in-memory twin for tests: the real store on `MemoryDocs` with a `MemorySealer`."""

    def __init__(self, *, base: CallSettings | None = None) -> None:
        super().__init__(MemoryDocs(), prefix="test_", sealer=MemorySealer(), base=base)


__all__ = [
    "CALLS_COLL",
    "KEY_PURPOSE",
    "LANG_COLL",
    "DocCallStore",
    "KeyringSealer",
    "MemoryCallStore",
    "MemorySealer",
]

# src/jarvis/vault/service.py
"""The document vault (R2 D1-D8; Layer 3 service over the Layer 7 store).

Files arrive through `add_file` (the Vault panel upload and, via `intake`, the DigiLocker inbox),
are checked by magic bytes, deduped by SHA-256, sealed in chunks (`VaultCrypto`) and become an item
only once the index entry is written (header last). Fields found in a PDF are a PROPOSAL that the
owner confirms; nothing is confirmed on its own. Deletes are soft (Undo 30 days through the bin);
`purge` crypto-shreds (index entry first, then the chunks by path). Reads fail closed.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import secrets
import zipfile
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from jarvis.integrations.vault import VaultError
from jarvis.logging import get_logger
from jarvis.recall.sensitive import sensitive_reason
from jarvis.tools.card import one_line
from jarvis.undo.models import DeletedItem
from jarvis.undo.service import Gone, Restored, discard_kind
from jarvis.vault.crypto import VaultCrypto, chunk_count
from jarvis.vault.fields import propose
from jarvis.vault.models import (
    HOLDER_LABEL_MAX,
    ID_FILE,
    ID_HOLDER,
    ID_ITEM,
    LAST4,
    MAX_FILES_PER_ITEM,
    MAX_HOLDERS,
    MAX_ITEMS,
    ME,
    NOTE_MAX,
    REMINDER_CHOICES,
    TITLE_MAX,
    TYPES,
    FileRef,
    Holder,
    Item,
    Orphan,
    Pending,
    Proposal,
    Source,
    SourceKind,
    VaultIndex,
    VaultRejected,
    VaultSettings,
    VaultUnavailable,
    days_left,
    replace_item,
)
from jarvis.vault.ports import MAX_FILE_BYTES, IntakeResult
from jarvis.vault.store import VaultStore

log = get_logger(__name__)
Extractor = Callable[[bytes, str], Awaitable[Any]]
IST = ZoneInfo("Asia/Kolkata")
MB = 1024 * 1024
KEEP_ONLY_LAST4 = "JARVIS keeps only the last 4 characters of an ID number."
IDS_IN_FILE = "Keep the number in the file; type only its last 4 in 'Ends with'."
EXT = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png"}
NEEDS_JPEG = "JARVIS keeps PDF, JPEG and PNG files. Save it as PDF or JPEG first."
VAULT_BIN_TITLE = "A document"  # R2 review H2: bin titles are in clear, so no document type


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def sniff_mime(data: bytes) -> str | None:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return None


def _convertible(data: bytes) -> bool:
    """HEIC / WebP get the friendlier 'save it as PDF or JPEG first'."""
    return data[8:12] in (b"heic", b"heix", b"mif1", b"msf1") or (
        data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    )


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:30] or "file"


@dataclass(frozen=True)
class Added:
    item: Item
    proposal: Proposal | None
    duplicate: bool = False


@dataclass(frozen=True)
class Due:
    item_id: str
    type: str
    type_label: str
    holder_id: str
    whose: str  # "you" or "family"
    holder_label: str
    expires_on: dt.date
    days_left: int
    reminders: tuple[int, ...]


@dataclass(frozen=True)
class Download:
    filename: str
    mime: str
    size: int | None
    body: AsyncIterator[bytes]
    files: int = 1


class _Sink:
    """An unseekable write-only target for a streamed ZIP: bytes pile up until yielded."""

    def __init__(self) -> None:
        self.parts: list[bytes] = []
        self.pos = 0

    def write(self, b: bytes) -> int:
        self.parts.append(bytes(b))
        self.pos += len(b)
        return len(b)

    def tell(self) -> int:
        return self.pos

    def flush(self) -> None:
        return None

    def take(self) -> bytes:
        out = b"".join(self.parts)
        self.parts.clear()
        return out


def clean_text(value: Any, limit: int, what: str, *, allow_empty: bool = True) -> str:
    text = one_line(value, limit + 1) if value is not None else ""
    if not text and not allow_empty:
        raise VaultRejected("invalid", f"{what} can't be empty.")
    if len(text) > limit:
        raise VaultRejected("invalid", f"{what} can be at most {limit} characters.")
    if text and sensitive_reason(text) is not None:
        raise VaultRejected("sensitive", IDS_IN_FILE)
    return text


def clean_last4(value: Any) -> str | None:
    text = re.sub(r"[\s\-]", "", str(value or "")).upper()
    if not text:
        return None
    if not LAST4.fullmatch(text):
        raise VaultRejected("invalid", KEEP_ONLY_LAST4)
    return text


def clean_reminders(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list | tuple) or any(
        isinstance(v, bool) or v not in REMINDER_CHOICES for v in value
    ):
        raise VaultRejected("invalid", "Reminders can be 180, 90, 60, 30, 14, 7 or 1 days before.")
    return tuple(sorted(set(value), reverse=True))


class VaultService:
    def __init__(
        self,
        store: VaultStore,
        crypto: VaultCrypto,
        *,
        extract: Extractor | None = None,
        undo: Any = None,
        max_total_mb: int = 150,
        clock: Callable[[], dt.datetime] = utcnow,
        tz: ZoneInfo = IST,
    ) -> None:
        self.store = store
        self._crypto = crypto
        self._extract = extract
        self._undo = undo
        self._limit = max_total_mb * MB
        self._clock = clock
        self._tz = tz

    @property
    def limit_mb(self) -> int:
        return self._limit // MB

    def today(self) -> dt.date:
        return self._clock().astimezone(self._tz).date()

    # ---- reads -------------------------------------------------------------------------------

    async def index(self, uid: str) -> VaultIndex:
        return (await self.store.load(uid))[1]

    async def get_item(self, uid: str, item_id: str) -> Item | None:
        item = (await self.index(uid)).item(item_id) if ID_ITEM.fullmatch(item_id) else None
        return item if item is not None and item.live else None

    def item_view(self, index: VaultIndex, item: Item, today: dt.date) -> dict[str, Any]:
        info = TYPES.get(item.type, TYPES["other"])
        left = days_left(item, today) if item.dates_confirmed else None
        prop = item.proposal
        return {
            "id": item.id,
            "type": item.type,
            "type_label": info.label,
            "normally_expires": info.expires,
            "holder_id": item.holder_id,
            "holder": index.holder_label(item.holder_id),
            "title": item.title,
            "last4": item.last4,
            "ends": f"••{item.last4}" if item.last4 else None,
            "note": item.note,
            "issued_on": item.issued_on.isoformat() if item.issued_on else None,
            "expires_on": item.expires_on.isoformat() if item.expires_on else None,
            "days_left": left,
            "dates_confirmed": item.dates_confirmed,
            "needs_check": not item.dates_confirmed,
            "reminders": list(item.reminders),
            "from_digilocker": item.source.kind == "digilocker",
            "files": [{"fid": f.fid, "mime": f.mime, "size": f.size} for f in item.files],
            "proposal": None
            if prop is None or prop.empty
            else {
                "type": prop.type,
                "type_label": TYPES[prop.type].label if prop.type in TYPES else None,
                "issued_on": prop.issued_on.isoformat() if prop.issued_on else None,
                "issued_label": prop.issued_label,
                "expires_on": prop.expires_on.isoformat() if prop.expires_on else None,
                "expires_label": prop.expires_label,
                "last4": prop.last4,
            },
            "created_at": item.created_at.isoformat(),
        }

    async def view(self, uid: str) -> dict[str, Any]:
        index = await self.index(uid)
        today = self.today()
        live = index.live_items()
        counts = {h.id: sum(1 for i in live if i.holder_id == h.id) for h in index.holders}
        return {
            "available": True,
            "items": [self.item_view(index, i, today) for i in live],
            "holders": [
                {"id": ME, "label": "you", "count": sum(1 for i in live if i.holder_id == ME)},
                *({"id": h.id, "label": h.label, "count": counts[h.id]} for h in index.holders),
            ],
            "totals": {
                "items": len(live),
                "max_items": MAX_ITEMS,
                "mb": round(index.bytes_total() / MB, 1),
                "limit_mb": self._limit // MB,
            },
            "settings": index.settings.model_dump(),
        }

    async def due(
        self,
        uid: str,
        today: dt.date | None = None,
        *,
        within_days: int = 90,
        expired_days: int = 30,
    ) -> list[Due]:
        """Confirmed live items expiring within `within_days` or expired in the last
        `expired_days`, soonest first. Unconfirmed items never appear."""
        index = await self.index(uid)
        return self.due_of(index, today or self.today(), within_days, expired_days)

    def due_of(
        self, index: VaultIndex, today: dt.date, within_days: int = 90, expired_days: int = 30
    ) -> list[Due]:
        out = []
        for i in index.live_items():
            left = days_left(i, today)
            if not i.dates_confirmed or left is None or i.expires_on is None:
                continue
            if -expired_days <= left <= within_days:
                out.append(
                    Due(
                        item_id=i.id,
                        type=i.type,
                        type_label=TYPES.get(i.type, TYPES["other"]).label,
                        holder_id=i.holder_id,
                        whose="you" if i.holder_id == ME else "family",
                        holder_label=index.holder_label(i.holder_id),
                        expires_on=i.expires_on,
                        days_left=left,
                        reminders=i.reminders,
                    )
                )
        return sorted(out, key=lambda d: d.days_left)

    # ---- adding files ----------------------------------------------------------------------

    def _check_bytes(self, data: bytes) -> str:
        if not data:
            raise VaultRejected("empty", "That file is empty.")
        if len(data) > MAX_FILE_BYTES:
            raise VaultRejected("too_large", "Files can be up to 10 MB.", status=413)
        mime = sniff_mime(data)
        if mime is None:
            raise VaultRejected(
                "unsupported", NEEDS_JPEG if _convertible(data) else NEEDS_JPEG, status=415
            )
        return mime

    async def add_file(
        self,
        uid: str,
        data: bytes,
        *,
        source: str = "upload",
        drive_id: str | None = None,
        item_id: str | None = None,
        type_hint: str | None = None,
        holder_id: str | None = None,
    ) -> Added:
        mime = self._check_bytes(data)
        if type_hint is not None and type_hint not in TYPES:
            raise VaultRejected("invalid", "That isn't a document type JARVIS knows.")
        if item_id is not None and not ID_ITEM.fullmatch(item_id):
            raise VaultRejected("not_found", "That document isn't in your vault.", status=404)
        sha = hashlib.sha256(data).hexdigest()
        fid = f"f_{secrets.token_hex(6)}"
        now = self._clock()
        count = chunk_count(len(data))

        def reserve(index: VaultIndex) -> tuple[VaultIndex, str | None]:
            for i in index.live_items():
                if any(f.sha256 == sha for f in i.files):
                    return index, i.id  # the same file again
            self._check_room(index, item_id, holder_id, len(data))
            pend = Pending(
                fid=fid, item_id=item_id or "", chunks=count, size=len(data), started_at=now
            )
            return index.model_copy(update={"pending": (*index.pending, pend)}), None

        dup = await self.store.change(uid, reserve)
        if dup is not None:
            item = await self.get_item(uid, dup)
            if item is not None:
                return Added(item, None, duplicate=True)
            raise VaultRejected("duplicate", "That file is already in your vault.", status=409)
        new_id = item_id or f"v_{secrets.token_hex(6)}"
        try:
            return await self._store_file(
                uid, data, mime, sha, fid, new_id, item_id is None, source, drive_id,
                type_hint, holder_id, now, count,
            )  # fmt: skip
        except BaseException:
            await self._abandon(uid, fid, count)
            raise

    def _check_room(
        self, index: VaultIndex, item_id: str | None, holder_id: str | None, size: int
    ) -> None:
        if (
            holder_id is not None
            and holder_id != ME
            and not any(h.id == holder_id for h in index.holders)
        ):
            raise VaultRejected("invalid", "That family member isn't in your vault list.")
        if item_id is not None:
            target = index.item(item_id)
            if target is None or not target.live:
                raise VaultRejected("not_found", "That document isn't in your vault.", status=404)
            if len(target.files) >= MAX_FILES_PER_ITEM:
                raise VaultRejected(
                    "files_full", "A document holds two files (front and back).", status=409
                )
        elif len(index.live_items()) >= MAX_ITEMS:
            raise VaultRejected(
                "vault_full", f"Your vault holds {MAX_ITEMS} documents already.", status=409
            )
        if index.bytes_total() + size > self._limit:
            raise VaultRejected(
                "vault_full",
                f"The vault is full ({self._limit // MB} MB). Remove a document first.",
                status=409,
            )

    async def _proposal(self, data: bytes, mime: str, hint: str | None) -> Proposal | None:
        if mime != "application/pdf" or self._extract is None:
            return None
        try:
            got = await self._extract(data, "pdf")
            found = propose(str(getattr(got, "text", "")), hint)
        except Exception as exc:  # noqa: BLE001 - no text layer or a hostile file: the owner types
            log.info("vault fields not read", extra={"error": type(exc).__name__})
            return None
        return None if found.empty else found

    async def _store_file(
        self, uid: str, data: bytes, mime: str, sha: str, fid: str, new_id: str, is_new: bool,
        source: str, drive_id: str | None, hint: str | None, holder_id: str | None,
        now: dt.datetime, count: int,
    ) -> Added:  # fmt: skip
        try:
            wrapped, blobs = self._crypto.seal(uid, new_id, fid, data)
        except VaultError:
            raise VaultUnavailable("the file could not be sealed") from None
        await self.store.put_chunks(uid, fid, blobs)
        found = await self._proposal(data, mime, hint)
        ref = FileRef(
            fid=fid, mime=mime, size=len(data), sha256=sha, chunks=count, dek=wrapped, added_at=now
        )
        kind: SourceKind = "digilocker" if source == "digilocker" else "upload"

        def commit(index: VaultIndex) -> tuple[VaultIndex, Item]:
            if not any(p.fid == fid for p in index.pending):
                raise VaultUnavailable("the upload took too long and was cleared")
            rest = tuple(p for p in index.pending if p.fid != fid)
            if is_new:
                type_id = hint or (found.type if found and found.type else "other")
                item = Item(
                    id=new_id, type=type_id, holder_id=holder_id or ME,
                    title=TYPES[type_id].label, source=Source(kind=kind, drive_id=drive_id),
                    files=(ref,), proposal=found, created_at=now, updated_at=now,
                )  # fmt: skip
                return index.model_copy(
                    update={"items": (*index.items, item), "pending": rest}
                ), item
            cur = index.item(new_id)
            if cur is None or not cur.live:
                raise VaultRejected("not_found", "That document isn't in your vault.", status=404)
            item = cur.model_copy(update={"files": (*cur.files, ref), "updated_at": now})
            return replace_item(index, item).model_copy(update={"pending": rest}), item

        item = await self.store.change(uid, commit)
        return Added(item, found if is_new else None)

    async def _abandon(self, uid: str, fid: str, count: int) -> None:
        """An upload failed half-way: its chunks go (by path); if even that fails the sweep will."""
        try:
            await self.store.drop_chunks(uid, fid, count)

            def clear(index: VaultIndex) -> tuple[VaultIndex, None]:
                keep = tuple(p for p in index.pending if p.fid != fid)
                return index.model_copy(update={"pending": keep}), None

            await self.store.change(uid, clear)
        except Exception as exc:  # noqa: BLE001
            log.warning("vault upload cleanup deferred", extra={"error": type(exc).__name__})

    async def intake(
        self, uid: str, data: bytes, *, source: Any, drive_id: str | None = None
    ) -> IntakeResult:
        """The `VaultIntake` port (R2 D9): plain words, never the file name or a number."""
        try:
            got = await self.add_file(uid, data, source=source, drive_id=drive_id)
        except VaultRejected as exc:
            return IntakeResult(status="skipped", code=exc.code, message=exc.detail)
        except (VaultUnavailable, VaultError):
            return IntakeResult(
                status="skipped", code="unavailable", message="The vault isn't available right now."
            )
        return IntakeResult(status="duplicate" if got.duplicate else "added", item_id=got.item.id)

    # ---- changes ---------------------------------------------------------------------------

    async def update(
        self, uid: str, item_id: str, patch: dict[str, Any], *, dates_flag: str = "auto"
    ) -> dict[str, Any]:
        """Apply the fields the owner sent. `confirm: true` fills missing dates / last 4 from the
        proposal and marks the dates confirmed (reminders start). `dates_flag` (tools only): "set"
        confirms the dates without touching the proposal, "keep" leaves the flag as it is."""
        if not ID_ITEM.fullmatch(item_id):
            raise VaultRejected("not_found", "That document isn't in your vault.", status=404)
        now = self._clock()
        fields = self._clean_patch(patch)
        confirm = patch.get("confirm") is True

        def apply(index: VaultIndex) -> tuple[VaultIndex, Item]:
            cur = index.item(item_id)
            if cur is None or not cur.live:
                raise VaultRejected("not_found", "That document isn't in your vault.", status=404)
            if (
                "holder_id" in fields
                and fields["holder_id"] != ME
                and not any(h.id == fields["holder_id"] for h in index.holders)
            ):
                raise VaultRejected("invalid", "That family member isn't in your vault list.")
            upd: dict[str, Any] = {**fields, "updated_at": now}
            if confirm:
                upd.update(self._confirmed(cur, fields))
            elif dates_flag == "set":
                upd["dates_confirmed"] = True
            elif dates_flag == "auto" and {"issued_on", "expires_on"} & fields.keys():
                upd["dates_confirmed"] = False  # a changed date is the owner's to confirm again
            item = cur.model_copy(update=upd)
            if item.issued_on and item.expires_on and item.expires_on < item.issued_on:
                raise VaultRejected("invalid", "The expiry date is before the issue date.")
            return replace_item(index, item), item

        item = await self.store.change(uid, apply)
        return self.item_view(await self.index(uid), item, self.today())

    @staticmethod
    def _confirmed(cur: Item, fields: dict[str, Any]) -> dict[str, Any]:
        prop = cur.proposal
        out: dict[str, Any] = {"dates_confirmed": True, "proposal": None}
        if prop is not None:
            for name in ("issued_on", "expires_on", "last4"):
                if name not in fields and getattr(cur, name) is None:
                    out[name] = getattr(prop, name)
        return out

    def _clean_patch(self, patch: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if "type" in patch:
            if patch["type"] not in TYPES:
                raise VaultRejected("invalid", "That isn't a document type JARVIS knows.")
            out["type"] = patch["type"]
        if "holder_id" in patch:
            hid = patch["holder_id"]
            if hid != ME and not (isinstance(hid, str) and ID_HOLDER.fullmatch(hid)):
                raise VaultRejected("invalid", "That family member isn't in your vault list.")
            out["holder_id"] = hid
        if "title" in patch:
            out["title"] = clean_text(patch["title"], TITLE_MAX, "The title", allow_empty=False)
        if "note" in patch:
            out["note"] = clean_text(patch["note"], NOTE_MAX, "The note")
        if "last4" in patch:
            out["last4"] = clean_last4(patch["last4"])
        for name in ("issued_on", "expires_on"):
            if name in patch:
                out[name] = self._date(patch[name])
        if "reminders" in patch:
            out["reminders"] = clean_reminders(patch["reminders"])
        return out

    @staticmethod
    def _date(value: Any) -> dt.date | None:
        if value in (None, ""):
            return None
        try:
            d = value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value))
        except ValueError:
            raise VaultRejected("invalid", "Dates look like 2031-02-11.") from None
        if not 1950 <= d.year <= 2100:
            raise VaultRejected("invalid", "That date is out of range.")
        return d

    async def set_dates(
        self, uid: str, item_id: str, *, issued_on: Any = None, expires_on: Any = None
    ) -> dict[str, Any]:
        """The `vault_set_dates` tool: the owner told JARVIS the date, so it counts as confirmed."""
        # Only the dates given are applied: the proposal (read from untrusted file text) is never
        # copied in or cleared, and only an expiry the owner gave counts as confirmed (R2 M2).
        patch: dict[str, Any] = {}
        if issued_on is not None:
            patch["issued_on"] = issued_on
        if expires_on is not None:
            patch["expires_on"] = expires_on
        return await self.update(
            uid, item_id, patch, dates_flag="set" if expires_on is not None else "keep"
        )

    # ---- holders and settings ---------------------------------------------------------------

    async def add_holder(self, uid: str, label: Any) -> Holder:
        text = clean_text(label, HOLDER_LABEL_MAX, "The name", allow_empty=False)
        holder = Holder(id=f"h_{secrets.token_hex(4)}", label=text)

        def add(index: VaultIndex) -> tuple[VaultIndex, Holder]:
            if len(index.holders) >= MAX_HOLDERS:
                raise VaultRejected(
                    "holders_full", f"You can list {MAX_HOLDERS} family members.", status=409
                )
            if text.casefold() in {h.label.casefold() for h in index.holders} | {"you", "me"}:
                raise VaultRejected("duplicate", "That name is already in the list.", status=409)
            return index.model_copy(update={"holders": (*index.holders, holder)}), holder

        return await self.store.change(uid, add)

    async def remove_holder(self, uid: str, holder_id: str) -> None:
        def remove(index: VaultIndex) -> tuple[VaultIndex, None]:
            if not any(h.id == holder_id for h in index.holders):
                raise VaultRejected(
                    "not_found", "That family member isn't in the list.", status=404
                )
            if any(i.holder_id == holder_id for i in index.items):
                raise VaultRejected(
                    "in_use",
                    "Documents still belong to them. Move or remove those first.",
                    status=409,
                )
            keep = tuple(h for h in index.holders if h.id != holder_id)
            return index.model_copy(update={"holders": keep}), None

        await self.store.change(uid, remove)

    async def update_settings(self, uid: str, patch: dict[str, Any]) -> dict[str, Any]:
        known = set(VaultSettings.model_fields)
        try:
            if not patch or set(patch) - known:
                raise ValueError
            VaultSettings.model_validate(patch)  # types are checked before the transaction
        except ValueError:
            raise VaultRejected("invalid", "That setting isn't one JARVIS knows.") from None

        def apply(index: VaultIndex) -> tuple[VaultIndex, VaultSettings]:
            new = VaultSettings.model_validate({**index.settings.model_dump(), **patch})
            return index.model_copy(update={"settings": new}), new

        return (await self.store.change(uid, apply)).model_dump()

    # ---- delete, restore, purge ---------------------------------------------------------------

    async def remove(self, uid: str, item_id: str, *, session_id: str | None = None) -> str:
        """Soft delete with Undo (30 days). Fails closed: no bin, no delete. Returns the undo id."""
        item = await self.get_item(uid, item_id)
        if item is None:
            raise VaultRejected("not_found", "That document isn't in your vault.", status=404)
        if self._undo is None:
            raise VaultUnavailable("Recently deleted isn't available, so nothing was deleted")
        now = self._clock()
        snapshot = {"ref": item_id, "deleted_at": now.isoformat()}  # the purge matches on this
        try:
            kept = await self._undo.keep(
                uid, "vault_item", VAULT_BIN_TITLE, snapshot,
                owner_authored=True, session_id=session_id,
            )  # fmt: skip
        except Exception as exc:  # noqa: BLE001
            log.error("vault delete not kept", extra={"error": type(exc).__name__})
            raise VaultUnavailable(
                "a copy for Undo could not be kept, so nothing was deleted"
            ) from None

        def tombstone(index: VaultIndex) -> tuple[VaultIndex, None]:
            cur = index.item(item_id)
            if cur is None:
                raise VaultRejected("not_found", "That document isn't in your vault.", status=404)
            return replace_item(index, cur.model_copy(update={"deleted_at": now})), None

        try:
            await self.store.change(uid, tombstone)
        except BaseException:
            await self._undo.discard(uid, kept.id)
            raise
        return str(kept.id)

    async def restore(self, uid: str, item_id: str) -> Item:
        def clear(index: VaultIndex) -> tuple[VaultIndex, Item]:
            cur = index.item(item_id) if ID_ITEM.fullmatch(item_id) else None
            if cur is None:
                raise VaultRejected(
                    "gone", "That document was already removed for good.", status=404
                )
            if cur.live:
                return index, cur
            back = cur.model_copy(update={"deleted_at": None})
            return replace_item(index, back), back

        return await self.store.change(uid, clear)

    async def purge(self, uid: str, item_id: str, *, deleted_at: dt.datetime | None = None) -> bool:
        """Hard delete: the index entry first (the wrapped keys go with it, so the chunks are
        unreadable at once), then the chunks by path. Safe to repeat. With `deleted_at` it shreds
        only an item still tombstoned at exactly that time (the bin entry's own delete)."""
        removed: list[Item] = []

        def shred(index: VaultIndex) -> tuple[VaultIndex, bool]:
            cur = index.item(item_id) if ID_ITEM.fullmatch(item_id) else None
            if cur is None:
                return index, False
            if deleted_at is not None and (cur.deleted_at is None or cur.deleted_at != deleted_at):
                return index, False
            removed.clear()
            removed.append(cur)
            orphans = (*index.orphans, *(Orphan(fid=f.fid, chunks=f.chunks) for f in cur.files))
            keep = tuple(i for i in index.items if i.id != item_id)
            return index.model_copy(update={"items": keep, "orphans": orphans}), True

        found = await self.store.change(uid, shred)
        if found:
            await self._drop_orphans(uid, [f.fid for f in removed[0].files], removed[0].files)
        return found

    async def _drop_orphans(self, uid: str, fids: list[str], files: Any) -> None:
        done = []
        for f in files:
            try:
                await self.store.drop_chunks(uid, f.fid, f.chunks)
                done.append(f.fid)
            except Exception as exc:  # noqa: BLE001 - kept in orphans; the sweep retries
                log.warning("vault chunks left for the sweep", extra={"error": type(exc).__name__})
        if done:
            try:
                await self.store.forget_orphans(uid, done)
            except Exception as exc:  # noqa: BLE001
                log.warning("vault orphan list not cleared", extra={"error": type(exc).__name__})

    async def wipe(self, uid: str) -> int:
        """Delete everything the owner keeps in the vault (the privacy dashboard), and its entries
        in Recently deleted (R2 review H2). Returns items."""
        files: list[FileRef] = []
        pend: list[Pending] = []
        count = [0]

        def clear(index: VaultIndex) -> tuple[VaultIndex, int]:
            files.clear()
            pend.clear()
            files.extend(f for i in index.items for f in i.files)
            pend.extend(index.pending)
            count[0] = len(index.items)
            orphans = (
                *index.orphans,
                *(Orphan(fid=f.fid, chunks=f.chunks) for f in files),
                *(Orphan(fid=p.fid, chunks=p.chunks) for p in pend),
            )
            return VaultIndex(orphans=orphans), count[0]

        n = await self.store.change(uid, clear)
        todo = [*files, *(Orphan(fid=p.fid, chunks=p.chunks) for p in pend)]
        await self._drop_orphans(uid, [], todo)
        _, index = await self.store.load(uid)
        if not index.orphans:
            await self.store.delete_all(uid)
        await discard_kind(self._undo, uid, "vault_item")
        return n

    # ---- opening files (the console only; tickets are checked by the API) -------------------

    def _name(self, index: VaultIndex, item: Item, position: int, mime: str) -> str:
        who = "you" if item.holder_id == ME else slug(index.holder_label(item.holder_id))
        return f"{TYPES.get(item.type, TYPES['other']).slug}-{who}-{position}.{EXT[mime]}"

    async def _chunks(self, uid: str, item: Item, ref: FileRef) -> AsyncIterator[bytes]:
        try:
            dek = self._crypto.unwrap(uid, item.id, ref.fid, ref.dek)
        except VaultError:
            raise VaultUnavailable("the file can't be opened") from None
        digest, total = hashlib.sha256(), 0
        for n in range(ref.chunks):
            blob = await self.store.chunk(uid, ref.fid, n)
            try:
                plain = self._crypto.open_chunk(dek, uid, item.id, ref.fid, n, ref.chunks, blob)
            except VaultError:
                raise VaultUnavailable("the file can't be opened") from None
            digest.update(plain)
            total += len(plain)
            yield plain
        if digest.hexdigest() != ref.sha256 or total != ref.size:
            log.error("vault file failed its checksum")
            raise VaultUnavailable("the file failed its check")

    async def stream_file(self, uid: str, item_id: str, fid: str) -> Download:
        if not ID_FILE.fullmatch(fid):
            raise VaultRejected("not_found", "That file isn't in your vault.", status=404)
        index = await self.index(uid)
        item = index.item(item_id) if ID_ITEM.fullmatch(item_id) else None
        pos = next((n for n, f in enumerate(item.files, 1) if f.fid == fid), 0) if item else 0
        if item is None or not item.live or not pos:
            raise VaultRejected("not_found", "That file isn't in your vault.", status=404)
        ref = item.files[pos - 1]
        gen = self._chunks(uid, item, ref)
        try:
            first = await gen.__anext__()  # fail before any byte is sent
        except StopAsyncIteration:
            first = b""

        async def body() -> AsyncIterator[bytes]:
            yield first
            async for part in gen:
                yield part

        return Download(self._name(index, item, pos, ref.mime), ref.mime, ref.size, body())

    def _manifest(self, index: VaultIndex, names: dict[str, list[str]]) -> bytes:
        import json

        rows = []
        for i in index.live_items():
            rows.append(
                {
                    "type": TYPES.get(i.type, TYPES["other"]).label,
                    "holder": index.holder_label(i.holder_id),
                    "title": i.title,
                    "ends": i.last4,
                    "note": i.note,
                    "issued_on": i.issued_on.isoformat() if i.issued_on else None,
                    "expires_on": i.expires_on.isoformat() if i.expires_on else None,
                    "files": names.get(i.id, []),
                }
            )
        return json.dumps({"documents": rows}, indent=2, ensure_ascii=False).encode()

    async def stream_export(self, uid: str) -> Download:
        index = await self.index(uid)
        plan = [(i, ref, n) for i in index.live_items() for n, ref in enumerate(i.files, 1)]
        names: dict[str, list[str]] = {}
        for i, ref, n in plan:
            names.setdefault(i.id, []).append(self._name(index, i, n, ref.mime))
        manifest = self._manifest(index, names)

        async def body() -> AsyncIterator[bytes]:
            sink = _Sink()
            with zipfile.ZipFile(sink, "w", zipfile.ZIP_STORED) as zf:  # type: ignore[call-overload]
                zf.writestr("vault.json", manifest)
                yield sink.take()
                for i, ref, n in plan:
                    info = zipfile.ZipInfo(self._name(index, i, n, ref.mime))
                    info.compress_type = zipfile.ZIP_STORED
                    with zf.open(info, "w", force_zip64=True) as entry:
                        async for part in self._chunks(uid, i, ref):
                            entry.write(part)
                            yield sink.take()
                    yield sink.take()
            yield sink.take()

        return Download("jarvis-vault.zip", "application/zip", None, body(), files=len(plan))


class VaultRestorer:
    """Undo restorer for kind `vault_item`: clears the tombstone in place (same id)."""

    def __init__(self, svc: VaultService) -> None:
        self._svc = svc

    async def restore(self, uid: str, item: DeletedItem, *, outside: bool = False) -> Restored:
        ref = str(item.snapshot.get("ref", ""))
        try:
            await self._svc.restore(uid, ref)
        except VaultRejected:  # removed for good (purged, or the vault was wiped)
            raise Gone() from None
        return Restored(new_id=ref)


class VaultPurger:
    """Undo purger for kind `vault_item`: hard delete (crypto-shred). Safe to repeat."""

    def __init__(self, svc: VaultService) -> None:
        self._svc = svc

    async def purge(self, uid: str, item: DeletedItem) -> None:
        """Shreds only while the item is still tombstoned by THIS entry's delete (R2 review C1):
        a restored, re-deleted or legacy entry (no tombstone time) does nothing."""
        try:
            stamp = dt.datetime.fromisoformat(str(item.snapshot.get("deleted_at", "")))
        except ValueError:
            return
        if stamp.tzinfo is None:
            return
        await self._svc.purge(uid, str(item.snapshot.get("ref", "")), deleted_at=stamp)


__all__ = [
    "VAULT_BIN_TITLE",
    "Added",
    "Download",
    "Due",
    "VaultPurger",
    "VaultRestorer",
    "VaultService",
    "clean_last4",
    "sniff_mime",
]

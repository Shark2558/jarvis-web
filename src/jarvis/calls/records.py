# src/jarvis/calls/records.py
"""Call records in the vault (R18 A1; docs/plans/r18-calls.md section 4 step 8, section 7 item 3;
BUILD-BRIEF.md "Records"; Layer 7 data, cross-cutting security).

A call's audio (Opus or compressed 16 kHz mono, D8), its transcript (each line in the language it
was spoken and in English), its English summary and its ₹ are sealed with the vault's envelope
encryption (`jarvis.vault.crypto.VaultCrypto`: a random data key per file, AES-256-GCM in 512 KiB
chunks, the key wrapped by the keyring's `vault` key; every AAD names the owner, the call and the
kind, so a chunk moved to another call, kind or owner fails to open):

    {prefix}calls/{uid}/sealed/{call_id}_{kind}             {wrapped, count, size, media, at}
    {prefix}calls/{uid}/sealed_chunks/{call_id}_{kind}_{nn} {blob, n, of}

Chunks are written first and the header last (a file exists once its header does); a delete
removes the header first (its wrapped key goes with it: crypto-shredded) and then the chunks.
`CallRecord` (I0's store) carries the references only.

- `RecordKeeper.save_audio` / `save_transcript` / `save_summary`: the engine's wrap-up.
- `RecordKeeper.objected`: the other person asked not to be recorded: the audio and the transcript
  recorded so far are deleted, no more are kept for that call (`recorded` False, `objected`
  True), and only the summary's notes stay.
- `delete` (his Delete, and the retention job), `keep` (past retention), `audio`, `transcript`,
  `summary` (reads fail closed: a part that does not open is `RecordUnreadable`, never empty).
Every step is in the audit chain (`approvals.audit_step`); logs never carry a number, a
transcript, a summary or audio.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from jarvis.calls.approvals import audit_step
from jarvis.calls.models import LANG_CODE, CallRecord, Speaker
from jarvis.calls.ports import CallStore
from jarvis.calls.settings import owner_key
from jarvis.core.guardrails import ActionRisk
from jarvis.integrations.vault import VaultError
from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, Set
from jarvis.tools.audit import AuditTrail
from jarvis.vault.crypto import VaultCrypto

log = get_logger(__name__)

Kind = Literal["audio", "transcript", "summary"]
KINDS: tuple[Kind, ...] = ("audio", "transcript", "summary")
AUDIO_TYPES = frozenset({"audio/ogg", "audio/webm", "audio/wav"})
JSON_TYPE = "application/json"
MAX_AUDIO_BYTES = 16 * 1024 * 1024  # 30 minutes of compressed audio with room to spare
MAX_TEXT_BYTES = 2 * 1024 * 1024
WRITE_GROUP = 6
RECORD_TOOL = "calls_record"

MSG_NO_RECORD = "There is no such call record."
MSG_NOT_RECORDED = "This call has no recording (it wasn't recorded, or it was deleted)."
MSG_OBJECTED = "The other person asked not to be recorded, so this call keeps no recording."
MSG_UNREADABLE = "A part of this call record can't be opened, so it isn't shown."
MSG_TOO_BIG = "That recording is too big to keep."
MSG_TYPE = "A recording is kept as Ogg/Opus, WebM/Opus or 16 kHz WAV."


class RecordRefused(ValueError):
    """A record step that can't be done; `str()` is plain words, `code` stable."""

    def __init__(self, code: str, words: str) -> None:
        super().__init__(words)
        self.code, self.words = code, words


class RecordUnreadable(RecordRefused):
    def __init__(self) -> None:
        super().__init__("unreadable", MSG_UNREADABLE)


# ---- what is sealed ---------------------------------------------------------------------------
class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TranscriptLine(_Frozen):
    who: Speaker
    lang: str = Field(pattern=LANG_CODE)
    text: str = Field(max_length=4_000)  # as spoken
    english: str = Field(default="", max_length=4_000)  # "" when it was spoken in English
    at: AwareDatetime | None = None


class Transcript(_Frozen):
    lines: tuple[TranscriptLine, ...] = Field(default=(), max_length=2_000)


class CallMessage(_Frozen):
    """A message taken on an answered call (row 104): what the caller said, never a promise."""

    name: str = Field(default="", max_length=80)
    reason: str = Field(default="", max_length=500)
    call_back: str = Field(default="", max_length=20)


class CallSummary(_Frozen):
    english: str = Field(min_length=1, max_length=4_000)  # who, what was agreed, what's next
    agreed: tuple[str, ...] = Field(default=(), max_length=20)
    next_steps: tuple[str, ...] = Field(default=(), max_length=20)
    needs_owner: tuple[str, ...] = Field(default=(), max_length=20)
    message: CallMessage | None = None
    booked_start: AwareDatetime | None = None  # a booking accepted inside the card's windows
    cost_inr: float = Field(default=0, ge=0)
    cost_parts: dict[str, float] = Field(default_factory=dict)


# ---- sealed blobs on the Docs port ------------------------------------------------------------
def _utcnow() -> datetime:
    return datetime.now(UTC)


class SealedBlobs:
    def __init__(self, docs: Docs, crypto: VaultCrypto, *, prefix: str = "jarvis_") -> None:
        self.docs, self.crypto, self._root = docs, crypto, f"{prefix}calls"

    def _head(self, uid: str, ref: str) -> str:
        return f"{self._root}/{owner_key(uid)}/sealed/{ref}"

    def _chunk(self, uid: str, ref: str, n: int) -> str:
        return f"{self._root}/{owner_key(uid)}/sealed_chunks/{ref}_{n:02d}"

    @staticmethod
    def ref(call_id: str, kind: Kind) -> str:
        return f"{call_id}_{kind}"

    @staticmethod
    def _split(ref: str) -> tuple[str, str]:
        call_id, _, kind = ref.rpartition("_")
        if kind not in KINDS or not call_id.startswith("call_"):
            raise RecordUnreadable()
        return call_id, kind

    async def put(self, uid: str, call_id: str, kind: Kind, data: bytes, media: str) -> str:
        ref = self.ref(call_id, kind)
        wrapped, blobs = self.crypto.seal(uid, call_id, kind, data)
        total = len(blobs)
        for start in range(0, total, WRITE_GROUP):
            ops = [
                Set(self._chunk(uid, ref, n), {"blob": blobs[n], "n": n, "of": total})
                for n in range(start, min(total, start + WRITE_GROUP))
            ]
            await self.docs.write(ops)
        head = {
            "wrapped": wrapped,
            "count": total,
            "size": len(data),
            "media": media,
            "kind": kind,
            "at": _utcnow().isoformat(),
        }
        await self.docs.write([Set(self._head(uid, ref), head)])
        return ref

    async def get(self, uid: str, ref: str) -> tuple[bytes, str]:
        call_id, kind = self._split(ref)
        head = await self.docs.get(self._head(uid, ref))
        if head is None:
            raise RecordRefused("gone", MSG_NOT_RECORDED)
        try:
            count, wrapped, media = int(head["count"]), str(head["wrapped"]), str(head["media"])
            dek = self.crypto.unwrap(uid, call_id, kind, wrapped)
            parts: list[bytes] = []
            for n in range(count):
                doc = await self.docs.get(self._chunk(uid, ref, n))
                blob = (doc or {}).get("blob")
                if not isinstance(blob, str):
                    raise RecordUnreadable()
                parts.append(self.crypto.open_chunk(dek, uid, call_id, kind, n, count, blob))
        except (KeyError, TypeError, ValueError, VaultError):
            log.error("a sealed call part does not open", extra={"kind": kind})
            raise RecordUnreadable() from None
        return b"".join(parts), media

    async def delete(self, uid: str, ref: str) -> None:
        """Header first (the wrapped key goes: nothing can be opened again), then the chunks.
        Safe to repeat."""
        head = await self.docs.get(self._head(uid, ref))
        count = int((head or {}).get("count", 0) or 0)
        await self.docs.write([Delete(self._head(uid, ref))])
        paths = [self._chunk(uid, ref, n) for n in range(count)]
        for start in range(0, len(paths), 200):
            await self.docs.write([Delete(p) for p in paths[start : start + 200]])


# ---- the keeper -------------------------------------------------------------------------------
class RecordKeeper:
    def __init__(
        self,
        store: CallStore,
        blobs: SealedBlobs,
        *,
        audit: AuditTrail | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.store, self.blobs, self.audit, self._clock = store, blobs, audit, clock

    async def record(self, uid: str, call_id: str) -> CallRecord:
        rec = await self.store.get_record(uid, call_id)
        if rec is None:
            raise RecordRefused("not_found", MSG_NO_RECORD)
        return rec

    async def _step(self, call_id: str, outcome: str, detail: str) -> None:
        await audit_step(
            self.audit, RECORD_TOOL, outcome, {"call": call_id}, detail, ActionRisk.REVERSIBLE
        )

    async def _put(self, uid: str, rec: CallRecord, **changes: Any) -> CallRecord:
        new = rec.model_copy(update=changes)
        await self.store.put_record(uid, new)
        return new

    async def save_audio(self, uid: str, call_id: str, data: bytes, media: str) -> CallRecord:
        rec = await self.record(uid, call_id)
        if rec.objected:
            raise RecordRefused("objected", MSG_OBJECTED)
        settings = await self.store.settings(uid)
        if not rec.recorded or not settings.record_audio:
            raise RecordRefused("not_recorded", MSG_NOT_RECORDED)
        if media not in AUDIO_TYPES:
            raise RecordRefused("type", MSG_TYPE)
        if not data or len(data) > MAX_AUDIO_BYTES:
            raise RecordRefused("too_big", MSG_TOO_BIG)
        ref = await self.blobs.put(uid, call_id, "audio", data, media)
        await self._step(call_id, "audio_kept", f"{len(data)} bytes, sealed")
        return await self._put(uid, rec, audio_ref=ref)

    async def _save_json(self, uid: str, call_id: str, kind: Kind, body: BaseModel) -> str:
        raw = body.model_dump_json().encode("utf-8")
        if len(raw) > MAX_TEXT_BYTES:
            raise RecordRefused("too_big", MSG_TOO_BIG)
        ref = await self.blobs.put(uid, call_id, kind, raw, JSON_TYPE)
        await self._step(call_id, f"{kind}_kept", "sealed")
        return ref

    async def save_transcript(self, uid: str, call_id: str, transcript: Transcript) -> CallRecord:
        rec = await self.record(uid, call_id)
        if rec.objected:
            raise RecordRefused("objected", MSG_OBJECTED)
        ref = await self._save_json(uid, call_id, "transcript", transcript)
        return await self._put(uid, rec, transcript_ref=ref)

    async def save_summary(self, uid: str, call_id: str, summary: CallSummary) -> CallRecord:
        rec = await self.record(uid, call_id)
        ref = await self._save_json(uid, call_id, "summary", summary)
        return await self._put(uid, rec, summary_ref=ref)

    async def objected(self, uid: str, call_id: str) -> CallRecord:
        """The other person asked not to be recorded: what was recorded (audio and transcript)
        is deleted now and nothing more is kept for this call; the summary's notes stay."""
        rec = await self.record(uid, call_id)
        for ref in (rec.audio_ref, rec.transcript_ref):
            if ref:
                await self.blobs.delete(uid, ref)
        await self._step(call_id, "objection", "recording stopped; audio and transcript deleted")
        return await self._put(
            uid, rec, recorded=False, objected=True, audio_ref=None, transcript_ref=None
        )

    async def delete(self, uid: str, call_id: str, *, why: str = "owner") -> bool:
        """Every sealed part, then the record. False when there was no such record."""
        rec = await self.store.get_record(uid, call_id)
        if rec is None:
            return False
        for ref in (rec.audio_ref, rec.transcript_ref, rec.summary_ref):
            if ref:
                await self.blobs.delete(uid, ref)
        gone = await self.store.delete_record(uid, call_id)
        await self._step(call_id, "deleted", f"by {why}")
        return gone

    async def keep(self, uid: str, call_id: str, keep: bool) -> CallRecord:
        rec = await self.store.set_keep(uid, call_id, keep)
        if rec is None:
            raise RecordRefused("not_found", MSG_NO_RECORD)
        await self._step(call_id, "kept" if keep else "unkept", "past retention" if keep else "")
        return rec

    async def audio(self, uid: str, call_id: str) -> tuple[bytes, str]:
        rec = await self.record(uid, call_id)
        if not rec.audio_ref:
            raise RecordRefused("not_recorded", MSG_OBJECTED if rec.objected else MSG_NOT_RECORDED)
        await self._step(call_id, "audio_read", "")
        return await self.blobs.get(uid, rec.audio_ref)

    async def _json(self, uid: str, ref: str | None, model: type[BaseModel]) -> Any:
        if not ref:
            return None
        raw, _ = await self.blobs.get(uid, ref)
        try:
            return model.model_validate(json.loads(raw.decode("utf-8")))
        except (ValueError, UnicodeDecodeError, ValidationError):
            raise RecordUnreadable() from None

    async def transcript(self, uid: str, call_id: str) -> Transcript | None:
        rec = await self.record(uid, call_id)
        found: Transcript | None = await self._json(uid, rec.transcript_ref, Transcript)
        return found

    async def summary(self, uid: str, call_id: str) -> CallSummary | None:
        rec = await self.record(uid, call_id)
        found: CallSummary | None = await self._json(uid, rec.summary_ref, CallSummary)
        return found


__all__ = [
    "AUDIO_TYPES",
    "KINDS",
    "MAX_AUDIO_BYTES",
    "CallMessage",
    "CallSummary",
    "RecordKeeper",
    "RecordRefused",
    "RecordUnreadable",
    "SealedBlobs",
    "Transcript",
    "TranscriptLine",
]

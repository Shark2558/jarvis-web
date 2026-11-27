# tests/test_calls_records.py — R18 A1: call records sealed in the vault (calls.records): audio,
# transcript and summary; Keep / Delete; the "stop recording on objection" path; the 30-day
# retention job (calls.retention); nothing stored in clear.
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from jarvis.calls.models import CallRecord, Speaker
from jarvis.calls.records import (
    CallSummary,
    RecordKeeper,
    RecordRefused,
    RecordUnreadable,
    SealedBlobs,
    Transcript,
    TranscriptLine,
)
from jarvis.calls.retention import CallRetentionJob
from jarvis.calls.store import MemoryCallStore
from jarvis.keyring import Keyring
from jarvis.tools.audit import AuditLog
from jarvis.vault.crypto import CHUNK_BYTES, VaultCrypto

UID = "u_0123456789abcdef"
AT = datetime(2026, 11, 27, 5, 0, tzinfo=UTC)
AUDIO = b"OggS" + bytes(range(256)) * 9000  # a little over 2 MB: more than one chunk
WORDS = "naale pathu manikku varaam"


def _keeper(now: datetime = AT) -> tuple[RecordKeeper, MemoryCallStore, AuditLog]:
    store, audit = MemoryCallStore(), AuditLog()
    blobs = SealedBlobs(store.docs, VaultCrypto(Keyring(bytes(range(32)))), prefix="test_")
    return RecordKeeper(store, blobs, audit=audit, clock=lambda: now), store, audit


async def _record(store: MemoryCallStore, **kw: object) -> CallRecord:
    rec = CallRecord(number_e164="+919000000001", started_at=AT, **kw)  # type: ignore[arg-type]
    await store.put_record(UID, rec)
    return rec


def _transcript() -> Transcript:
    return Transcript(
        lines=(
            TranscriptLine(who=Speaker.JARVIS, lang="en-IN", text="Hello, this is JARVIS."),
            TranscriptLine(who=Speaker.THEM, lang="ml-IN", text=WORDS, english="Tomorrow at ten"),
        )
    )


def _summary() -> CallSummary:
    return CallSummary(english="Pickup booked for tomorrow at 10:00.", cost_inr=0.42)


async def test_audio_transcript_and_summary_round_trip_sealed() -> None:
    keeper, store, audit = _keeper()
    rec = await _record(store)
    await keeper.save_audio(UID, rec.id, AUDIO, "audio/ogg")
    await keeper.save_transcript(UID, rec.id, _transcript())
    after = await keeper.save_summary(UID, rec.id, _summary())
    assert after.audio_ref and after.transcript_ref and after.summary_ref
    assert await keeper.audio(UID, rec.id) == (AUDIO, "audio/ogg")
    assert await keeper.transcript(UID, rec.id) == _transcript()
    assert await keeper.summary(UID, rec.id) == _summary()
    raw = json.dumps(store.docs._data)  # noqa: SLF001 - the test reads the raw documents
    assert WORDS not in raw and "Pickup booked" not in raw and "9000000001" not in raw
    assert len(AUDIO) > CHUNK_BYTES
    outcomes = [e.outcome for e in (await audit.tail(10)).entries]
    assert {"audio_kept", "transcript_kept", "summary_kept", "audio_read"} <= set(outcomes)


async def test_a_part_moved_to_another_call_does_not_open() -> None:
    keeper, store, _ = _keeper()
    one, two = await _record(store), await _record(store)
    await keeper.save_audio(UID, one.id, AUDIO, "audio/ogg")
    await keeper.save_audio(UID, two.id, b"OggS-two", "audio/ogg")
    data = store.docs._data  # noqa: SLF001
    head_one = next(k for k in data if k.endswith(f"/sealed/{one.id}_audio"))
    head_two = next(k for k in data if k.endswith(f"/sealed/{two.id}_audio"))
    data[head_two] = dict(data[head_one])  # someone copies call one's key over call two's
    with pytest.raises(RecordUnreadable):
        await keeper.audio(UID, two.id)


async def test_an_objection_deletes_the_recording_and_keeps_none_after() -> None:
    keeper, store, audit = _keeper()
    rec = await _record(store)
    await keeper.save_audio(UID, rec.id, AUDIO, "audio/ogg")
    await keeper.save_transcript(UID, rec.id, _transcript())
    after = await keeper.objected(UID, rec.id)
    assert after.objected and not after.recorded
    assert after.audio_ref is None and after.transcript_ref is None
    assert not any("_audio" in k or "_transcript" in k for k in store.docs._data)  # noqa: SLF001
    with pytest.raises(RecordRefused) as err:
        await keeper.save_audio(UID, rec.id, AUDIO, "audio/ogg")
    assert err.value.code == "objected"
    with pytest.raises(RecordRefused):
        await keeper.save_transcript(UID, rec.id, _transcript())
    await keeper.save_summary(UID, rec.id, _summary())  # notes for the summary stay
    with pytest.raises(RecordRefused) as gone:
        await keeper.audio(UID, rec.id)
    assert "asked not to be recorded" in gone.value.words
    assert "objection" in [e.outcome for e in (await audit.tail(10)).entries]


async def test_audio_is_not_kept_when_recording_is_off() -> None:
    keeper, store, _ = _keeper()
    await store.save_settings(UID, {"record_audio": False})
    rec = await _record(store)
    with pytest.raises(RecordRefused):
        await keeper.save_audio(UID, rec.id, AUDIO, "audio/ogg")


@pytest.mark.parametrize(("data", "media"), [(b"x", "video/mp4"), (b"", "audio/ogg")])
async def test_only_sound_files_of_a_sane_size(data: bytes, media: str) -> None:
    keeper, store, _ = _keeper()
    rec = await _record(store)
    with pytest.raises(RecordRefused):
        await keeper.save_audio(UID, rec.id, data, media)


async def test_delete_removes_every_sealed_part_and_the_record() -> None:
    keeper, store, audit = _keeper()
    rec = await _record(store)
    await keeper.save_audio(UID, rec.id, AUDIO, "audio/ogg")
    await keeper.save_summary(UID, rec.id, _summary())
    assert await keeper.delete(UID, rec.id)
    assert await store.get_record(UID, rec.id) is None
    assert not any("/sealed" in k for k in store.docs._data)  # noqa: SLF001
    assert not await keeper.delete(UID, rec.id)
    assert "deleted" in [e.outcome for e in (await audit.tail(10)).entries]


async def test_keep_pins_a_call_and_unknown_calls_are_refused() -> None:
    keeper, store, _ = _keeper()
    rec = await _record(store)
    assert (await keeper.keep(UID, rec.id, True)).keep
    with pytest.raises(RecordRefused):
        await keeper.keep(UID, "call_ffffffffffff", True)
    with pytest.raises(RecordRefused):
        await keeper.audio(UID, "call_ffffffffffff")


async def test_retention_deletes_old_calls_but_not_kept_ones() -> None:
    now = AT + timedelta(days=31)
    keeper, store, _ = _keeper(now)
    old = await _record(store)
    kept = await _record(store, keep=True)
    fresh = CallRecord(number_e164="+919000000001", started_at=now - timedelta(days=2))
    await store.put_record(UID, fresh)
    await keeper.save_audio(UID, old.id, AUDIO, "audio/ogg")
    job = CallRetentionJob(store, keeper, clock=lambda: now)
    assert await job.run([UID]) == {"deleted": 1, "failed": 0}
    assert await store.get_record(UID, old.id) is None
    assert await store.get_record(UID, kept.id) is not None
    assert await store.get_record(UID, fresh.id) is not None


async def test_retention_follows_a_lowered_setting() -> None:
    now = AT + timedelta(days=10)
    keeper, store, _ = _keeper(now)
    rec = await _record(store)  # stored with 30 days
    await store.save_settings(UID, {"retention_days": 7})
    job = CallRetentionJob(store, keeper, clock=lambda: now)
    assert (await job.run([UID]))["deleted"] == 1
    assert await store.get_record(UID, rec.id) is None


async def test_retention_counts_an_owner_it_could_not_serve() -> None:
    keeper, store, _ = _keeper()
    job = CallRetentionJob(store, keeper)
    assert await job.run(["not/an/owner", UID]) == {"deleted": 0, "failed": 1}
    assert job.name == "calls_retention" and 0 < job.budget_s <= 60

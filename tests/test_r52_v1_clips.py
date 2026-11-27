# tests/test_r52_v1_clips.py -- R5.2 V1 (plan D4): the session's recordings stay on the laptop,
# encrypted at rest with a key only the kit holds. Nothing readable on disk, a moved or damaged file
# does not open, the key file is the owner's only, caps hold, delete removes the files, and
# deleting everything replaces the key so a copy left behind can't be read.
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from kit_fakes import pcm

from jarvis.localspeech import protocol as p
from jarvis.localspeech.clips import MAX_CLIPS_PER_SESSION, ClipVault
from jarvis.localspeech.clips import MAX_SESSIONS as MAX_S

A = "vs_aaaaaaaaaaaa"
B = "vs_bbbbbbbbbbbb"


def vault(tmp: Path) -> ClipVault:
    return ClipVault(tmp / "clips", tmp / "clips.secret")


def clip(session: str, prompt: str, audio: bytes, **kw: object) -> p.ClipIn:
    return p.ClipIn(
        session_id=session,
        prompt_id=prompt,
        audio=p.encode_pcm(audio),
        kind=kw.get("kind", p.PromptKind.NUMBERS),  # type: ignore[arg-type]
        held_out=bool(kw.get("held_out", False)),
    )


def test_a_clip_is_stored_encrypted_and_read_back(tmp_path: Path) -> None:
    v = vault(tmp_path)
    audio = pcm(1.5, 1234)
    stored = v.put(clip(A, "num_1", audio, held_out=True))
    assert (stored.clips, stored.seconds) == (1, 1.5)
    on_disk = (tmp_path / "clips" / A / "num_1.clip").read_bytes()
    assert audio[:64] not in on_disk and b"numbers" not in on_disk and b"held_out" not in on_disk
    (back,) = v.clips(A)
    assert (back.pcm, back.kind, back.held_out, back.prompt_id) == (
        audio,
        p.PromptKind.NUMBERS,
        True,
        "num_1",
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_the_key_and_folders_are_the_owners_only(tmp_path: Path) -> None:
    v = vault(tmp_path)
    v.put(clip(A, "num_1", pcm()))
    assert (tmp_path / "clips.secret").stat().st_mode & 0o777 == 0o600
    assert len((tmp_path / "clips.secret").read_bytes()) == 32
    assert (tmp_path / "clips").stat().st_mode & 0o777 == 0o700
    assert (tmp_path / "clips" / A / "num_1.clip").stat().st_mode & 0o777 == 0o600


def test_a_moved_or_damaged_file_does_not_open(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    v = vault(tmp_path)
    v.put(clip(A, "num_1", pcm(1.0, 1)))
    v.put(clip(A, "num_2", pcm(1.0, 2)))
    folder = tmp_path / "clips" / A
    shutil.copy(folder / "num_1.clip", folder / "num_9.clip")  # renamed: bound to its name
    damaged = bytearray((folder / "num_2.clip").read_bytes())
    damaged[-1] ^= 1
    (folder / "num_2.clip").write_bytes(bytes(damaged))
    assert [c.prompt_id for c in v.clips(A)] == ["num_1"]
    assert "could not be opened" in caplog.text


def test_a_new_vault_on_the_same_folder_reads_with_the_kept_key(tmp_path: Path) -> None:
    vault(tmp_path).put(clip(A, "num_1", pcm(1.0, 3)))
    assert vault(tmp_path).clips(A)[0].pcm == pcm(1.0, 3)


def test_deleting_one_session_keeps_the_others_and_the_key(tmp_path: Path) -> None:
    v = vault(tmp_path)
    v.put(clip(A, "num_1", pcm()))
    v.put(clip(A, "num_2", pcm()))
    v.put(clip(B, "num_1", pcm()))
    key = (tmp_path / "clips.secret").read_bytes()
    assert v.delete(A) == 2 and v.sessions() == [B]
    assert (tmp_path / "clips.secret").read_bytes() == key and len(v.clips(B)) == 1


def test_deleting_everything_replaces_the_key(tmp_path: Path) -> None:
    v = vault(tmp_path)
    v.put(clip(A, "num_1", pcm(1.0, 8)))
    leftover = (tmp_path / "clips" / A / "num_1.clip").read_bytes()  # e.g. a backup copy
    old_key = (tmp_path / "clips.secret").read_bytes()
    assert v.delete(None) == 1 and v.sessions() == []
    assert (tmp_path / "clips.secret").read_bytes() != old_key
    (tmp_path / "clips" / A).mkdir(parents=True)
    (tmp_path / "clips" / A / "num_1.clip").write_bytes(leftover)
    assert v.clips(A) == []  # the old copy no longer opens


def test_what_the_engines_heard_is_kept_encrypted_too(tmp_path: Path) -> None:
    v = vault(tmp_path)
    v.put(clip(A, "num_1", pcm()))
    rows = (p.HeardRow(prompt_id="num_1", slot=p.EngineSlot.WHISPER_SMALL, text="four four two"),)
    v.put_heard(A, rows)
    assert b"four four two" not in (tmp_path / "clips" / A / "_heard.bin").read_bytes()
    assert v.heard(A).rows == rows
    assert v.heard(B).rows == ()
    v.delete(A)
    v.put_heard(A, rows)  # a scoring run that ends after the delete keeps nothing
    assert not (tmp_path / "clips" / A).exists()


def test_the_caps_hold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    v = vault(tmp_path)
    monkeypatch.setattr("jarvis.localspeech.clips.MAX_CLIPS_PER_SESSION", 2)
    monkeypatch.setattr("jarvis.localspeech.clips.MAX_SESSIONS", 1)
    v.put(clip(A, "num_1", pcm()))
    v.put(clip(A, "num_2", pcm()))
    v.put(clip(A, "num_2", pcm(1.0, 4)))  # a redo replaces, never counts twice
    assert v.count(A) == 2
    for refused in (clip(A, "num_3", pcm()), clip(B, "num_1", pcm())):
        with pytest.raises(p.KitRefused) as err:
            v.put(refused)
        assert err.value.code == "too_large"
    assert MAX_CLIPS_PER_SESSION >= 120 + 30 and MAX_S >= 1


def test_a_bad_session_id_never_touches_the_disk(tmp_path: Path) -> None:
    v = vault(tmp_path)
    for bad in ("../escape", "vs_ZZZ", "vs_aaaaaaaaaaaa/.."):
        with pytest.raises(p.KitRefused):
            v.count(bad)
        with pytest.raises(p.KitRefused):
            v.delete(bad)
    assert not (tmp_path / "clips").exists()

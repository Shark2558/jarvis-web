# tests/test_r52_v1_selftest.py -- R5.2 V1 (plan 5 "Laptop kit"): the self-test the owner pastes.
# It checks the pinned models, the recordings' encryption, MP3, a round trip against the plan's
# bars and the gate; its report never holds the key, a folder (it would show the Windows user
# name), the Tailscale name or anything but the fixed test sentence. In-process kit, fake gate.
from __future__ import annotations

import hashlib
import io
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

import pytest
from kit_fakes import KEY, FakeMp3, make_service

from jarvis.localspeech import selftest as st
from jarvis.localspeech.clips import ClipVault
from jarvis.localspeech.manager import Manifest, ModelEntry, ModelFile, ModelManager
from jarvis.localspeech.protocol import EngineSlot, KitUnavailable, SttRequest, SttResult


def gate(statuses: dict[tuple[str, bool | None], int | None]) -> st.Probe:
    async def probe(path: str, key: str | None) -> int | None:
        kind = None if key is None else key == KEY
        return statuses.get((path, kind))

    return probe


GOOD_GATE = gate(
    {
        ("/v1/health", None): 401,
        ("/v1/health", False): 401,
        ("/v1/nothing-here", True): 404,
        ("/v1/health", True): 200,
    }
)


def empty_manager(tmp: Path) -> ModelManager:
    return ModelManager(
        Manifest(manifest=1, kit_version="1.0.0"), tmp / "models", tmp / "installed.json"
    )


def test_word_error_on_the_test_sentence() -> None:
    assert st.word_error(st.TEST_SENTENCE, "hello this is jarvis 1 2 3 4 5") == 0.0
    assert st.word_error(
        st.TEST_SENTENCE, "hello this is travis one two three four five"
    ) == pytest.approx(1 / 9)
    assert st.word_error(st.TEST_SENTENCE, "") == 1.0
    assert st.word_error("", "") == 0.0


async def test_a_healthy_kit_passes_and_the_report_is_safe_to_paste(tmp_path: Path) -> None:
    service, engines = make_service(tmp_path, mp3=FakeMp3())
    engines.heard.clear()
    real_stt = service.stt

    async def hears_the_sentence(req: SttRequest) -> SttResult:
        result = await real_stt(req)
        return result.model_copy(update={"text": "Hello, this is Jarvis. 1, 2, 3, 4, 5."})

    service.stt = hears_the_sentence  # type: ignore[method-assign]
    report = await st.run(
        service,
        manager=empty_manager(tmp_path),
        vault=ClipVault(tmp_path / "v", tmp_path / "v.secret"),
        key=KEY,
        mp3=FakeMp3(),
        probe=GOOD_GATE,
    )
    by_name = {c.name: c for c in report.checks}
    assert by_name["models"].ok is None  # this kit pins none yet: said, not failed
    for name in ("recordings", "MP3", "kit", "voice", "listening", "gate"):
        assert by_name[name].ok, by_name[name]
    text = report.text()
    assert "word error 0%" in text and "Paste everything" in text and "FAIL" not in text
    for leak in (KEY, str(tmp_path), "ts.net", "Users"):
        assert leak not in text
    assert '"ok": true' in st.report_json(report)
    await service.close()


async def test_a_kit_without_english_engines_skips_the_round_trip(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path, ready=frozenset())
    checks = await st.check_round_trip(service)
    assert [c.name for c in checks] == ["kit", "round trip"] and checks[1].ok is None
    assert "ready: none" in checks[0].words


async def test_the_gate_check_fails_when_it_lets_anything_through(tmp_path: Path) -> None:
    open_gate = gate({("/v1/health", None): 200, ("/v1/health", True): 200})
    (check,) = await st.check_gate(KEY, open_gate)
    assert check.ok is False and "no key: 200" in check.words
    (down,) = await st.check_gate(KEY, gate({}))
    assert down.ok is False and "not answering" in down.words
    (none,) = await st.check_gate(None, GOOD_GATE)
    assert none.ok is None


def test_mp3_check_needs_real_mp3_bytes() -> None:
    class NotMp3:
        def encode(self, pcm: bytes, sample_rate: int) -> bytes:
            return b"RIFF...."

    class Broken:
        def encode(self, pcm: bytes, sample_rate: int) -> bytes:
            raise RuntimeError("no lame")

    pytest.importorskip("numpy")
    assert st.check_mp3(FakeMp3()).ok
    assert st.check_mp3(NotMp3()).ok is False
    assert "RuntimeError" in st.check_mp3(Broken()).words
    assert st.check_mp3(None).ok is False


def test_the_vault_check_leaves_nothing_behind(tmp_path: Path) -> None:
    pytest.importorskip("numpy")
    vault = ClipVault(tmp_path / "clips", tmp_path / "clips.secret")
    check = st.check_vault(vault)
    assert check.ok and vault.sessions() == []


def test_the_model_check_rehashes_each_pinned_model(tmp_path: Path) -> None:
    data = b"weights" * 10
    f = ModelFile(
        name="model.bin",
        url="https://huggingface.co/x/y/resolve/0123456/model.bin",
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
    )
    entry = ModelEntry(
        slot=EngineSlot.WHISPER_SMALL,
        model="small-int8",
        source="https://huggingface.co/x/y",
        revision="0123456",
        licence="MIT",
        files=(f,),
    )

    @contextmanager
    def web(url: str) -> Iterator[IO[bytes]]:
        yield io.BytesIO(data)

    m = ModelManager(
        Manifest(manifest=1, kit_version="1.0.0", models=(entry,)),
        tmp_path / "m",
        tmp_path / "i.json",
        opener=web,
    )
    assert st.check_models(m)[0].ok is False  # not installed yet
    m.install(EngineSlot.WHISPER_SMALL)
    (ok,) = st.check_models(m)
    assert ok.ok and "MIT, hashes OK" in ok.words


async def test_the_gate_calls_say_offline_when_nothing_listens() -> None:
    calls = st.GateCalls(KEY, base="http://127.0.0.1:9/v1")
    with pytest.raises(KitUnavailable):
        await calls.health()
    assert KEY not in repr(calls)

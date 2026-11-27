# tests/test_r52_v4_streaming.py -- R5.2 V4 (row 83): the console's "Hey Jarvis" pipeline in Python
# (jarvis.localspeech.wakeword.streaming) on deterministic fake models: the same seed noise as the
# browser, the same buffers, warm-up, reset after a wake, the 2-frame rule, and the verifier after
# today's score.
from __future__ import annotations

import json
import random
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from jarvis.localspeech.wakeword import fakes, formats  # noqa: E402
from jarvis.localspeech.wakeword.formats import VerifierFile  # noqa: E402
from jarvis.localspeech.wakeword.streaming import (  # noqa: E402
    INIT_NOISE_SEED,
    Stream,
    frames,
    listen,
    mulberry32,
    pad,
    rescorer,
    scan,
)

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = json.loads((ROOT / "tests/fixtures/wakeword/reference_scores.json").read_text())


@pytest.fixture(scope="module")
def stream() -> Stream:
    return Stream(fakes.tone_models())


def test_seed_noise_is_the_browsers_mulberry32() -> None:
    js = (ROOT / "src/jarvis/api/static/console-wakeword.js").read_text(encoding="utf-8")
    seed = re.search(r"const INIT_NOISE_SEED = (0x[0-9a-f]+);", js)
    assert seed and int(seed.group(1), 16) == INIT_NOISE_SEED == REFERENCE["init_noise"]["seed"]
    head = np.floor(mulberry32(INIT_NOISE_SEED, 8) * 2000) - 1000
    assert head.astype(int).tolist() == REFERENCE["init_noise"]["head"]


def test_frames_are_whole_1280_sample_steps_from_an_offset() -> None:
    pcm = fakes.silence(0.25)  # 4000 samples: 3 whole frames
    assert [f.shape[0] for f in frames(pcm)] == [1280, 1280, 1280]
    assert len(list(frames(pcm, offset=1000))) == 2
    assert len(pad(b"")) == 2 * 2 * 16_000


def test_a_stream_gives_16_by_96_windows_and_warms_up(stream: Stream) -> None:
    rows = scan(stream, pad(fakes.tone(fakes.OWNER_HZ, 0.9)))
    assert all(w.shape == (formats.FRAMES, formats.DIM) for _, w in rows)
    assert [s for s, _ in rows[: formats.WARMUP]] == [0.0] * formats.WARMUP
    assert max(s for s, _ in rows) > 0.9  # the fake detector fires on a loud phrase
    again = scan(stream, pad(fakes.tone(fakes.OWNER_HZ, 0.9)))
    assert [s for s, _ in again] == [s for s, _ in rows]  # scan starts from fresh buffers


def test_listen_wakes_once_per_phrase_and_never_on_quiet(stream: Stream) -> None:
    phrase = fakes.tone(fakes.OWNER_HZ, 0.9)
    assert listen(stream, pad(phrase)) == 1
    assert listen(stream, pad(fakes.silence(3))) == 0
    assert listen(stream, pad(fakes.bursts(fakes.OWNER_HZ, 6))) == 0
    apart = phrase + fakes.silence(2.5) + phrase
    assert listen(stream, pad(apart)) == 2  # reset after the first wake, the cooldown over


def test_a_higher_threshold_wakes_less(stream: Stream) -> None:
    soft = fakes.tone(fakes.OWNER_HZ, 0.9, amplitude=4500)
    assert listen(stream, pad(soft)) == 1
    assert listen(stream, pad(soft), threshold=0.99) == 0


def test_the_verifier_runs_after_todays_score_and_can_veto(stream: Stream) -> None:
    phrase = pad(fakes.tone(fakes.OWNER_HZ, 0.9))
    veto = VerifierFile(
        embedding_sha256="a" * 64,
        weights=tuple([0.0] * formats.FEATURES),
        bias=-20.0,
        trained_at=datetime.now(UTC),
        clips=10,
    )
    assert listen(stream, phrase) == 1
    assert listen(stream, phrase, verifier=veto) == 0
    allow = veto.model_copy(update={"bias": 20.0})
    assert listen(stream, phrase, verifier=allow) == 1


def test_the_fast_rescorer_equals_the_files_own_rule() -> None:
    rng = random.Random(4)
    v = VerifierFile(
        embedding_sha256="a" * 64,
        weights=tuple(rng.uniform(-0.01, 0.01) for _ in range(formats.FEATURES)),
        bias=0.3,
        trained_at=datetime.now(UTC),
        clips=10,
    )
    fast = rescorer(v)
    for base in (0.05, 0.1, 0.7):
        window = np.array([rng.uniform(-3, 3) for _ in range(formats.FEATURES)], dtype=np.float32)
        expected = v.score(base, window.astype(np.float64).tolist())
        assert fast(base, window.reshape(16, 96)) == pytest.approx(expected, abs=1e-12)

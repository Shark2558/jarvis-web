# tests/test_r52_v4_formats.py -- R5.2 V4 (row 83): the wake word's two files, their licence record,
# the console detector's numbers (equal to static/console-wakeword.js) and the evals' rules (equal
# to the plan's bars in jarvis.voice.profile.BARS). Pure: no NumPy, no model.
from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jarvis.localspeech.protocol import OWNER_LICENCE
from jarvis.localspeech.wakeword import evals, formats
from jarvis.localspeech.wakeword.evals import Decider, WakeEval, beats, passes, verifier_passes
from jarvis.localspeech.wakeword.formats import DataSource, ModelCard, VerifierFile
from jarvis.voice.profile import BARS

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/jarvis/api/static"
NOW = datetime(2026, 11, 27, 10, 0, tzinfo=UTC)
SHA = "a" * 64


def _verifier(**over: object) -> VerifierFile:
    fields: dict[str, object] = {
        "embedding_sha256": SHA,
        "weights": tuple([0.0] * formats.FEATURES),
        "bias": 0.0,
        "trained_at": NOW,
        "clips": 12,
    }
    return VerifierFile.model_validate(fields | over)


# ---- the console's numbers ---------------------------------------------------------------------
def _js_const(name: str) -> str:
    js = (STATIC / "console-wakeword.js").read_text(encoding="utf-8")
    found = re.search(rf"const {name} = ([^;]+);", js)
    assert found, name
    return found.group(1).split("//")[0].strip()


def test_the_detectors_numbers_are_the_consoles() -> None:
    assert float(_js_const("DEFAULT_THRESHOLD")) == formats.THRESHOLD
    assert int(_js_const("PATIENCE_FRAMES")) == formats.PATIENCE
    assert int(_js_const("COOLDOWN_MS")) == formats.COOLDOWN_FRAMES * formats.FRAME_MS
    assert int(_js_const("WARMUP_FRAMES")) == formats.WARMUP
    assert int(_js_const("EMB_FRAMES")) == formats.FRAMES
    assert int(_js_const("EMB_DIM")) == formats.DIM
    assert int(_js_const("FRAME")) == formats.FRAME_SAMPLES
    assert _js_const("WAKE_MODEL") == f"'{formats.CURRENT_MODEL}'"


def test_the_wake_bars_are_the_plans() -> None:
    bars = evals.WAKE_BARS
    assert bars.false_wakes_per_hour_max == BARS.false_wakes_per_hour_max
    assert bars.wake_miss_max == BARS.wake_miss_max
    assert bars.other_speaker_reject_min == BARS.other_speaker_reject_min
    assert bars.tv_audio_hours == BARS.tv_audio_hours


# ---- stage 1: the verifier's file --------------------------------------------------------------
def test_verifier_below_the_gate_leaves_the_score_and_above_gives_its_probability() -> None:
    weights = [0.0] * formats.FEATURES
    weights[0], weights[1] = 2.0, -1.0
    v = _verifier(weights=tuple(weights), bias=0.5)
    window = [0.0] * formats.FEATURES
    window[0], window[1] = 1.0, 3.0
    assert v.score(0.05, window) == 0.05  # below VERIFIER_GATE: today's score stands
    assert v.score(0.9, window) == pytest.approx(1 / (1 + math.exp(0.5)))  # z = 0.5 + 2 - 3
    with pytest.raises(ValueError, match="16 x 96"):
        v.score(0.9, [0.0] * 10)


def test_verifier_file_round_trips_and_is_owned_json() -> None:
    v = _verifier(evals={"miss_rate": 0.0})
    data = v.to_bytes()
    assert data.startswith(b"{") and b'"licence":"LicenseRef-Owner"' in data
    assert VerifierFile.parse(data) == v
    assert v.licence == OWNER_LICENCE and v.format == "jarvis-wake-verifier"


@pytest.mark.parametrize(
    "over",
    [
        {"weights": (0.0,) * 10},
        {"weights": (math.nan,) * formats.FEATURES},
        {"bias": math.inf},
        {"licence": "CC-BY-NC-SA-4.0"},
        {"frames": 17},
        {"embedding_sha256": "not-a-hash"},
        {"gate": 1.0},
        {"clips": 0},
    ],
)
def test_verifier_file_refuses_what_the_console_should_never_run(over: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _verifier(**over)


def test_verifier_parse_refuses_big_or_foreign_files_in_fixed_words() -> None:
    with pytest.raises(ValueError, match="too large"):
        VerifierFile.parse(b" " * (formats.VERIFIER_MAX_BYTES + 1))
    with pytest.raises(ValueError, match="not a JARVIS wake-word verifier file") as info:
        VerifierFile.parse(b'{"format": "secret words"}')
    assert "secret" not in str(info.value)


# ---- stage 2: the MANIFEST and its licences ----------------------------------------------------
def _card(**over: object) -> ModelCard:
    fields: dict[str, object] = {
        "sha256": SHA,
        "size": 1234,
        "trained_at": NOW,
        "feature_models": {formats.MEL_MODEL: "b" * 64, formats.EMBEDDING_MODEL: "c" * 64},
        "sources": (
            DataSource(name="his recordings", licence=OWNER_LICENCE, detail="25 clips"),
            DataSource(name="voice kokoro-bm_george", licence="Apache-2.0"),
        ),
        "evals": {"miss_rate": 0.02, "false_wakes_per_hour": 0.1},
        "current_evals": {"miss_rate": 0.04},
        "beats_current": True,
    }
    return ModelCard.model_validate(fields | over)


def test_manifest_records_licence_reads_data_evals_and_its_hash() -> None:
    text = _card().text()
    assert "licence:   LicenseRef-Owner" in text
    assert f"bbbbbbbb{'b' * 56} {formats.MEL_MODEL}" in text
    assert "CC-BY-NC-SA-4.0" in text  # what it reads, recorded honestly
    assert "voice kokoro-bm_george [Apache-2.0]" in text
    assert "beats:     yes" in text and "miss_rate 0.02" in text
    assert formats.manifest_sha256(text) == SHA
    assert text.splitlines()[-1] == f"sha256 {SHA} 1234 {formats.OWNED_FILE}"


@pytest.mark.parametrize("licence", ["CC-BY-NC-SA-4.0", "CC-BY-SA-4.0", "GPL-3.0", "unknown"])
def test_training_audio_of_an_unclear_licence_is_left_out(licence: str) -> None:
    with pytest.raises(ValueError, match="left out"):
        DataSource(name="some set", licence=licence)


def test_manifest_sha_is_none_without_its_line() -> None:
    assert formats.manifest_sha256("no hash here\n") is None


def test_the_launch_record_names_both_licence_gaps() -> None:
    words = formats.LAUNCH_WORDS
    assert "non-commercial" in words and "before any launch" in words
    assert "feature models" in words
    assert formats.CURRENT_LICENCE == "CC-BY-NC-SA-4.0"
    licence = (STATIC / "wakeword/LICENSE.txt").read_text(encoding="utf-8")
    assert "CC BY-NC-SA 4.0" in licence  # the vendored record this mirrors


def test_compact_evals_keeps_finite_numbers_only_and_at_most_twelve() -> None:
    values = {f"k{i:02d}": float(i) for i in range(20)} | {"bad": math.nan}
    kept = formats.compact_evals(values)
    assert len(kept) == formats.EVALS_MAX and "bad" not in kept


# ---- the console's wake rule and the bars ------------------------------------------------------
def test_two_frames_wake_once_then_the_cooldown_holds() -> None:
    d = Decider()
    assert [d.feed(s) for s in (0.9, 0.2, 0.9)] == [False, False, False]  # one frame is not enough
    assert d.feed(0.9) is True  # the 2nd consecutive frame
    later = [d.feed(0.9) for _ in range(formats.COOLDOWN_FRAMES - 1)]
    assert not any(later)  # within 2 s
    assert d.feed(0.9) is True  # 25 frames after the first wake


def test_the_threshold_is_inclusive_as_in_the_console() -> None:
    d = Decider(threshold=0.5)
    assert [d.feed(0.5), d.feed(0.5)] == [False, True]


def test_miss_false_wake_and_other_speaker_rates() -> None:
    e = WakeEval(clips=20, misses=1, negative_seconds=7200, false_wakes=1, others=10)
    assert e.miss_rate == 0.05 and e.false_wakes_per_hour == 0.5 and e.other_reject == 1.0
    assert WakeEval().miss_rate is None and WakeEval().false_wakes_per_hour is None
    assert set(e.as_evals("x_", counts=False)) == {
        "x_miss_rate",
        "x_false_wakes_per_hour",
        "x_other_reject",
    }


def test_passes_needs_every_bar_that_applies() -> None:
    good = WakeEval(clips=20, misses=1, negative_seconds=7200, false_wakes=1)
    assert passes(good, needs_negatives=True)
    assert not passes(WakeEval(clips=20, misses=2), needs_negatives=False)
    assert not passes(
        WakeEval(clips=20, negative_seconds=7200, false_wakes=2), needs_negatives=True
    )
    assert not passes(WakeEval(clips=20), needs_negatives=True)  # false wakes not measured
    assert not passes(WakeEval(), needs_negatives=False)  # misses not measured
    others_bad = WakeEval(clips=20, others=10, others_accepted=2)
    assert not passes(others_bad, needs_negatives=False)


def test_the_verifier_is_used_only_when_other_speakers_were_measured() -> None:
    assert not verifier_passes(WakeEval(clips=10))
    assert verifier_passes(WakeEval(clips=10, others=10, others_accepted=1))
    assert not verifier_passes(WakeEval(clips=10, others=10, others_accepted=2))


def test_the_owned_model_beats_only_when_no_worse_and_passing() -> None:
    current = WakeEval(clips=20, misses=1, negative_seconds=7200, false_wakes=1)
    tie = WakeEval(clips=20, misses=1, negative_seconds=7200, false_wakes=1)
    better = WakeEval(clips=20, misses=0, negative_seconds=7200, false_wakes=0)
    worse = WakeEval(clips=20, misses=0, negative_seconds=7200, false_wakes=2)
    assert beats(tie, current)  # a tie goes to the owned model (its licence)
    assert beats(better, current)
    assert not beats(worse, current)  # fails the bar and is worse on false wakes
    quiet = WakeEval(clips=20, misses=1, negative_seconds=7200, false_wakes=0)
    trade = WakeEval(clips=20, misses=0, negative_seconds=7200, false_wakes=1)
    assert passes(trade, needs_negatives=True) and not beats(trade, quiet)  # worse on one measure

# evals/wakeword/run.py
"""R5.2 row 83 eval -- the owner's own "Hey Jarvis" (plan docs/plans/r5-2-voice.md section 5):

    python evals/wakeword/run.py --mock    # CI: fake models, synthetic tones, gates + controls
    python evals/wakeword/run.py --real [--hours 2] [--clips DIR]
                                           # the laptop kit: today's vendored models (onnxruntime)
                                           # on generated music and noise, and his held-out
                                           # "Hey Jarvis" WAV clips in DIR if given (never in the
                                           # repo); no onnxruntime: "skipped", exit 0

Mock suites (hard gates; each with a negative control that MUST fail it):
  stage1  the verifier trained on a synthetic session: his held-out clips missed <= 5 %, other
          speakers' "Hey Jarvis" rejected >= 90 %, so it is applied (beats_current). Control: a
          verifier that accepts everyone.
  stage2  the owned model on the same session: misses <= 5 % and false wakes <= 0.5 an hour on
          synthetic TV from voices it never trained on, no worse than today's model (so it is
          swapped in), and its file's MANIFEST names its hash. Control: an untrained network.
Bars: `jarvis.localspeech.wakeword.evals.WAKE_BARS` (= `jarvis.voice.profile.BARS`). Openly
licensed recordings are not fetched: none could be pinned with a SHA-256 (`synth.LEFT_OUT`).
"""

from __future__ import annotations

import argparse
import json
import sys
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent / "src"))

from jarvis.localspeech.protocol import WakeArtifact  # noqa: E402
from jarvis.localspeech.wakeword import formats  # noqa: E402
from jarvis.localspeech.wakeword.evals import WAKE_BARS, WakeEval, passes  # noqa: E402
from jarvis.localspeech.wakeword.port import WakeJob  # noqa: E402

NOW = datetime(2026, 11, 27, 10, 0, tzinfo=UTC)
SESSION = "vs_0123456789ab"


def _case(name: str, failures: list[str]) -> dict[str, Any]:
    return {"id": name, "passed": not failures, "failures": failures}


def _stage1(accept_everyone: bool = False) -> dict[str, Any]:
    from jarvis.localspeech.wakeword import fakes
    from jarvis.localspeech.wakeword.formats import VerifierFile
    from jarvis.localspeech.wakeword.port import split_wake
    from jarvis.localspeech.wakeword.streaming import Stream
    from jarvis.localspeech.wakeword.verifier_train import evaluate, other_clips, train_verifier

    job = WakeJob(
        artifact=WakeArtifact.VERIFIER, session_id=SESSION, clips=fakes.session_clips(30, 40)
    )
    stream = Stream(fakes.tone_models())
    trained = train_verifier(job, stream, "e" * 64, fakes.ToneVoices(), lambda f, w: None, now=NOW)
    verifier = VerifierFile.parse(trained.data)
    if accept_everyone:
        verifier = verifier.model_copy(update={"bias": 50.0})
    _, test_others, _ = other_clips(fakes.ToneVoices())
    result = evaluate(stream, verifier, split_wake(job).held, test_others)
    failures = []
    if not passes(result, WAKE_BARS, needs_negatives=False) or result.others == 0:
        failures.append(f"bars: {result.as_evals()}")
    if not accept_everyone and trained.info.beats_current is not True:
        failures.append("the verifier would not be applied")
    return _case("stage1", failures)


def _stage2(untrained: bool = False) -> dict[str, Any]:
    from jarvis.localspeech.wakeword import fakes
    from jarvis.localspeech.wakeword.mlp import Recipe
    from jarvis.localspeech.wakeword.owned_train import train_owned
    from jarvis.localspeech.wakeword.streaming import Stream

    recipe = Recipe(
        hidden=16, epochs=0 if untrained else 10, copies=1, tv_train_s=60, tv_eval_s=600
    )
    job = WakeJob(
        artifact=WakeArtifact.OWNED, session_id=SESSION, clips=fakes.session_clips(30, 40)
    )
    trained = train_owned(
        job,
        Stream(fakes.tone_models()),
        {formats.MEL_MODEL: "b" * 64},
        fakes.ToneVoices(),
        lambda f, w: None,
        now=NOW,
        recipe=recipe,
    )
    failures = []
    if trained.info.beats_current is not True:
        failures.append(f"not swapped in: {trained.info.evals}")
    if formats.manifest_sha256(trained.manifest) != formats.sha256_hex(trained.data):
        failures.append("the MANIFEST does not name the file")
    return _case("stage2", failures)


def run_mock() -> dict[str, Any]:
    cases = [_stage1(), _stage2()]
    controls = {"stage1": not _stage1(True)["passed"], "stage2": not _stage2(True)["passed"]}
    ok = all(c["passed"] for c in cases) and all(controls.values())
    return {
        "suite": "wakeword",
        "mode": "mock",
        "passed": ok,
        "cases": cases,
        "controls_failed_the_suite": controls,
    }


def _wav_clips(folder: Path) -> list[bytes]:
    clips = []
    for path in sorted(folder.glob("*.wav")):
        with wave.open(str(path), "rb") as f:
            if (f.getframerate(), f.getnchannels(), f.getsampwidth()) == (16_000, 1, 2):
                clips.append(f.readframes(f.getnframes()))
    return clips


def run_real(hours: float, clips: Path | None) -> dict[str, Any]:
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return {"suite": "wakeword", "mode": "real", "skipped": "onnxruntime is not installed"}
    import numpy as np

    from jarvis.localspeech.wakeword import synth
    from jarvis.localspeech.wakeword.runtime import open_console_models
    from jarvis.localspeech.wakeword.streaming import Stream, listen, pad

    stream = Stream(open_console_models().features)
    rng = np.random.default_rng(0)
    seconds = wakes = 0
    while seconds < hours * 3600:
        piece = synth.music(rng, 30, 3000.0) + synth.noise(rng, 30, "pink", 800.0)
        wakes += listen(stream, synth.as_pcm(piece))
        seconds += 30
    held = _wav_clips(clips) if clips else []
    misses = sum(listen(stream, pad(c)) == 0 for c in held)
    result = WakeEval(clips=len(held), misses=misses, negative_seconds=seconds, false_wakes=wakes)
    return {
        "suite": "wakeword",
        "mode": "real",
        "model": formats.CURRENT_MODEL,
        "evals": result.as_evals(),
        "bars": WAKE_BARS.__dict__,
        "passed": passes(result, WAKE_BARS, needs_negatives=True) if held else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--hours", type=float, default=WAKE_BARS.tv_audio_hours)
    ap.add_argument("--clips", type=Path)
    args = ap.parse_args()
    report = run_real(args.hours, args.clips) if args.real else run_mock()
    print(json.dumps(report, indent=2))
    (HERE / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report.get("passed") is not False else 1


if __name__ == "__main__":
    sys.exit(main())

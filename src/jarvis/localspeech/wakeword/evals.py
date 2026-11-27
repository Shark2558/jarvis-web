# src/jarvis/localspeech/wakeword/evals.py
"""The wake word's evals (plan section 5) and the console's wake rule, in pure Python (kit-safe).

- `Decider`: `decide()` of static/console-wakeword.js — `PATIENCE` consecutive frames at or above
  the threshold wake, then nothing for `COOLDOWN_FRAMES`; the caller resets its stream after a
  wake (openWakeWord's `reset()`, then `WARMUP` frames that score 0), as the console does.
- `WakeEval`: misses on his held-out clips, false wakes an hour on negative audio, other speakers'
  "Hey Jarvis" rejected; `passes` checks `WAKE_BARS` (the plan's bars; equal to
  `jarvis.voice.profile.BARS`, which the kit cannot import), `beats` decides the stage 2 swap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from jarvis.localspeech.wakeword.formats import COOLDOWN_FRAMES, FRAME_SAMPLES, PATIENCE, THRESHOLD


@dataclass(frozen=True)
class WakeBars:
    false_wakes_per_hour_max: float = 0.5
    wake_miss_max: float = 0.05
    other_speaker_reject_min: float = 0.90
    tv_audio_hours: float = 2.0


WAKE_BARS: Final = WakeBars()
SECONDS_PER_FRAME: Final = FRAME_SAMPLES / 16_000


@dataclass
class Decider:
    """One stream's wake decisions, frame by frame (`feed` -> True on a wake)."""

    threshold: float = THRESHOLD
    consecutive: int = 0
    frame: int = 0
    last_wake: int | None = None

    def feed(self, score: float) -> bool:
        index = self.frame
        self.frame += 1
        self.consecutive = self.consecutive + 1 if score >= self.threshold else 0
        if self.consecutive < PATIENCE:
            return False
        if self.last_wake is not None and index - self.last_wake < COOLDOWN_FRAMES:
            return False
        self.last_wake = index
        self.consecutive = 0
        return True

    def reset_run(self) -> None:
        """The stream starts again (a pause, a new clip): the run, not the cooldown."""
        self.consecutive = 0


@dataclass(frozen=True)
class WakeEval:
    """One model's results. Rates are fractions (0.05 = 5 %)."""

    clips: int = 0  # his held-out "Hey Jarvis" clips
    misses: int = 0
    negative_seconds: float = 0.0
    false_wakes: int = 0
    others: int = 0  # other speakers' "Hey Jarvis" clips
    others_accepted: int = 0
    notes: tuple[str, ...] = field(default=())

    @property
    def miss_rate(self) -> float | None:
        return self.misses / self.clips if self.clips else None

    @property
    def false_wakes_per_hour(self) -> float | None:
        if self.negative_seconds <= 0:
            return None
        return self.false_wakes * 3600 / self.negative_seconds

    @property
    def other_reject(self) -> float | None:
        return 1 - self.others_accepted / self.others if self.others else None

    def as_evals(self, prefix: str = "", *, counts: bool = True) -> dict[str, float]:
        """For `ArtifactInfo.evals` and the MANIFEST: only what was measured (`counts`: also how
        many clips and hours it was measured on)."""
        found: dict[str, float | None] = {
            "miss_rate": self.miss_rate,
            "false_wakes_per_hour": self.false_wakes_per_hour,
            "other_reject": self.other_reject,
        }
        if counts:
            found |= {
                "held_out_clips": float(self.clips),
                "negative_hours": round(self.negative_seconds / 3600, 4),
            }
        return {f"{prefix}{k}": v for k, v in found.items() if v is not None}


def passes(result: WakeEval, bars: WakeBars = WAKE_BARS, *, needs_negatives: bool) -> bool:
    """Every bar that applies: misses always; false wakes when `needs_negatives` (stage 2);
    other speakers' rejection whenever other speakers were heard."""
    miss = result.miss_rate
    if miss is None or miss > bars.wake_miss_max:
        return False
    if needs_negatives:
        fwph = result.false_wakes_per_hour
        if fwph is None or fwph > bars.false_wakes_per_hour_max:
            return False
    other = result.other_reject
    return other is None or other >= bars.other_speaker_reject_min


def verifier_passes(result: WakeEval, bars: WakeBars = WAKE_BARS) -> bool:
    """Stage 1 is applied only when it was shown to reject other speakers and not miss him."""
    return result.others > 0 and passes(result, bars, needs_negatives=False)


def beats(new: WakeEval, current: WakeEval, bars: WakeBars = WAKE_BARS) -> bool:
    """Stage 2 replaces today's model only when it passes every bar and is no worse on each
    measure (a tie goes to the owned model: its licence is the reason it exists)."""
    if not passes(new, bars, needs_negatives=True):
        return False
    pairs = (
        (new.miss_rate, current.miss_rate),
        (new.false_wakes_per_hour, current.false_wakes_per_hour),
    )
    return all(n is not None and (c is None or n <= c + 1e-12) for n, c in pairs)


__all__ = [
    "SECONDS_PER_FRAME",
    "WAKE_BARS",
    "Decider",
    "WakeBars",
    "WakeEval",
    "beats",
    "passes",
    "verifier_passes",
]

# src/jarvis/voice/session_compare.py
"""The voice session's Google comparison and its ₹ question (R5.2 row 81; plan 4; brief "Costs").

The comparison lets Google (with his words) hear the held-out lines, at most
`voice_session_compare_minutes` (20) of its listening, counted at Google's 15-second billing step
per clip (`STEP_S`, the voice service's own). Inside this month's free minutes every call is
free-only: it can never be priced. Beyond them the answer is 402 `needs_yes` with the ₹ (≈ ₹2.29
a minute, at most ≈ ₹46 for 20 minutes) and nothing is sent until he types YES; or he goes on
without Google. Free minutes that can't be read are never promised (he is asked).

Google can hear a clip only while it passes through the cloud on its way to the laptop (the cloud
keeps no audio), so the question is asked at the start, and again before a clip when the free
minutes ran out mid-session (`check`), never after the money is spent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Protocol, TypeVar

from pydantic import BaseModel

from jarvis.billing.service import BudgetError, BudgetReached, FreeAllowanceUsed, rupees
from jarvis.logging import get_logger
from jarvis.voice.ports import VoiceError
from jarvis.voice.profile_ports import ProfileRefused
from jarvis.voice.service import FREE_ONLY_STEP_S
from jarvis.voice.session_store import Compare, CompareMode

log = get_logger(__name__)
M = TypeVar("M", bound=BaseModel)

STEP_S: Final = FREE_ONLY_STEP_S  # Google may bill each clip in 15-second steps
YES_WORD: Final = "YES"
HEARS: Final = (CompareMode.FREE, CompareMode.YES, CompareMode.NEEDS_YES)


def with_(model: M, **changes: Any) -> M:
    """A validated copy of a frozen model with `changes`."""
    return type(model).model_validate({**model.model_dump(), **changes})


@dataclass(frozen=True)
class GoogleHeard:
    text: str
    ms: int | None = None


class GoogleEar(Protocol):
    """Google's listening with his words (`jarvis.voice.service.VoiceService.transcribe`)."""

    def ready(self) -> bool: ...

    async def free_seconds_left(self) -> float: ...  # BudgetError when it can't be read

    async def inr_per_minute(self) -> float: ...

    async def hear(self, uid: str, wav: bytes, *, free_only: bool) -> GoogleHeard: ...


def needs_yes(compare: Compare) -> ProfileRefused:
    """402 `needs_yes`: the ₹ for the clips Google has still to hear, in plain words."""
    left = max(0, compare.cap_clips - compare.clips)
    minutes = max(1, round(left * STEP_S / 60))
    most = left * STEP_S / 60 * compare.inr_per_minute
    words = (
        f"Comparing with Google's listening takes about {minutes} minutes, and this month's free "
        f"minutes don't cover it: about {rupees(compare.inr_per_minute)} a minute, at most about "
        f"{rupees(round(most))}. Type {YES_WORD} to include Google, or go on without it."
    )
    return ProfileRefused(402, "needs_yes", words)


class Comparison:
    def __init__(
        self, google: GoogleEar | None, *, minutes: int, now: Callable[[], datetime]
    ) -> None:
        self.google = google
        self.minutes = minutes
        self.now = now

    async def _free_left(self) -> float:
        if self.google is None:
            return 0.0
        try:
            return await self.google.free_seconds_left()
        except BudgetError:
            return 0.0  # can't tell: never promise free

    async def plan(self, count: int, *, yes: bool, skip: bool, ask: bool) -> Compare:
        """The comparison for a session with `count` held-out lines. `ask`: beyond the free
        minutes without his YES, refuse (402); else say NEEDS_YES (a preview)."""
        cap = min(count, int(self.minutes * 60 // STEP_S))
        minutes = round(cap * STEP_S / 60, 2)
        if cap == 0 or skip:
            return Compare(mode=CompareMode.OFF, cap_clips=cap, minutes=minutes)
        if self.google is None or not self.google.ready():
            return Compare(mode=CompareMode.UNAVAILABLE, cap_clips=cap, minutes=minutes)
        rate = await self.google.inr_per_minute()
        plan = Compare(
            mode=CompareMode.FREE,
            cap_clips=cap,
            minutes=minutes,
            inr_per_minute=round(rate, 4),
            inr_max=round(minutes * rate, 2),
        )
        if await self._free_left() >= cap * STEP_S:
            return plan
        if yes:
            return with_(plan, mode=CompareMode.YES, yes_at=self.now())
        if ask:
            raise needs_yes(plan)
        return with_(plan, mode=CompareMode.NEEDS_YES)

    def answer(self, compare: Compare, *, yes: bool, skip: bool) -> Compare | None:
        """His answer mid-session: without Google, or YES to the ₹ for what is left."""
        if skip and compare.mode in HEARS:
            return with_(compare, mode=CompareMode.OFF)
        if yes and compare.mode is CompareMode.NEEDS_YES:
            left = max(0, compare.cap_clips - compare.clips) * STEP_S / 60
            most = round(left * compare.inr_per_minute, 2)
            return with_(compare, mode=CompareMode.YES, yes_at=self.now(), inr_max=most)
        return None

    def hears(self, compare: Compare) -> bool:
        return (
            self.google is not None and compare.mode in HEARS and compare.clips < compare.cap_clips
        )

    async def check(self, compare: Compare) -> Compare | None:
        """Before a clip Google would hear: 402 when he must answer first. Returns the changed
        comparison to keep (NEEDS_YES) with the refusal, else None."""
        if compare.mode is CompareMode.NEEDS_YES:
            raise needs_yes(compare)
        if compare.mode is CompareMode.FREE and await self._free_left() < STEP_S:
            return with_(compare, mode=CompareMode.NEEDS_YES)
        return None

    async def hear(
        self, uid: str, wav: bytes, mode: CompareMode
    ) -> tuple[GoogleHeard | None, CompareMode]:
        """Google hears one clip: (what it heard or None, the mode from now on)."""
        if self.google is None:
            return None, mode
        try:
            return await self.google.hear(uid, wav, free_only=mode is CompareMode.FREE), mode
        except FreeAllowanceUsed:
            return None, CompareMode.NEEDS_YES
        except BudgetReached:
            return None, CompareMode.LIMIT
        except (BudgetError, VoiceError) as exc:  # this clip isn't compared; the session goes on
            log.warning(
                "voice session: Google didn't hear a clip", extra={"why": type(exc).__name__}
            )
            return None, mode


__all__ = [
    "HEARS",
    "STEP_S",
    "YES_WORD",
    "Comparison",
    "GoogleEar",
    "GoogleHeard",
    "needs_yes",
    "with_",
]

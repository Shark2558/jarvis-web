# src/jarvis/config_coach.py
"""R8's settings (docs/plans/r8-vision.md v8.0.3 D12; I0 seam S22), a base class of
`jarvis.config.Settings` like R18's `config_calls.CallsConfig` and R5.2's
`config_voice.LocalSpeechConfig`: every key is read like any other (`JARVIS_<NAME>`, .env) and
reached as `settings.<name>`; config.py stays near its size guard. Pydantic only.

- `coach_enabled`: the coaches' routes and stores are offered (each coach still starts only when
  he switches it on and taps; nothing is kept without the token key).
- `coach_keep_days`: how long kept coach results are kept (D12: 90 days, settable 7 to 365); the
  daily sweep deletes older days.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

COACH_KEEP_DAYS = 90
COACH_KEEP_RANGE = (7, 365)


class CoachConfig(BaseModel):
    coach_enabled: bool = True
    coach_keep_days: int = Field(
        default=COACH_KEEP_DAYS, ge=COACH_KEEP_RANGE[0], le=COACH_KEEP_RANGE[1]
    )


__all__ = ["COACH_KEEP_DAYS", "COACH_KEEP_RANGE", "CoachConfig"]

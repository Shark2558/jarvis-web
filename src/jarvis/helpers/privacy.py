# src/jarvis/helpers/privacy.py
"""I0's privacy row (docs/plans/r11-free-helpers.md D17): `helpers_nudge`, the nudge caps,
snoozes and stops, and the send log (kind, due minute, sent minute and outcome; never text).
Delete is a confirm: the defaults come back (every nudge still off until switched on in its tab).
The parts register their own rows (`kinds.PRIVACY_IDS`)."""

from __future__ import annotations

from typing import Any

from jarvis.helpers.gate import KEEP_DAYS, GateStore
from jarvis.helpers.kinds import GATE_PRIVACY_ID, PRIVACY_SECTION
from jarvis.privacy.sources import GOOGLE_ENC, CallbackSource, Look, Spec


def nudge_privacy(store: GateStore) -> CallbackSource:
    async def look(uid: str) -> Look:
        state = await store.state(uid)
        days = await store.days(uid)
        sends = sum(len(s) for _, s in days)
        saved = 1 if state.rev > 0 else 0
        return Look(saved + sends, [state.rev, sends], deletable=bool(saved or days))

    async def export(uid: str) -> dict[str, Any]:
        state = await store.state(uid)
        return {
            "nudges": state.model_dump(exclude={"rev"}),
            "sent": [{"day": day, "sends": sends} for day, sends in await store.days(uid)],
        }

    async def delete(uid: str) -> int:
        return await store.delete_all(uid)

    return CallbackSource(
        Spec(
            GATE_PRIVACY_ID,
            PRIVACY_SECTION,
            "Nudge limits and the helpers' send log",
            "Your daily nudge caps, snoozes and stops, and when each helper message went out "
            "(its kind and the minute only, never its words).",
            "items",
            f"The send log {KEEP_DAYS} days; your nudge choices until you change them.",
            GOOGLE_ENC,
            delete="confirm",
            recoverable=False,
            note="Deleting brings back the default caps; every nudge stays as you switched it.",
        ),
        look,
        export,
        delete,
    )


__all__ = ["nudge_privacy"]

# src/jarvis/helpers/nudges/privacy.py
"""Part C's privacy row (plan D17): `helpers_wellbeing`, section "Helpers", delete with the passkey.

It lists, exports and deletes everything Part C keeps: the sealed log (`wellbeing/{uid}_{date}`:
water, stand-ups, planned-activity check-ins by fingerprint), his nudge settings and free-time list
(`nudges/{uid}`) and the content-free claims (`nudges/{uid}_told`). The export is the log opened
(amounts as numbers, his words as he typed them), never a calendar title or time, never the
encrypted blob. Deleting brings every nudge back to OFF with the defaults. The gate's caps,
snoozes and send log are I0's own row (`helpers_nudge`).
"""

from __future__ import annotations

from typing import Any

from jarvis.helpers.kinds import PRIVACY_SECTION
from jarvis.helpers.nudges.store import KEEP_WELL_DAYS, NudgeStore, WellbeingStore
from jarvis.privacy.sources import OURS_ENC, CallbackSource, Look, Spec

ID = "helpers_wellbeing"


def wellbeing_privacy(store: NudgeStore, well: WellbeingStore) -> CallbackSource:
    async def look(uid: str) -> Look:
        days = await well.days(uid)
        s = await store.settings(uid)
        kept = len(days) + (1 if s.rev else 0)
        basis = [s.rev, len(s.ideas), [d for d, _ in days]]
        return Look(kept, basis, deletable=bool(kept or await store.told(uid)))

    async def export(uid: str) -> dict[str, Any]:
        s = await store.settings(uid)
        log = [
            {
                "day": day,
                "glasses_of_water": d.water,
                "stand_ups": d.stood,
                "planned_activities": [
                    {"word": c.w, "at": c.at, "outcome": c.o} for c in d.checkins.values()
                ],
            }
            for day, d in await well.days(uid)
        ]
        return {
            "nudges": {k: n.model_dump(mode="json") for k, n in s.nudges.items()},
            "free_time_ideas": [i.model_dump(mode="json", exclude={"id"}) for i in s.ideas],
            "log": log,
        }

    async def delete(uid: str) -> int:
        return await well.delete_all(uid) + await store.delete_all(uid)

    return CallbackSource(
        Spec(
            ID,
            PRIVACY_SECTION,
            "Water, stand-ups, activities and free time",
            "The glasses of water and stand-ups you logged, whether a planned activity happened, "
            "your nudge settings and your free-time ideas.",
            "items",
            f"The log {KEEP_WELL_DAYS} days; your settings and ideas until you change them.",
            OURS_ENC,
            encrypted_by_jarvis=True,
            delete="passkey",
            recoverable=False,
            note="Never kept: your calendar's event titles; a planned activity is kept only as a "
            "fingerprint with your own word for it. Deleting switches every nudge off.",
        ),
        look,
        export,
        delete,
    )


__all__ = ["ID", "wellbeing_privacy"]

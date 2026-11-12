# src/jarvis/helpers/house/privacy.py
"""Part B's two privacy rows (docs/plans/r11-free-helpers.md D17; section "Helpers"):

- `helpers_house` (confirm): the chores rota and the home upkeep list (his own labels), and those
  reminders' claims (hashes only). Delete removes them all; the weather and SACHET claims stay
  with his place.
- `helpers_place` (simple): his place for weather and alerts (district, state, the rounded
  coordinates), his thresholds, whether breach notices are watched, the feeds' bookkeeping and
  SACHET's words of the warnings still active; sealed by JARVIS (`alerts_place`). Delete removes
  it and its claims: weather, disaster alerts and breach notices are then off until he types his
  district again. Without a keyring nothing is ever kept (the row says so).
Export is JSON of exactly what is kept.
"""

from __future__ import annotations

from typing import Any

from jarvis.helpers.house.store import (
    OFF_WORDS,
    PLACE_TAGS,
    HouseStore,
    OutsideOff,
    OutsideStore,
)
from jarvis.helpers.house.words import ADULTS_ONLY
from jarvis.helpers.kinds import PRIVACY_SECTION
from jarvis.privacy.sources import GOOGLE_ENC, OURS_ENC, CallbackSource, Look, Spec


def house_privacy(store: HouseStore) -> CallbackSource:
    async def look(uid: str) -> Look:
        cs, xs = await store.chores(uid), await store.upkeep(uid)
        ids = sorted([c.id for c in cs] + [x.id for x in xs])
        return Look(len(ids), [ids, [c.turn for c in cs]], deletable=bool(ids))

    async def export(uid: str) -> dict[str, Any]:
        return {
            "chores": [c.model_dump(mode="json") for c in await store.chores(uid)],
            "upkeep": [x.model_dump(mode="json") for x in await store.upkeep(uid)],
            "never_kept": "Ages, children's data, or anyone else's contact details.",
        }

    return CallbackSource(
        Spec(
            "helpers_house",
            PRIVACY_SECTION,
            "Chores rota and home upkeep",
            "Your chores (when they are due and the rota labels you typed) and your home upkeep "
            "list, and when each reminder went (a hash, never the words).",
            "items",
            "Until you delete them; the reminder hashes 30 days.",
            GOOGLE_ENC,
            delete="confirm",
            note=ADULTS_ONLY,
        ),
        look,
        export,
        store.delete_house,
    )


def place_privacy(outside: OutsideStore, store: HouseStore) -> CallbackSource:
    async def look(uid: str) -> Look:
        rev = await outside.rev(uid)
        note = "" if outside.available else OFF_WORDS
        return Look(0 if rev is None else 1, [rev], note=note, deletable=rev is not None)

    async def export(uid: str) -> dict[str, Any]:
        try:
            o = await outside.read(uid)
        except OutsideOff:
            return {"note": OFF_WORDS}
        return {
            "place": o.place.model_dump(mode="json") if o.place else None,
            "thresholds": o.thresholds.model_dump(mode="json"),
            "breach": {"on": o.breach_on, **o.breach.model_dump(mode="json")},
            "weather": o.weather.model_dump(mode="json"),
            "sachet": o.sachet.model_dump(mode="json", exclude={"etag"}),
        }

    async def delete(uid: str) -> int:
        return await outside.delete(uid) + await store.drop_claims(uid, PLACE_TAGS)

    return CallbackSource(
        Spec(
            "helpers_place",
            PRIVACY_SECTION,
            "Your place for weather and alerts",
            "Your district and state, its coordinates rounded to about 1 km, your weather "
            "thresholds, whether breach notices are watched, and the weather and SACHET "
            "bookkeeping (with SACHET's words of the warnings still active).",
            "settings",
            "Until you delete it; the alert hashes 30 days.",
            OURS_ENC,
            encrypted_by_jarvis=True,
            delete="simple",
            note="Deleting switches weather, disaster alerts and breach notices off.",
        ),
        look,
        export,
        delete,
    )


__all__ = ["house_privacy", "place_privacy"]

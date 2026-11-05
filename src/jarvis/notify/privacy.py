# src/jarvis/notify/privacy.py
"""The Alerts and browser-notification categories of the privacy dashboard (R3 D14; I1).

- `notify`: quiet hours, which alerts ring, names in alerts, the snapshot opt-in, the VIP
  references (sealed) and the alerts held during quiet hours (kinds and times only). Delete is
  simple: the defaults come back (burglar and hazard alerts still ring) and held alerts go.
- `webpush`: the browsers that receive notifications (sealed endpoints and keys). Export lists
  names and dates only, never an endpoint or a key; delete removes every browser (each can be
  added again from Integrations -> Alerts).
"""

from __future__ import annotations

from typing import Any

from jarvis.notify.store import NotifyStore
from jarvis.privacy.sources import OURS_ENC, CallbackSource, Look, Spec
from jarvis.webpush.store import PushStore

SECTION = "Home and camera"


def notify_source(store: NotifyStore) -> CallbackSource:
    async def look(uid: str) -> Look:
        settings = await store.get(uid)
        held = await store.held_list(uid)
        saved = 1 if settings.rev > 0 else 0
        return Look(
            saved + len(held),
            [settings.rev, len(held)],
            deletable=bool(saved or held),
        )

    async def export(uid: str) -> dict[str, Any]:
        settings = await store.get(uid)
        held = await store.held_list(uid)
        return {
            "settings": settings.model_dump(mode="json", exclude={"tz"}),
            "held": [{"kind": h.get("kind"), "at": h.get("at")} for h in held],
        }

    async def delete(uid: str) -> int:
        held = await store.held_list(uid)
        await store.reset(uid)
        if held:
            await store.held_discard(uid, held)
        return 1 + len(held)

    return CallbackSource(
        Spec(
            "notify",
            SECTION,
            "Alert choices",
            "Quiet hours, which alerts ring, VIPs, names in alerts, the photo choice, and alerts "
            "held during quiet hours (kinds and times only).",
            "items",
            "Until you change them; held alerts until quiet hours end.",
            OURS_ENC,
            encrypted_by_jarvis=True,
            delete="simple",
            recoverable=False,
            note="Deleting brings back the defaults: burglar and hazard alerts still ring.",
        ),
        look,
        export,
        delete,
    )


def webpush_source(store: PushStore) -> CallbackSource:
    async def look(uid: str) -> Look:
        devices = await store.list(uid)
        return Look(
            len(devices),
            sorted(d.id for d in devices),
            deletable=bool(devices),
        )

    async def export(uid: str) -> dict[str, Any]:
        return {"browsers": [d.view() for d in await store.list(uid)]}

    async def delete(uid: str) -> int:
        count = len(await store.list(uid))
        await store.clear(uid)
        return count

    return CallbackSource(
        Spec(
            "webpush",
            SECTION,
            "Browsers that get notifications",
            "Each browser you enabled for notifications: its name, when it was added and the "
            "address its browser company gave for sending to it.",
            "browsers",
            "Until you remove them.",
            OURS_ENC,
            encrypted_by_jarvis=True,
            delete="simple",
            recoverable=False,
            note="You can enable a browser again in Integrations -> Alerts.",
        ),
        look,
        export,
        delete,
    )


__all__ = ["SECTION", "notify_source", "webpush_source"]

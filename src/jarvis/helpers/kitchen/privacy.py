# src/jarvis/helpers/kitchen/privacy.py
"""The kitchen's two privacy rows (docs/plans/r11-free-helpers.md D17), section "Helpers":

- `helpers_kitchen` (delete: confirm): his pantry, tastes (diet, spice, oil, cuisines, note),
  saved recipes and the cooking / washing-up plan, sealed by JARVIS (purpose `kitchen`).
- `helpers_spend` (delete: passkey): per order the shop, the day and the amount, sealed by JARVIS
  (purpose `spend`), 13 months; and whether he switched receipts on. Amounts export in ₹.
Both say what is never kept: recipe prompts and the AI's replies, the mails themselves, items
bought, card or account numbers. The keyed hashes that keep an order (or a mail) from counting
twice never leave in an export. Without a keyring both rows show nothing kept (nothing can be).
"""

from __future__ import annotations

from typing import Any

from jarvis.billing.service import rupees
from jarvis.helpers.kinds import PRIVACY_SECTION
from jarvis.helpers.kitchen.store import KitchenStore, SpendStore
from jarvis.privacy.sources import OURS_ENC, CallbackSource, Look, Spec

KITCHEN_ID = "helpers_kitchen"
SPEND_ID = "helpers_spend"
OFF_NOTE = "Off: JARVIS has no token key, so nothing is kept."


def kitchen_privacy(store: KitchenStore) -> CallbackSource:
    async def look(uid: str) -> Look:
        if not store.sealed:
            return Look(0, deletable=False, note=OFF_NOTE)
        if not await store.exists(uid):
            return Look(0, deletable=False)
        k = await store.load(uid)
        count = len(k.pantry) + len(k.recipes) + 1  # + his tastes and block plan
        return Look(count, [len(k.pantry), [r.id for r in k.recipes], k.prefs.model_dump_json()])

    async def export(uid: str) -> dict[str, Any]:
        if not store.sealed or not await store.exists(uid):
            return {"pantry": [], "recipes": []}
        k = await store.load(uid)
        return k.model_dump(mode="json")

    return CallbackSource(
        Spec(
            KITCHEN_ID,
            PRIVACY_SECTION,
            "Kitchen: pantry, tastes and saved recipes",
            "What you have, your diet, spice and oil, cuisines and note, the recipes you saved "
            "(ingredients with grams) and your cooking and washing-up times.",
            "items",
            "Until you delete it.",
            OURS_ENC,
            encrypted_by_jarvis=True,
            delete="confirm",
            note="Never kept: recipe prompts or the AI's replies beyond the conversation.",
        ),
        look,
        export,
        store.delete,
    )


def spend_privacy(store: SpendStore) -> CallbackSource:
    async def look(uid: str) -> Look:
        if not store.sealed:
            return Look(0, deletable=False, note=OFF_NOTE)
        months = await store.months(uid)
        scan = await store.scan(uid)
        orders = sum(len(m.orders) for m in months)
        basis = [scan.on, scan.rev, [(m.month, len(m.orders)) for m in months]]
        return Look(orders, basis, deletable=bool(months) or scan.rev > 0)

    async def export(uid: str) -> dict[str, Any]:
        if not store.sealed:
            return {"receipts_on": False, "months": []}
        months = [
            {
                "month": m.month,
                "total": rupees(m.total_paise / 100),
                "orders": [
                    {"merchant": o.merchant, "day": o.day, "amount": rupees(o.paise / 100)}
                    for o in m.orders
                ],
            }
            for m in await store.months(uid)
        ]
        return {"receipts_on": (await store.scan(uid)).on, "months": months}

    return CallbackSource(
        Spec(
            SPEND_ID,
            PRIVACY_SECTION,
            "Grocery spend from your receipts",
            "Per grocery order from your e-mailed receipts: the shop, the day and the amount; "
            "and whether reading receipts is on.",
            "orders",
            "13 months.",
            OURS_ENC,
            encrypted_by_jarvis=True,
            delete="passkey",
            note="Never kept: the mails, what you bought, card or account numbers.",
        ),
        look,
        export,
        store.delete_all,
    )


__all__ = ["KITCHEN_ID", "SPEND_ID", "kitchen_privacy", "spend_privacy"]

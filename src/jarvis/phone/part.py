# src/jarvis/phone/part.py
"""R7 Part C (Phone link and security): the part's one join with the app
(`jarvis.mobile.ports`).

    services["phone"]     the PhoneService the routes of `api/phone.py` read
    services["door"]      {"hello", "inbox"}: Part C's two door handlers (D's are health and sos)
    services["app_lock"]  the app lock's check for I0's slot (D21)
    privacy               the "Linked phones" row

With `mobile_enabled` off nothing of the phone is offered: the routes answer 404 and the slot
passes everything through.
"""

from __future__ import annotations

from jarvis.mobile.ports import MobileContext, MobilePart
from jarvis.phone.privacy import PhonePrivacy
from jarvis.phone.service import PhoneService

READY = "ready"
OFF = "switched off"
NO_STORE = "no document store"


def build(ctx: MobileContext) -> MobilePart:
    if not ctx.s.mobile_enabled:
        return MobilePart("phone", ready=OFF)
    if ctx.docs is None:
        return MobilePart("phone", ready=NO_STORE)
    svc = PhoneService(ctx, ctx.docs)
    return MobilePart(
        "phone",
        privacy=(PhonePrivacy(svc),),
        services={"phone": svc, "door": svc.handlers.services(), "app_lock": svc.lock},
        ready=READY,
    )


__all__ = ["build"]

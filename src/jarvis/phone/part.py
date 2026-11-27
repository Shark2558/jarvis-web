# src/jarvis/phone/part.py
"""R7 Part C (Phone link and security): the part's one join with the app
(`jarvis.mobile.ports`).

    services["phone"]     the PhoneService the routes of `api/phone.py` read
    services["door"]      {"hello", "inbox"}: Part C's two door handlers (D's are health and sos)
    services["app_lock"]  the app lock's check for I0's slot (D21)
    services["linked_since"]  async (uid) -> the earliest link time of his phones (unix seconds)
                          or None: Part D's `watch_stale` tells him once about a phone that was
                          linked and never sent anything (I1)
    services["phone_calls"]   R18 I1: the calls' `PhoneCalls` (its door route `calls` is in
                          services["door"]); the calls join sets its late ports
    privacy               the "Linked phones" row

With `mobile_enabled` off nothing of the phone is offered: the routes answer 404 and the slot
passes everything through.
"""

from __future__ import annotations

from typing import Any

from jarvis.mobile.ports import MobileContext, MobilePart
from jarvis.phone.calls import PhoneCalls, PushDoorbell, StoreDirectory
from jarvis.phone.calls_wire import CommandSigner
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

    async def linked_since(uid: str) -> float | None:
        return min((p.linked_at for p in (await svc.store.owner(uid)).phones), default=None)

    # R18 I1 (INTEGRATION-D.md 3.2): one per process. Its signing key is made at each start: the
    # door's every answer carries it with the commands (the outbox is in memory too)
    audit: Any = ctx.audit  # the audit chain (its `append` takes the calls' rows by keyword)
    calls = PhoneCalls(
        phones=StoreDirectory(svc.store),
        signer=CommandSigner.ephemeral(),
        doorbell=PushDoorbell(lambda: ctx.state("push")),
        audit=audit,
    )
    return MobilePart(
        "phone",
        privacy=(PhonePrivacy(svc),),
        services={
            "phone": svc,
            "door": {**svc.handlers.services(), **calls.door_handlers()},
            "app_lock": svc.lock,
            "linked_since": linked_since,
            "phone_calls": calls,
        },
        ready=READY,
    )


__all__ = ["build"]

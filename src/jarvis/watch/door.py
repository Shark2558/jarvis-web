# src/jarvis/watch/door.py
"""Part D's two handlers behind the phone's signed door (docs/plans/r7-mobile.md D6, D17, D19;
docs/plans/r7-integration/phone-contract.md section 4). Part C's door runs every check of D6
first (route, no query, cap, header, device, time, nonce, signature, rate) and hands over a
`PhoneRequest`; these never see a request that failed a check.

- `health`: 200 {ok, days} | 422 {error: invalid} (the body refused whole, fixed words, no value
  echoed) | 503 {error: watch_off | unavailable}.
- `sos`: 200 with the send's honest view (`SendResult.view`: per contact, the message text for
  the phone's SMS screen, 112) whatever the outcome, refused and failed included, so the phone
  always opens its SMS screen and the 112 button | 422 {error: invalid} | 500 {error: failed}
  for anything unforeseen, which still says to use the SMS screen or call 112.
Logs carry the route and a class name only: never a value, a place or a word of the body.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from jarvis.logging import get_logger
from jarvis.mobile.ports import PhoneHandler, PhoneReply, PhoneRequest
from jarvis.sos.models import SosIn
from jarvis.sos.service import SosService
from jarvis.watch.models import IntakeRefused
from jarvis.watch.service import WatchService
from jarvis.watch.store import WatchOff, WatchUnavailable

log = get_logger(__name__)
SOS_FAILED = "The SOS could not be sent from the server. Use the SMS screen or call 112."


def health_handler(watch: WatchService) -> PhoneHandler:
    async def health(req: PhoneRequest) -> PhoneReply:
        if not watch.enabled:
            return PhoneReply(503, {"error": "watch_off"})
        try:
            days = await watch.intake(req.uid, req.body)
        except IntakeRefused:
            log.warning("door: a health body was refused", extra={"route": "health"})
            return PhoneReply(422, {"error": "invalid", "detail": IntakeRefused.WORDS})
        except WatchOff:
            return PhoneReply(503, {"error": "watch_off", "detail": WatchOff.WORDS})
        except WatchUnavailable:
            return PhoneReply(503, {"error": "unavailable", "detail": WatchUnavailable.WORDS})
        return PhoneReply(200, {"ok": True, "days": days})

    return health


def sos_handler(sos: SosService) -> PhoneHandler:
    async def send(req: PhoneRequest) -> PhoneReply:
        try:
            body = SosIn.model_validate(json.loads(req.body.decode("utf-8")))
        except (UnicodeDecodeError, ValueError, ValidationError, TypeError):
            log.warning("door: an sos body was refused", extra={"route": "sos"})
            return PhoneReply(422, {"error": "invalid"})
        try:
            result = await sos.send(req.uid, body.kind, body.location, via="phone", at=body.at)
        except Exception as exc:  # noqa: BLE001 - the phone must still open SMS and 112
            log.error("door: the sos send failed", extra={"error": type(exc).__name__})
            return PhoneReply(500, {"error": "failed", "detail": SOS_FAILED, "sent": False})
        return PhoneReply(200, result.view())

    return send


__all__ = ["SOS_FAILED", "health_handler", "sos_handler"]

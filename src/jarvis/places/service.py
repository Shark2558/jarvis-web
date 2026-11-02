# src/jarvis/places/service.py
"""Wiring for Maps (slice 12 D3): the server-key client, the allowance ledger, the owner's
Home / Work and the per-owner hourly count. Built from settings in `jarvis.media.service`, which
also builds YouTube on the same client and ledger. No key → None: the tools are not registered.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from jarvis.integrations.google_key import GoogleKeyClient
from jarvis.places.store import MapsPlaces
from jarvis.quota.ledger import HourlyCounter, QuotaLedger


@dataclass
class MapsService:
    client: GoogleKeyClient
    ledger: QuotaLedger
    places: MapsPlaces
    clock: Callable[[], float] = time.monotonic
    hourly: HourlyCounter = field(init=False)

    def __post_init__(self) -> None:
        self.hourly = HourlyCounter(clock=self.clock)


__all__ = ["MapsService"]

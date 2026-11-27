# src/jarvis/calls/speech/meter.py
"""Every rupee of a call's speech, through `jarvis.billing` (R18 B; cross-cutting: costs).

Three kinds of price, one meter, the voice's own counters reused (never a second ledger):

    Google    `gate` + `charge` on `jarvis.voice.catalogue.Price` (its keys "stt_seconds",
              "tts_chirp3-hd"): the SAME deployment-wide free allowance as JARVIS's English voice,
              then priced at the day's rate under the owner's monthly limit (BudgetReached →
              OptionUnavailable("budget"))
    Azure F0  `hold` / `give_back` on a `FreeAllowance`: the units are held in one transaction
              (two calls can't both take the last free seconds); F0 cannot bill, so past its
              allowance the option stops and says so (AllowanceUsedUp), never priced
    Sarvam    `gate_inr` + `charge_inr`: priced in rupees (₹30 an hour of hearing, ₹30 per 10,000
              characters of voice by default, `jarvis.calls.prices`), under the owner's limit

Rupees are added to the owner's month under the label "calls" (Vitals' calls line). `report`
hands each part's ₹ to the call (`on_cost(part, inr)`; None: a price JARVIS does not know) so the
engine can hold the call to its ₹ cap. Nothing here sees audio or text.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from jarvis.billing import Billing, BudgetReached, BudgetUnavailable
from jarvis.billing.meter import Hold
from jarvis.billing.service import FreeAllowanceUsed
from jarvis.calls.speech.errors import AllowanceUsedUp, OptionUnavailable
from jarvis.logging import get_logger
from jarvis.voice.catalogue import Price

log = get_logger(__name__)

CALLS_LABEL = "calls"
CostSink = Callable[[str, float | None], None]


def _no_sink(_part: str, _inr: float | None) -> None:
    return None


@dataclass(frozen=True)
class FreeAllowance:
    """A free tier that cannot bill (Azure F0): its counter key, its monthly units, and what it
    counts in the owner's words ("hearing", "voice")."""

    key: str
    free_units: float
    what: str


class SpeechMeter:
    def __init__(
        self, billing: Billing, uid: str, *, label: str = CALLS_LABEL, on_cost: CostSink = _no_sink
    ) -> None:
        self.billing = billing
        self.uid = uid
        self.label = label
        self._sink = on_cost

    def report(self, part: str, inr: float | None) -> None:
        """Tell the call what one hearing or voice cost (None: unknown). Never raises."""
        try:
            self._sink(part, inr)
        except Exception as exc:  # noqa: BLE001 — the audio matters more than the tally
            log.error("call cost not reported", extra={"part": part, "why": type(exc).__name__})

    # ---- Google: the shared free allowance, then priced ---------------------------------------

    async def gate(self, option: str, price: Price, units: float) -> None:
        try:
            await self.billing.ensure_units_allowed(
                self.uid, key=price.key, units=units, free_units=price.free_units
            )
        except (BudgetReached, BudgetUnavailable):
            raise OptionUnavailable(option, "budget") from None

    async def charge(self, price: Price, units: float) -> float:
        """Count `units` and price what is past the allowance; the ₹ (never raises)."""
        c = await self.billing.record_units(
            self.uid,
            key=price.key,
            units=units,
            free_units=price.free_units,
            usd_per_unit=price.usd_per_unit,
            label=self.label,
        )
        return c.inr

    async def left(self, option: str, key: str, free_units: float) -> float:
        """The free units left this month (the language check's estimate)."""
        try:
            used = (await self.billing.allowance([key])).used(key)
        except BudgetUnavailable:
            raise OptionUnavailable(option, "meter_unreadable") from None
        return max(0.0, free_units - used)

    # ---- a free tier that cannot bill -----------------------------------------------------------

    async def hold(self, option: str, allowance: FreeAllowance, units: float) -> Hold:
        try:
            return await self.billing.reserve_free(
                key=allowance.key, units=units, free_units=allowance.free_units
            )
        except FreeAllowanceUsed:
            raise AllowanceUsedUp(option, allowance.what) from None
        except BudgetUnavailable:
            raise OptionUnavailable(option, "meter_unreadable") from None

    async def give_back(self, hold: Hold) -> None:
        """A request the vendor surely did not process gives its units back (never raises)."""
        await self.billing.release_free(hold)

    # ---- priced in rupees -----------------------------------------------------------------------

    async def gate_inr(self, option: str, key: str, units: float) -> None:
        try:
            await self.billing.ensure_units_allowed(self.uid, key=key, units=units, free_units=0)
        except (BudgetReached, BudgetUnavailable):
            raise OptionUnavailable(option, "budget") from None

    async def charge_inr(self, key: str, units: float, inr_per_unit: float) -> float:
        """Count and price `units` at `inr_per_unit` rupees (exact: the dollar leg cancels)."""
        rate = (await self.billing.fx.rate()).inr_per_usd
        c = await self.billing.record_units(
            self.uid,
            key=key,
            units=units,
            free_units=0,
            usd_per_unit=inr_per_unit / rate,
            label=self.label,
        )
        return c.inr


__all__ = ["CALLS_LABEL", "CostSink", "FreeAllowance", "SpeechMeter"]

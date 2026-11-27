# src/jarvis/calls/prices.py
"""What a call's speech costs, in ₹, per speech option (docs/plans/r18-calls.md 5.1, 6).

Read from `Settings` (`voice_price_*`): Google's list prices in US$ (as `jarvis.voice.catalogue`)
at the day's rate, Azure's free tier F0 at ₹0 (it cannot bill), Sarvam in ₹ (paid, off unless the
owner turns it on), the laptop's own models at ₹0. A price JARVIS does not know (Bhashini unless
set) is `None` and `inr_per_minute` / `inr_per_chars` raise `PriceUnknown`: an estimate never counts
an unknown price as ₹0.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from jarvis.calls.models import SpeechOption

if TYPE_CHECKING:
    from jarvis.config import Settings


class PriceUnknown(ValueError):
    """This option's price is not known: no ₹ estimate (and no call card offering it as free)."""


@dataclass(frozen=True)
class SpeechPrice:
    option: SpeechOption
    hear_inr_per_minute: float | None  # None: unknown
    voice_inr_per_1k_chars: float | None
    hear_free_seconds: int = 0  # a month, for the whole deployment
    voice_free_chars: int = 0
    can_bill: bool = True  # False: the option can never charge (laptop, Azure F0)
    paid: bool = False  # True: off unless the owner said YES (Sarvam)

    def inr_per_minute(self) -> float:
        if self.hear_inr_per_minute is None:
            raise PriceUnknown(f"{self.option.value}: hearing price unknown")
        return self.hear_inr_per_minute

    def inr_per_chars(self, chars: int) -> float:
        if self.voice_inr_per_1k_chars is None:
            raise PriceUnknown(f"{self.option.value}: voice price unknown")
        return self.voice_inr_per_1k_chars * chars / 1_000


def speech_prices(s: Settings, usd_inr: float) -> dict[SpeechOption, SpeechPrice]:
    """Every option's price at `usd_inr` rupees a dollar (`billing.fx`'s rate of the day)."""
    if usd_inr <= 0:
        raise ValueError("a rupee rate is above 0")
    bhashini = s.voice_price_bhashini_inr_per_minute
    return {
        SpeechOption.LAPTOP: SpeechPrice(SpeechOption.LAPTOP, 0.0, 0.0, can_bill=False),
        SpeechOption.GOOGLE: SpeechPrice(
            SpeechOption.GOOGLE,
            round(s.voice_price_stt_usd_per_min * usd_inr, 4),
            round(s.voice_price_chirp3_hd_usd_per_m / 1_000 * usd_inr, 4),
            hear_free_seconds=s.voice_stt_free_seconds,  # shared with JARVIS's English voice
            voice_free_chars=s.voice_tts_free_chars,
        ),
        SpeechOption.AZURE: SpeechPrice(
            SpeechOption.AZURE,
            s.voice_price_azure_f0_inr_per_hour / 60,
            s.voice_price_azure_f0_inr_per_m_chars / 1_000,
            hear_free_seconds=s.voice_azure_f0_stt_free_seconds,
            voice_free_chars=s.voice_azure_f0_tts_free_chars,
            can_bill=False,
        ),
        # hearing priced only when set; its voice has no published price: unknown
        SpeechOption.BHASHINI: SpeechPrice(SpeechOption.BHASHINI, bhashini, None),
        SpeechOption.SARVAM: SpeechPrice(
            SpeechOption.SARVAM,
            round(s.voice_price_sarvam_inr_per_hour / 60, 4),
            round(s.voice_price_sarvam_inr_per_10k_chars / 10, 4),
            paid=True,
        ),
    }


__all__ = ["PriceUnknown", "SpeechPrice", "speech_prices"]

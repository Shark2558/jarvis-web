# src/jarvis/calls/speech/build.py
"""The speech options this deployment has, built from `Settings` (R18 B; what the I1 join wires).

    google    when JARVIS's cloud voice is on (`voice_cloud`) and its credentials exist: the
              voice's own HTTP client and token source are reused (`jarvis.voice`)
    azure     when `azure_speech_key` is set (F0; its region `azure_speech_region`)
    bhashini  when `bhashini_user_id` and `bhashini_api_key` are set
    sarvam    when `sarvam_api_key` is set AND `sarvam_enabled`; each request still asks the
              owner's own YES (`sarvam_on`, his Calls setting) and is refused without it
    laptop    the call desk's local models, when the desk offers them (passed in by the hub)

An option that is not built is listed in `missing` with the reason in plain words, for the
language table. One `SpeechMeter` per owner (and per call, to tally that call's ₹).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx

from jarvis.calls.models import SpeechOption
from jarvis.calls.ports import Hearing, Voice
from jarvis.calls.prices import speech_prices
from jarvis.calls.speech.azure import AzureHearing, AzureVoice, allowances
from jarvis.calls.speech.bhashini import BhashiniHearing, BhashiniPipeline, BhashiniVoice
from jarvis.calls.speech.catalogue import AZURE, BHASHINI, GOOGLE, LAPTOP, SARVAM
from jarvis.calls.speech.google import GoogleHearing, GoogleVoice
from jarvis.calls.speech.meter import SpeechMeter
from jarvis.calls.speech.rest import IN_CALL, RetryPolicy
from jarvis.calls.speech.sarvam import SarvamHearing, SarvamVoice
from jarvis.config import Settings
from jarvis.voice.catalogue import PriceList
from jarvis.voice.ports import TokenSource

OwnerYes = Callable[[], Awaitable[bool]]


@dataclass(frozen=True)
class SpeechOptions:
    hearing: dict[str, Hearing] = field(default_factory=dict)
    voices: dict[str, Voice] = field(default_factory=dict)
    missing: dict[str, str] = field(default_factory=dict)  # option -> why it is not here


def _sarvam_yes(s: Settings, owner_yes: OwnerYes) -> OwnerYes:
    async def yes() -> bool:
        return bool(s.sarvam_enabled) and await owner_yes()

    return yes


def build_speech(
    s: Settings,
    meter: SpeechMeter,
    *,
    http: httpx.AsyncClient,
    google_tokens: TokenSource | None,
    google_http: httpx.AsyncClient | None = None,
    sarvam_on: OwnerYes,
    laptop: tuple[Hearing | None, Voice | None] = (None, None),
    policy: RetryPolicy = IN_CALL,
) -> SpeechOptions:
    out = SpeechOptions()
    hearing_l, voice_l = laptop
    if hearing_l is not None:
        out.hearing[LAPTOP] = hearing_l
    if voice_l is not None:
        out.voices[LAPTOP] = voice_l
    if hearing_l is None and voice_l is None:
        out.missing[LAPTOP] = "The call desk has not offered its laptop speech models."

    if s.voice_cloud and google_tokens is not None and not google_tokens.not_configured:
        prices = PriceList.from_settings(s)
        g_http = google_http or http
        out.hearing[GOOGLE] = GoogleHearing(g_http, google_tokens, meter, prices, policy=policy)
        out.voices[GOOGLE] = GoogleVoice(g_http, google_tokens, meter, prices, policy=policy)
    else:
        out.missing[GOOGLE] = "JARVIS's cloud voice (Google) is off or not set up."

    if s.azure_speech_key is not None:
        stt, tts = allowances(s.voice_azure_f0_stt_free_seconds, s.voice_azure_f0_tts_free_chars)
        key, region = s.azure_speech_key, s.azure_speech_region
        out.hearing[AZURE] = AzureHearing(http, key, region, meter, allowance=stt, policy=policy)
        out.voices[AZURE] = AzureVoice(http, key, region, meter, allowance=tts, policy=policy)
    else:
        out.missing[AZURE] = "No Azure free-tier key is set (it is optional)."

    if s.bhashini_user_id and s.bhashini_api_key is not None:
        pipeline = BhashiniPipeline(http, s.bhashini_user_id, s.bhashini_api_key, policy=policy)
        per_minute = s.voice_price_bhashini_inr_per_minute
        out.hearing[BHASHINI] = BhashiniHearing(pipeline, meter, inr_per_minute=per_minute)
        out.voices[BHASHINI] = BhashiniVoice(pipeline, meter)
    else:
        out.missing[BHASHINI] = "Bhashini is not set up (it is optional)."

    if s.sarvam_api_key is not None and s.sarvam_enabled:
        yes = _sarvam_yes(s, sarvam_on)
        price = speech_prices(s, 1.0)[SpeechOption.SARVAM]  # in rupees: no dollar rate enters
        out.hearing[SARVAM] = SarvamHearing(
            http, s.sarvam_api_key, meter, enabled=yes,
            inr_per_hour=price.inr_per_minute() * 60, policy=policy,
        )  # fmt: skip
        out.voices[SARVAM] = SarvamVoice(
            http, s.sarvam_api_key, meter, enabled=yes,
            inr_per_10k_chars=price.inr_per_chars(10_000), policy=policy,
        )  # fmt: skip
    else:
        out.missing[SARVAM] = "Sarvam is a paid option and is off."
    return out


__all__ = ["OwnerYes", "SpeechOptions", "build_speech"]

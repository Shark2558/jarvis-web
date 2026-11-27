# src/jarvis/calls/speech/errors.py
"""What a call's speech adapter raises (R18 B; Layer 6): one family, plain words, no vendor text.

Every adapter (Google, Azure free tier, Bhashini, Sarvam; the laptop's through the desk) maps its
vendor's failures to these. All of them are `jarvis.calls.ports.SpeechUnavailable` (I0's seam:
"the caller tries the next option or ends the call politely"), so the call engine catches one
class and may look closer:

    OptionUnavailable  the option is off, not set up, refused our key, down or too slow
                       (`reason`; `maybe_billed`: the request may have reached the vendor)
    SpeechBusy         the vendor throttled us (`retry_after_s`)
    SpeechRejected     the vendor refused this audio or text (an invalid request, not an outage)
    AllowanceUsedUp    a free tier's monthly allowance is used up (Azure F0 cannot bill: it stops)
    PaidOptionOff      a paid option (Sarvam) that the owner has not turned on
    NotOffered         the option does not hear or speak that language

`str(exc)` is safe to show the owner; `option` names the option ("google", "azure", ...).
"""

from __future__ import annotations

from typing import Literal

from jarvis.calls.ports import SpeechUnavailable

Reason = Literal[
    "not_configured",
    "off",
    "auth",
    "upstream_error",
    "timeout",
    "budget",
    "meter_unreadable",
    "bad_answer",
]

_LABEL = {
    "laptop": "The laptop's speech",
    "google": "Google's speech service",
    "azure": "Microsoft Azure's free speech tier",
    "bhashini": "Bhashini",
    "sarvam": "Sarvam",
}
_WHY: dict[str, str] = {
    "not_configured": "is not set up on this server",
    "off": "is switched off",
    "auth": "refused JARVIS's key; check the key in the settings",
    "upstream_error": "could not answer just now; try again shortly",
    "timeout": "took too long to answer",
    "budget": "would cost money and this month's limit does not allow it",
    "meter_unreadable": "is not used: its usage can't be counted just now",
    "bad_answer": "sent an answer JARVIS could not read",
}


def label(option: str) -> str:
    return _LABEL.get(option, "That speech option")


class SpeechError(SpeechUnavailable):
    def __init__(self, option: str, message: str) -> None:
        self.option = option
        super().__init__(message)


class OptionUnavailable(SpeechError):
    def __init__(self, option: str, reason: Reason, *, maybe_billed: bool = False) -> None:
        self.reason: Reason = reason
        self.maybe_billed = maybe_billed
        super().__init__(option, f"{label(option)} {_WHY[reason]}.")


class SpeechBusy(SpeechError):
    def __init__(self, option: str, retry_after_s: float = 5.0) -> None:
        self.retry_after_s = retry_after_s
        super().__init__(option, f"{label(option)} is busy right now; try again in a few seconds.")


class SpeechRejected(SpeechError):
    def __init__(self, option: str) -> None:
        super().__init__(option, f"{label(option)} refused that audio or text.")


class AllowanceUsedUp(SpeechError):
    def __init__(self, option: str, what: str) -> None:
        super().__init__(
            option,
            f"{label(option)}: this month's free allowance for {what} is used up. It comes back "
            "at the start of next month; JARVIS uses another option meanwhile.",
        )


class PaidOptionOff(SpeechError):
    def __init__(self, option: str) -> None:
        super().__init__(
            option,
            f"{label(option)} is a paid option and is off. Turn it on in the Calls settings, "
            "with its price, to use it.",
        )


class NotOffered(SpeechError):
    def __init__(self, option: str, lang: str) -> None:
        super().__init__(option, f"{label(option)} does not offer {lang}.")


__all__ = [
    "AllowanceUsedUp",
    "NotOffered",
    "OptionUnavailable",
    "PaidOptionOff",
    "Reason",
    "SpeechBusy",
    "SpeechError",
    "SpeechRejected",
    "label",
]

# src/jarvis/helpers/today/upi.py
"""The prepared payment: an NPCI UPI pay intent (docs/plans/r11-free-helpers.md D7).

`upi://pay?pa=<UPI ID>&pn=<payee name>&am=<rupees, 2 decimals>&cu=INR&tn=<note>`: the parameters
of NPCI's UPI linking specification (pa and pn mandatory; am a decimal string, so the payer can't
edit it; cu only INR; tn a short description). Values are percent-encoded per RFC 3986 (a space
is %20, never "+": the specification says so, and some apps read "+" as a plus), `@` kept as is.
A payer-initiated intent: P2P collect requests ended on 1 Oct 2025 and are not used. JARVIS only
writes the link; he opens it in his UPI app, checks it and enters his PIN there. The link is never
stored or logged by anything in Part A. `pn` passes the same payee check his entry did (the safe
set) and `tn` the same number check, so nothing here can carry a UPI ID or a card number.
"""

from __future__ import annotations

from urllib.parse import quote

from jarvis.helpers.today.models import (
    NOTE_MAX,
    NUMBER_REFUSAL,
    PAY_CAP_PAISE,
    BillRefused,
    clean_payee,
    has_number,
    inr,
    parse_upi,
)
from jarvis.tools.card import one_line

SCHEME = "upi://pay?"
CAP_REFUSAL = (
    f"That is over your {inr(PAY_CAP_PAISE)} limit for a prepared payment, Sir. Pay it from your "
    "bank's app."
)


def amount_text(paise: int) -> str:
    """`am`: rupees with exactly two decimals, within the cap."""
    if isinstance(paise, bool) or not isinstance(paise, int) or paise <= 0:
        raise BillRefused("A payment needs an amount of more than ₹0.")
    if paise > PAY_CAP_PAISE:
        raise BillRefused(CAP_REFUSAL)
    return f"{paise // 100}.{paise % 100:02d}"


def upi_link(*, pa: str, pn: str, paise: int, tn: str) -> str:
    payee = parse_upi(pa)
    name = clean_payee(pn)
    if not name:
        raise BillRefused("A UPI payment needs the payee's name.")
    note = one_line(tn, NOTE_MAX)
    if has_number(note):
        raise BillRefused(NUMBER_REFUSAL)
    params = (
        ("pa", payee),
        ("pn", name),
        ("am", amount_text(paise)),
        ("cu", "INR"),
        ("tn", note),
    )
    return SCHEME + "&".join(f"{k}={quote(v, safe='@')}" for k, v in params if v)


__all__ = ["CAP_REFUSAL", "SCHEME", "amount_text", "upi_link"]

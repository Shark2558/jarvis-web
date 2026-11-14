# src/jarvis/helpers/house/service_request.py
"""Row 102, home services (docs/plans/r14-hardening.md D2): PREPARED, never booked.

Urban Company (the default site) has no public API, and booking or paying for him would be an
irreversible act on his behalf. So `maint_service_request` (R1, one of R11's house tools, row
"household" through `maint_*`, Telegram open) only writes:

- a fixed-template request: the job (one of `JOBS`), his problem in his words (at most 200
  characters, one line) and his preferred time (at most 40). JARVIS adds nothing of his: no
  address, no phone number, no district; text that carries a phone number, a PIN code, an e-mail
  address or a link is refused, so none of those goes into a request by accident;
- the booking site's address AS TEXT (`helpers.sources.URBAN_COMPANY_URL`): no card, no tap, no
  auto-open (a checked tap card for it is deferred, plan D16).

To message a provider he picks, the brain uses the existing `whatsapp_draft` (a draft he sends
himself). Nothing here books, pays, sends or opens anything; the R3 rule stands for anything that
would.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from jarvis.helpers.sources import URBAN_COMPANY_NAME, URBAN_COMPANY_URL
from jarvis.tools.card import one_line

TOOL = "maint_service_request"
PROBLEM_MAX = 200
WHEN_MAX = 40
JOBS: Mapping[str, str] = MappingProxyType(
    {
        "plumber": "a plumber",
        "electrician": "an electrician",
        "carpenter": "a carpenter",
        "ac": "an AC technician",
        "cleaning": "home cleaning",
        "appliance": "an appliance repair technician",
        "pest": "pest control",
        "other": "a home service professional",
    }
)
NO_PROBLEM = "to be described on the visit"
ANY_TIME = "any time that suits"
PRIVATE_LINE = "Address and phone number: shared only with the provider you choose."
CONTACT_REFUSAL = (
    "A service request carries no phone number, PIN code, e-mail address or link, Sir: give "
    "those to the provider you choose yourself."
)
NEVER_BOOKS = (
    "I never book or pay, Sir. To book it yourself, {site}'s address is:\n{url}\n"
    "To send it to someone you know, ask me to draft a WhatsApp to them; you send it yourself."
)
_DIGITS_MIN = 6  # a phone number, a PIN code (a date, a time or a flat number is fewer)
_DIGIT_RUN = re.compile(r"[0-9][0-9 ()+./-]*[0-9]")
_DATE = re.compile(r"(?<![0-9])[0-9]{1,4}[/.-][0-9]{1,2}[/.-][0-9]{1,4}(?![0-9])")
_CONTACT = re.compile(r"@|https?:|www\.|\.(?:com|in|net|org)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ServiceRequest:
    job: str
    problem: str
    when: str

    @property
    def text(self) -> str:
        return "\n".join(
            (
                f"Service request: {JOBS[self.job]}.",
                f"Problem: {self.problem or NO_PROBLEM}.",
                f"Preferred time: {self.when or ANY_TIME}.",
                PRIVATE_LINE,
            )
        )


def _contact(text: str) -> bool:
    flat = unicodedata.normalize("NFKC", text)
    if _CONTACT.search(flat):
        return True
    flat = _DATE.sub(" ", flat)  # "14/11/2026" is a day, not a phone number
    return any(sum(c.isdigit() for c in m[0]) >= _DIGITS_MIN for m in _DIGIT_RUN.finditer(flat))


def _words(value: Any, limit: int, what: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{what} must be text.")
    text = one_line(value, limit + 1).strip(" .")
    if len(text) > limit:
        raise ValueError(f"{what} is at most {limit} characters.")
    if _contact(text):
        raise ValueError(CONTACT_REFUSAL)
    return text


def clean_request(job: Any, problem: Any = None, when: Any = None) -> ServiceRequest:
    """The request from the call's arguments, or ValueError in plain words (never echoing them)."""
    if not isinstance(job, str) or job.strip().lower() not in JOBS:
        raise ValueError("job is one of: " + ", ".join(JOBS) + ".")
    return ServiceRequest(
        job=job.strip().lower(),
        problem=_words(problem, PROBLEM_MAX, "The problem"),
        when=_words(when, WHEN_MAX, "The preferred time"),
    )


def check_request(a: dict[str, Any]) -> None:
    clean_request(a.get("job"), a.get("problem"), a.get("when"))


async def service_request(a: dict[str, Any]) -> dict[str, Any]:
    """The tool: the request text and the site's address as text. Reads nothing of his."""
    req = clean_request(a.get("job"), a.get("problem"), a.get("when"))
    tail = NEVER_BOOKS.format(site=URBAN_COMPANY_NAME, url=URBAN_COMPANY_URL)
    return {
        "request": req.text,
        "booking_site": URBAN_COMPANY_NAME,
        "booking_address": URBAN_COMPANY_URL,
        "booked": False,
        "paid": False,
        "message": f"{req.text}\n\n{tail}",
    }


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "job": {"type": "string", "enum": list(JOBS)},
        "problem": {"type": "string", "maxLength": PROBLEM_MAX},
        "when": {
            "type": "string",
            "maxLength": WHEN_MAX,
            "description": "his words, e.g. Sat 10am",
        },
    },
    "required": ["job"],
}
DESCRIPTION = (
    "Write a request for a home service (plumber, electrician, carpenter, AC, cleaning, "
    "appliance repair, pest control, other) from his problem and preferred time, and give the "
    f"booking site's address ({URBAN_COMPANY_NAME}) as text. It never books, pays, sends or opens "
    "anything: he books it himself, or asks you to draft a WhatsApp to a person he picks "
    "(whatsapp_draft, a draft he sends). Never put an address or a phone number in it."
)

__all__ = [
    "CONTACT_REFUSAL",
    "DESCRIPTION",
    "JOBS",
    "PROBLEM_MAX",
    "SCHEMA",
    "TOOL",
    "WHEN_MAX",
    "ServiceRequest",
    "check_request",
    "clean_request",
    "service_request",
]

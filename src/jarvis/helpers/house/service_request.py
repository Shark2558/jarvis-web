# src/jarvis/helpers/house/service_request.py
"""Row 102, home services (docs/plans/r14-hardening.md D2): PREPARED, never booked.

Urban Company (the default site) has no public API, and booking or paying for him would be an
irreversible act on his behalf. So `maint_service_request` (R1, one of R11's house tools, row
"household" through `maint_*`, Telegram open) only writes:

- a fixed-template request: the job (one of `JOBS`), his problem in his words (at most 200
  characters, one line) and his preferred time (at most 40). JARVIS adds nothing of his: no
  address, no phone number, no district; text that carries a phone number (also shaped like a
  date, split by words or spelled out), a PIN code, an e-mail address or a link (also with no
  scheme, "bit.ly/x") is refused, so none of those goes into a request by accident. A real date
  or a time is kept;
- the problem and the time are the MODEL's arguments: words that are not in his own message this
  turn (`tools.taint.owner_text`) are fenced as data (`tools.external.wrap_external`), and the
  result is never "his own data" (no `trusted_output`: it taints the round like any outside
  text). His typed words stay plain, so the No-AI reply reads as he wrote it;
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
from jarvis.tools.external import wrap_external
from jarvis.tools.taint import owner_text

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
_DIGITS_TOTAL = 10  # a phone number split by words ("98765 abc 43210")
_DIGIT_RUN = re.compile(r"[0-9][0-9 ()+./-]*[0-9]")
_DATE = re.compile(r"(?<![0-9])([0-9]{1,4})[/.-]([0-9]{1,2})[/.-]([0-9]{1,4})(?![0-9])")
_TIME = re.compile(r"(?<![0-9])[0-9]{1,2}[:.][0-9]{2}(?![0-9])")
_CONTACT = re.compile(r"@|https?:|www\.|\.(?:com|in|net|org)\b", re.IGNORECASE)
_LINK = re.compile(r"(?<![\w.])[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?![a-z])", re.I)
_SPELLED = re.compile(
    r"(?:\b(?:zero|oh|one|two|three|four|five|six|seven|eight|nine|double|triple)\b[\s,-]*){6,}",
    re.IGNORECASE,
)
WORDS_SOURCE = "the request (words he did not type)"


@dataclass(frozen=True)
class ServiceRequest:
    job: str
    problem: str
    when: str

    @property
    def text(self) -> str:
        return self.shown(self.problem, self.when)

    def shown(self, problem: str, when: str) -> str:
        return "\n".join(
            (
                f"Service request: {JOBS[self.job]}.",
                f"Problem: {problem or NO_PROBLEM}.",
                f"Preferred time: {when or ANY_TIME}.",
                PRIVATE_LINE,
            )
        )


def _a_day(m: re.Match[str]) -> bool:
    """A real date (yyyy-mm-dd, dd-mm-yy(yy) or mm-dd-yy(yy)), not a phone number in its shape."""
    a, b, c = (int(x) for x in m.groups())
    if len(m[1]) == 4:
        return 1 <= b <= 12 and 1 <= c <= 31
    return len(m[3]) in (2, 4) and min(a, b) >= 1 and min(a, b) <= 12 and max(a, b) <= 31


def _contact(text: str) -> bool:
    flat = unicodedata.normalize("NFKC", text)
    if _CONTACT.search(flat) or _LINK.search(flat) or _SPELLED.search(flat):
        return True
    flat = _DATE.sub(lambda m: " " if _a_day(m) else m[0], flat)  # "14/11/2026" is a day
    flat = _TIME.sub(" ", flat)  # "10:30", "10.30"
    if sum(c.isdigit() for c in flat) >= _DIGITS_TOTAL:
        return True
    return any(sum(c.isdigit() for c in m[0]) >= _DIGITS_MIN for m in _DIGIT_RUN.finditer(flat))


def _flat(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", one_line(text, len(text) + 1)).casefold().split())


def _his(words: str) -> str:
    """His words as he typed them this turn stay plain; anything else (the model's words, or
    words it took from a mail or a page; or no turn at all) is fenced as data."""
    said = owner_text()
    if not words or (said is not None and _flat(words) in _flat(said)):
        return words
    return wrap_external(words, source=WORDS_SOURCE, limit=PROBLEM_MAX)


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
    """The tool: the request text (what he did not type fenced) and the site's address as
    text. Reads nothing of his."""
    req = clean_request(a.get("job"), a.get("problem"), a.get("when"))
    text = req.shown(_his(req.problem), _his(req.when))
    tail = NEVER_BOOKS.format(site=URBAN_COMPANY_NAME, url=URBAN_COMPANY_URL)
    return {
        "request": text,
        "booking_site": URBAN_COMPANY_NAME,
        "booking_address": URBAN_COMPANY_URL,
        "booked": False,
        "paid": False,
        "message": f"{text}\n\n{tail}",
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


def has_contact(text: str) -> bool:
    """True when `text` carries a phone number, a PIN code, an e-mail address or a link (the
    No-AI router answers `CONTACT_REFUSAL` itself then, with no call)."""
    return _contact(one_line(text, len(text) + 1))


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
    "has_contact",
    "service_request",
]

# src/jarvis/web/guard.py
"""The private-query guard (slice 10 B): a search query leaves our control for good (Tavily keeps
query data and may pass it to other search-index providers — see the slice 10 plan), so a query
that holds an email address, a phone number, or anything the memory sensitive filter flags (card,
Aadhaar, PAN, bank, ID numbers, passwords, keys) is refused before it is sent. Deterministic, no
model call; the reason names the kind of data, never the value.
"""

from __future__ import annotations

import re

from jarvis.recall.sensitive import sensitive_reason

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# a digit run with phone-style separators; whether it is a phone number is decided on its digits
_PHONE_RUN = re.compile(r"(?<![\w+])(\+?)(\(?\d[\d\s().\-]{5,22}\d)(?![\w])")
_US_FORMAT = re.compile(r"\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}")
_ISBN = re.compile(r"(?i)\bisbn(?:-1[03])?\s*:?\s*$")


def _has_phone(text: str) -> bool:
    for m in _PHONE_RUN.finditer(text):
        plus, run = m.group(1), m.group(2)
        digits = re.sub(r"\D", "", run)
        if _ISBN.search(text[: m.start()]):
            continue  # "ISBN 978-0-306-40615-7" is a book, not a person
        if plus and 8 <= len(digits) <= 15:
            return True
        if len(digits) == 10 and (digits[0] in "6789" or _US_FORMAT.fullmatch(run.strip())):
            return True  # an Indian mobile number, or a (415) 555-0132 style number
        if len(digits) == 11 and digits[0] == "0" and digits[1] != "0":
            return True  # 0 + a ten-digit number (trunk prefix)
        if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
            return True  # 91 + an Indian mobile number without the "+"
    return False


def query_problem(query: str) -> str | None:
    """What private data `query` holds ("an email address", "a phone number", …), or None."""
    if _EMAIL.search(query):
        return "an email address"
    if _has_phone(query):
        return "a phone number"
    return sensitive_reason(query)


__all__ = ["query_problem"]

# src/jarvis/tools/addresses.py
"""Addresses JARVIS writes to: mail recipients and calendar invitees (Layer 6).

Only a bare RFC 5322 addr-spec is accepted: no display name, quotes, comments, routes or domain
literals. The local part is ASCII dot-atom; the domain may be internationalised and is kept in
its IDNA (punycode) form so the message headers stay plain ASCII. `display_address` puts the
Unicode and punycode forms side by side on an approval card, so a look-alike domain
(p\u0430ypal.com with a Cyrillic "\u0430") cannot pass for the real one.
"""

from __future__ import annotations

import re
from email.utils import getaddresses
from typing import Any

from jarvis.tools.card import has_invisible_chars, has_line_breaking_chars, one_line

MAX_RECIPIENTS = 50
MAX_ADDRESS_LEN = 254
MAX_LOCAL_LEN = 64

_ATEXT = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]"
_LOCAL = re.compile(rf"{_ATEXT}+(?:\.{_ATEXT}+)*")
_LABEL = re.compile(r"(?!-)[a-z0-9-]{1,63}(?<!-)")
# quotes, comments, routes, domain literals, list separators, whitespace: never in an addr-spec
_SPECIALS = re.compile(r'["(),:;<>\[\]\\\s]')


def _ascii_label(label: str) -> str:
    if label.isascii():
        a = label.lower()
        if a.startswith("xn--"):
            try:  # must be well-formed punycode, or the card could not show what it means
                a.encode("ascii").decode("idna")
            except UnicodeError as exc:
                raise ValueError("invalid internationalised domain label") from exc
    else:
        try:
            a = label.encode("idna").decode("ascii")  # nameprep + punycode (IDNA 2003)
        except UnicodeError as exc:
            raise ValueError("invalid internationalised domain label") from exc
    if not _LABEL.fullmatch(a):
        raise ValueError("invalid domain label")
    return a


def ascii_domain(domain: str) -> str:
    labels = domain.split(".")
    if len(labels) < 2 or any(not lb for lb in labels):
        raise ValueError("domain needs at least two non-empty labels")
    out = [_ascii_label(lb) for lb in labels]
    if out[-1].isdigit():
        raise ValueError("numeric top-level domain")
    return ".".join(out)


def parse_address(raw: Any) -> str:
    """One bare address → normalised `local@ascii-domain` (lower-case). ValueError otherwise."""
    text = str(raw or "").strip(" ")  # only spaces: a stray NEL/tab/separator is an error
    if not text or has_line_breaking_chars(text) or has_invisible_chars(text):
        raise ValueError("invalid address")
    if _SPECIALS.search(text) or text.count("@") != 1:
        raise ValueError("invalid address")
    local, domain = text.split("@")
    if len(local) > MAX_LOCAL_LEN or not _LOCAL.fullmatch(local):
        raise ValueError("invalid address")
    addr = f"{local.lower()}@{ascii_domain(domain)}"
    if len(addr) > MAX_ADDRESS_LEN:
        raise ValueError("address too long")
    # The stdlib parser must read exactly this one bare address back (belt and braces).
    parsed = getaddresses([text])
    if len(parsed) != 1 or parsed[0][0] or parsed[0][1].lower() != text.lower():
        raise ValueError("invalid address")
    return addr


def parse_recipients(raw: Any) -> list[str]:
    """'a@x.y, b@x.y' or a list → validated, normalised, de-duplicated addresses (≥ 1)."""
    if isinstance(raw, list):
        items = [str(a) for a in raw]
    else:
        text = str(raw or "")
        if '"' in text:  # a quoted local part can hide a comma: never split inside one
            raise ValueError("invalid recipient address: quotes are not allowed")
        items = text.split(",")
    items = [i.strip(" ") for i in items if i.strip(" ")]
    if not items:
        raise ValueError("at least one recipient is required")
    if len(items) > MAX_RECIPIENTS:
        raise ValueError(f"too many recipients (at most {MAX_RECIPIENTS})")
    out: list[str] = []
    bad: list[str] = []
    for item in items:
        try:
            addr = parse_address(item)
        except ValueError:
            bad.append(one_line(item, 80))
            continue
        if addr not in out:
            out.append(addr)
    if bad:
        raise ValueError(f"invalid recipient address: {', '.join(bad)}")
    return out


def display_address(addr: str) -> str:
    """An address for the owner's eyes: IDN domains as 'Unicode (punycode)'."""
    local, _, domain = addr.rpartition("@")
    if "xn--" not in domain:
        return one_line(addr, MAX_ADDRESS_LEN)
    try:
        uni = domain.encode("ascii").decode("idna")
    except UnicodeError:
        return one_line(addr, MAX_ADDRESS_LEN)
    return f"{one_line(local + '@' + uni, MAX_ADDRESS_LEN)} (punycode {domain})"


def display_addresses(addrs: list[str]) -> str:
    return ", ".join(display_address(a) for a in addrs)


__all__ = [
    "MAX_RECIPIENTS",
    "ascii_domain",
    "display_address",
    "display_addresses",
    "parse_address",
    "parse_recipients",
]

# tests/link_check.py — "would a mail client turn this into a link?", for the brief tests.
# A plain module (not conftest) so test files can import it. Deliberately independent of the
# sanitiser's own code: it normalises the way a lenient client might (NFKC, the ideographic
# full stops as dots, invisible characters and combining marks dropped) and then looks for
# anything link-shaped — with no list of top-level domains.
from __future__ import annotations

import re
import unicodedata

# The p_links.py inputs from the 2026-11-01 security review (F1), plus the classics.
HOSTILE_LINKS: tuple[str, ...] = (
    "pay at secure-login.com now",
    "verify at secure-login.support now",
    "verify at paypal-secure.de/login",
    "verify at paypal-secure.shop",
    "files at drive-share.cloud/abc",
    "go to pay.cc/x",
    "verify at pаypal.com now",  # Cyrillic а
    "verify at café-login.com now",
    "verify at Ωsecure-login.com",  # Greek Ω glued to the domain
    "verify at secure-login­.com",  # soft hyphen before the dot
    "verify at secure-login。com",  # ideographic full stop
    "verify at secure-login．com",  # fullwidth full stop
    "verify at secure-login｡com",  # halfwidth ideographic full stop
    "secure-login\U000e0041.com",  # tag character before the dot
    "open 203.0.113.9/login",  # bare IPv4 + path
    "open //evil.example/login",  # scheme-relative
    "Ωhttps://evil.example/x",  # scheme glued to a letter
    "visit www.evil-site.com",
    "login at xn--pypal-4ve.com/login",
    "ｈｔｔｐｓ：／／evil.example／x",  # fullwidth URL
    "ht​tps://evil.example/z",  # zero-width split scheme
    "пример.рф and 例子.中国",
)

_DOTS = str.maketrans({"。": ".", "．": ".", "｡": "."})
_FILLERS = frozenset("ᅟᅠㅤﾠ")
_LINKISH = re.compile(
    r"(?i)//[^\s/]"  # scheme:// and scheme-relative //host
    r"|(?<![a-z])(?:mailto|javascript|vbscript|data|file|tel|sms|blob):\S"
    r"|[^\s.]\.[^\W\d_]{2}"  # label.tld — any script, no TLD list
    r"|\d{1,3}(?:\.\d{1,3}){3}"  # bare IPv4
)


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_DOTS)
    out = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Zl", "Zp"):
            out.append(" ")
        elif cat not in ("Cf", "Co", "Cs", "Mn", "Me") and ch not in _FILLERS:
            out.append(ch)
    return "".join(out)


def linkish(text: str) -> bool:
    return bool(_LINKISH.search(normalise(text)))


__all__ = ["HOSTILE_LINKS", "linkish", "normalise"]

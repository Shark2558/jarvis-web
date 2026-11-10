# src/jarvis/buildbook/gen/scrub.py
"""R6 D3: no personal data in the book. Every text the generator takes from the repository (plan
lines, docstrings, setting descriptions) passes `Scrubber.clean`, which replaces with "[removed]":

    url     a URL (any case; `http(s)://`, `gs://`, `s3://`, `ftp://` or a bare `www.`) unless it
            is http(s) on the public-docs allow list (`PUBLIC_DOCS`) with no user part and, once
            percent-decoded, no e-mail address or secret in it
    host    a `*.run.app`, `*.ts.net` or other project-id-like host (`PRIVATE_HOSTS`), and an
            Artifact Registry / Container Registry / Cloud Storage address with its path
    email   an e-mail address
    phone   an Indian mobile number, with or without +91 / 0091 / 0 and any single spaces,
            hyphens or dots between its digits ("98765 43210", "987 654 3210"); an 11-digit
            number starting with 0 (a landline with its STD code); a number written with "+"
            and 8-15 digits
    digits  any run of 10 or more digits (account and project numbers), also when written in
            groups of 3 or more digits split by single spaces or hyphens ("1234 5678 9012");
            dates (2-digit groups), versions, decimals and IP addresses are left alone
    secret  a secret-shaped string (the same shapes the snapshot scan refuses, `SECRET_SHAPES`;
            a private key as its whole block)
    name    any word whose SHA-256 is in gen/redact.json (hashes only: no one named), matched on
            its NFKD form with accents, zero-width and other format characters removed, Cyrillic /
            Greek look-alikes folded and case folded; also its camel-case parts and the word
            without leading or trailing digits ("NameSurname", "name2558")

`verify` walks the finished book and raises `ScrubLeak` (paths and kinds, never the text) if any
of these is left anywhere but a commit id or a code symbol. `NoScrub` is the eval's negative
control: with it a plan's e-mail reaches book.json, and the `gen` suite must fail.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable
from functools import lru_cache
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from urllib.parse import unquote, urlsplit

from jarvis.buildbook.gen.repo import GenError

REMOVED = "[removed]"
# package data (pyproject.toml), read through importlib.resources: the deploy job's non-editable
# install finds it; a missing file stays an error (the name scrub must never turn itself off)
REDACT_FILE: Traversable | Path = files("jarvis.buildbook.gen") / "redact.json"
SKIP_KEYS = frozenset({"sha", "symbol"})  # a commit id, a code symbol: never personal

PUBLIC_DOCS = frozenset(
    {
        "ai.google.dev",
        "cloud.google.com",
        "core.telegram.org",
        "developer.mozilla.org",
        "developers.google.com",
        "docs.anthropic.com",
        "docs.claude.com",
        "docs.github.com",
        "docs.pydantic.dev",
        "docs.python.org",
        "fastapi.tiangolo.com",
        "firebase.google.com",
        "platform.claude.com",
        "pypi.org",
        "spdx.org",
        "support.google.com",
        "threejs.org",
        "www.home-assistant.io",
        "www.w3.org",
    }
)
PRIVATE_HOSTS = (
    "run.app",
    "appspot.com",
    "firebaseapp.com",
    "web.app",
    "cloudfunctions.net",
    "ts.net",
)
# A private key is matched as its WHOLE block (header to END), so a listed fake covers that one
# block and never every key with the same header; a header with no END is matched alone.
_KEY_BLOCK = (
    r"-----BEGIN ((?:[A-Z0-9]+ )*)PRIVATE KEY((?: BLOCK)?)-----"
    r"(?:[\s\S]*?-----END \1PRIVATE KEY\2-----)?"
)
_NOT_TOKEN = r"(?![A-Za-z0-9_-])"
SECRET_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(_KEY_BLOCK)),  # PEM, OpenSSH and PGP ("... KEY BLOCK")
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("google_oauth_secret", re.compile(r"GOCSPX-[A-Za-z0-9_-]{20,}")),
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("openrouter_key", re.compile(r"sk-or-v1-[A-Za-z0-9]{20,}")),
    ("openai_key", re.compile(r"(?<![A-Za-z0-9_-])sk-(?!ant-|or-v1-)[A-Za-z0-9_-]{20,}")),
    ("groq_key", re.compile(r"gsk_[A-Za-z0-9]{20,}")),
    ("tavily_key", re.compile(r"tvly-[A-Za-z0-9_-]{20,}")),
    ("github_token", re.compile(r"ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{22,}")),
    ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    # also inside api.telegram.org/bot<id>:<secret>, and a secret ending in "-" or "_"
    ("telegram_token", re.compile(r"(?<![0-9])[0-9]{8,10}:[A-Za-z0-9_-]{35}" + _NOT_TOKEN)),
)
_SECRET_KINDS = frozenset(kind for kind, _ in SECRET_SHAPES)
_URL = re.compile(
    r"\b(?:https?|gs|s3|ftp)://[^\s<>\"'`)\]]+"
    r"|(?<![\w.@/-])www\.[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:/[^\s<>\"'`)\]]*)?",
    re.IGNORECASE,
)
_HOST = re.compile(
    r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:" + "|".join(re.escape(h) for h in PRIVATE_HOSTS) + r")\b"
    r"|\b(?:[a-z0-9-]+\.)*(?:pkg\.dev|gcr\.io|storage\.googleapis\.com)(?:/[^\s<>\"'`)\]]*)?",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_SEP = "[ \u00a0.\u2010-\u2013-]"  # one space, no-break space, dot or hyphen / dash
_GAP = "[ \u00a0\u2010-\u2013-]"  # the same without the dot (decimals, versions, IPs)
_START = r"(?<![\d.,\u2010-\u2013-])"  # not inside a longer number, date or version
_PHONE = re.compile(
    rf"{_START}(?:(?:\+|00)91{_SEP}?|0{_SEP}?)?[6-9]\d(?:{_SEP}?\d){{8}}(?!\d)"  # mobile
    rf"|{_START}0(?:{_GAP}?\d){{10}}(?!\d)"  # a landline with its STD code
    rf"|(?<![\w+])\+\d(?:{_GAP}?\d){{7,14}}(?!\d)"  # any number written with "+"
)
_DIGITS = re.compile(r"\d{10,}")
_GROUPED = re.compile(rf"{_START}\d{{3,}}(?:{_GAP}\d{{3,}})+(?!\d)")
_TEN = 10  # digits that make a grouped number personal
# a word, with format characters (soft hyphen, zero-width) and combining marks inside it
_WORD = re.compile(r"(?:[^\W_]|[\u00ad\u200b-\u200d\u2060\ufeff\u0300-\u036f])+")
_CAMEL = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|[^\W\d_]+")
_DROP = frozenset({"Cf", "Mn", "Me", "Mc"})
# Cyrillic and Greek letters that look like Latin ones, read as Latin (the same table as
# recall/sensitive.py's, copied: the generator imports nothing from the app)
_CONFUSABLES = str.maketrans(
    "АВСЕНІЈКМОРЅТХУҮԚԜӀасеіјорѕхуԁһԛԝӏΑΒΕΖΗΙΚΜΝΟΡΤΥΧονικρχαυϲϳ",
    "ABCEHIJKMOPSTXYYQWIaceijopsxydhqwlABEZHIKMNOPTYXovikpxaucj",
)


class ScrubLeak(GenError):
    """Personal text survived into the book (the message names paths and kinds only)."""


def _url_allowed(url: str) -> bool:
    parts = urlsplit(url if "://" in url else f"https://{url}")
    if parts.scheme.lower() not in ("http", "https") or "@" in parts.netloc:
        return False
    if (parts.hostname or "").lower() not in PUBLIC_DOCS:
        return False
    decoded = unquote(url)
    return not (_EMAIL.search(decoded) or any(p.search(decoded) for _, p in SECRET_SHAPES))


def _hash(word: str) -> str:
    return hashlib.sha256(word.encode("utf-8")).hexdigest()


def _plain(word: str) -> str:
    """The word as names are matched: NFKD, accents and format characters gone, look-alikes
    folded (case kept, for the camel-case split)."""
    kept = (c for c in unicodedata.normalize("NFKD", word) if unicodedata.category(c) not in _DROP)
    return "".join(kept).translate(_CONFUSABLES)


def name_keys(word: str) -> frozenset[str]:
    """The case-folded forms a hashed name is looked up by: the word, the word without leading
    or trailing digits, and its camel-case parts."""
    plain = _plain(word)
    forms = {plain, plain.strip("0123456789"), *_CAMEL.findall(plain)}
    return frozenset(f.casefold() for f in forms if f)


def _few_digits(text: str) -> bool:
    return sum(c.isdigit() for c in text) < _TEN


class Scrubber:
    """`clean` replaces personal text with "[removed]"; `findings` names what is left."""

    def __init__(self, redact: frozenset[str]) -> None:
        self._redact = redact

    def _rules(self) -> tuple[tuple[str, re.Pattern[str], Callable[[str], bool]], ...]:
        never: Callable[[str], bool] = lambda _s: False  # noqa: E731 - a tiny predicate
        secrets = tuple((kind, pat, never) for kind, pat in SECRET_SHAPES)
        return (
            ("url", _URL, _url_allowed),
            *secrets,
            ("host", _HOST, never),
            ("email", _EMAIL, never),
            ("phone", _PHONE, never),
            ("digits", _DIGITS, never),
            ("digits", _GROUPED, _few_digits),
            ("name", _WORD, self._not_a_name),
        )

    def _not_a_name(self, word: str) -> bool:
        return not any(_hash(k) in self._redact for k in name_keys(word))

    def _pass(self, text: str) -> tuple[str, frozenset[str]]:
        """One pass of every rule in order: the cleaned text and the kinds it removed."""
        out, found = unicodedata.normalize("NFC", text), set()
        for kind, pattern, keep in self._rules():

            def swap(m: re.Match[str], k: Callable[[str], bool] = keep, kd: str = kind) -> str:
                if k(m.group(0)):
                    return m.group(0)
                found.add("secret" if kd in _SECRET_KINDS else kd)
                return REMOVED

            out = pattern.sub(swap, out)
        return out, frozenset(found)

    def clean(self, text: str) -> str:
        return self._pass(text)[0]

    def findings(self, text: str) -> tuple[str, ...]:
        """The kinds of personal text in `text` (sorted, unique); () when clean."""
        return tuple(sorted(self._pass(text)[1]))

    def verify(self, tree: object) -> None:
        leaks = [f"{path} ({', '.join(kinds)})" for path, kinds in self._walk(tree, "")]
        if leaks:
            shown = "; ".join(leaks[:5])
            raise ScrubLeak(f"personal text survived in {len(leaks)} place(s): {shown}")

    def _walk(self, node: object, path: str) -> list[tuple[str, tuple[str, ...]]]:
        if isinstance(node, str):
            kinds = self.findings(node)
            return [(path or "(root)", kinds)] if kinds else []
        if isinstance(node, dict):
            kept = ((str(k), v) for k, v in node.items() if k not in SKIP_KEYS)
            return [leak for k, v in kept for leak in self._walk(v, f"{path}.{k}" if path else k)]
        if isinstance(node, (list, tuple)):
            return [leak for i, v in enumerate(node) for leak in self._walk(v, f"{path}[{i}]")]
        return []


class NoScrub(Scrubber):
    """The negative control (scrub off): passes everything through, verifies nothing."""

    def __init__(self) -> None:
        super().__init__(frozenset())

    def clean(self, text: str) -> str:
        return text

    def findings(self, text: str) -> tuple[str, ...]:
        return ()


def load_redact(path: Traversable | Path | None = None) -> frozenset[str]:
    data = json.loads((path or REDACT_FILE).read_text(encoding="utf-8"))
    hashes = data.get("sha256", [])
    if not all(isinstance(h, str) and re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes):
        raise GenError("gen/redact.json must hold lower-case SHA-256 hex strings only")
    return frozenset(hashes)


@lru_cache(maxsize=1)
def default_scrubber() -> Scrubber:
    return Scrubber(load_redact())


__all__ = [
    "PUBLIC_DOCS",
    "REDACT_FILE",
    "REMOVED",
    "SECRET_SHAPES",
    "NoScrub",
    "ScrubLeak",
    "Scrubber",
    "default_scrubber",
    "load_redact",
]

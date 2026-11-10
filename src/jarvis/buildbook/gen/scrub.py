# src/jarvis/buildbook/gen/scrub.py
"""R6 D3: no personal data in the book. Every text the generator takes from the repository (plan
lines, docstrings, setting descriptions) passes `Scrubber.clean`, which replaces with "[removed]":

    url     a URL whose host is not on the public-docs allow list (`PUBLIC_DOCS`)
    host    a `*.run.app`, `*.ts.net` or other project-id-like host (`PRIVATE_HOSTS`)
    email   an e-mail address
    phone   an Indian mobile number, `(\\+91[\\s-]?)?[6-9]\\d{9}` (also written 5 + 5)
    digits  any run of 10 or more digits (account and project numbers)
    secret  a secret-shaped string (the same shapes the snapshot scan refuses, `SECRET_SHAPES`)
    name    any word whose lower-case SHA-256 is in gen/redact.json (hashes only: no one named)

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
from pathlib import Path
from urllib.parse import urlsplit

from jarvis.buildbook.gen.repo import GenError

REMOVED = "[removed]"
REDACT_FILE = Path(__file__).with_name("redact.json")
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
SECRET_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")),
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("github_token", re.compile(r"ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{22,}")),
    ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("telegram_token", re.compile(r"\b[0-9]{8,10}:[A-Za-z0-9_-]{35}\b")),
)
_SECRET_KINDS = frozenset(kind for kind, _ in SECRET_SHAPES)
_URL = re.compile(r"https?://[^\s<>\"'`)\]]+")
_HOST = re.compile(
    r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:" + "|".join(re.escape(h) for h in PRIVATE_HOSTS) + r")\b",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<!\d)(?:\+91[\s-]?)?[6-9]\d{9}(?!\d)|\+91[\s-]?\d{5}[\s-]\d{5}(?!\d)")
_DIGITS = re.compile(r"\d{10,}")
_WORD = re.compile(r"[^\W_]+")


class ScrubLeak(GenError):
    """Personal text survived into the book (the message names paths and kinds only)."""


def _url_allowed(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host in PUBLIC_DOCS


def _hash(word: str) -> str:
    return hashlib.sha256(word.lower().encode("utf-8")).hexdigest()


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
            ("name", _WORD, lambda w: _hash(w) not in self._redact),
        )

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


def load_redact(path: Path = REDACT_FILE) -> frozenset[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
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

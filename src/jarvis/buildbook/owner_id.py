# src/jarvis/buildbook/owner_id.py
"""D3's owner-identity rule, ONE function for the sealer, the guest door and the reply guard (R6 D3
amendment, integrated review SEC-1; docs/plans/r6-build-book.md).

- **The full address always counts**, in any form: NFKC and case folded, zero-width characters
  out, look-alike letters folded, HTML entities and percent-encoding undone (twice), JSON `\\uXXXX`
  escapes undone, " at " / " dot " / "[at]" / "(dot)" spellings read as symbols and the spaces
  around "@" and "." squeezed.
- **The local part counts only by its distinctive tokens**: it is split on `. _ - +` and digit runs;
  a token counts when it has >= 3 letters AND is not in JARVIS's fixed `vocabulary()` (the words of
  the generator's templates, the book's own fixed text and a short common-word list). A counted
  token found as a whole word (no letter either side) is a match, so "first.last@" also matches
  "First Last" and "Last, First". A local part made only of vocabulary words ("owner", "jarvis",
  "home.vault") is checked as the address alone: it never blocks a release, a guest show or the
  owner's own replies.

`match(text)` and `in_book(book_json)` answer "address", "word" or None. Nothing here logs.
"""

from __future__ import annotations

import ast
import html
import json
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

from jarvis.buildbook.guard_words import LOOKALIKE, spelled, visible

Hit = Literal["address", "word"]
TOKEN_MIN = 3  # a shorter token is not a name
_SPLIT = re.compile(r"[._+\-]+|\d+")
_JSON_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")
_AROUND_SYMBOL = re.compile(r"\s*([@.])\s*")
_WORD = re.compile(r"[^\W\d_]{3,}")
_DECODE_ROUNDS = 2  # "&amp;#64;" and "%2540" are undone; deeper nesting is not a form anyone reads

# the book's own fixed text: the generator's templates and the words people wrote for it
_FIXED_TEXT = (
    "lines.py",
    "plain.py",
    "model.py",
    "sections.py",
    "gen/show.py",
    "gen/flows.py",
    "gen/costs.py",
    "gen/layers.py",
    "gen/chunks.py",
)
# mailbox words and JARVIS's own name: a local part made of these is not a name
COMMON = frozenset(
    {
        "account", "admin", "book", "build", "contact", "dev", "email", "family", "gmail",
        "google", "hello", "home", "inbox", "info", "jarvis", "mail", "main", "noreply",
        "office", "owner", "personal", "private", "reply", "support", "team", "test", "the",
        "user", "vault", "work",
    }
)  # fmt: skip


@dataclass(frozen=True)
class Marks:
    """What counts for a set of owner addresses: the folded addresses and the distinctive tokens."""

    addresses: tuple[str, ...]
    tokens: tuple[str, ...]


def _docstrings(tree: ast.Module) -> set[int]:
    """The ids of every docstring node: docstrings are never vocabulary (only fixed text is)."""
    owners = [tree, *(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef | ast.FunctionDef))]
    out: set[int] = set()
    for node in owners:
        body = getattr(node, "body", [])
        first = body[0] if body else None
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            out.add(id(first.value))
    return out


def _literal_words(source: str) -> set[str]:
    tree = ast.parse(source)
    skip = _docstrings(tree)
    words: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            words.update(_WORD.findall(node.value.casefold()))
    return words


@lru_cache(maxsize=1)
def vocabulary() -> frozenset[str]:
    """JARVIS's fixed vocabulary, built once, deterministically, from fixed text in the image
    (never from plans, docstrings or the book being checked). A file that can't be read only
    makes it smaller, which counts more tokens: the check fails closed."""
    words = set(COMMON)
    here = Path(__file__).resolve().parent
    for rel in _FIXED_TEXT:
        try:
            words |= _literal_words((here / rel).read_text("utf-8"))
        except (OSError, SyntaxError, ValueError):
            continue
    return frozenset(words)


def fold(text: str) -> str:
    """One comparable form: entities, percent-encoding and JSON escapes undone, NFKC, invisible
    characters out, case folded, look-alike letters folded to Latin."""
    s = unicodedata.normalize("NFKC", text)
    for _ in range(_DECODE_ROUNDS):
        s = unquote(html.unescape(s))
    s = _JSON_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), s)
    return visible(unicodedata.normalize("NFKC", s)).casefold().translate(LOOKALIKE)


def _symbols(folded: str) -> str:
    """Spelled-out symbols read as symbols, with the spaces around "@" and "." squeezed."""
    return _AROUND_SYMBOL.sub(r"\1", spelled(folded))


def tokens(local: str) -> tuple[str, ...]:
    """A local part's distinctive tokens, in order, each once."""
    vocab = vocabulary()
    out: list[str] = []
    for part in _SPLIT.split(local):
        if len(part) >= TOKEN_MIN and part not in vocab and part not in out:
            out.append(part)
    return tuple(out)


def marks(emails: Iterable[str]) -> Marks:
    addresses: list[str] = []
    found: list[str] = []
    for raw in emails:
        address = fold(raw).strip()
        local, at, domain = address.partition("@")
        if not (at and local and domain):
            continue
        addresses.append(address)
        found.extend(t for t in tokens(local) if t not in found)
    return Marks(tuple(addresses), tuple(found))


def _word_in(token: str, text: str) -> bool:
    return re.search(rf"(?<![^\W\d_]){re.escape(token)}(?![^\W\d_])", text) is not None


def _hit(views: Sequence[str], m: Marks) -> Hit | None:
    folded = [fold(v) for v in views]
    for view in folded:
        if any(a in view or a in _symbols(view) for a in m.addresses):
            return "address"
    if any(_word_in(t, view) for view in folded for t in m.tokens):
        return "word"
    return None


def match(text: str, emails: Iterable[str]) -> Hit | None:
    """Does this text name an owner: his full address in any form ("address"), or a distinctive
    token of its local part as a whole word ("word")? None otherwise."""
    m = marks(emails)
    if not m.addresses:
        return None
    return _hit((text,), m)


def in_book(book_json: bytes, emails: Iterable[str]) -> Hit | None:
    """`match` over a book.json, raw and with its JSON escapes undone."""
    m = marks(emails)
    if not m.addresses:
        return None
    raw = book_json.decode("utf-8", "replace")
    try:
        unescaped = json.dumps(json.loads(book_json), ensure_ascii=False)
    except ValueError:
        unescaped = raw
    return _hit((raw, unescaped), m)


__all__ = [
    "COMMON",
    "TOKEN_MIN",
    "Hit",
    "Marks",
    "fold",
    "in_book",
    "marks",
    "match",
    "tokens",
    "vocabulary",
]

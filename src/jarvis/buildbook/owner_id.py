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
- **More forms of the address** (security re-review #4): Markdown's backslash escapes, short HTML
  tags and "-at-" / "-dot-" are read through (for the address only, so no two words are joined),
  and a Gmail address also counts as Gmail's own mailbox (dots and a `+tag` don't count, at
  gmail.com or googlemail.com). Two or more distinctive tokens also count run together
  ("akashkumar").
- **A handle counts as a whole** (security re-review #3): the whole local part (and its mailbox
  without a `+tag`) is a needle too when it has >= 4 characters and is not made only of vocabulary
  words, so "rk1987@" matches "rk1987" (bounded like an address part) while "owner@", "info@" and
  "home.vault@" still do not.

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
WHOLE_MIN = 4  # a shorter whole local part ("rk1") is not a handle
_SPLIT = re.compile(r"[._+\-]+|\d+")
_RUNS = re.compile(r"[^\W\d_]+|\d+")  # letter runs and digit runs; a digit run is never vocabulary
_JSON_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")
_AROUND_SYMBOL = re.compile(r"\s*([@.])\s*")
_WORD = re.compile(r"[^\W\d_]{3,}")
_DECODE_ROUNDS = 2  # "&amp;#64;" and "%2540" are undone; deeper nesting is not a form anyone reads
_ESCAPED = re.compile(r"\\+(?=[@._+\-])")  # Markdown: home\.vault\@gmail\.com
_TAG = re.compile(r"<[^<>]{0,40}>")  # home.vault<b>@</b>gmail.com
_DASHED = re.compile(r"\s*-(at|dot)-\s*")  # home.vault -at- gmail.com
_GMAIL = re.compile(r"([\w.+\-]+)@(?:gmail|googlemail)\.com(?![\w\-])")
GMAIL_DOMAINS = ("gmail.com", "googlemail.com")

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
    """What counts for a set of owner addresses: the folded addresses, the distinctive tokens and
    the whole local parts that are handles."""

    addresses: tuple[str, ...]
    tokens: tuple[str, ...]
    whole: tuple[str, ...] = ()
    gmail: tuple[str, ...] = ()  # Gmail's own mailbox of each gmail.com / googlemail.com address


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


def _plain(folded: str) -> str:
    """Markdown's backslash escapes, short HTML tags and "-at-" / "-dot-" read through: for the
    address check only, so no two words are joined into a token."""
    s = _TAG.sub("", _ESCAPED.sub("", folded))
    return _DASHED.sub(lambda m: "@" if m.group(1) == "at" else ".", s)


def mailbox(local: str) -> str:
    """Gmail's own mailbox for a local part: its dots and a `+tag` don't count."""
    return local.partition("+")[0].replace(".", "")


def tokens(local: str) -> tuple[str, ...]:
    """A local part's distinctive tokens, in order, each once; two or more also run together."""
    vocab = vocabulary()
    out: list[str] = []
    for part in _SPLIT.split(local):
        if len(part) >= TOKEN_MIN and part not in vocab and part not in out:
            out.append(part)
    return (*out, "".join(out)) if len(out) > 1 else tuple(out)


def whole(local: str) -> tuple[str, ...]:
    """The local part as a whole, and its mailbox without a `+tag`, each when it has >= 4
    characters and is not made only of vocabulary words (a digit run is never vocabulary)."""
    vocab = vocabulary()
    out: list[str] = []
    for part in (local, local.partition("+")[0]):
        runs = _RUNS.findall(part)
        if len(part) >= WHOLE_MIN and not all(r in vocab for r in runs) and part not in out:
            out.append(part)
    return tuple(out)


def marks(emails: Iterable[str]) -> Marks:
    addresses: list[str] = []
    found: list[str] = []
    handles: list[str] = []
    boxes: list[str] = []
    for raw in emails:
        address = fold(raw).strip()
        local, at, domain = address.partition("@")
        if not (at and local and domain):
            continue
        addresses.append(address)
        found.extend(t for t in tokens(local) if t not in found)
        handles.extend(h for h in whole(local) if h not in handles)
        if domain in GMAIL_DOMAINS and mailbox(local) not in boxes:
            boxes.append(mailbox(local))
    return Marks(tuple(addresses), tuple(found), tuple(handles), tuple(boxes))


def _word_in(token: str, text: str) -> bool:
    return re.search(rf"(?<![^\W\d_]){re.escape(token)}(?![^\W\d_])", text) is not None


def _whole_in(local: str, text: str) -> bool:
    """The whole local part, bounded as a mailbox name is: no word character, ".", "+" or "-"
    before it, no word character or "-" after it."""
    return re.search(rf"(?<![\w.+\-]){re.escape(local)}(?![\w\-])", text) is not None


def _address_in(view: str, m: Marks) -> bool:
    symbols, plain = _symbols(view), _plain(view)
    read = symbols if plain == view else _symbols(plain)  # a book seldom needs reading through
    if any(a in f for f in (view, symbols, read) for a in m.addresses):
        return True
    if not m.gmail or not any(f"@{d}" in read for d in GMAIL_DOMAINS):
        return False
    return any(mailbox(x) in m.gmail for x in _GMAIL.findall(read))


def _hit(views: Sequence[str], m: Marks) -> Hit | None:
    folded = [fold(v) for v in views]
    if any(_address_in(view, m) for view in folded):
        return "address"
    if any(_word_in(t, view) for view in folded for t in m.tokens):
        return "word"
    if any(_whole_in(h, view) for view in folded for h in m.whole):
        return "word"
    return None


def match(text: str, emails: Iterable[str]) -> Hit | None:
    """Does this text name an owner: his full address in any form ("address"), or a distinctive
    token of its local part as a whole word, or the local part itself when it is a handle
    ("word")? None otherwise."""
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
    "WHOLE_MIN",
    "Hit",
    "Marks",
    "GMAIL_DOMAINS",
    "fold",
    "in_book",
    "mailbox",
    "marks",
    "match",
    "tokens",
    "vocabulary",
    "whole",
]

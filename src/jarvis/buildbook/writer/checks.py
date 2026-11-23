# src/jarvis/buildbook/writer/checks.py
"""R6.3 D10 (Phase A §7.5, plan review H5): the six checks every draft passes before anything is
kept. A brain's reply is untrusted data: it is parsed into the five sections of the wire format
(`model.DRAFT_SECTIONS`, `## <heading>` blocks in order) or refused as `shape`, then checked:

1. `refs`: every backticked path, `path:symbol`, `path:CONSTANT`, setting, collection and route is
   in the fact index (paths stored scrubbed, H6); a short or partial name is resolved by D3's rule,
   against the page's own `refs` first, then `src/jarvis/api/static`, `src/jarvis/api`,
   `src/jarvis` and the repository.
2. `numbers`: outside the "Example (made up)" section every number is a `{{fact:...}}` placeholder
   the filler knows. Not numbers here: digits inside a backticked reference, C-ids, release
   labels, versions and the pack's own dates, an HTTP status next to a route or the word
   "status", and `STANDARD_NAMES`.
3. `personal`: the scrubber's findings on the filled text (secret shapes, e-mails, phones, long
   digit runs, hashed names and A's new kinds) and an owner e-mail in any form (`owner_id.match`).
4. `unverified`: a sentence using a fact with `verified: false` says "From repo configuration" or
   "Unverified".
5. `invented`: every sentence of "How it works" cites a reference or a fact; elsewhere a sentence
   that claims a capability ("also", "can", "by itself", ...) cites one; `planned`: words of a
   future feature only after a "Planned" line.
6. `shape`: the five headings in order, every section written and under its cap once filled, no
   HTML, no link, no fence marker and never the reference marker (the canary).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from jarvis.buildbook.facts_model import FactPack, IndexedPage
from jarvis.buildbook.gen.scrub import Scrubber
from jarvis.buildbook.owner_id import match
from jarvis.buildbook.writer import fill
from jarvis.buildbook.writer.model import (
    DRAFT_SECTIONS,
    FACT_PLACEHOLDER,
    HEADINGS,
    SECTION_CAPS,
    CheckCode,
    SectionId,
)

STANDARD_NAMES: tuple[str, ...] = (
    "AES-256-GCM", "SHA-256", "UTF-8", "IPv4", "IPv6", "WebGL2", "HTTP/2", "ES2020",
    "OAuth 2.0", "ISO 8601", "3D", "2D",
)  # fmt: skip
PREFIXES = ("src/jarvis/api/static/", "src/jarvis/api/", "src/jarvis/", "")  # D3's rule
UNVERIFIED_WORDS = ("from repo configuration", "unverified")
STATUS_NEAR = 60  # characters before a status in which a route or the word "status" must be
_HEAD = re.compile(r"^## (.+?)[ \t]*$", re.M)
_TICK = re.compile(r"`([^`\n]{1,200})`")
_ROUTE_TICK = re.compile(r"`(?:[A-Z]+ )?/[^`\n]*`")
_HTML = re.compile(r"</?[A-Za-z][^>\n]*>")
_LINK = re.compile(r"\[[^\]\n]*\]\([^)\n]*\)")
_FENCE = re.compile(r"<<|>>")
_CID = re.compile(r"\bC\d{2}\b")
_LABEL = re.compile(r"\bR\d+(?:\.\d+)*\b")
_VERSION = re.compile(r"\bv?\d+\.\d+\.\d+\b")
_RUPEE_ZERO = re.compile(r"₹0(?!\d|[.,]\d)")  # R6.3.1: "₹0" says plainly that a part is free
_STATUS = re.compile(r"\b[1-5]\d\d\b")
_ROUTE = re.compile(r"^(?:(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|WEBSOCKET) )?(/\S*)$")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_FUTURE = re.compile(
    r"\b(?:soon|planned|not built yet|in a (?:later|future) release|will (?:also|soon)|"
    r"one day|coming)\b",
    re.I,
)
_CLAIM = re.compile(r"\b(?:also|can|automatically|by itself|on its own)\b", re.I)
_PLANNED_LINE = re.compile(r"^(?:#{3,4} )?Planned\b.*$", re.M)
ORDER: tuple[CheckCode, ...] = (
    "refs", "numbers", "personal", "unverified", "invented", "planned", "shape",
)  # fmt: skip


@dataclass(frozen=True)
class Context:
    page: IndexedPage
    facts: FactPack
    scrub: Scrubber
    emails: tuple[str, ...]
    canary: str = ""
    _sets: dict[str, frozenset[str]] = field(default_factory=dict, compare=False, repr=False)

    def known(self, kind: str) -> frozenset[str]:
        if kind not in self._sets:
            self._sets[kind] = frozenset(getattr(self.facts.index, kind))
        return self._sets[kind]


def parse(text: str) -> dict[SectionId, str] | None:
    """The five sections of a draft, or None when its shape is wrong (check (6))."""
    heads = list(_HEAD.finditer(text))
    if [h.group(1) for h in heads] != [HEADINGS[s] for s in DRAFT_SECTIONS]:
        return None
    if text[: heads[0].start()].strip():
        return None
    out: dict[SectionId, str] = {}
    for i, (sid, head) in enumerate(zip(DRAFT_SECTIONS, heads, strict=True)):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out[sid] = text[head.end() : end].strip()
    return out


def check(sections: Mapping[SectionId, str], ctx: Context) -> tuple[CheckCode, ...]:
    """The checks a draft (its sections with placeholders) fails, in `ORDER`; () when it passes."""
    filled = {sid: fill.fill(text, ctx.facts) for sid, text in sections.items()}
    whole = "\n".join(filled.values())
    kinds = set(ctx.scrub.findings(whole))
    failed: set[CheckCode] = set()
    if not all(_ref_ok(span, ctx) for text in sections.values() for span in _TICK.findall(text)):
        failed.add("refs")
    if not all(_numbers_ok(t, ctx.facts) for sid, t in sections.items() if sid != "example"):
        failed.add("numbers")
    if kinds - {"url"} or match(whole, ctx.emails) is not None:
        failed.add("personal")
    if not _unverified_ok(sections.values(), ctx.facts):
        failed.add("unverified")
    if _invented(sections):
        failed.add("invented")
    if _planned(sections):
        failed.add("planned")
    if "url" in kinds or _bad_shape(sections, filled, ctx.canary):
        failed.add("shape")
    return tuple(code for code in ORDER if code in failed)


# ---- (1) references ------------------------------------------------------------------------------
def resolve(name: str, ctx: Context) -> str | None:
    """A cited path, full, by D3's rule (the page's own refs first); None when it isn't there."""
    paths = ctx.known("paths")
    if name in paths:
        return name
    own = [r for r in ctx.page.refs if r == name or r.endswith("/" + name)]
    if own:
        return own[0]
    for prefix in PREFIXES:
        if prefix + name in paths:
            return prefix + name
    folder = name.rstrip("/") + "/"
    return name if any(p.startswith(folder) for p in paths) and "/" in name else None


def _ref_ok(span: str, ctx: Context) -> bool:
    s = span.strip()
    if FACT_PLACEHOLDER.fullmatch(s):
        return True
    route = _ROUTE.match(s)
    if route is not None:
        method, path = route.groups()
        known = ctx.known("routes")
        return f"{method} {path}" in known if method else any(r.endswith(" " + path) for r in known)
    if ":" in s:
        path, _, name = s.rpartition(":")
        full = resolve(path, ctx)
        named = f"{full}:{name}"
        return full is not None and (
            named in ctx.known("symbols") or named in ctx.known("constants")
        )
    if "/" in s or "." in s:
        return resolve(s, ctx) is not None
    if _IDENT.match(s) is not None and _name_ok(s, ctx):
        return True
    return s in ctx.known("paths")  # R6.3.1: a bare tracked file name (`Dockerfile`, `Makefile`)


def _name_ok(name: str, ctx: Context) -> bool:
    if name in ctx.known("settings") or name in ctx.known("collections"):
        return True
    named = ctx.known("symbols") | ctx.known("constants")
    if any(f"{ref}:{name}" in named for ref in ctx.page.refs):
        return True
    return any(n.endswith(":" + name) for n in named)


# ---- (2) numbers ---------------------------------------------------------------------------------
def _pack_words(facts: FactPack) -> tuple[str, ...]:
    """The pack's own versions and dates: not numbers to check (2)."""
    keep = [
        str(v.value)
        for k, v in facts.values.items()
        if k.startswith("release.") or k.endswith((".date", ".version"))
    ]
    if facts.release is not None and facts.release.version:
        keep.append(facts.release.version)
    return tuple(sorted({w for w in keep if any(c.isdigit() for c in w)}, key=len, reverse=True))


def _statuses_out(text: str) -> str:
    def swap(m: re.Match[str]) -> str:
        before = text[max(0, m.start() - STATUS_NEAR) : m.start()]
        near = "status" in before.lower() or _ROUTE_TICK.search(before) is not None
        return " " if near else m.group(0)

    return _STATUS.sub(swap, text)


def _numbers_ok(text: str, facts: FactPack) -> bool:
    if fill.unknown_keys(text, facts):
        return False
    t = _statuses_out(FACT_PLACEHOLDER.sub(" ", text))
    t = _TICK.sub(" ", t)
    for word in (*STANDARD_NAMES, *_pack_words(facts)):
        t = t.replace(word, " ")
    for pattern in (_CID, _LABEL, _VERSION, _RUPEE_ZERO):
        t = pattern.sub(" ", t)
    return not any(c.isdigit() for c in t)


# ---- (4) unverified, (5) invented and planned, (6) shape -----------------------------------------
def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE.split(text) if s.strip()]


def _unverified_ok(texts: Iterable[str], facts: FactPack) -> bool:
    for text in texts:
        for sentence in _sentences(text):
            weak = [k for k in fill.keys_in(sentence) if k in facts.values]
            if any(not facts.values[k].verified for k in weak):
                if not any(w in sentence.lower() for w in UNVERIFIED_WORDS):
                    return False
    return True


def _before_planned(text: str) -> str:
    found = _PLANNED_LINE.search(text)
    return text if found is None else text[: found.start()]


def _invented(sections: Mapping[SectionId, str]) -> bool:
    for sid, text in sections.items():
        if sid == "example":
            continue
        for sentence in _sentences(_before_planned(text)):
            cites = "`" in sentence or "{{fact:" in sentence
            if not cites and (sid == "how" or _CLAIM.search(sentence)):
                return True
    return False


def _planned(sections: Mapping[SectionId, str]) -> bool:
    return any(
        _FUTURE.search(_before_planned(text)) for sid, text in sections.items() if sid != "example"
    )


def _bad_shape(
    sections: Mapping[SectionId, str], filled: Mapping[SectionId, str], canary: str
) -> bool:
    for sid, text in filled.items():
        if not sections[sid].strip() or len(text) > SECTION_CAPS[sid]:
            return True
        if _HTML.search(text) or _LINK.search(text) or _FENCE.search(text):
            return True
        if canary and canary in text:
            return True
    return False


__all__ = ["ORDER", "PREFIXES", "STANDARD_NAMES", "Context", "check", "parse", "resolve"]

# src/jarvis/buildbook/book/explain.py
"""R6.3.1 D5, D6 (docs/plans/r6-3-1-book-at-build.md): the words `pages --check` says for a page.

`check_words(codes, sections, ctx)` turns the codes R6.3's six checks returned
(`writer/checks.check`, the one authority on pass and fail) into one line per problem, naming the
section, the sentence, the fact key or the reference so a writer can fix it: "numbers: a typed
number in How it works ...". It reads the checks' own patterns and helpers, so the words never
disagree with the verdict; a code with no detail found still gets its general line.

`private_kinds(text, scrub, emails)` is the flowchart's word guard (D3): the scrubber's findings
and the private-word guard's reply patterns (`guard_words`: an address in any spelling, a secret
or long blob, a link or a domain, a long digit run, a control character) on the text as written
and in the guard's normal form, and the owner's address or a word of it.

A line quotes only what is safe to show: a backticked reference or a fact key in plain path
characters that the scrubber finds nothing in. Personal findings are named by kind, never shown.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence

from jarvis.buildbook import guard_words as W
from jarvis.buildbook.gen.scrub import Scrubber
from jarvis.buildbook.owner_id import match
from jarvis.buildbook.writer import checks, fill
from jarvis.buildbook.writer.model import DRAFT_SECTIONS, HEADINGS, SECTION_CAPS, CheckCode
from jarvis.buildbook.writer.model import SectionId as Sid

SHOWN = 8  # problems of one kind named one by one; the rest are counted
_QUOTABLE = re.compile(r"^[A-Za-z0-9_./:\-\[\] {}]{1,160}$")
GENERAL: dict[CheckCode, str] = {
    "refs": "a backticked reference the index doesn't know (see `pages --pack`)",
    "numbers": "a number outside the made-up example that is not a {{fact:<key>}}",
    "personal": "personal data, a secret or a private word",
    "unverified": 'a sentence using an Unverified fact doesn\'t say "Unverified"',
    "invented": "a sentence claims something without a backticked reference or a {{fact:<key>}}",
    "planned": 'future words before a "Planned:" line',
    "shape": "the five sections, each written, under its cap, no HTML, link or << >>",
}
Sections = Mapping[Sid, str]
Detail = Callable[[Sections, checks.Context], list[str]]


def quotable(text: str, scrub: Scrubber) -> bool:
    return _QUOTABLE.fullmatch(text) is not None and not scrub.findings(text)


def _capped(code: str, lines: list[str]) -> list[str]:
    unique = list(dict.fromkeys(lines))
    if len(unique) <= SHOWN:
        return unique
    return [*unique[:SHOWN], f"{code}: and {len(unique) - SHOWN} more like these"]


def _refs(sections: Sections, ctx: checks.Context) -> list[str]:
    spans = [s for text in sections.values() for s in checks._TICK.findall(text)]
    bad = [s for s in spans if not checks._ref_ok(s, ctx)]
    return [
        f"refs: `{s}` is not a path, symbol, setting, collection or route the index knows "
        "(see `pages --pack`)"
        if quotable(s, ctx.scrub)
        else "refs: a backticked reference the index doesn't know"
        for s in bad
    ]


def _numbers(sections: Sections, ctx: checks.Context) -> list[str]:
    out = []
    for sid, text in sections.items():
        if sid == "example":
            continue
        unknown = fill.unknown_keys(text, ctx.facts)
        out += [
            f"numbers: {{{{fact:{k}}}}} is not a fact key (see `pages --pack`)"
            if quotable(k, ctx.scrub)
            else "numbers: a {{fact:...}} key that is not a fact key"
            for k in unknown
        ]
        if not unknown and not checks._numbers_ok(text, ctx.facts):
            out.append(
                f"numbers: a typed number in {HEADINGS[sid]} (write {{{{fact:<key>}}}}, or keep "
                "the number in the made-up example)"
            )
    return out


def _personal(sections: Sections, ctx: checks.Context) -> list[str]:
    whole = "\n".join(fill.fill(t, ctx.facts) for t in sections.values())
    kinds = sorted(set(ctx.scrub.findings(whole)) - {"url"})
    out = []
    if kinds:
        out.append(f"personal: {', '.join(kinds)} (no personal data, secrets or private words)")
    if match(whole, ctx.emails) is not None:
        out.append("personal: the owner's e-mail address or a word of it")
    return out


def _unverified(sections: Sections, ctx: checks.Context) -> list[str]:
    out = []
    for text in sections.values():
        for sentence in checks._sentences(text):
            if any(w in sentence.lower() for w in checks.UNVERIFIED_WORDS):
                continue
            weak = [k for k in fill.keys_in(sentence) if k in ctx.facts.values]
            out += [
                f'unverified: {{{{fact:{k}}}}} is Unverified: say "Unverified" in its sentence'
                for k in weak
                if not ctx.facts.values[k].verified
            ]
    return out


def _invented(sections: Sections, _ctx: checks.Context) -> list[str]:
    out = []
    for sid, text in sections.items():
        if sid == "example":
            continue
        for n, sentence in enumerate(checks._sentences(checks._before_planned(text)), start=1):
            cites = "`" in sentence or "{{fact:" in sentence
            if not cites and (sid == "how" or checks._CLAIM.search(sentence)):
                out.append(
                    f"invented: {HEADINGS[sid]}, sentence {n} cites no backticked reference or "
                    "{{fact:<key>}}"
                )
    return out


def _planned(sections: Sections, _ctx: checks.Context) -> list[str]:
    return [
        f'planned: future words in {HEADINGS[sid]} before a "Planned:" line'
        for sid, text in sections.items()
        if sid != "example" and checks._FUTURE.search(checks._before_planned(text))
    ]


def _shape_of(sid: Sid, raw: str, text: str, ctx: checks.Context) -> list[str]:
    name, cap = HEADINGS[sid], SECTION_CAPS[sid]
    out = []
    if not raw.strip():
        out.append(f"shape: {name} is empty")
    elif len(text) > cap:
        size = f"{len(text):,} characters once filled, over its cap of {cap:,}"
        out.append(f"shape: {name} is {size}")
    if checks._HTML.search(text):
        out.append(f"shape: HTML in {name}")
    if checks._LINK.search(text) or "url" in ctx.scrub.findings(text):
        out.append(f"shape: a link or a web address in {name}")
    if checks._FENCE.search(text):
        out.append(f"shape: << or >> in {name}")
    if ctx.canary and ctx.canary in text:
        out.append(f"shape: the reference marker in {name}")
    return out


def _shape(sections: Sections, ctx: checks.Context) -> list[str]:
    out = []
    for sid in DRAFT_SECTIONS:
        raw = sections.get(sid, "")
        out += _shape_of(sid, raw, fill.fill(raw, ctx.facts), ctx)
    return out


DETAILS: dict[CheckCode, Detail] = {
    "refs": _refs,
    "numbers": _numbers,
    "personal": _personal,
    "unverified": _unverified,
    "invented": _invented,
    "planned": _planned,
    "shape": _shape,
}


def check_words(codes: Sequence[CheckCode], sections: Sections, ctx: checks.Context) -> list[str]:
    """One line per problem behind each failed check code, in the checks' order."""
    out: list[str] = []
    for code in codes:
        detail = DETAILS.get(code)
        found = detail(sections, ctx) if detail is not None else []
        out += _capped(code, found) or [f"{code}: {GENERAL.get(code, 'failed')}"]
    return out


# ---- the flowchart's words (D3) ----------------------------------------------------------------
_GUARD: tuple[tuple[str, Callable[[str], bool]], ...] = (
    ("email", lambda t: bool(W.EMAIL.search(t) or W.SPELLED_EMAIL.search(W.spelled(t)))),
    ("secret", lambda t: bool(W.SECRETS.search(t) or W.BLOB.search(t))),
    ("url", lambda t: bool(W.URL.search(t) or W.DOMAIN.search(t.lower()))),
    ("digits", lambda t: W.DIGITS.search(t) is not None),
    ("control", lambda t: W.CONTROL.search(t) is not None),
)


def private_kinds(text: str, scrub: Scrubber, emails: Sequence[str] = ()) -> list[str]:
    """What a flowchart's title or label must not hold, by kind (empty: it may be shown)."""
    kinds = set(scrub.findings(text))
    forms = (text, W.normalise(text))
    kinds.update(kind for kind, found in _GUARD if any(found(f) for f in forms))
    if emails and match(text, emails) is not None:
        kinds.add("owner")
    return sorted(kinds)


__all__ = ["DETAILS", "GENERAL", "SHOWN", "check_words", "private_kinds", "quotable"]

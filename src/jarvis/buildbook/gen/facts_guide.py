# src/jarvis/buildbook/gen/facts_guide.py
"""R6.3 D2, D3 (docs/plans/r6-3-book-content.md): what the fact pack reads from the guide
(`docs/architecture/JARVIS-Architecture.md`) and the console, standard library only.

- `guide_cards(repo)`: each `#### Cnn · Title` card with its field table (the coverage checker's
  reading, `scripts/arch_coverage.py`), in the guide's order
- `card_facts(repo, scrub, cards, table, known)`: each card's module (`gen/modules.py`), its
  "Where in the code" resolved by `gen/refs.resolve` to full, scrubbed paths (a span that
  resolves nowhere is a GenError naming the card) and its "Outside services" as the coverage
  checker names them (`known`; with no services table, as the guide writes them)
- `screens(repo, routes, scrub)`: the console's `id="p-*"` panels in console.html's order, each
  with console.html, its `console-<panel>*.js` modules and the files of its `/v1/<panel>` routes,
  then the show (`/book/show`: book.html, the scripts it loads, the `/v1/book/show` routes' files)
- `roadmap(text)`: the guide §11's rows, the release and its content in words ("R6.4, the Book's
  new look"); the tour reads the first two (seam 15)
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from jarvis.buildbook.facts_model import CardFact, Route, ScreenFact
from jarvis.buildbook.gen import refs as refs_mod
from jarvis.buildbook.gen.code import clip
from jarvis.buildbook.gen.modules import Module, module_of
from jarvis.buildbook.gen.repo import GenError, Repo
from jarvis.buildbook.gen.scrub import Scrubber

GUIDE = "docs/architecture/JARVIS-Architecture.md"
STATIC = "src/jarvis/api/static/"
CONSOLE = STATIC + "console.html"
SHOW = STATIC + "book.html"
SHOW_TITLE = "The Build Book show"
_HEAD = re.compile(r"^####\s+(C\d{2})\s+·\s+(.+?)\s*$")
_ANY_HEAD = re.compile(r"^#{1,4}\s")
_PANEL = re.compile(r"\bid=\"p-([a-z0-9-]+)\"")
_SCRIPT = re.compile(r"<script[^>]*\bsrc=\"[^\"]*?/?([\w.-]+\.m?js)\"")
_RELEASE = re.compile(r"^(R\d+(?:\.\d+)*)\s+(\S.*)$")
TITLE_MAX = 120
NONE = frozenset({"none", "-", "—"})


@dataclass(frozen=True)
class Card:
    id: str
    title: str
    fields: dict[str, str]


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def guide_cards(repo: Repo) -> tuple[Card, ...]:
    out: list[Card] = []
    head: tuple[str, str] | None = None
    fields: dict[str, str] = {}
    for line in (repo.text(GUIDE) or "").splitlines():
        m = _HEAD.match(line)
        if m or _ANY_HEAD.match(line):
            if head:
                out.append(Card(head[0], head[1], fields))
            head, fields = ((m.group(1), m.group(2)) if m else None), {}
        elif head and line.strip().startswith("|") and not set(line.strip()) <= set("|-: "):
            row = _cells(line)
            if len(row) >= 2 and row[0] != "Field":
                fields[row[0].strip("* ")] = " | ".join(row[1:])
    if head:
        out.append(Card(head[0], head[1], fields))
    return tuple(out)


def service_items(field: str) -> list[str]:
    """The items of an "Outside services" field as written: split at top-level `,` `;` " and "
    " or ", each up to its first bracket (the coverage checker's `service_names`, case kept)."""
    items, depth, cur = [], 0, ""
    for ch in field.replace(" and ", ",").replace(" or ", ","):
        depth += (ch == "(") - (ch == ")")
        if ch in ",;" and depth == 0:
            items.append(cur)
            cur = ""
        else:
            cur += ch
    items.append(cur)
    heads = (re.sub(r"^(?:and|or)\s+", "", i.split("(")[0].strip(" `*")) for i in items)
    return [h for h in heads if h and h.lower() not in NONE]


def _services(field: str, known: Sequence[str]) -> tuple[str, ...]:
    items = service_items(field)
    if not known:
        return tuple(sorted(set(items)))
    spelled = {k.lower(): k for k in known}
    return tuple(sorted({spelled[i.lower()] for i in items if i.lower() in spelled}))


def resolved(repo: Repo, card: Card) -> tuple[str, ...]:
    """The card's "Where in the code" as repository paths (a folder ends in `/`, a glob keeps
    its `*`), in order, once each; a span that exists nowhere is a GenError."""
    out: list[str] = []
    for span, path in refs_mod.resolve(repo.root, card.fields.get("Where in the code", "")):
        if path is None:
            raise GenError(f"{card.id}: `{span}` in its Where in the code resolves to no file")
        if path not in out:
            out.append(path)
    return tuple(out)


def expand(repo: Repo, refs: Iterable[str]) -> tuple[str, ...]:
    """Tracked files a list of resolved references names: a folder's files, a glob's matches."""
    found: set[str] = set()
    for ref in refs:
        if ref.endswith("/"):
            found.update(repo.under(ref))
        elif "*" in ref:
            found.update(f for f in repo.files if fnmatch.fnmatchcase(f, ref))
        elif repo.has(ref):
            found.add(ref)
    return tuple(sorted(found))


def card_facts(
    repo: Repo,
    scrub: Scrubber,
    cards: Sequence[Card],
    table: tuple[Module, ...],
    known: Sequence[str],
) -> tuple[CardFact, ...]:
    return tuple(
        CardFact(
            id=c.id,
            title=clip(scrub.clean(c.title), TITLE_MAX),
            module=module_of(c.id, table),
            refs=tuple(dict.fromkeys(scrub.clean(r) for r in resolved(repo, c))),
            services=_services(c.fields.get("Outside services", ""), known),
        )
        for c in cards
    )


def _route_files(routes: Sequence[Route], prefix: str) -> set[str]:
    return {r.module for r in routes if r.path == prefix or r.path.startswith(prefix + "/")}


def _panel(repo: Repo, routes: Sequence[Route], scrub: Scrubber, pid: str, text: str) -> ScreenFact:
    title = re.search(rf"\bid=\"t-{re.escape(pid)}\"[^>]*>([^<]+)<", text)
    mods = {f for f in repo.under(STATIC) if fnmatch.fnmatchcase(f, f"{STATIC}console-{pid}*.js")}
    files = {scrub.clean(f) for f in {CONSOLE, *mods}} | _route_files(routes, f"/v1/{pid}")
    return ScreenFact(
        id=pid.replace("-", "_"),
        title=clip(scrub.clean(title.group(1).strip()) if title else pid.title(), 80),
        refs=tuple(sorted(files)),
    )


def _show(repo: Repo, routes: Sequence[Route], scrub: Scrubber) -> ScreenFact:
    loads = {STATIC + name for name in _SCRIPT.findall(repo.text(SHOW) or "")}
    files = {scrub.clean(f) for f in {SHOW, *loads} if repo.has(f)}
    return ScreenFact(
        id="show",
        title=SHOW_TITLE,
        refs=tuple(sorted(files | _route_files(routes, "/v1/book/show"))),
    )


def screens(repo: Repo, routes: Sequence[Route], scrub: Scrubber) -> tuple[ScreenFact, ...]:
    text = repo.text(CONSOLE)
    if text is None:
        return ()
    ids = list(dict.fromkeys(_PANEL.findall(text)))
    panels = [_panel(repo, routes, scrub, pid, text) for pid in ids]
    return (*panels, _show(repo, routes, scrub)) if repo.has(SHOW) else tuple(panels)


def roadmap(text: str) -> tuple[str, ...]:
    """§11's first cells in words: "R6.4 The Book's new look" -> "R6.4, the Book's new look"."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if re.match(r"^## 11\.", ln)), None)
    if start is None:
        return ()
    out: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        cells = _cells(line) if line.startswith("|") else []
        if len(cells) < 2 or cells[0] in ("Release", "") or set(cells[0]) <= set("-: "):
            continue
        m = _RELEASE.match(cells[0])
        rest = m.group(2) if m else ""
        rest = "the" + rest[3:] if rest.startswith("The ") else rest
        out.append(f"{m.group(1)}, {rest}" if m else cells[0])
    return tuple(out)


__all__ = [
    "GUIDE",
    "SHOW_TITLE",
    "Card",
    "card_facts",
    "expand",
    "guide_cards",
    "resolved",
    "roadmap",
    "screens",
    "service_items",
]

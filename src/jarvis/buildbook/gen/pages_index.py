# src/jarvis/buildbook/gen/pages_index.py
"""R6.3 D3 (docs/plans/r6-3-book-content.md): the full book's pages index, deterministic, from
the fact pack (which read the guide, the module map, the console and the services inventory).

`build(repo, facts) -> tuple[IndexedPage, ...]`, in this fixed order:

    chapters  the eight of "JARVIS in plain words" (`facts_model.CHAPTERS`, `pg_chapter_<id>`),
              each from a fixed list of cards and files (`CHAPTER_SOURCES`): its files and its
              cards' own file references (an overview: a card's folders are that card's page's);
              "What's planned" also from this release's own plan
    modules   each module of the map (`pg_module_<id>`): its cards and the files they name
              themselves (an overview, like a chapter; their folders only when they name none)
    cards     each card under its module (`pg_card_c16`, `chapter` = the module id): its "Where in
              the code" (resolved and scrubbed by the pack)
    screens   the console's panels and the show (`pg_screen_<id>`): their files; sources = the
              cards citing one of them
    services  each outside service (`pg_service_<slug>`): sources = the cards naming it; refs =
              config.py and every module that reads one of its settings or names one of its API
              hosts (the coverage checker's `service_fields` and `api_hosts`)

Every page's `refs` are full, scrubbed paths of tracked files, sorted: a folder reference is
expanded to its files and a glob to its matches, leaving out what no reading pack reads (D4:
tests/, evals/, .claude/, `*.env*`), vendored files and binary assets (D12's change test compares
files; a file the guide names itself always stays). A card whose references name no tracked file is
a GenError. On this branch 8 + 18 + 73 + 23 + 31 = 153 pages (the plan's 152 counts 22 screens;
the show is the 23rd).
"""

from __future__ import annotations

import bisect
import fnmatch
import re
from collections.abc import Iterable, Mapping, Sequence

from jarvis.buildbook.facts_model import CHAPTERS, CardFact, FactPack, IndexedPage
from jarvis.buildbook.gen import plans
from jarvis.buildbook.gen import services as services_mod
from jarvis.buildbook.gen.code import service_owners, slug
from jarvis.buildbook.gen.repo import GenError, Repo

# each chapter's cards (when the guide has them) and files (when the checkout has them)
CHAPTER_SOURCES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "what": (("C01", "C09", "C13", "C57"), ("README.md", "src/jarvis/__init__.py")),
    "example": (
        ("C05", "C06", "C13", "C16", "C18", "C28", "C30", "C48", "C52"),
        ("src/jarvis/tools/google_calendar.py", "src/jarvis/tools/calendar_undo.py"),
    ),
    "data": (("C41", "C42", "C49", "C51", "C53", "C66"), ("deploy/cloudrun.sh",)),
    "answers": (("C13", "C14", "C15", "C16", "C17", "C68"), ()),
    "setup": (("C01", "C02", "C03", "C49"), ("Makefile", "docker-compose.yml", "pyproject.toml")),
    "technology": (
        ("C58",),
        (
            "pyproject.toml",
            "requirements.lock",
            "android/gradle/libs.versions.toml",
            "deploy/home/docker-compose.yml",
            "deploy/home/bridge-requirements.txt",
            "tools/markdy/package-lock.json",
        ),
    ),
    "costs": (("C44", "C54", "C55"), ("src/jarvis/llm/pricing.py", "src/jarvis/billing/fx.py")),
    "planned": ((), ("docs/architecture/JARVIS-Architecture.md",)),
}
CONFIG = "src/jarvis/config.py"
SRC = "src/jarvis/"
VENDORED = re.compile(r"(?:^|/)(?:vendor|node_modules)/")
PACKLESS = ("tests/", "evals/", ".claude/")  # D4: no reading pack reads these
BINARY = (".woff2", ".woff", ".ttf", ".onnx", ".wasm", ".glb", ".png", ".jpg", ".webp", ".ico")


def quoted(path: str) -> bool:
    """A file a folder's page may quote: one a reading pack may read (D4: never `tests/**`,
    `evals/**`, `.claude/**` or a `*.env*` file), not vendored, not a binary asset."""
    if path.startswith(PACKLESS) or ".env" in path.rsplit("/", 1)[-1]:
        return False
    return not VENDORED.search(path) and not path.lower().endswith(BINARY)


def direct(card: CardFact) -> list[str]:
    """The files a card names itself (not its folders or globs)."""
    return [r for r in card.refs if not r.endswith("/") and "*" not in r]


def _under(paths: Sequence[str], folder: str) -> Iterable[str]:
    start = bisect.bisect_left(paths, folder)
    for path in paths[start:]:
        if not path.startswith(folder):
            return
        yield path


def expand(refs: Iterable[str], paths: Sequence[str]) -> tuple[str, ...]:
    """The tracked files (`paths`: the pack's sorted, scrubbed index) a list of references
    names: a folder (ending in `/`) its files and a glob its matches, each `quoted`; a file
    itself (whatever it is: the guide named it)."""
    found: set[str] = set()
    for ref in refs:
        if ref.endswith("/"):
            found.update(p for p in _under(paths, ref) if quoted(p))
        elif "*" in ref:
            pattern = ref.replace("[", "[[]")  # a scrubbed "[removed]" is no character class
            found.update(p for p in paths if fnmatch.fnmatchcase(p, pattern) and quoted(p))
        elif ref in paths:
            found.add(ref)
    return tuple(sorted(found))


def _page(kind: str, pid: str, title: str, part: str, **kw: object) -> IndexedPage:
    fields = {"id": f"pg_{kind}_{pid}", "kind": kind, "title": title, "part": part, **kw}
    return IndexedPage.model_validate(fields)


def _card_refs(card: CardFact, paths: Sequence[str]) -> tuple[str, ...]:
    files = expand(card.refs, paths)
    if card.refs and not files:
        raise GenError(f"{card.id}: its Where in the code names no tracked file")
    return files


def _chapters(repo: Repo, facts: FactPack) -> list[IndexedPage]:
    own = plans.plan_paths(repo)[:1]
    named = {c.id: direct(c) for c in facts.cards}
    known = set(facts.index.paths)
    out = []
    for cid, title in CHAPTERS:
        cards, files = CHAPTER_SOURCES.get(cid, ((), ()))
        cards = tuple(c for c in cards if c in named)
        plan = tuple(own) if cid == "planned" else ()
        refs = {r for c in cards for r in named[c]} | set(files) | set(plan)
        kept = tuple(sorted(r for r in refs if r in known))
        out.append(_page("chapter", cid, title, "plain", refs=kept, sources=(*cards, *plan)))
    return out


def _either(names: Iterable[str], head: str, tail: str) -> re.Pattern[str] | None:
    alts = sorted(map(re.escape, names))
    return re.compile(head + "(" + "|".join(alts) + ")" + tail) if alts else None


def service_files(repo: Repo, facts: FactPack) -> dict[str, tuple[str, ...]]:
    """Each service's files (only paths the scrubber leaves as they are: src/ holds no handle)."""
    try:
        table = services_mod.tables(repo.root)
    except ValueError:
        return {}
    fields = tuple(table.get("service_fields", ()))
    hosts: Mapping[str, str] = dict(table.get("api_hosts", {}))
    readers = {s.name: o for s in facts.settings if (o := service_owners(s.name, fields))}
    found: dict[str, set[str]] = {}
    for owners in readers.values():
        for owner in owners:
            found.setdefault(owner, set()).add(CONFIG)
    attr, host = _either(readers, r"\.", r"\b"), _either(hosts, r"://", r"\b")
    for rel in (r for r in repo.under(SRC) if r.endswith(".py") and r != CONFIG):
        text = repo.text(rel) or ""
        for m in attr.finditer(text) if attr else ():
            for owner in readers[m.group(1)]:
                found.setdefault(owner, set()).add(rel)
        for m in host.finditer(text) if host else ():
            found.setdefault(hosts[m.group(1)], set()).add(rel)
    known = set(facts.index.paths)
    return {s: tuple(sorted(f for f in files if f in known)) for s, files in found.items()}


def _citing(refs: Iterable[str], refs_of: Mapping[str, tuple[str, ...]]) -> tuple[str, ...]:
    wanted = set(refs)
    return tuple(sorted(c for c, files in refs_of.items() if wanted & set(files)))


def build(repo: Repo, facts: FactPack) -> tuple[IndexedPage, ...]:
    refs_of = {c.id: _card_refs(c, facts.index.paths) for c in facts.cards}
    titles = {c.id: c.title for c in facts.cards}
    pages = _chapters(repo, facts)
    named = {c.id: direct(c) for c in facts.cards}
    known = set(facts.index.paths)
    for m in facts.modules:
        mine = tuple(c for c in m.cards if c in refs_of)
        refs = tuple(sorted({r for c in mine for r in named[c] if r in known}))
        refs = refs or tuple(sorted({r for c in mine for r in refs_of[c]}))
        pages.append(_page("module", m.id, m.title, "modules", refs=refs, sources=mine))
    for m in facts.modules:
        for c in (c for c in m.cards if c in refs_of):
            kw = {"refs": refs_of[c], "sources": (c,), "chapter": m.id}
            pages.append(_page("card", c.lower(), titles[c], "parts", **kw))
    for s in facts.screens:
        kw = {"refs": s.refs, "sources": _citing(s.refs, refs_of)}
        pages.append(_page("screen", s.id, s.title, "screens", **kw))
    files = service_files(repo, facts)
    for name in facts.services:
        naming = tuple(sorted(c.id for c in facts.cards if name in c.services))
        refs = files.get(name) or tuple(sorted({r for c in naming for r in refs_of[c]}))
        pages.append(_page("service", slug(name), name, "services", refs=refs, sources=naming))
    return tuple(pages)


__all__ = ["CHAPTER_SOURCES", "build", "expand", "quoted", "service_files", "slug"]

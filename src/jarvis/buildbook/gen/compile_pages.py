# src/jarvis/buildbook/gen/compile_pages.py
"""R6.3.1 D4 (docs/plans/r6-3-1-book-at-build.md): the Workshop's authored pages compiled into the
release's full book, by the generator, with no AI call and no owner step.

`compile_pages(repo, pack, scrub=...)` reads every indexed page's files under `repo.root`
(`book/authored.judge`: the six checks, the flowchart's and staleness, against THIS release's
fact pack) and gives `Compiled`:

- `pages`: `writer/model.PagesFile` v2 (`writer/pages.encode_file`: gzipped canonical JSON, at
  most 2 MiB), every indexed page in the index's order. A page that is `ok` or `stale` (CI is the
  gate for staleness, D6) is served written: its five sections filled from the pack, the
  generated "Where in the code", and `PageMeta {written_by, written_on, release, version}`. A
  page that is `missing` or `failing`, or that can't be filled within its caps, is the
  generator's plain text (`pages.generator_page`): a page never breaks the build or the deploy.
- `flows`: the flowcharts of the pages served written, by page id (`pages.encode_flows`).
- `counts`: {"written": n, "generator": n}, for the generator's summary (no text).

The owner-address check runs when JARVIS_OWNER_EMAILS names them (`pages_cli.owner_emails`).
The same files and pack always give the same bytes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import ValidationError

from jarvis.buildbook.book import authored
from jarvis.buildbook.book.authored import Env, PageFile
from jarvis.buildbook.book.flow import FlowSpec
from jarvis.buildbook.facts_model import FactPack, IndexedPage
from jarvis.buildbook.gen.repo import GenError, Repo
from jarvis.buildbook.gen.scrub import Scrubber
from jarvis.buildbook.writer import fill, pages
from jarvis.buildbook.writer.model import Page, PageMeta, PagesFile

SERVED = ("ok", "stale")  # D4, D6: a stale page is served; CI refuses to merge it


@dataclass(frozen=True)
class Compiled:
    pages: bytes
    flows: bytes
    counts: dict[str, int] = field(default_factory=dict)


def _meta(page: PageFile, pack: FactPack) -> PageMeta:
    release = pack.release
    if release is None:
        raise GenError("the fact pack names no release to compile the pages for")
    return PageMeta(written_by=page.written_by, written_on=page.written_on, release=release.id,
                    version=release.version)  # fmt: skip


def _written(ip: IndexedPage, page: PageFile, pack: FactPack) -> Page | None:
    """The page filled from the pack, or None when a fact is gone or a section passes its cap."""
    if any(fill.unknown_keys(text, pack) for text in page.sections.values()):
        return None
    try:
        filled = {sid: fill.fill(text, pack) for sid, text in page.sections.items()}
        return pages.written(ip, filled, _meta(page, pack))
    except (ValueError, ValidationError):
        return None


def compile_pages(
    repo: Repo, pack: FactPack, *, scrub: Scrubber, emails: tuple[str, ...] = ()
) -> Compiled:
    env = Env(facts=pack, scrub=scrub, repo=repo, emails=emails)
    flows = authored.all_flows(repo.root).items
    out: list[Page] = []
    charts: dict[str, FlowSpec] = {}
    for ip in pack.pages:
        verdict = authored.judge(repo.root, ip, env)
        page = None
        if verdict.page is not None and verdict.status in SERVED:
            page = _written(ip, verdict.page, pack)
        if page is None:
            out.append(pages.generator_page(ip, pack))
            continue
        out.append(page)
        if ip.id in flows:
            charts[ip.id] = flows[ip.id]
    written = sum(p.meta is not None for p in out)
    f = PagesFile(
        release=pack.release.id if pack.release is not None else "0000000",
        pages=tuple(out),
        modules={m.id: m.title for m in pack.modules},
        limitations=len(pack.limitations),
    )
    try:
        data, chart_bytes = pages.encode_file(f), pages.encode_flows(charts)
    except ValueError as exc:
        raise GenError(f"the full book can't be written: {exc}") from None
    return Compiled(data, chart_bytes, {"written": written, "generator": len(out) - written})


__all__ = ["SERVED", "Compiled", "compile_pages"]

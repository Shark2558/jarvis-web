# src/jarvis/buildbook/gen/compile_narration.py
"""R6.4 D6 (docs/plans/r6-4-book-look.md): the chapters' narration compiled with the pages, by the
generator, with no AI call: `compile_narration(env, written)` -> (`writer/model.Narration`, the
number of chapters narrated).

Every chapter of the release's index (`book/chapters.py`, 26 on this tree) is in the block. A
chapter is narrated when its script is `ok` or `stale` (CI is the gate for staleness, as for the
pages) AND every page of it is served written (`written`: the page ids compiled from the
Workshop's text): its lines with their facts filled and their cues kept (a `count` cue's target is
its filled amount, "₹2.9"), its minutes at 150 words a minute and who wrote it. Any other chapter
is listed with its pages only. A script that is missing, fails a check, or breaks in a way nobody
foresaw is that chapter's problem alone: the build goes on (`pages --check` is the strict gate).
The pages file carries the block (`compile_pages`), so the sealer seals it with the release.
"""

from __future__ import annotations

from jarvis.buildbook.book import chapters as ch
from jarvis.buildbook.book import narration_check as nc
from jarvis.buildbook.book.authored import Env
from jarvis.buildbook.facts_model import FactPack
from jarvis.buildbook.writer import fill
from jarvis.buildbook.writer.model import (
    BookChapter,
    ChapterCue,
    ChapterLine,
    Narration,
    ScriptMeta,
)
from jarvis.logging import get_logger

log = get_logger(__name__)
SERVED = ("ok", "stale")


def _line(t: nc.Told, facts: FactPack) -> ChapterLine:
    filled = (fill.fill(c.target, facts) if c.kind == "count" else c.target for c in t.cues)
    cues = tuple(ChapterCue(kind=c.kind, target=f) for c, f in zip(t.cues, filled, strict=True))
    return ChapterLine(n=t.n, page=t.page, text=fill.fill(t.text, facts), cues=cues)


def _narrated(env: Env, plan: ch.ChapterPlan, base: BookChapter) -> BookChapter:
    verdict = nc.judge_script(env.repo.root, plan, env)
    if verdict.status not in SERVED or verdict.script is None:
        return base
    lines = tuple(_line(t, env.facts) for t in verdict.told)
    meta = ScriptMeta(written_by=verdict.script.written_by, written_on=verdict.script.written_on)
    minutes = nc.minutes_of(ln.text for ln in lines)
    done = {"lines": [ln.model_dump() for ln in lines], "minutes": minutes,
            "written": meta.model_dump()}  # fmt: skip
    return BookChapter.model_validate({**base.model_dump(), **done})


def compiled_chapter(env: Env, plan: ch.ChapterPlan, written: frozenset[str]) -> BookChapter:
    base = BookChapter(id=plan.id, title=plan.title, kind=plan.kind, pages=plan.pages)
    if not all(p in written for p in plan.pages):
        return base
    try:
        return _narrated(env, plan, base)
    except Exception as exc:  # noqa: BLE001 - one chapter never breaks the build (as the pages)
        log.warning("a narration script was not compiled", extra={"error": type(exc).__name__})
        return base


def compile_narration(env: Env, written: frozenset[str]) -> tuple[Narration, int]:
    out = tuple(compiled_chapter(env, plan, written) for plan in ch.chapters(env.facts.pages))
    return Narration(chapters=out), sum(c.narrated for c in out)


__all__ = ["SERVED", "compile_narration", "compiled_chapter"]

# tests/test_r64_i0_compile.py
"""R6.4 D6 (docs/plans/r6-4-book-look.md): the narration is compiled with the pages at build time
(facts filled, cues kept) and sealed with each release INSIDE the pages file, as its optional
`narration` block: the chapters (all 26, narrated or not) and each narrated chapter's lines. A
pages file with no narration has exactly the v6.3.2 bytes; the sealed release keeps its four
files, so a rollback to v6.3.2 still opens the vault's index (I0-NOTES, the sealing choice)."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from r631_i0_fakes import PACK, STORE, hashes_of, make_repo, page_text, write_flow, write_page
from test_r64_i0_narration import GOOD_LINES, script, write_script

from jarvis.buildbook.book import chapters as ch
from jarvis.buildbook.book import narration_check as nc
from jarvis.buildbook.book.authored import Env
from jarvis.buildbook.book.files import stamped
from jarvis.buildbook.book.narration import script_path
from jarvis.buildbook.gen import compile_pages
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.gen.scrub import default_scrubber
from jarvis.buildbook.writer import pages
from jarvis.buildbook.writer.model import BookChapter, ChapterLine, Narration, PagesFile


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    base = make_repo(tmp_path)
    for page in PACK.pages:
        write_page(base, page.id, page_text(page.id, hashes_of(base, page.refs)))
    for pid in ("pg_chapter_example", "pg_module_demo"):
        write_flow(base, pid)
    return base


def _stamp_script(root: Path, lines: list[str] | None = None) -> None:
    write_script(root, script(lines))
    plan = ch.find(ch.chapters(PACK.pages), "module_demo")
    assert plan is not None
    path = script_path(root, plan.id)
    path.write_text(stamped(path.read_text(encoding="utf-8"), nc.stamps(root, plan), "pages"))


def _compiled(root: Path) -> tuple[PagesFile, compile_pages.Compiled]:
    out = compile_pages.compile_pages(Repo.from_git(root), PACK, scrub=default_scrubber())
    return pages.decode_file(out.pages), out


def test_a_good_script_is_compiled_with_facts_filled_and_cues_kept(root: Path) -> None:
    _stamp_script(root)
    f, out = _compiled(root)
    assert f.narration is not None and out.counts["narrated"] == 1
    story, demo = f.narration.chapters
    assert (story.id, story.narrated, story.minutes, story.lines) == ("story_example", False, 0, ())
    assert demo.id == "module_demo" and demo.narrated and demo.minutes == 1
    assert demo.pages == ("pg_module_demo", "pg_card_c01", "pg_card_c02")
    assert demo.written is not None and demo.written.written_by == "Workshop · Mark XXIV"
    five = demo.lines[4]
    assert (five.n, five.page, five.text) == (5, "pg_module_demo", "It tries at most 3 times "
                                              "before it gives up.")  # fmt: skip
    assert [(c.kind, c.target) for c in five.cues] == [("count", "3")]
    six = demo.lines[5]
    assert [(c.kind, c.target) for c in six.cues] == [("page", "pg_card_c01"), ("show", "plain")]
    assert demo.lines[6].text == "The store keeps its notes for 30 days."
    assert [ln.n for ln in demo.lines] == list(range(1, 8))


def test_a_stale_script_is_still_compiled_and_a_failing_one_is_not(root: Path) -> None:
    write_script(root, script())  # never stamped: stale, served (CI is the gate)
    assert _compiled(root)[0].narration.chapters[1].narrated  # type: ignore[union-attr]
    write_script(root, script(["It tries 3 times.", *GOOD_LINES]))
    f, out = _compiled(root)
    assert f.narration is not None and not f.narration.chapters[1].narrated
    assert out.counts["narrated"] == 0


def test_a_chapter_with_a_page_served_as_the_generator_s_text_is_not_narrated(root: Path) -> None:
    _stamp_script(root)
    write_page(root, "pg_card_c02", page_text("pg_card_c02", hashes_of(root, (STORE,)), "## Bad"))
    f, _ = _compiled(root)
    assert f.narration is not None and not f.narration.chapters[1].narrated


def test_the_bytes_are_the_same_twice_and_a_file_without_narration_is_v6_3_2_s(
    root: Path,
) -> None:
    _stamp_script(root)
    one, two = _compiled(root)[1], _compiled(root)[1]
    assert one.pages == two.pages
    tree = json.loads(gzip.decompress(one.pages))
    assert set(tree) == {"v", "release", "pages", "modules", "limitations", "narration"}
    bare = PagesFile(release=tree["release"], pages=pages.decode_file(one.pages).pages)
    assert "narration" not in json.loads(gzip.decompress(pages.encode_file(bare)))
    assert pages.decode_file(pages.encode_file(bare)).narration is None


LINE: dict[str, Any] = {"n": 1, "page": "pg_module_demo", "text": "Hello.", "cues": []}


def _chapter(**kw: Any) -> dict[str, Any]:
    line = LINE
    who = {"written_by": "Workshop · Mark XXIV", "written_on": "2026-11-25"}
    base = {"id": "module_demo", "title": "The demo", "kind": "module",
            "pages": ["pg_module_demo"], "minutes": 1, "lines": [line], "written": who}  # fmt: skip
    return {**base, **kw}


@pytest.mark.parametrize(
    "bad",
    [
        _chapter(lines=[{"n": 1, "page": "pg_card_c01", "text": "Elsewhere.", "cues": []}]),
        _chapter(lines=[{"n": 2, "page": "pg_module_demo", "text": "Two.", "cues": []}]),
        _chapter(written=None),
        _chapter(minutes=0),
        _chapter(id="vault"),
        _chapter(lines=[{"n": 1, "page": "pg_module_demo", "text": "x" * 241, "cues": []}]),
        _chapter(lines=[{**LINE, "cues": [{"kind": "glow", "target": "a"}]}]),
        _chapter(mood="calm"),
    ],
)
def test_a_compiled_chapter_that_does_not_hold_together_is_refused(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        BookChapter.model_validate(bad)


def test_the_narration_block_holds_each_page_once_and_only_the_file_s_pages(root: Path) -> None:
    ok = BookChapter.model_validate(_chapter())
    twice = ok.model_copy(update={"id": "story_example"})
    with pytest.raises(ValidationError):
        Narration(chapters=(ok, twice))
    f, _ = _compiled(root)
    ghost = ok.model_copy(update={"pages": ("pg_card_c99",), "lines": (
        ChapterLine(n=1, page="pg_card_c99", text="Ghost."),)})  # fmt: skip
    with pytest.raises(ValidationError):
        PagesFile(release=f.release, pages=f.pages, narration=Narration(chapters=(ghost,)))


def test_the_env_the_compile_uses_is_the_pages_one(root: Path) -> None:
    """The compile judges each script with the same fact pack, scrubber and repo as the pages."""
    env = Env(facts=PACK, scrub=default_scrubber(), repo=Repo.from_git(root))
    plan = ch.find(ch.chapters(PACK.pages), "module_demo")
    assert plan is not None and nc.judge_script(root, plan, env).status == "missing"

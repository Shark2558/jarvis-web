# tests/test_r64_i0_narration_cli.py
"""R6.4 D6 (docs/plans/r6-4-book-look.md): the narration writers' tools in `pages`:
`--narration-list`, `--narration-pack ID`, `--narration-check [IDS] [--allow-missing]`,
`--narration-stamp IDS`, and the strict `pages --check` that checks the narration too."""

from __future__ import annotations

from pathlib import Path

import pytest
from r631_i0_fakes import (
    BOOK,
    PACK,
    ROUTER,
    hashes_of,
    make_repo,
    page_text,
    seed_cache,
    write_flow,
    write_page,
)
from test_r64_i0_narration import GOOD_LINES, TRIES, script, write_script

from jarvis.buildbook.gen import __main__ as gen_main


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    base = make_repo(tmp_path)
    seed_cache(base)
    for page in PACK.pages:  # every page written and stamped: `pages --check` passes
        write_page(base, page.id, page_text(page.id, hashes_of(base, page.refs)))
    for pid in ("pg_chapter_example", "pg_module_demo"):
        write_flow(base, pid)
    return base


def _run(root: Path, capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, list[str]]:
    code = gen_main.main(["pages", "--repo", str(root), *args])
    return code, capsys.readouterr().out.splitlines()


def test_list_names_every_chapter_with_its_pages_status_and_minutes(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_script(root, script())
    code, lines = _run(root, capsys, "--narration-list")
    assert code == 0
    assert lines == [
        "story_example\tstory\tThe running example\t1 page\tmissing\t0 min",
        "module_demo\tmodule\tThe demo\t3 pages\tstale\t1 min",
        "2 chapters: 0 ok, 1 stale, 0 failing, 1 missing",
    ]


def test_check_then_stamp_then_ok_and_strays_are_named(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_script(root, script())
    write_script(root, script(chapter="module_gone"), name="module_gone")
    code, lines = _run(root, capsys, "--narration-check", "--allow-missing")
    assert code == 1
    assert "module_demo: stale: not stamped yet: run `pages --narration-stamp module_demo`" in lines
    assert "narration/module_gone.md: not a chapter of the book" in lines
    assert (
        lines[-1]
        == "checked 2 narrations: 0 ok, 1 stale, 0 failing, 1 missing (allowed); 2 problems"
    )
    assert _run(root, capsys, "--narration-stamp", "module_demo") == (
        0, ["module_demo: stamped (3 pages)"],
    )  # fmt: skip
    text = (root / BOOK / "narration" / "module_demo.md").read_text(encoding="utf-8")
    assert '"pg_card_c02": "' in text and "- [show:title]" in text
    (root / BOOK / "narration" / "module_gone.md").unlink()
    code, lines = _run(root, capsys, "--narration-check", "module_demo")
    assert (code, lines[-1]) == (
        0,
        "checked 1 narration: 1 ok, 0 stale, 0 failing, 0 missing; 0 problems",
    )
    code, lines = _run(root, capsys, "--narration-check", "module_nope")
    assert code == 1 and lines[0] == "module_nope: not a chapter of the book"


def test_stamp_refuses_a_script_with_a_problem_and_a_missing_one(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_script(root, script(["It tries 3 times.", *GOOD_LINES]))
    before = path.read_text(encoding="utf-8")
    code, lines = _run(root, capsys, "--narration-stamp", "module_demo", "story_example")
    assert code == 1 and path.read_text(encoding="utf-8") == before
    assert lines == [
        "module_demo: not stamped: numbers: line 6: a typed number (write {{fact:<key>}})",
        "story_example: not stamped: missing",
    ]


def test_the_strict_page_check_checks_the_narration_too(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, lines = _run(root, capsys, "--check")
    assert code == 1
    assert "story_example: missing" in lines and "module_demo: missing" in lines
    assert lines[-1].startswith(
        "checked 6 pages: 6 ok, 0 stale, 0 failing, 0 missing; 2 narrations"
    )
    code, lines = _run(root, capsys, "--check", "--allow-missing")
    assert code == 0 and lines[-1].endswith("2 missing (allowed); 0 problems")
    write_script(root, script(["[node:nope] A box.", *GOOD_LINES]))
    code, lines = _run(root, capsys, "--check", "--allow-missing")
    assert (
        code == 1
        and "module_demo: cues: line 6: [node:nope] is not a box of pg_module_demo" in lines
    )
    assert _run(root, capsys, "--check", "pg_card_c01")[0] == 0  # a page check by id: pages only


def test_pack_gives_a_writer_each_page_s_sections_boxes_connectors_and_facts(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, lines = _run(root, capsys, "--narration-pack", "module_demo")
    text = "\n".join(lines)
    assert code == 0
    wanted = (
        "chapter: module_demo - The demo (module, 3 pages)",
        f"write: {BOOK}/narration/module_demo.md",
        "page 1 of 3: pg_module_demo - The demo (module)",
        "  box ask: A request (person)", "  connector pick>notes: keeps (side)",
        "page 2 of 3: pg_card_c01 - Demo router (card)", "  flowchart: none (use [show:...] cues)",
        "  How it works: The router", f"{ROUTER}:MAX_TRIES = 3  [verified]",
    )  # fmt: skip
    for want in wanted:
        assert want in text, want
    assert TRIES.strip("{}").removeprefix("fact:") in text
    assert _run(root, capsys, "--narration-pack", "module_nope") == (
        1, ["module_nope: not a chapter of the book"],
    )  # fmt: skip

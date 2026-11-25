# tests/test_r64_i0_narration.py
"""R6.4 D6 (docs/plans/r6-4-book-look.md): a chapter's narration script, `book/narration/<id>.md`:
front matter (chapter, written_by, written_on, pages -> stamps), one spoken line per list item with
optional cues first; and its checks: pages of the chapter told in order, each at least once; cue
targets in that page's flowchart; facts that resolve; no backticks, paths, code names or web
addresses read aloud; a line <= 240 characters once filled; stale when a page changes."""

from __future__ import annotations

from pathlib import Path

import pytest
from r631_i0_fakes import (
    BOOK,
    GOOD_FLOW,
    PACK,
    ROUTER,
    STORE,
    make_repo,
    page_text,
    write_flow,
    write_page,
)

from jarvis.buildbook.book import chapters as ch
from jarvis.buildbook.book import narration_check as nc
from jarvis.buildbook.book.authored import AuthoredError, Env
from jarvis.buildbook.book.files import stamped
from jarvis.buildbook.book.narration import all_scripts, load_script, script_path
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.gen.scrub import default_scrubber

PLAN = ch.find(ch.chapters(PACK.pages), "module_demo")
TRIES, KEEP = f"{{{{fact:{ROUTER}:MAX_TRIES}}}}", f"{{{{fact:{STORE}:KEEP_DAYS}}}}"
GOOD_LINES = [
    "[show:title] The demo module picks one model for each request.",
    "[show:overview] Here is the whole path at a glance.",
    "[node:ask] It starts with a request.",
    "[edge:ask>pick] The request goes to the picker, which chooses a tier.",
    f"[count:{TRIES}] It tries at most {TRIES} times before it gives up.",
    "[page:pg_card_c01] [show:plain] The router is the part that does the picking.",
    f"[page:pg_card_c02] [show:costs] The store keeps its notes for {KEEP} days.",
]


def script(lines: list[str] | None = None, *, chapter: str = "module_demo", extra: str = "") -> str:
    body = "\n".join(f"- {line}" for line in (GOOD_LINES if lines is None else lines))
    head = ["---", f"chapter: {chapter}", "written_by: Workshop · Mark XXIV",
            "written_on: 2026-11-25", *([extra] if extra else []), "---"]  # fmt: skip
    return "\n".join(head) + "\n" + body + "\n"


def write_script(root: Path, text: str, name: str = "module_demo") -> Path:
    path = root / BOOK / "narration" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = make_repo(tmp_path)
    for pid in ("pg_module_demo", "pg_card_c01", "pg_card_c02", "pg_chapter_example"):
        write_page(r, pid, page_text(pid))
    write_flow(r, "pg_module_demo")
    return r


def env_of(root: Path) -> Env:
    return Env(facts=PACK, scrub=default_scrubber(), repo=Repo.from_git(root))


def judge(root: Path, lines: list[str] | None = None) -> nc.ScriptVerdict:
    assert PLAN is not None
    write_script(root, script(lines))
    return nc.judge_script(root, PLAN, env_of(root))


def problems(root: Path, lines: list[str]) -> list[str]:
    return [p for p in judge(root, lines).problems if not p.startswith(nc.STALE)]


def stamp(root: Path) -> None:
    assert PLAN is not None
    path = script_path(root, PLAN.id)
    path.write_text(stamped(path.read_text(encoding="utf-8"), nc.stamps(root, PLAN), "pages"))


# ---- the file -----------------------------------------------------------------------------------
def test_a_good_script_parses_with_its_rows_cues_and_words(root: Path) -> None:
    got = load_script(write_script(root, script()))
    assert got.chapter == "module_demo" and got.pages == {}
    assert [s.row for s in got.lines] == list(range(6, 13))
    first = got.lines[5]
    assert [(c.kind, c.target) for c in first.cues] == [("page", "pg_card_c01"), ("show", "plain")]
    assert first.text == "The router is the part that does the picking."


@pytest.mark.parametrize(
    ("text", "said"),
    [
        (script(["Not a list item"]).replace("- Not", "Not"), "line 6 is not a list item"),
        (script(["[say:hello] Hi there."]), "[say:...] is not a cue"),
        (script(["[node:ask]"]), "no words after its cues"),
        (script(["[node: ] Words."]), "a cue names nothing"),
        (script(["[node:ask Words."]), "a cue is written [kind:target]"),
        (script(chapter="module_other"), "the chapter field must equal the file name"),
        (script(extra="mood: calm"), "an unknown field"),
        (script(extra="pages: {pg_module_demo: xyz}"), "16 lower-case hex"),
        ("- [show:title] No front matter.\n", "no front matter"),
        (script([]), "no spoken lines"),
    ],
)
def test_a_file_that_cannot_be_read_is_one_plain_error(root: Path, text: str, said: str) -> None:
    with pytest.raises(AuthoredError) as err:
        load_script(write_script(root, text))
    assert said in str(err.value) and str(err.value).startswith("narration/module_demo.md")


def test_the_file_name_must_be_a_chapter_id_and_strays_are_listed(root: Path) -> None:
    write_script(root, script(), name="module_demo")
    (root / BOOK / "narration" / "notes.txt").write_text("x", encoding="utf-8")
    write_script(root, script(chapter="Bad-Name"), name="Bad-Name")
    found = all_scripts(root)
    assert set(found.items) == {"module_demo"}
    assert set(found.errors) == {"narration/notes.txt", "narration/Bad-Name.md"}
    assert "not a chapter id" in found.errors["narration/Bad-Name.md"]


# ---- the checks ---------------------------------------------------------------------------------
def test_a_good_script_needs_only_its_stamp_then_is_ok(root: Path) -> None:
    first = judge(root)
    assert first.status == "stale" and first.problems == (
        "stale: not stamped yet: run `pages --narration-stamp module_demo`",
    )
    assert [t.page for t in first.told] == ["pg_module_demo"] * 5 + ["pg_card_c01", "pg_card_c02"]
    stamp(root)
    assert nc.judge_script(root, PLAN, env_of(root)).status == "ok"  # type: ignore[arg-type]


def test_a_page_s_text_or_flow_change_makes_it_stale_but_its_sources_stamp_doesnt(
    root: Path,
) -> None:
    judge(root)
    stamp(root)
    write_page(root, "pg_card_c01", page_text("pg_card_c01", {ROUTER: "0" * 16}))
    assert nc.judge_script(root, PLAN, env_of(root)).status == "ok"  # type: ignore[arg-type]
    write_flow(root, "pg_module_demo", {**GOOD_FLOW, "title": "The demo router, again"})
    got = nc.judge_script(root, PLAN, env_of(root))  # type: ignore[arg-type]
    assert got.status == "stale"
    assert got.problems == ("stale: pg_module_demo changed since the script was stamped",)


@pytest.mark.parametrize(
    ("line", "said"),
    [
        ("[node:nope] A box.", "cues: line 6: [node:nope] is not a box of pg_module_demo"),
        ("[edge:pick>ask] Back.", "is not a connector of pg_module_demo"),
        ("[show:intro] Hello.", "[show:...] is one of title, plain"),
        ("[count:5] Five.", "[count:...] is ₹{{fact:<key>}}"),
        ("[count:{{fact:hosting.region}}] Unverified region.", "[count:...] is ₹"),
        ("[show:costs] [show:fails] Two.", "has two [show:...]"),
        ("Light [node:ask] now.", "a cue after its words"),
        ("See `pick` here.", "spoken: line 6: a backtick"),
        ("It lives in src/jarvis/demo/router.py today.", "a file name or a path"),
        ("The panel is console-vault.js in the end.", "a file name or a path"),
        ("It calls pick_tier for you.", "a code name"),
        ("It sets textContent on the page.", "a code name"),
        ("It calls pick() for you.", "a code name"),
        ("It reads jarvis.config first.", "a code name"),
        ("Visit https://example.com for more.", "spoken: line 6: a web address"),
        ("It tries 3 times.", "numbers: line 6: a typed number"),
        ("It keeps {{fact:nope.never}} things.", "numbers: line 6: {{fact:nope.never}} is not"),
        ("It runs in {{fact:hosting.region}} today.", 'say "Unverified" in the line'),
        ("Write to someone@example.com today.", "personal: line 6"),
        ("Long " * 60 + "line.", "characters once filled (at most 240)"),
    ],
)
def test_each_check_names_the_file_line_and_the_rule(root: Path, line: str, said: str) -> None:
    found = problems(root, [line, *GOOD_LINES])
    assert any(said in p for p in found), found


def test_a_box_on_a_page_without_a_flowchart_and_an_overview_there(root: Path) -> None:
    found = problems(root, [*GOOD_LINES[:5], "[page:pg_card_c01] [node:ask] Here.",
                            "[show:overview] All.", GOOD_LINES[6]])  # fmt: skip
    assert "cues: line 11: pg_card_c01 has no flowchart to light (use [show:...])" in found
    assert "cues: line 12: [show:overview] needs a flowchart; pg_card_c01 has none" in found


def test_pages_are_told_in_order_each_at_least_once(root: Path) -> None:
    skip = problems(root, [GOOD_LINES[0], "[page:pg_card_c02] Too soon."])
    assert "cues: line 7: pages are told in the chapter's order; the next is pg_card_c01" in skip
    assert "pages: pg_card_c01 has no line (every page is told at least once)" in skip
    assert "pages: pg_card_c02 has no line (every page is told at least once)" in skip
    other = problems(root, ["[page:pg_chapter_example] Elsewhere.", *GOOD_LINES])
    assert "cues: line 6: [page:pg_chapter_example] is not in this chapter" in other
    late = problems(root, ["[show:title] [page:pg_module_demo] Late.", *GOOD_LINES])
    assert "cues: line 6: [page:...] comes before its other cues" in late


def test_an_unwritten_page_fails_and_a_missing_script_is_missing(root: Path) -> None:
    (root / BOOK / "pages" / "pg_card_c02.md").unlink()
    assert "pages: pg_card_c02 has no written page to tell (write it first)" in problems(
        root, GOOD_LINES
    )
    script_path(root, "module_demo").unlink()
    got = nc.judge_script(root, PLAN, env_of(root))  # type: ignore[arg-type]
    assert (got.status, got.problems) == ("missing", ("missing",))


def test_no_problem_line_quotes_the_spoken_words(root: Path) -> None:
    secret = "Zebracornflakes"
    found = problems(root, [f"It tries 3 {secret} pick_tier src/x.py https://a.example.com."])
    assert found and all(secret not in p and "pick_tier" not in p for p in found)


def test_minutes_are_spoken_words_at_150_a_minute() -> None:
    assert nc.minutes_of(["word " * 150]) == 1
    assert nc.minutes_of(["word " * 300, "word " * 74]) == 2
    assert nc.minutes_of(["word " * 300, "word " * 75]) == 3
    assert nc.minutes_of([]) == 0 and nc.minutes_of(["a"]) == 1

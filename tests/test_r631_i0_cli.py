# tests/test_r631_i0_cli.py -- R6.3.1 I0 (docs/plans/r6-3-1-book-at-build.md D5, D6): the writer's
# tools, `python -m jarvis.buildbook.gen pages --list | --pack ID | --check [IDS] | --stamp IDS`,
# their output and exit codes, and the fact pack cached per tree in build/book-cache/ (a page
# being written never invalidates it; a code change does).
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from book_gen_fakes import ROOT, commit_all
from r631_i0_fakes import (
    BOOK,
    GOOD_BODY,
    PACK,
    ROUTER,
    STORE,
    hashes_of,
    make_repo,
    page_text,
    seed_cache,
    write_flow,
    write_page,
)

from jarvis.buildbook.facts_model import FactPack, canonical_facts
from jarvis.buildbook.gen import __main__ as gen_main
from jarvis.buildbook.gen import facts_cache, pages_cli
from jarvis.buildbook.gen.repo import Repo

IDS = [p.id for p in PACK.pages]


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    base = make_repo(tmp_path)
    seed_cache(base)
    return base


def _run(root: Path, capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, list[str]]:
    code = gen_main.main(["pages", "--repo", str(root), *args])
    return code, capsys.readouterr().out.splitlines()


def _stamped(root: Path, pid: str, body: str = GOOD_BODY) -> Path:
    page = PACK.page(pid)
    assert page is not None
    return write_page(root, pid, page_text(pid, hashes_of(root, page.refs), body))


# ---- --list -----------------------------------------------------------------------------------
def test_list_names_every_page_with_its_status_then_the_totals(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _stamped(root, "pg_card_c01")
    _stamped(root, "pg_module_demo")  # no flowchart: failing
    write_page(root, "pg_card_c02", page_text("pg_card_c02"))  # never stamped: stale
    code, lines = _run(root, capsys, "--list")
    assert code == 0
    assert lines[:4] == [
        "pg_chapter_example\tchapter\tThe running example\tmissing",
        "pg_module_demo\tmodule\tThe demo\tfailing",
        "pg_card_c01\tcard\tDemo router\tok",
        "pg_card_c02\tcard\tDemo store\tstale",
    ]
    assert lines[-1] == "6 pages: 1 ok, 1 stale, 1 failing, 3 missing"
    assert "chapter 1" in lines[-2] and "card 2" in lines[-2] and "service 1" in lines[-2]


# ---- --check ----------------------------------------------------------------------------------
def test_check_fails_on_missing_pages_unless_they_are_allowed(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, lines = _run(root, capsys, "--check")
    assert code == 1 and [ln for ln in lines if ln.endswith(": missing")] == [
        f"{pid}: missing" for pid in IDS
    ]
    _stamped(root, "pg_card_c01")
    code, lines = _run(root, capsys, "--check", "--allow-missing")
    assert code == 0 and not [ln for ln in lines if ln.endswith(": missing")]
    assert lines[-1].startswith("checked 6 pages: 1 ok, 0 stale, 0 failing, 5 missing")
    assert _run(root, capsys, "--check", "pg_card_c01")[0] == 0


def test_check_names_each_problem_on_its_own_line(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _stamped(root, "pg_card_c01", GOOD_BODY.replace("{{fact:settings.demo_limit}}", "5"))
    write_page(root, "pg_card_c02", page_text("pg_card_c02"))
    write_page(root, "pg_card_c77", page_text("pg_card_c77"))
    write_page(root, "pg_service_anthropic", "no front matter\n")
    write_flow(root, "pg_chapter_example", "{")
    code, lines = _run(root, capsys, "--check", "--allow-missing")
    assert code == 1
    assert "pg_card_c01: numbers: a typed number in How it works" in "\n".join(lines)
    assert "pg_card_c02: stale: not stamped yet: run `pages --stamp pg_card_c02`" in lines
    assert "pg_card_c77: not an indexed page (pages/pg_card_c77.md)" in lines
    broken = "pg_service_anthropic: pages/pg_service_anthropic.md: "
    assert any(ln.startswith(broken) for ln in lines)
    assert not [ln for ln in lines if ln.startswith("pg_chapter_example")]  # its page is missing
    code, lines = _run(root, capsys, "--check", "pg_card_c99", "pg_card_c02")
    assert code == 1 and "pg_card_c99: not an indexed page" in lines


def test_a_stale_page_after_a_code_change(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _stamped(root, "pg_card_c01")
    (root / ROUTER).write_text((root / ROUTER).read_text(encoding="utf-8") + "\n", encoding="utf-8")
    commit_all(root, "code")
    seed_cache(root)  # a code change is a new tree: a new cache entry
    code, lines = _run(root, capsys, "--check", "pg_card_c01")
    assert code == 1
    assert lines[0] == f"pg_card_c01: stale: `{ROUTER}` changed since the page was stamped"


# ---- --stamp ----------------------------------------------------------------------------------
def test_stamp_writes_the_sources_of_a_page_that_passes(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_page(root, "pg_card_c02", page_text("pg_card_c02"))
    code, lines = _run(root, capsys, "--stamp", "pg_card_c02")
    assert (code, lines) == (0, ["pg_card_c02: stamped (1 source)"])
    assert f'"{STORE}": "{hashes_of(root, (STORE,))[STORE]}"' in path.read_text(encoding="utf-8")
    assert _run(root, capsys, "--check", "pg_card_c02")[0] == 0


def test_stamp_refuses_a_page_that_fails_anything_but_staleness(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    typed = page_text("pg_card_c01", body=GOOD_BODY.replace("{{fact:settings.demo_limit}}", "5"))
    path = write_page(root, "pg_card_c01", typed)
    write_page(root, "pg_module_demo", page_text("pg_module_demo"))  # no flowchart
    code, lines = _run(root, capsys, "--stamp", "pg_card_c01", "pg_module_demo", "pg_card_c02")
    assert code == 1 and path.read_text(encoding="utf-8") == typed
    assert lines[0].startswith("pg_card_c01: not stamped: numbers: a typed number")
    assert lines[1].startswith("pg_module_demo: not stamped: flow: missing")
    assert lines[2] == "pg_card_c02: not stamped: missing"
    write_flow(root, "pg_module_demo")
    assert _run(root, capsys, "--stamp", "pg_module_demo")[0] == 0


# ---- --pack -----------------------------------------------------------------------------------
def test_pack_shows_a_writer_what_the_page_may_cite_and_every_fact(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, lines = _run(root, capsys, "--pack", "pg_card_c01")
    text = "\n".join(lines)
    assert code == 0
    wanted = (
        "pg_card_c01", "Demo router", "card", f"{BOOK}/pages/pg_card_c01.md", f"{ROUTER}:pick",
        f"{ROUTER}:MAX_TRIES = 3  [verified]", "release.label = R6.3  [verified]",
        "This page is about Demo router.",
    )  # fmt: skip
    for want in wanted:
        assert want in text, want
    code, lines = _run(root, capsys, "--pack", "pg_chapter_example")
    assert "flowchart: required" in "\n".join(lines)
    assert _run(root, capsys, "--pack", "pg_card_c99") == (1, ["pg_card_c99: not an indexed page"])


def test_pack_marks_an_unverified_fact(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_repo(tmp_path)
    values = dict(PACK.values)
    values["release.hosting"] = values["hosting.region"]
    seed_cache(root, PACK.model_copy(update={"values": values}))
    text = "\n".join(_run(root, capsys, "--pack", "pg_card_c01")[1])
    assert 'release.hosting = asia-south1  [Unverified: say "Unverified" in its sentence]' in text


# ---- the facts cache (D5) ---------------------------------------------------------------------
def test_the_cache_key_follows_the_code_and_never_the_pages(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    first = facts_cache.key(Repo.from_git(root))
    write_page(root, "pg_card_c01", page_text("pg_card_c01"))
    commit_all(root, "a page")
    write_page(root, "pg_card_c02", page_text("pg_card_c02"))
    assert facts_cache.key(Repo.from_git(root)) == first
    (root / STORE).write_text("KEEP_DAYS = 31\n", encoding="utf-8")  # uncommitted code counts
    assert facts_cache.key(Repo.from_git(root)) != first
    path = facts_cache.path_for(Repo.from_git(root))
    assert path.parent == root / "build" / "book-cache" and path.name.startswith("facts-")


def test_a_cold_cache_builds_once_then_reads(tmp_path: Path) -> None:
    root, calls = make_repo(tmp_path), []

    def build(repo: Repo) -> FactPack:
        calls.append(repo.sha)
        return PACK

    repo = Repo.from_git(root)
    assert facts_cache.facts_for(repo, build) == (PACK, False)
    assert facts_cache.facts_for(repo, build) == (PACK, True) and len(calls) == 1
    assert facts_cache.path_for(repo).read_bytes() == canonical_facts(PACK)
    facts_cache.path_for(repo).write_bytes(b"{broken")
    assert facts_cache.facts_for(repo, build) == (PACK, False) and len(calls) == 2
    assert pages_cli.main(["--repo", str(root), "--list"], build=build) == 0 and len(calls) == 2


def test_the_cache_keeps_only_the_newest_trees(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    folder = root / facts_cache.CACHE_DIR
    folder.mkdir(parents=True)
    for i in range(facts_cache.KEEP + 3):
        old = folder / f"facts-{i:032x}.json"
        old.write_bytes(b"{}")
        os.utime(old, (1_000 + i, 1_000 + i))
    (folder / "other.txt").write_text("kept", encoding="utf-8")
    facts_cache.facts_for(Repo.from_git(root), lambda _r: PACK)
    kept = sorted(p.name for p in folder.glob("facts-*.json"))
    assert len(kept) == facts_cache.KEEP and facts_cache.path_for(Repo.from_git(root)).name in kept
    assert (folder / "other.txt").exists()


# ---- the entry point ---------------------------------------------------------------------------
def test_the_module_runs_the_pages_tools(root: Path) -> None:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    cmd = [sys.executable, "-m", "jarvis.buildbook.gen", "pages", "--repo", str(root)]
    done = subprocess.run([*cmd, "--list"], env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and done.stdout.splitlines()[-1].endswith("6 missing")
    done = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 2 and "one of the arguments" in done.stderr

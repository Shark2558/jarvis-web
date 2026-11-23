# tests/test_r631_i0_status.py -- R6.3.1 I0 (docs/plans/r6-3-1-book-at-build.md D3, D5, D6): what a
# written page's status is (missing, stale, failing, ok) and every problem `pages --check` names:
# the parse, the six checks of R6.3 (writer/checks.py) in plain words, the flowchart's rules and
# staleness against the tracked files' SHA-256 (the first 16 hex, the scrubbed refs resolved).
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any

import pytest
from r631_i0_fakes import (
    ANDROID,
    ANDROID_RAW,
    GOOD_BODY,
    GOOD_FLOW,
    PACK,
    ROUTER,
    STORE,
    hashes_of,
    make_repo,
    page_text,
    short,
    write_flow,
    write_page,
)

from jarvis.buildbook.book import authored
from jarvis.buildbook.book.authored import Env, check_page, load_page, source_hashes, status
from jarvis.buildbook.book.flow import FlowSpec
from jarvis.buildbook.facts_model import IndexedPage
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.gen.scrub import default_scrubber

S = default_scrubber()


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    return make_repo(tmp_path)


def _env(root: Path, emails: tuple[str, ...] = ()) -> Env:
    return Env(facts=PACK, scrub=S, repo=Repo.from_git(root), emails=emails)


def _ip(pid: str) -> IndexedPage:
    page = PACK.page(pid)
    assert page is not None
    return page


def _written(root: Path, pid: str, body: str = GOOD_BODY, *, stamped: bool = True) -> Any:
    sources = hashes_of(root, _ip(pid).refs) if stamped else None
    return load_page(write_page(root, pid, page_text(pid, sources, body)))


# ---- source hashes (D2, D6) -------------------------------------------------------------------
def test_source_hashes_are_the_first_16_hex_of_the_files_sha256(root: Path) -> None:
    repo = Repo.from_git(root)
    got = source_hashes(repo, (ROUTER, STORE, ANDROID, "src/jarvis/ghost.py"))
    assert got[ROUTER] == hashlib.sha256((root / ROUTER).read_bytes()).hexdigest()[:16]
    assert got[STORE] == short((root / STORE).read_bytes())
    assert got[ANDROID] == short((root / ANDROID_RAW).read_bytes())  # the scrubbed ref resolved
    assert "src/jarvis/ghost.py" not in got


# ---- status (D5) ------------------------------------------------------------------------------
def test_status_missing_ok_stale_and_failing(root: Path) -> None:
    env, ip = _env(root), _ip("pg_card_c01")
    assert status(None, ip, env.repo) == "missing"
    pf = _written(root, "pg_card_c01")
    assert check_page(pf, ip, env) == [] and status(pf, ip, env.repo) == "ok"
    (root / ROUTER).write_text("MAX_TRIES = 4\n", encoding="utf-8")
    env = _env(root)
    found = check_page(pf, ip, env)
    assert found == [f"stale: `{ROUTER}` changed since the page was stamped"]
    assert status(pf, ip, env.repo) == "stale" and status(pf, ip, env.repo, found) == "stale"
    typed = GOOD_BODY.replace("{{fact:settings.demo_limit}}", "5")
    bad = _written(root, "pg_card_c01", typed)
    assert status(bad, ip, env.repo, check_page(bad, ip, env)) == "failing"


def test_a_page_never_stamped_or_with_other_sources_is_stale(root: Path) -> None:
    env, ip = _env(root), _ip("pg_module_demo")
    write_flow(root, "pg_module_demo")
    flow = authored.load_flow(root / authored.BOOK_DIR / "flows" / "pg_module_demo.json")
    pf = _written(root, "pg_module_demo", stamped=False)
    assert check_page(pf, ip, env, flow=flow) == [
        "stale: not stamped yet: run `pages --stamp pg_module_demo`"
    ]
    one = {ROUTER: hashes_of(root, (ROUTER,))[ROUTER], "src/jarvis/old.py": "0" * 16}
    pf = load_page(write_page(root, "pg_module_demo", page_text("pg_module_demo", one)))
    assert check_page(pf, ip, env, flow=flow) == [
        f"stale: `{STORE}` is new to this page",
        "stale: `src/jarvis/old.py` is no longer one of the page's refs",
    ]


def test_the_scrubbed_android_ref_is_stamped_and_checked(root: Path) -> None:
    env, ip = _env(root), _ip("pg_screen_phone")
    body = GOOD_BODY.replace(f"(`{ROUTER}`)", f"(`{ANDROID}`)")
    pf = _written(root, "pg_screen_phone", body)
    assert pf.sources == {ANDROID: short((root / ANDROID_RAW).read_bytes())}
    assert check_page(pf, ip, env) == []


# ---- the six checks, in plain words (R6.3 D10) ------------------------------------------------
@pytest.mark.parametrize(
    ("old", "new", "said"),
    [
        (f"`{ROUTER}`", "`src/jarvis/demo/ghost.py`",
         "refs: `src/jarvis/demo/ghost.py` is not a path, symbol, setting, collection or route"),
        ("{{fact:settings.demo_limit}}", "5", "numbers: a typed number in How it works"),
        ("{{fact:settings.demo_limit}}", "{{fact:settings.nope}}",
         "numbers: {{fact:settings.nope}} is not a fact key"),
        ("calls nothing else", "writes to someone@example.org", "personal: email"),
        ("When every try fails", "It also books flights by itself. When every try fails",
         "invented: When it fails, sentence 1"),
        ("Nothing: it runs inside the server.", "Nothing. Soon it will also pick a voice.",
         "planned: future words in What it costs"),
        ("Nothing: it runs inside the server.", "It runs in {{fact:hosting.region}}.",
         'unverified: {{fact:hosting.region}} is Unverified: say "Unverified"'),
        ("Nothing: it runs inside the server.", "See [the docs](https://example.org).",
         "shape: a link or a web address in What it costs"),
        ("Nothing: it runs inside the server.", "Nothing <b>at all</b>.",
         "shape: HTML in What it costs"),
        ("Nothing: it runs inside the server.", "Nothing << at all.",
         "shape: << or >> in What it costs"),
        ("Nothing: it runs inside the server.", "Nothing. " * 120,
         "shape: What it costs is 1,079 characters once filled, over its cap of 900"),
    ],
)  # fmt: skip
def test_each_check_names_its_problem(root: Path, old: str, new: str, said: str) -> None:
    env, ip = _env(root), _ip("pg_card_c01")
    assert old in GOOD_BODY
    pf = _written(root, "pg_card_c01", GOOD_BODY.replace(old, new))
    found = check_page(pf, ip, env)
    assert any(p.startswith(said) for p in found), found
    assert not any("someone@example.org" in p for p in found)


def test_the_planned_line_and_the_example_keep_their_freedom(root: Path) -> None:
    env, ip = _env(root), _ip("pg_card_c01")
    body = GOOD_BODY.replace(
        "Nothing: it runs inside the server.",
        "Nothing: it runs inside the server.\nPlanned: soon it will also pick a voice.",
    ).replace("asks for the weather twice", "asks for the weather 2 times at 9:30")
    assert check_page(_written(root, "pg_card_c01", body), ip, env) == []


def test_an_owner_address_in_any_form_is_personal(root: Path) -> None:
    env, ip = _env(root, emails=("asha.verma@example.com",)), _ip("pg_card_c01")
    body = GOOD_BODY.replace("calls nothing else", "tells Asha Verma")
    found = check_page(_written(root, "pg_card_c01", body), ip, env)
    assert "personal: the owner's e-mail address or a word of it" in found
    assert not any("Verma" in p for p in found)


# ---- the flowchart (D3) -----------------------------------------------------------------------
def _spec(**changes: Any) -> FlowSpec:
    data = copy.deepcopy(GOOD_FLOW)
    data.update(changes)
    return FlowSpec.model_validate(data)


def test_chapters_and_modules_need_their_flow_cards_may_have_one(root: Path) -> None:
    env = _env(root)
    for pid in ("pg_chapter_example", "pg_module_demo"):
        pf = _written(root, pid)
        assert check_page(pf, _ip(pid), env) == [
            f"flow: missing: write flows/{pid}.json (every chapter and module has one)"
        ]
        assert check_page(pf, _ip(pid), env, flow=_spec()) == []
    card = _written(root, "pg_card_c01")
    assert check_page(card, _ip("pg_card_c01"), env) == []
    nodes = copy.deepcopy(GOOD_FLOW["nodes"])
    nodes[2]["ref"] = None
    assert check_page(card, _ip("pg_card_c01"), env, flow=_spec(nodes=nodes)) == []


def test_a_flow_ref_must_be_one_of_the_page_s_refs(root: Path) -> None:
    env, ip = _env(root), _ip("pg_card_c01")  # refs: the router only
    found = check_page(_written(root, "pg_card_c01"), ip, env, flow=_spec())
    assert found == [f"flow: node notes: `{STORE}` is not one of the page's refs"]


@pytest.mark.parametrize(
    ("where", "text", "kind"),
    [
        ("title", "Mail asha@example.org", "email"),
        ("node", "Call +91 98765 43210", "phone"),
        ("node", "See www.example.org", "url"),
        ("edge", "a\x07b", "control"),
    ],
)
def test_flow_words_pass_the_scrubber_and_the_private_word_guard(
    root: Path, where: str, text: str, kind: str
) -> None:
    env, ip = _env(root), _ip("pg_module_demo")
    data = copy.deepcopy(GOOD_FLOW)
    if where == "title":
        data["title"] = text
    elif where == "node":
        data["nodes"][0]["label"] = text
    else:
        data["edges"][0]["label"] = text
    flow = FlowSpec.model_validate(data)
    found = check_page(_written(root, "pg_module_demo"), ip, env, flow=flow)
    assert len(found) == 1 and found[0].startswith("flow: ") and kind in found[0], found
    assert text not in found[0]


def test_a_flow_that_failed_to_load_is_named(root: Path) -> None:
    env, ip = _env(root), _ip("pg_module_demo")
    found = check_page(_written(root, "pg_module_demo"), ip, env, flow_error="flows/x: bad")
    assert found == ["flow: flows/x: bad"]


# ---- the sources block, rewritten alone (D5 --stamp) --------------------------------------------
def test_stamping_rewrites_only_the_sources_block(root: Path) -> None:
    extra = "# a comment the writer keeps"
    old = page_text("pg_card_c01", {"src/jarvis/old.py": "0" * 16}, extra=extra)
    new = authored.stamped(old, {ROUTER: "abcdef0123456789"})
    assert new.replace(f'  "{ROUTER}": "abcdef0123456789"', "") == old.replace(
        '  "src/jarvis/old.py": "0000000000000000"', ""
    )
    path = write_page(root, "pg_card_c01", new)
    assert load_page(path).sources == {ROUTER: "abcdef0123456789"}
    bare = authored.stamped(page_text("pg_card_c01"), {ROUTER: "abcdef0123456789"})
    assert load_page(write_page(root, "pg_card_c01", bare)).sources == {ROUTER: "abcdef0123456789"}
    empty = authored.stamped(page_text("pg_card_c01", {}), {STORE: "1" * 16})
    assert load_page(write_page(root, "pg_card_c01", empty)).sources == {STORE: "1" * 16}

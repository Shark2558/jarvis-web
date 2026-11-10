# tests/test_book_gen_code.py
"""R6 D2: the generator's view of the code — the repository (`gen.repo`), the packages and their
layers (`gen.code`, `gen.layers`), the AST look-ups the flows use, and the Integrations section
(Settings by prefix, health probes, keyring purposes, alert kinds, words from `buildbook.plain`).
All read as text and ASTs: the generator imports nothing from the app."""

from __future__ import annotations

import ast
import re
import typing
from pathlib import Path

import pytest
from book_gen_fakes import COMMIT_DATE, ROOT, commit_all, fixture_repo

from jarvis.buildbook import plain
from jarvis.buildbook.gen import code, layers
from jarvis.buildbook.gen.repo import GenError, Repo
from jarvis.buildbook.gen.scrub import NoScrub, Scrubber
from jarvis.buildbook.model import LAYERS
from jarvis.buildbook.sections import Integrations, Package

SCRUB = Scrubber(frozenset())


@pytest.fixture(scope="module")
def real() -> Repo:
    return Repo.from_git(ROOT)


@pytest.fixture()
def fx(tmp_path: Path) -> Repo:
    return Repo.from_git(fixture_repo(tmp_path))


# ---- the repository --------------------------------------------------------------------------
def test_a_git_checkout_gives_its_tracked_files_commit_and_date(fx: Repo) -> None:
    assert fx.files == tuple(sorted(fx.files))
    assert "src/jarvis/core/loop.py" in fx.files and ".git/HEAD" not in fx.files
    assert re.fullmatch(r"[0-9a-f]{40}", fx.sha) and fx.id == fx.sha[:7]
    assert fx.committed_at == COMMIT_DATE


def test_the_same_tree_and_dates_give_the_same_commit(tmp_path: Path) -> None:
    a = Repo.from_git(fixture_repo(tmp_path, "a"))
    b = Repo.from_git(fixture_repo(tmp_path, "b"))
    assert a.sha == b.sha and a.files == b.files


def test_a_sub_folder_finds_the_top_of_the_checkout(fx: Repo) -> None:
    assert Repo.from_git(fx.root / "src" / "jarvis").root == fx.root


def test_outside_a_checkout_is_a_plain_error(tmp_path: Path) -> None:
    with pytest.raises(GenError, match="git"):
        Repo.from_git(tmp_path)


def test_untracked_files_are_not_in_the_book(fx: Repo) -> None:
    (fx.root / "notes.txt").write_text("private", encoding="utf-8")
    assert "notes.txt" not in Repo.from_git(fx.root).files


def test_a_tracked_symlink_is_never_followed(fx: Repo, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("not part of the repo", encoding="utf-8")
    (fx.root / "link.txt").symlink_to(outside)
    (fx.root / "src" / "jarvis" / "core" / "inner.py").symlink_to(fx.root / "Dockerfile")
    commit_all(fx.root, "links")
    files = Repo.from_git(fx.root).files
    assert "link.txt" not in files and "src/jarvis/core/inner.py" not in files


def test_text_is_none_for_missing_and_binary_files(fx: Repo, tmp_path: Path) -> None:
    assert fx.text("nope.py") is None
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "b.bin").write_bytes(b"\xff\xfe\x00")
    r = Repo.from_dir(tmp_path / "x", sha="a" * 40, committed_at=COMMIT_DATE)
    assert r.files == ("b.bin",) and r.text("b.bin") is None


# ---- packages and layers ---------------------------------------------------------------------
def test_the_fixture_packages_have_files_lines_summaries_and_layers(fx: Repo) -> None:
    pkgs = {p.name: p for p in code.packages(fx, layers.LAYER_OF, SCRUB)}
    assert set(pkgs) == {"core", "notify", "vault"}
    core = pkgs["core"]
    assert isinstance(core, Package)
    assert (core.files, core.lines, core.layer) == (2, 11, "L4")
    assert core.summary == "Core reasoning (build book fixture)."


def test_an_unmapped_package_fails_and_names_it(fx: Repo) -> None:
    table = {k: v for k, v in layers.LAYER_OF.items() if k != "vault"}
    with pytest.raises(GenError, match="src/jarvis/vault"):
        code.packages(fx, table, SCRUB)


def test_every_real_package_and_module_is_mapped_to_a_known_layer(real: Repo) -> None:
    names = code.package_names(real)
    assert {"core", "llm", "buildbook", "config", "keyring", "ticks"} <= set(names)
    assert set(names) <= set(layers.LAYER_OF)  # an unmapped one fails --check
    assert set(layers.LAYER_OF.values()) <= {lid for lid, _ in LAYERS}
    stale = set(layers.LAYER_OF) - set(names)
    assert not stale, f"gen/layers.py names packages that no longer exist: {stale}"


def test_a_summary_is_scrubbed_and_a_missing_one_has_plain_words(tmp_path: Path) -> None:
    pkg = tmp_path / "src" / "jarvis"
    (pkg / "core").mkdir(parents=True)
    (pkg / "core" / "__init__.py").write_text('"""Ask a@example.org."""\n', encoding="utf-8")
    (pkg / "llm").mkdir()
    (pkg / "llm" / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    r = Repo.from_dir(tmp_path, sha="b" * 40, committed_at=COMMIT_DATE)
    got = {p.name: p.summary for p in code.packages(r, layers.LAYER_OF, SCRUB)}
    assert got["core"] == "Ask [removed]."
    assert got["llm"] == plain.PACKAGE_WORDS["llm"]


# ---- AST look-ups ----------------------------------------------------------------------------
SAMPLE = """
X: int = 3
NAMES = ("a", "b")
Kind = typing.Literal["k1", "k2"]
def f(): ...
class C:
    LIMIT = 2
    async def go(self): ...
"""


def test_defines_finds_names_methods_and_class_attributes() -> None:
    tree = ast.parse(SAMPLE)
    assert code.defines(tree, None, None)
    assert code.defines(tree, "f", None) and code.defines(tree, "X", None)
    assert code.defines(tree, "C", "go") and code.defines(tree, "C", "LIMIT")
    assert not code.defines(tree, "C", "stop") and not code.defines(tree, "g", None)
    assert not code.defines(tree, "f", "x")


def test_top_value_reads_literals_only() -> None:
    tree = ast.parse(SAMPLE)
    assert code.top_value(tree, "X") == 3
    assert code.top_value(tree, "NAMES") == ("a", "b")
    assert code.literal_args(tree, "Kind") == ("k1", "k2")
    assert code.top_value(tree, "f") is None and code.top_value(tree, "nope") is None


def test_module_paths_resolve_modules_and_packages(real: Repo) -> None:
    assert code.module_path(real, "core.brain") == "src/jarvis/core/brain.py"
    assert code.module_path(real, "buildbook") == "src/jarvis/buildbook/__init__.py"
    assert code.module_path(real, "nope.nothing") is None


# ---- integrations ----------------------------------------------------------------------------
def test_settings_are_read_from_config_by_ast_names_and_descriptions(real: Repo) -> None:
    from jarvis.config import Settings

    fields = dict(code.settings_fields(real))
    assert list(fields) == list(Settings.model_fields)
    assert fields["book_max_total_mb"] == Settings.model_fields["book_max_total_mb"].description


def test_integrations_of_the_real_code(real: Repo) -> None:
    from jarvis import alerts, keyring
    from jarvis.notify.ports import DEFAULT_URGENCY

    integ = code.integrations(real, SCRUB)
    assert isinstance(integ, Integrations)
    assert integ.key_purposes == keyring.PURPOSES
    kinds = typing.get_args(alerts.AlertKind)
    assert tuple(a.kind for a in integ.alert_kinds) == kinds
    assert all(a.level == DEFAULT_URGENCY.get(a.kind, "important") for a in integ.alert_kinds)
    assert all(a.what and "_" not in a.what for a in integ.alert_kinds)
    services = {s.id: s for s in integ.services}
    assert {"anthropic", "telegram", "google", "firestore"} <= set(services)
    assert services["telegram"].checked and "telegram_bot_token" in services["telegram"].settings
    known = set(dict(code.settings_fields(real)))
    assert all(set(s.settings) <= known for s in integ.services)


def test_integrations_of_the_fixture_are_empty_but_valid(fx: Repo) -> None:
    integ = code.integrations(fx, NoScrub())
    assert integ.services == () and integ.key_purposes == () and integ.alert_kinds == ()


def test_every_service_in_plain_words_names_prefixes_and_short_words() -> None:
    ids = [s.id for s in plain.SERVICES]
    assert len(ids) == len(set(ids))
    for s in plain.SERVICES:
        assert s.prefixes and 0 < len(s.what) <= 300 and len(s.label) <= 80


def test_plain_words_cover_every_layer() -> None:
    assert set(plain.LAYER_WORDS) == {lid for lid, _ in LAYERS}


# ---- review fix: a tracked module that can't be parsed fails instead of reading as absent ----
def test_a_tracked_module_that_is_not_python_fails(tmp_path: Path) -> None:
    (tmp_path / "src" / "jarvis").mkdir(parents=True)
    (tmp_path / "src" / "jarvis" / "keyring.py").write_text("PURPOSES = (\n", encoding="utf-8")
    r = Repo.from_dir(tmp_path, sha="d" * 40, committed_at=COMMIT_DATE)
    with pytest.raises(GenError, match="keyring.py"):
        code.tree(r, "src/jarvis/keyring.py")
    assert code.tree(r, "src/jarvis/absent.py") is None and code.tree(r, None) is None


def test_key_purposes_that_are_not_a_literal_fail(tmp_path: Path) -> None:
    (tmp_path / "src" / "jarvis").mkdir(parents=True)
    (tmp_path / "src" / "jarvis" / "keyring.py").write_text("PURPOSES = load()\n", "utf-8")
    r = Repo.from_dir(tmp_path, sha="d" * 40, committed_at=COMMIT_DATE)
    with pytest.raises(GenError, match="PURPOSES"):
        code.integrations(r, Scrubber(frozenset()))

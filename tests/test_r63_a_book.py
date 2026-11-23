# tests/test_r63_a_book.py -- R6.3 part A, D10's content gaps in book.json
# (docs/plans/r6-3-book-content.md): G3, the book's integrations name every one of the coverage
# checker's 31 outside services (M7), the 15 rows in plain words unchanged and one row for each
# service they don't cover; G7, the costs: GitHub Actions on a public repository marked Unverified
# and Firestore's daily free reads, writes and deletes. Fixtures and this checkout; no app import.
from __future__ import annotations

from pathlib import Path

import pytest
from r63_fakes_a import a_repo, repo_of

from jarvis.buildbook import plain
from jarvis.buildbook.gen import code, costs
from jarvis.buildbook.gen import services as services_mod
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.gen.scrub import default_scrubber

ROOT = Path(__file__).resolve().parents[1]
S = default_scrubber()


@pytest.fixture(scope="module")
def real() -> Repo:
    return Repo.from_git(ROOT)


# ---- G7: the costs --------------------------------------------------------------------------
def test_g7_github_actions_on_a_public_repository_is_marked_unverified(tmp_path: Path) -> None:
    items = {i.id: i for i in costs.costs(a_repo(tmp_path)).items}
    actions = items["github_actions"]
    assert "public" in actions.free and "Unverified" in actions.free
    assert "2,000" not in actions.free  # the private-repository allowance (Phase A G7)
    assert actions.kind == "cloud" and actions.inr == 0


def test_g7_firestore_lists_its_daily_free_reads_writes_and_deletes(tmp_path: Path) -> None:
    free = {i.id: i for i in costs.costs(a_repo(tmp_path)).items}["firestore"].free
    assert free.startswith("1 GiB stored")  # R6's pin (test_book_gen_costs) stays
    for words in ("50,000 reads", "20,000 writes", "20,000 deletes a day"):
        assert words in free, words
    assert len(free) <= 120


# ---- G3: the integrations -------------------------------------------------------------------
def test_g3_the_book_names_every_one_of_the_checker_s_31_services(real: Repo) -> None:
    names = services_mod.inventory(real.root).names
    rows = code.integrations(real, S).services
    assert len(names) == 31
    assert code.services_named(rows, services_mod.tables(real.root)) == set(names)
    ids = [r.id for r in rows]
    assert len(ids) == len(set(ids))


def test_g3_the_plain_rows_stay_first_and_unchanged(real: Repo) -> None:
    rows = code.integrations(real, S).services
    words = {w.id: w for w in plain.SERVICES}
    head = [r for r in rows if r.id in words]
    assert rows[: len(head)] == tuple(head)  # the plain rows first, in plain.SERVICES order
    assert [r.id for r in head] == [w.id for w in plain.SERVICES if w.id in {r.id for r in head}]
    assert all(r.what == S.clean(words[r.id].what) for r in head)


def test_g3_each_other_service_gets_a_row_with_its_settings(real: Repo) -> None:
    table = services_mod.tables(real.root)
    rows = code.integrations(real, S).services
    others = [r for r in rows if r.id not in {w.id for w in plain.SERVICES}]
    assert others and all(r.what == code.OTHER_WHAT and not r.checked for r in others)
    names = set(services_mod.inventory(real.root).names)
    assert all(r.label in names for r in others)  # each named as the checker names it
    assert len({r.label for r in others}) == len(others)  # one row a service
    assert all(r.label in code.services_named((r,), table) for r in others)
    known = {n for n, _ in code.settings_fields(real)}
    assert all(set(r.settings) <= known for r in others)
    assert [r.label for r in others] == sorted(r.label for r in others)


def test_g3_a_checkout_without_the_checker_s_table_keeps_today_s_rows(tmp_path: Path) -> None:
    repo = repo_of(tmp_path, {"src/jarvis/keyring.py": 'PURPOSES = ("vault",)\n'})
    assert code.integrations(repo, S).services == ()  # R6's fixture rule (no settings, no probe)

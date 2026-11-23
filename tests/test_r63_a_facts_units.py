# tests/test_r63_a_facts_units.py -- R6.3 part A, D2 (docs/plans/r6-3-book-content.md): the fact
# pack's scanners on small fixtures (tests/r63_fakes_a.py): every literal module constant (H5),
# the settings with bounds, the collections, the routes of every router whatever its name (M9),
# the guide's cards with resolved and scrubbed references, the screens, the roadmap, the hosting
# facts left unverified, and I0's fixture pack (tests/r63_fakes.FIXTURE_FACTS) where its files
# allow. Standard library and the generator only; no app import.
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from r63_fakes import FIXTURE_FACTS
from r63_fakes_a import DEMO, a_repo, i0_repo, repo_of

from jarvis.buildbook.facts_model import FactPack
from jarvis.buildbook.gen import facts, facts_code, facts_guide, facts_routes
from jarvis.buildbook.gen.repo import GenError
from jarvis.buildbook.gen.scrub import Scrubber, default_scrubber

S = default_scrubber()
C = "src/jarvis/demo/consts.py"


@pytest.fixture()
def pack(tmp_path: Path) -> FactPack:
    return facts.build(a_repo(tmp_path), S, modules=DEMO)


def test_every_literal_module_constant_as_path_name(tmp_path: Path) -> None:
    trees = facts_code.parse_src(a_repo(tmp_path))
    got = {k: v.value for k, v in facts_code.constants(trees, S).items() if k.startswith(C)}
    assert got == {
        f"{C}:MAX_TRIES": 3,
        f"{C}:BREAKER_S": 120.0,
        f"{C}:WINDOW_S": 900,
        f"{C}:OFFSET": -2,
        f"{C}:HOLD_S": 2,
        f"{C}:COUNTDOWN_S": 5,
        f"{C}:_PRIVATE_CAP": 1024,
        f"{C}:RATIO": 0.25,
    }  # not a bool, a string, a lower-case name, 1/0, a call, 10**400 or a name inside a def
    assert facts_code.constants(trees, S)[f"{C}:MAX_TRIES"].source == f"{C}:MAX_TRIES"


def test_settings_with_defaults_and_bounds(pack: FactPack) -> None:
    by = {s.name: s for s in pack.settings}
    assert [s.name for s in pack.settings] == sorted(by)
    assert (by["demo_limit"].default, by["demo_limit"].ge, by["demo_limit"].le) == (5, 1, 10)
    assert (by["ratio"].default, by["ratio"].ge, by["ratio"].le) == (0.5, 0.0, 1.0)
    assert by["region"].kind == "Literal['us', 'eu']" and by["region"].default == "us"
    assert by["api_key"].default is None and by["hosts"].default is None
    assert by["home_url"].default == "[removed]"  # a string default is scrubbed
    assert pack.values["settings.demo_limit"].value == 5
    assert pack.values["settings.demo_limit"].source == "src/jarvis/config.py:demo_limit"
    assert "settings.api_key" not in pack.values and "settings.hosts" not in pack.values


def test_collections_in_every_idiom(pack: FactPack) -> None:
    assert pack.collections == (
        "demo_drafts",
        "demo_items",
        "demo_notes",
        "demo_runs",
        "demo_votes",
    )
    assert pack.index.collections == pack.collections


def test_routes_of_every_router_whatever_its_name(pack: FactPack) -> None:
    mod = "src/jarvis/demo/routes.py"
    got = {(r.method, r.path) for r in pack.routes if r.module == mod}
    assert got == {
        ("GET", "/v1/demo/items"),
        ("GET", "/v1/demo/added"),
        ("GET", "/v1/base/public/ping"),
        ("POST", "/v1/base/public/ping"),
        ("WEBSOCKET", "/ws"),
        ("DELETE", "/v1/inner/{item_id}"),
        ("HEAD", "/healthz"),
        ("POST", "/v1/hook"),
        ("GET", "/v1/book/writer"),
        ("POST", "/v1/book/writer/trial"),
    }  # the ROUTES loop reads the table, and only its rows under the router's prefix
    assert list(pack.routes) == sorted(pack.routes, key=lambda r: (r.path, r.method, r.module))
    assert "GET /v1/demo/items" in pack.index.routes


def test_a_route_path_the_scan_cant_read_fails(tmp_path: Path) -> None:
    bad = "from fastapi import APIRouter\nr = APIRouter()\n\n\n@r.get(make_path())\ndef f(): ...\n"
    repo = repo_of(tmp_path, {"src/jarvis/x.py": bad})
    with pytest.raises(GenError, match="src/jarvis/x.py"):
        facts_routes.routes(facts_code.parse_src(repo), S)


def test_cards_from_the_guide_with_full_scrubbed_refs_and_services(pack: FactPack) -> None:
    by = {c.id: c for c in pack.cards}
    assert by["C01"].refs == ("src/jarvis/demo/router.py",)
    assert by["C03"].refs == ("src/jarvis/api/static/console-demo.js",)  # a short name, resolved
    assert by["C01"].services == ("Anthropic",) and by["C03"].services == ()
    assert {c.module for c in pack.cards} == {"demo"}
    assert pack.modules[0].cards == ("C01", "C02", "C03")


def test_a_card_reference_that_resolves_nowhere_fails(tmp_path: Path) -> None:
    repo = a_repo(tmp_path)
    guide = repo.root / "docs/architecture/JARVIS-Architecture.md"
    guide.write_text(guide.read_text().replace("demo/store.py", "demo/ghost.py"), "utf-8")
    with pytest.raises(GenError, match="C02"):
        facts.build(repo, S, modules=DEMO)


def test_a_card_in_no_module_fails(tmp_path: Path) -> None:
    table = (DEMO[0].__class__("demo", "The demo", ("C01", "C02")),)
    with pytest.raises(GenError, match="C03"):
        facts.build(a_repo(tmp_path), S, modules=table)


def test_screens_are_the_panels_and_the_show(pack: FactPack) -> None:
    assert [(s.id, s.title) for s in pack.screens] == [
        ("chat", "Conversation"),
        ("demo", "Demo panel"),
        ("show", "The Build Book show"),
    ]
    demo = pack.screens[1]
    assert "src/jarvis/api/static/console-demo-panel.js" in demo.refs
    assert "src/jarvis/api/static/console-demo.js" in demo.refs
    assert "src/jarvis/demo/routes.py" in demo.refs  # its routes' file (/v1/demo/...)
    show = pack.screens[2]
    assert "src/jarvis/api/static/console-book-show.js" in show.refs
    assert "src/jarvis/api/static/book.html" in show.refs


def test_the_roadmap_reads_the_guide_s_first_two_rows() -> None:
    text = (
        "## 11. Roadmap (PLANNED)\n\n| Release | PLANNED content |\n|---|---|\n"
        "| R6.3.1 The Build Book's pictures and storage | Pictures |\n"
        "| R6.4 The Book's new look | Look |\n| Voice | Fixes |\n\n## 12. Glossary\n"
    )
    assert facts_guide.roadmap(text) == (
        "R6.3.1, the Build Book's pictures and storage",
        "R6.4, the Book's new look",
        "Voice",
    )


def test_hosting_facts_are_unverified(pack: FactPack) -> None:
    region = pack.values["hosting.region"]
    assert (region.value, region.verified, region.source) == (
        "asia-south1",
        False,
        "deploy/cloudrun.sh",
    )
    assert pack.values["hosting.memory"].value == "512Mi"
    assert all(not v.verified for k, v in pack.values.items() if k.startswith("hosting."))
    assert all(v.verified for k, v in pack.values.items() if not k.startswith("hosting."))


def test_paths_are_stored_scrubbed(tmp_path: Path) -> None:
    secret = "zorblaxton"
    scrub = Scrubber(frozenset({hashlib.sha256(secret.encode()).hexdigest()}))
    rel = f"src/jarvis/{secret}/thing.py"
    repo = repo_of(tmp_path, {rel: "LIMIT = 4\n\n\ndef go() -> None: ...\n"})
    pack = facts.build(repo, scrub)
    blob = pack.model_dump_json()
    assert secret not in blob
    assert "src/jarvis/[removed]/thing.py" in pack.index.paths
    assert "src/jarvis/[removed]/thing.py:LIMIT" in pack.values
    assert "src/jarvis/[removed]/thing.py:go" in pack.index.symbols
    scrub.verify(pack.model_dump(mode="json"))


def test_build_leaves_release_and_pages_to_the_join(pack: FactPack) -> None:
    assert pack.release is None and pack.pages == ()


def test_the_pack_is_deterministic(tmp_path: Path) -> None:
    first = facts.build(a_repo(tmp_path / "a"), S, modules=DEMO)
    second = facts.build(a_repo(tmp_path / "b"), S, modules=DEMO)
    assert first == second


def test_a_repository_without_a_guide_builds_a_pack(tmp_path: Path) -> None:
    repo = repo_of(tmp_path, {"src/jarvis/x.py": "N = 1\n"})
    pack = facts.build(repo, S)
    assert pack.cards == () and pack.modules == () and pack.values["src/jarvis/x.py:N"].value == 1


def test_i0s_fixture_pack_where_its_files_allow(tmp_path: Path) -> None:
    """What `facts.build` computes for r63_fakes.fixture_repo equals FIXTURE_FACTS wherever the
    fixture's files hold the source (the differences are INTEGRATION-A's "Needs I1")."""
    got, want = facts.build(i0_repo(tmp_path), S, modules=DEMO), FIXTURE_FACTS
    for key in (
        "cards.count",
        "modules.count",
        "src/jarvis/demo/router.py:MAX_TRIES",
        "src/jarvis/demo/store.py:KEEP_DAYS",
        "settings.demo_limit",
        "release.label",
    ):
        assert got.values[key].value == want.values[key].value, key
    assert got.index.paths == want.index.paths
    assert got.index.constants == want.index.constants
    assert got.index.settings == want.index.settings
    assert set(want.index.symbols) <= set(got.index.symbols)
    assert got.settings == want.settings and got.modules == want.modules
    assert got.cards == want.cards and got.services == want.services
    assert got.routes == () and want.routes  # the fixture's files hold no router (Needs I1)

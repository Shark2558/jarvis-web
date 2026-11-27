# tests/test_r63_a_facts_real.py -- R6.3 part A on THIS repository (docs/plans/r6-3-book-content.md
# rows 379 and 380, D2, D3, H5, H6, M7, M9): the fact pack and the pages index the generator builds
# for the checkout these tests run in. Built once for the module (about 20 s on 2 CPUs).
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from r63_fakes_a import NOT_MOUNTED_HERE, TOUR, app_routes

from jarvis.buildbook.facts_model import (
    FACT_TOUR_KEYS,
    FACTS_JSON_CAP_BYTES,
    FactPack,
    canonical_facts,
)
from jarvis.buildbook.gen import facts, loc, pages_index
from jarvis.buildbook.gen import services as services_mod
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.gen.scrub import default_scrubber
from jarvis.buildbook.model import MAX_LIMITATIONS

ROOT = Path(__file__).resolve().parents[1]
S = default_scrubber()


@pytest.fixture(scope="module")
def repo() -> Repo:
    return Repo.from_git(ROOT)


@pytest.fixture(scope="module")
def pack(repo: Repo) -> FactPack:
    built = facts.build(repo, S)
    return built.model_copy(update={"pages": pages_index.build(repo, built)})


def test_row380_every_tour_key_is_known(pack: FactPack, repo: Repo) -> None:
    assert set(FACT_TOUR_KEYS) <= set(pack.values)
    for key, want in TOUR.items():
        assert pack.value(key) == want, key
    assert pack.value("loc.python_code") == loc.in_thousands(loc.python_code(pack.loc))
    assert re.fullmatch(r"\d{3} thousand", str(pack.value("loc.python_code")))
    months = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
    assert re.fullmatch(rf"\d{{1,2}} (?:{months}) 20\d\d", str(pack.value("release.date")))
    pins = [ln for ln in (repo.text("requirements.lock") or "").splitlines() if "==" in ln]
    assert pack.value("libs.python_pins") == len({p.split("==")[0].lower() for p in pins})


def test_row379_facts_index_holds_every_path_symbol_constant_setting_collection_route(
    pack: FactPack, repo: Repo
) -> None:
    ix = pack.index
    assert ix.paths == tuple(sorted({S.clean(f) for f in repo.files}))
    tops = {
        f"{S.clean(rel)}:{n.name}"
        for rel in repo.under("src/jarvis/")
        if rel.endswith(".py")
        for n in ast.parse(repo.text(rel) or "").body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assert set(ix.symbols) == tops
    assert len(ix.settings) == len(pack.settings) == 204  # R18 + 18, R5.2 + 7 (`config_*.py`)
    assert ix.collections == pack.collections and len(pack.collections) == _checker().collections
    assert ix.routes == tuple(sorted({f"{r.method} {r.path}" for r in pack.routes}))
    for field in ("paths", "symbols", "constants", "settings", "collections", "routes"):
        got = getattr(ix, field)
        assert list(got) == sorted(set(got)), field


def test_row379_every_number_a_page_quotes_is_a_values_key(pack: FactPack) -> None:
    assert pack.value("src/jarvis/llm/fallback.py:BREAKER_S") == 120
    assert pack.value("src/jarvis/llm/router.py:GUARD_REFRESH_S") == 5
    assert pack.value("src/jarvis/sos/service.py:HOLD_S") == 2  # a tuple assignment
    assert set(pack.index.constants) <= set(pack.values)
    assert all(f"settings.{s.name}" in pack.values for s in pack.settings if s.default is not None)
    assert len(pack.index.constants) > 1_400  # the plan counted 1,461 in 506 files on 47ee8fc
    for key in pack.index.constants:
        assert isinstance(pack.value(key), (int, float)) and not isinstance(pack.value(key), bool)


def test_h6_paths_are_scrubbed_and_android_pages_still_resolve(pack: FactPack, repo: Repo) -> None:
    raw = [f for f in repo.files if S.clean(f) != f]
    # R18 D: 16 more app files (the calls package, core's Calls and CallMachine, their tests)
    assert len(raw) == 62 and all(f.startswith("android/") for f in raw)
    S.verify(pack.model_dump(mode="json"))
    blob = pack.model_dump_json()
    assert not any(f in blob for f in raw)
    for cid in ("C62", "C64", "C65", "C78"):  # R18: C78 cites the app's calls code
        page = pack.page(f"pg_card_{cid.lower()}")
        assert page is not None and page.refs and set(page.refs) <= set(pack.index.paths)
    phone = pack.page("pg_card_c62")  # its `android/` folder, expanded in scrubbed form
    assert phone is not None and sum("/[removed]/" in r for r in phone.refs) >= 40


def test_m7_the_services_are_the_coverage_checker_s(pack: FactPack, repo: Repo) -> None:
    assert pack.services == services_mod.inventory(repo.root).names
    assert len(pack.services) == pack.value("services.count") == 35  # R18: +4
    assert {p.id for p in pack.pages if p.kind == "service"} == {
        f"pg_service_{pages_index.slug(s)}" for s in pack.services
    }


def test_d3_every_page_from_the_guide_and_the_code(pack: FactPack) -> None:
    kinds = [p.kind for p in pack.pages]
    # R18: the Phone calls module, cards C74-C78, the Calls screen, four services; R5.2: C79-C83
    # in Voice (no new module, screen or service: the voice session is in the Voice panel)
    assert kinds.count("chapter") == 8 and kinds.count("module") == 19
    assert kinds.count("card") == 83 and kinds.count("screen") == 24
    assert kinds.count("service") == 35 and len(pack.pages) == 169
    assert all(p.refs for p in pack.pages if p.kind in ("card", "module", "screen"))
    assert all(set(p.refs) <= set(pack.index.paths) for p in pack.pages)
    every_card = [c for m in pack.modules for c in m.cards]
    assert sorted(every_card) == sorted(set(every_card)) and len(every_card) == 83
    for cid, (_, files) in pages_index.CHAPTER_SOURCES.items():
        assert all(f in pack.index.paths for f in files), cid  # the fixed lists still exist


def test_g4_every_limitation_is_kept(pack: FactPack) -> None:
    assert len(pack.limitations) > MAX_LIMITATIONS
    assert pack.value("limitations.count") == len(pack.limitations)
    assert pack.value("limitations.shown") == MAX_LIMITATIONS


def test_the_pack_fits_its_cap(pack: FactPack) -> None:
    assert len(canonical_facts(pack)) <= FACTS_JSON_CAP_BYTES


def test_m9_the_route_list_is_the_app_s(pack: FactPack) -> None:
    """Every route of the app built with mock settings is in the pack, and every other route
    the pack lists is one the app mounts only in another mode (`NOT_MOUNTED_HERE`)."""
    mine = {(r.method, r.path) for r in pack.routes}
    app = app_routes()
    assert len(app) > 400 and app <= mine, sorted(app - mine)[:5]
    extra = [r for r in pack.routes if (r.method, r.path) not in app]
    loose = [
        r
        for r in extra
        if not any(r.module == m and r.path.startswith(p) for m, p in NOT_MOUNTED_HERE)
    ]
    assert extra and not loose, loose[:5]


def _checker() -> Any:
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import arch_inventory

        found = arch_inventory.inventory(ROOT)
    finally:
        sys.path.remove(str(ROOT / "scripts"))
    return type("Counts", (), {"collections": len(found.collections)})

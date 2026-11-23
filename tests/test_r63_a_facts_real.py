# tests/test_r63_a_facts_real.py -- R6.3 part A on THIS repository (docs/plans/r6-3-book-content.md
# rows 379 and 380, D2, D3, H5, H6, M7, M9): the fact pack and the pages index the generator builds
# for the checkout these tests run in. Built once for the module (about 20 s on 2 CPUs).
from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

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
# the plan's "The tour's facts" table, on this branch (the release's own values)
TOUR = {
    "release.label": "R6.3",
    "release.version": "v6.3.0",
    "release.new": "The Build Book: written by AI, short tour and full book",
    "cards.count": 73,
    "modules.count": 18,
    "modules.else_count": 11,
    "layers.count": 8,
    "brain.balanced_model": "Claude Sonnet 5.5",
    "undo.keep_days": 30,
    "keys.purposes": 26,
    "services.count": 31,
    "approvals.max_new_cards": 5,
    "memory.facts_per_turn": 12,
    "memory.learn_a_day": 20,
    "vault.unlock_minutes": 10,
    "vault.reminder_days_first": 180,
    "home.offline_minutes": 6,
    "sos.hold_s": 2,
    "sos.countdown_s": 5,
    "sos.max_contacts": 5,
    "sos.emergency": "112",
    "tryon.measures": 6,
    "seeme.inr_a_picture": "₹9",
    "seeme.month_cap_inr": "₹300",
    "costs.rate": 95.24,
    "roadmap.next": "R6.3.1, the Build Book's pictures and storage",
    "roadmap.after": "R6.4, the Book's new look",
}


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
    assert re.fullmatch(r"\d{1,2} [A-Z][a-z]+ 20\d\d", str(pack.value("release.date")))
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
    assert len(ix.settings) == len(pack.settings) == 179
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
    assert len(raw) == 46 and all(f.startswith("android/") for f in raw)
    S.verify(pack.model_dump(mode="json"))
    blob = pack.model_dump_json()
    assert not any(f in blob for f in raw)
    for cid in ("C62", "C64", "C65"):
        page = pack.page(f"pg_card_{cid.lower()}")
        assert page is not None and page.refs and set(page.refs) <= set(pack.index.paths)
    phone = pack.page("pg_card_c62")  # its `android/` folder, expanded in scrubbed form
    assert phone is not None and sum("/[removed]/" in r for r in phone.refs) >= 40


def test_m7_the_services_are_the_coverage_checker_s(pack: FactPack, repo: Repo) -> None:
    assert pack.services == services_mod.inventory(repo.root).names
    assert len(pack.services) == pack.value("services.count") == 31
    assert {p.id for p in pack.pages if p.kind == "service"} == {
        f"pg_service_{pages_index.slug(s)}" for s in pack.services
    }


def test_d3_every_page_from_the_guide_and_the_code(pack: FactPack) -> None:
    kinds = [p.kind for p in pack.pages]
    assert kinds.count("chapter") == 8 and kinds.count("module") == 18
    assert kinds.count("card") == 73 and kinds.count("screen") == 23
    assert kinds.count("service") == 31 and len(pack.pages) == 153
    assert all(p.refs for p in pack.pages if p.kind in ("card", "module", "screen"))
    assert all(set(p.refs) <= set(pack.index.paths) for p in pack.pages)
    every_card = [c for m in pack.modules for c in m.cards]
    assert sorted(every_card) == sorted(set(every_card)) and len(every_card) == 73
    for cid, (_, files) in pages_index.CHAPTER_SOURCES.items():
        assert all(f in pack.index.paths for f in files), cid  # the fixed lists still exist


def test_g4_every_limitation_is_kept(pack: FactPack) -> None:
    assert len(pack.limitations) > MAX_LIMITATIONS
    assert pack.value("limitations.count") == len(pack.limitations)
    assert pack.value("limitations.shown") == MAX_LIMITATIONS


def test_the_pack_fits_its_cap(pack: FactPack) -> None:
    assert len(canonical_facts(pack)) <= FACTS_JSON_CAP_BYTES


def _flat(routes: Any, prefix: str = "") -> Iterator[tuple[str, str]]:
    for r in routes:
        inner = getattr(r, "original_router", None)  # FastAPI's lazily included routers
        if inner is not None:
            yield from _flat(inner.routes, prefix + r.include_context.prefix)
            continue
        methods = getattr(r, "methods", None) or ("WEBSOCKET",)
        for m in methods:
            yield m, prefix + r.path


def _app_routes() -> set[tuple[str, str]]:
    from jarvis.api import create_app
    from jarvis.config import LLMBackend, SessionBackend, Settings

    s = Settings(  # type: ignore[call-arg]
        _env_file=None,
        env="dev",
        llm_backend=LLMBackend.MOCK,
        session_backend=SessionBackend.MEMORY,
        usd_inr_live=False,
    )
    return set(_flat(create_app(s).routes))


# routes the code declares that the app built with mock settings does not mount: the home
# bridge's own apps (the home laptop), Google sign-in (auth mode google), Google's tools link (a
# vault key) and the Scheduler's tick (its service account), each by module and path
NOT_MOUNTED_HERE = (
    ("src/jarvis/homebridge/app.py", "/"),
    ("src/jarvis/homebridge/local_page.py", "/"),
    ("src/jarvis/api/auth.py", "/auth/"),
    ("src/jarvis/api/integrations.py", "/connect/google"),
    ("src/jarvis/api/integrations.py", "/v1/integrations"),
    ("src/jarvis/api/brief.py", "/internal/brief/tick"),
)


def test_m9_the_route_list_is_the_app_s(pack: FactPack) -> None:
    """Every route of the app built with mock settings is in the pack, and every other route
    the pack lists is one the app mounts only in another mode (`NOT_MOUNTED_HERE`)."""
    mine = {(r.method, r.path) for r in pack.routes}
    app = _app_routes()
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

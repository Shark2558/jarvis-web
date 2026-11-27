# evals/r6_3/facts.py
"""R6.3 eval, part A's `facts` suite (evals/r6_3/run.py; docs/plans/r6-3-book-content.md "Tests
and evals"): the fact pack and pages index the generator builds for THIS checkout (built once,
about 25 s) and for fixtures (tests/r63_fakes_a.py). Each case is the eval case of a named test in
tests/test_r63_a_*.py: `--check` twice identical (two processes, two hash seeds); every tour key
known (row 380); the module map's 83 cards once (R5.2); the index; the counter's hand count; the
inventory's SPDX rows; the scrubber's kinds and phrases; the constants (H5); every page's refs;
H6; the 35 services (M7); the routes against the app built with mock settings (M9); G3 and G4; a
new card's page (row 380, grows). Controls, each turning its own case red: a set iterated
unsorted; the IPv4 pattern removed; C69 out of the map; raw paths (H6); a router name dropped
(M9); a fixed card list (row 380, grows); Wardrobe & Try-on dropped (row 380, tour). No model, no
network.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "src", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.append(str(_p))
from r63_fakes_a import (  # noqa: E402
    DEMO,
    INVENTORY_FILES,
    NOT_MOUNTED_HERE,
    TOUR,
    a_repo,
    app_routes,
    repo_of,
)

from jarvis.buildbook.facts_model import (  # noqa: E402
    FACT_TOUR_KEYS,
    FACTS_JSON_CAP_BYTES,
    FactIndex,
    FactPack,
    canonical_facts,
)
from jarvis.buildbook.gen import (  # noqa: E402
    code,
    facts,
    facts_code,
    facts_guide,
    facts_routes,
    flows,
    inventory,
    loc,
    pages_index,
    write,
)
from jarvis.buildbook.gen import modules as modules_mod  # noqa: E402
from jarvis.buildbook.gen import scrub as scrub_mod  # noqa: E402
from jarvis.buildbook.gen import services as services_mod  # noqa: E402
from jarvis.buildbook.gen.modules import Module  # noqa: E402
from jarvis.buildbook.gen.repo import GenError, Repo  # noqa: E402
from jarvis.buildbook.gen.scrub import Scrubber, default_scrubber  # noqa: E402
from jarvis.buildbook.model import MAX_LIMITATIONS  # noqa: E402

PART = "facts"
BUILT = True
S = default_scrubber()
NEVER = re.compile(r"(?!x)x")
FIXED_CARDS = ("C01", "C02", "C03")  # row 380 (grows)'s control: a list, not the guide
WITH_C74 = (Module("demo", "The demo", ("C01", "C02", "C03", "C74")),)
FLOWS = tuple((fid, fid, (("The demo router", "demo.router:pick"),)) for fid in flows.FLOW_IDS)
OPTS = write.Options(flows=FLOWS, layer_of={"demo": "L4", "config": "X"}, licence=lambda _n: "MIT")
PY = '"""Doc."""\n\n# a comment\nx = 1\n\n\ndef f() -> int:\n    """One line."""\n    return x\n'
Check = Callable[[], list[str]]


# ---- builds ---------------------------------------------------------------------------------
@cache
def repo() -> Repo:
    return Repo.from_git(ROOT)


def built(table: tuple[Module, ...] = modules_mod.MODULES) -> FactPack:
    pack = facts.build(repo(), S, modules=table)
    return pack.model_copy(update={"pages": pages_index.build(repo(), pack)})


@cache
def real() -> FactPack:
    return built()


def _need(ok: bool, why: str) -> list[str]:
    return [] if ok else [why]


def _guarded(check: Check) -> list[str]:
    try:
        return check()
    except Exception as exc:  # a case that breaks is a failed case, never a crashed eval
        return [f"{type(exc).__name__}: {str(exc)[:160]}"]


# ---- the cases ------------------------------------------------------------------------------
_SEEDED = """
import hashlib, sys
from pathlib import Path
from r63_fakes_a import DEMO, a_repo
from jarvis.buildbook.facts_model import canonical_facts
from jarvis.buildbook.gen import facts
from jarvis.buildbook.gen.scrub import default_scrubber
if sys.argv[2] == "unsorted":  # the control: a set iterated as it comes
    real = facts._index
    def _index(repo, scrub, trees, pack):
        paths = tuple({scrub.clean(f) for f in repo.files})
        return real(repo, scrub, trees, pack).model_copy(update={"paths": paths})
    facts._index = _index
pack = facts.build(a_repo(Path(sys.argv[1])), default_scrubber(), modules=DEMO)
print(hashlib.sha256(canonical_facts(pack)).hexdigest())
"""


def _seeded(seed: str, mode: str) -> str:
    path = os.pathsep.join([str(ROOT / "src"), str(ROOT / "tests")])
    env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": path}
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [sys.executable, "-c", _SEEDED, tmp, mode]
        done = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
    return done.stdout.strip() if done.returncode == 0 else f"failed {done.returncode}"


def check_twice_identical(mode: str = "sorted") -> list[str]:
    first, second = _seeded("1", mode), _seeded("2", mode)
    out = _need(first == second and len(first) == 64, "facts.json differs between two processes")
    original = facts.build
    with (
        tempfile.TemporaryDirectory() as tmp,
        mock.patch.object(facts, "build", lambda r, s: original(r, s, modules=DEMO)),
    ):
        fx = a_repo(Path(tmp))
        out += _need(write.check(fx, OPTS).facts == write.build(fx, OPTS).facts, "--check")
    return out


def tour_keys(pack: Callable[[], FactPack] = real) -> list[str]:
    got = pack()
    out = [f"missing {k}" for k in FACT_TOUR_KEYS if k not in got.values]
    out += [f"{k} = {got.value(k)!r}" for k, want in TOUR.items() if got.value(k) != want]
    return out


def module_map(table: tuple[Module, ...] = modules_mod.MODULES) -> list[str]:
    cards = [c.id for c in facts_guide.guide_cards(repo())]
    modules_mod.check(cards, table)  # a card in no module or two: GenError
    placed = [c for m in table for c in m.cards]
    # R18: + C74-C78 (73 -> 78); R5.2: + C79-C83 (78 -> 83)
    out = _need(len(cards) == len(placed) == len(set(placed)) == 83, "not 83 cards once")
    loose = tuple(Module(m.id, m.title, m.cards[1:]) if m.cards else m for m in table[:1])
    try:
        modules_mod.check(cards, (*loose, *table[1:]))
        out.append("a card left out of the map was not refused")
    except GenError:
        pass
    return out


def index() -> list[str]:
    ix, rp = real().index, repo()
    tops = {
        f"{S.clean(rel)}:{n.name}"
        for rel in rp.under("src/jarvis/")
        if rel.endswith(".py")
        for n in ast.parse(rp.text(rel) or "").body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    out = _need(ix.paths == tuple(sorted({S.clean(f) for f in rp.files})), "paths")
    # R18: CallsConfig's settings (179 -> 197); R5.2: LocalSpeechConfig's 7 (197 -> 204)
    out += _need(set(ix.symbols) == tops, "symbols") + _need(len(ix.settings) == 204, "settings")
    out += [
        f"{f} not sorted"
        for f in FactIndex.model_fields
        if list(getattr(ix, f)) != sorted(set(getattr(ix, f)))
    ]
    return out + _need(len(canonical_facts(real())) <= FACTS_JSON_CAP_BYTES, "over its 2 MiB cap")


def counter() -> list[str]:
    got = loc.count_text("x.py", PY)
    return _need((got.code, got.docstring, got.comment, got.blank) == (3, 2, 1, 3), str(got))


def inventory_rows() -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        rows = inventory.items(repo_of(Path(tmp), INVENTORY_FILES))
    groups = {r.group for r in rows}
    want = {"android library", "android build", "home kit image", "home bridge", "dev tool"}
    out = _need(groups == want, f"groups {sorted(groups)}")
    out += _need(any(r.licence == "Apache-2.0" for r in rows), "no SPDX Apache-2.0")
    out += _need(all(inventory.spdx(r.licence) == r.licence for r in rows), "a licence not SPDX")
    return out + _need({r.group for r in inventory.items(repo())} == want, "this checkout")


def scrubber() -> list[str]:
    caught = {
        "ipv4": "on 192.168.1.20 at home",
        "ipv6": "or fe80::1ff:fe23:4567:890a",
        "pan": "PAN ABCDE1234F",
        "aadhaar": "the number 2345 6789 0123",
        "project_id": "deployed to jarvis-home-482913",
    }
    out = [k for k, text in caught.items() if k not in S.findings(text)]
    domain = hashlib.sha256(b"owner-family.example").hexdigest()
    out += _need(
        "host"
        in Scrubber(frozenset(), domains=frozenset({domain})).findings("cam.owner-family.example"),
        "host",
    )
    phrase = Scrubber(
        frozenset(), phrases=frozenset({hashlib.sha256(b"quimbledorf works").hexdigest()})
    )
    out += _need("name" in phrase.findings("at QUIMBLEDORF  Works"), "phrase")
    alone = ("v6.3.0 shipped on 2026-11-23", "see model.py:235", "R6.3 and C16 and SHA-256")
    return out + [f"left alone: {t}" for t in alone if S.findings(t)]


def constants() -> list[str]:
    got = real()
    want = {
        "src/jarvis/llm/fallback.py:BREAKER_S": 120,
        "src/jarvis/llm/router.py:GUARD_REFRESH_S": 5,
        "src/jarvis/sos/service.py:HOLD_S": 2,
    }
    out = [k for k, v in want.items() if got.value(k) != v]
    numbers = all(isinstance(got.value(k), (int, float)) for k in got.index.constants)
    return out + _need(numbers and len(got.index.constants) > 1_400, "constants")


def refs() -> list[str]:
    got = real()
    paths = set(got.index.paths)
    bad = [
        p.id for p in got.pages if not set(p.refs) <= paths or any(r.endswith("/") for r in p.refs)
    ]
    empty = [p.id for p in got.pages if p.kind in ("card", "module", "screen") and not p.refs]
    return [f"refs of {p}" for p in bad[:5]] + [f"no refs: {p}" for p in empty[:5]]


def h6(pack: Callable[[], FactPack] = real) -> list[str]:
    got, raw = pack(), [f for f in repo().files if S.clean(f) != f]
    try:
        S.verify(got.model_dump(mode="json"))
    except scrub_mod.ScrubLeak as exc:
        return [f"verify: {str(exc)[:120]}"]
    blob = got.model_dump_json()
    # R18: the app's 16 calls files (46 -> 62)
    out = _need(len(raw) == 62 and not any(f in blob for f in raw), "a raw path in the pack")
    for cid in ("c62", "c64", "c65"):
        page = got.page(f"pg_card_{cid}")
        out += _need(
            page is not None and bool(page.refs) and set(page.refs) <= set(got.index.paths), cid
        )
    return out


def m7() -> list[str]:
    got = real()
    names = services_mod.inventory(repo().root).names
    # R18: + Azure Speech, Sarvam, Bhashini, Hugging Face (31 -> 35)
    out = _need(got.services == names and len(names) == 35 == got.value("services.count"), "35")
    pages = {p.id for p in got.pages if p.kind == "service"}
    return out + _need(pages == {f"pg_service_{code.slug(s)}" for s in names}, "service pages")


def m9(routes: Callable[[], Any] = lambda: real().routes) -> list[str]:
    got = routes()
    mine, app = {(r.method, r.path) for r in got}, app_routes()
    out = _need(len(app) > 400 and app <= mine, f"not in the pack: {sorted(app - mine)[:3]}")
    loose = [
        r
        for r in got
        if (r.method, r.path) not in app
        and not any(r.module == m and r.path.startswith(p) for m, p in NOT_MOUNTED_HERE)
    ]
    return out + [f"loose {r.method} {r.path}" for r in loose[:3]]


def g3_g4() -> list[str]:
    rows = code.integrations(repo(), S).services
    table = services_mod.tables(repo().root)
    out = _need(
        code.services_named(rows, table) == set(services_mod.inventory(repo().root).names), "G3"
    )
    got = real()
    total, shown = got.value("limitations.count"), got.value("limitations.shown")
    out += _need(isinstance(total, int) and total > MAX_LIMITATIONS == shown, f"G4 {total} {shown}")
    return out


def grows(build_pages: Callable[..., Any] | None = None) -> list[str]:
    make = build_pages or pages_index.build
    with tempfile.TemporaryDirectory() as tmp:
        fx = a_repo(Path(tmp) / "a", c74=True)
        pack = facts.build(fx, S, modules=WITH_C74)
        page = next((p for p in make(fx, pack) if p.id == "pg_card_c74"), None)
        out = _need(page is not None and page.chapter == "demo" and bool(page.refs), "no C74 page")
        try:
            facts.build(a_repo(Path(tmp) / "b", c74=True), S, modules=DEMO)
            out.append("a C74 in no module was not refused")
        except GenError:
            pass
    return out


CASES: dict[str, Check] = {
    "check_twice_identical": check_twice_identical,
    "row380_every_tour_key_is_known": tour_keys,
    "module_map": module_map,
    "index": index,
    "counter": counter,
    "inventory": inventory_rows,
    "scrubber": scrubber,
    "constants": constants,
    "refs": refs,
    "h6": h6,
    "m7": m7,
    "m9": m9,
    "g3_g4": g3_g4,
    "row380_a_new_card_gets_its_own_page_at_the_next_release": grows,
}


async def cases() -> list[dict[str, Any]]:
    got = {name: _guarded(check) for name, check in CASES.items()}
    return [{"id": f"{PART}:{n}", "passed": not f, "failures": f} for n, f in got.items()]


# ---- the controls ---------------------------------------------------------------------------
def _raw_index(original: Callable[..., FactIndex]) -> Callable[..., FactIndex]:
    def raw(rp: Repo, scrub: Scrubber, trees: Any, pack: Any) -> FactIndex:
        return original(rp, scrub, trees, pack).model_copy(
            update={"paths": tuple(sorted(rp.files))}
        )

    return raw


def _no_router(original: Callable[..., Any]) -> Callable[..., Any]:
    def target(self: Any, call: Any, routers: Any) -> Any:
        hit = original(self, call, routers)
        return None if hit and hit[0] == "router" else hit

    return target


def _fixed_list(rp: Repo, pack: FactPack) -> Any:
    kept = tuple(c for c in pack.cards if c.id in FIXED_CARDS)
    return pages_index.build(rp, pack.model_copy(update={"cards": kept}))


def _controls() -> dict[str, Check]:
    no_c69 = tuple(
        Module(m.id, m.title, tuple(c for c in m.cards if c != "C69")) for m in modules_mod.MODULES
    )
    no_wardrobe = tuple(m for m in modules_mod.MODULES if m.title != "Wardrobe & Try-on")

    def ip_removed() -> list[str]:
        with mock.patch.object(scrub_mod, "_IPV4", NEVER):
            return scrubber()

    def raw_paths() -> list[str]:
        with mock.patch.object(facts, "_index", _raw_index(facts._index)):
            return h6(built)

    def router_dropped() -> list[str]:
        scan = facts_routes._Scan
        with mock.patch.object(scan, "_target", _no_router(scan._target)):
            return m9(lambda: facts_routes.routes(facts_code.parse_src(repo()), S))

    return {
        "check_twice_identical": lambda: check_twice_identical("unsorted"),
        "scrubber": ip_removed,
        "module_map": lambda: module_map(no_c69),
        "h6": raw_paths,
        "m9": router_dropped,
        "row380_a_new_card_gets_its_own_page_at_the_next_release": lambda: grows(_fixed_list),
        "row380_every_tour_key_is_known": lambda: tour_keys(lambda: built(no_wardrobe)),
    }


async def control() -> dict[str, Any]:
    still_green = [n for n, check in _controls().items() if not _guarded(check)]
    return {
        "name": "a set unsorted; the IP pattern removed; C69 out of the map; raw paths (H6); a "
        "router name dropped (M9); a fixed card list (row 380 grows); Wardrobe & Try-on dropped",
        "suite_failed": not still_green,
        "failed_cases": [f"{PART}:{n}" for n in _controls() if n not in still_green],
        "still_green": still_green,
    }

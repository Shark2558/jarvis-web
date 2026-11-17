# evals/r13_1/contract.py
"""R13.1 eval, I0's own part (`contract`, BUILT): the two new parts in R13's contract
(jarvis.wardrobe.ports), through the real wiring (jarvis.api.r13_wiring) on in-memory fakes:

- all six parts build through `build_parts` under their own names, not "setup failed"; `tryon`
  and `seeme` register no tool and offer no `data`; their routers (`api/tryon.py`,
  `api/seeme.py`) answer only under their own prefix and only rows of the R13.1 HTTP contract
  (`wardrobe.tryon.http.ROUTES`);
- the check refuses a stray part: `data` on an R13.1 part (M4), another part's Privacy row, a row
  that is not one of the six, another part's service, `seeme_daily` as a clock job or from A, and
  a router with a route outside the contract;
- a broken R13.1 part is "setup failed" while R13's four still build and R13's Wardrobe rows still
  read; the Try-on section has its six rows (the stand-ins) and they say "Couldn't check right
  now" for documents they can't open;
- row 388's server half (D21, I0's join): "what should I wear?" -> `outfit_suggest` through the
  real gateway puts exactly ONE try-on card beside the reply, its slots the look's (a private slot
  covered, no id), and none while Try-on is off.

Negative control: the contract check taken away (`check_part` returns what it is given, and the
route check accepts any route): every refusal case must then fail; and row 388's own control, the
card left out of the reply (`tryon_card.show` does nothing): its case must then fail.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "src", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.append(str(_p))
from fastapi import APIRouter  # noqa: E402

from jarvis.api import r13_wiring as wiring  # noqa: E402
from jarvis.api.seeme import router as seeme_router  # noqa: E402
from jarvis.api.tryon import router as tryon_router  # noqa: E402
from jarvis.config import Settings  # noqa: E402
from jarvis.privacy.ports import CategoryView  # noqa: E402
from jarvis.storage.docs import MemoryDocs, Set  # noqa: E402
from jarvis.tools.audit import AuditLog  # noqa: E402
from jarvis.tools.reply_cards import collecting_cards  # noqa: E402
from jarvis.wardrobe.ports import PARTS, ROUTE_PREFIX, WardrobeContext, WardrobePart  # noqa: E402
from jarvis.wardrobe.styling import tryon_card  # noqa: E402
from jarvis.wardrobe.tryon import kept  # noqa: E402
from jarvis.wardrobe.tryon.http import ROUTES  # noqa: E402

PART = "contract"
BUILT = True
UID = "owner-eval"
ROUTERS: dict[str, APIRouter] = {"tryon": tryon_router, "seeme": seeme_router}
RouteCheck = Callable[[str, APIRouter], list[str]]


class _Job:
    def __init__(self, name: str) -> None:
        self.name, self.budget_s = name, 5.0

    async def run(self, owners: Any) -> dict[str, int]:
        return {}


class _Data:
    name, row = "laundry", "history"

    async def count(self, uid: str) -> int:
        return 0

    async def export(self, uid: str) -> dict[str, Any]:
        return {}

    async def delete(self, uid: str) -> int:
        return 0


class _Row:
    section, label = "Try-on", "a row"

    def __init__(self, rid: str) -> None:
        self.id = rid

    async def describe(self, uid: str) -> CategoryView:
        raise NotImplementedError

    async def export(self, uid: str) -> dict[str, Any] | None:
        return None

    async def delete(self, uid: str) -> int:
        return 0


STRAYS: dict[str, tuple[str, WardrobePart]] = {
    "data_on_tryon": ("tryon", WardrobePart("tryon", data=(_Data(),))),  # type: ignore[arg-type]
    "data_on_seeme": ("seeme", WardrobePart("seeme", data=(_Data(),))),  # type: ignore[arg-type]
    "another_parts_row": ("seeme", WardrobePart("seeme", privacy=(_Row("tryon_all"),))),
    "a_row_not_planned": ("tryon", WardrobePart("tryon", privacy=(_Row("tryon_extra"),))),
    "another_parts_service": ("tryon", WardrobePart("tryon", services={"seeme": object()})),
    "r13s_service": ("seeme", WardrobePart("seeme", services={"photos": object()})),
    "seeme_daily_as_clock": ("seeme", WardrobePart("seeme", clock_jobs=(_Job("seeme_daily"),))),
    "seeme_daily_from_a": ("tryon", WardrobePart("tryon", daily_jobs=(_Job("seeme_daily"),))),
}


def _ctx(docs: MemoryDocs, state: dict[str, Any] | None = None) -> WardrobeContext:
    async def zone(uid: str) -> ZoneInfo:
        return ZoneInfo("Asia/Kolkata")

    return WardrobeContext(
        s=Settings(_env_file=None), docs=docs, keyring=None, audit=AuditLog(),
        now=lambda: datetime(2026, 11, 17, 6, 30, tzinfo=UTC), zone=zone,
        state=(state if state is not None else {}).get,
    )  # fmt: skip


def route_failures(name: str, router: APIRouter) -> list[str]:
    planned = {(m, p) for m, p, part, *_ in ROUTES if part == name}
    out: list[str] = []
    for route in router.routes:
        path = str(getattr(route, "path", ""))
        methods = set(getattr(route, "methods", None) or ())
        if not any(path.startswith(x) for x in ROUTE_PREFIX[name]):  # type: ignore[index]
            out.append(f"route {path} outside {ROUTE_PREFIX[name]}")  # type: ignore[index]
        out += [
            f"route {m} {path} not in the contract" for m in methods if (m, path) not in planned
        ]
    return out


def _stray_router() -> APIRouter:
    r = APIRouter()

    @r.post("/v1/tryon/erase")
    async def erase() -> dict[str, str]:  # OPS-05 is a Privacy delete, never a route (M10)
        return {}

    return r


def _built_cases(routes: RouteCheck) -> list[dict[str, Any]]:
    parts = wiring.build_parts(_ctx(MemoryDocs()))
    out: list[dict[str, Any]] = []
    for name in PARTS:
        part = parts.get(name)
        failures: list[str] = []
        if not isinstance(part, WardrobePart) or part.name != name:
            failures.append("not a WardrobePart under its own name")
        elif part.ready == wiring.SETUP_FAILED:
            failures.append("left out: setup failed")
        elif name in ROUTERS:
            failures += [f"tool {t.name}" for t in part.tools]
            failures += ["data"] if part.data else []
            failures += routes(name, ROUTERS[name])
        out.append({"id": f"contract:{name}_builds", "passed": not failures, "failures": failures})
    return out


def _refusal_cases(check: Callable[[Any, Any], Any], routes: RouteCheck) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for case, (name, part) in STRAYS.items():
        try:
            check(name, part)
            failures = ["accepted"]
        except ValueError:
            failures = []
        out.append({"id": f"contract:refuses_{case}", "passed": not failures, "failures": failures})
    stray = routes("tryon", _stray_router())
    out.append({"id": "contract:refuses_a_stray_route", "passed": bool(stray),
                "failures": [] if stray else ["accepted"]})  # fmt: skip
    return out


async def _seeded() -> tuple[MemoryDocs, str]:
    docs, prefix = MemoryDocs(), Settings(_env_file=None).firestore_prefix
    paths = (f"{prefix}tryon/{UID}", f"{prefix}tryon_person/{UID}")
    await docs.write([Set(p, {"owner": UID, "blob": "sealed"}) for p in paths])
    return docs, prefix


async def _broken_case() -> list[dict[str, Any]]:
    real = wiring._build  # noqa: SLF001

    def build(name: Any, ctx: WardrobeContext) -> WardrobePart:
        if name in ("tryon", "seeme"):
            raise RuntimeError("a broken R13.1 part")
        return real(name, ctx)

    docs, _ = await _seeded()
    state: dict[str, Any] = {}
    wiring._build = build  # type: ignore[assignment]  # noqa: SLF001
    try:
        parts = wiring.build_parts(_ctx(docs, state))
    finally:
        wiring._build = real  # type: ignore[assignment]  # noqa: SLF001
    state["r13_parts"] = parts
    failures = [n for n in ("tryon", "seeme") if parts[n].ready != wiring.SETUP_FAILED]
    failures += [f"{n} left out" for n in PARTS[:4] if parts[n].ready == wiring.SETUP_FAILED]
    rows = {r.id: r for p in parts.values() for r in p.privacy}
    for rid in ("wardrobe_pieces", "wardrobe_history", "wardrobe_plans", "wardrobe_photos"):
        seen = await rows[rid].describe(UID)
        if not seen.available or seen.note.startswith("Couldn't check"):
            failures.append(f"{rid} doesn't read")
    stand = [r for r in kept.ROW_IDS if r in rows]
    if stand != list(kept.ROW_IDS):
        failures.append(f"the Try-on rows: {stand}")
    figure = await rows[kept.FIGURE_ID].describe(UID)
    if not figure.note.startswith("Couldn't check right now"):
        failures.append("the figure row claims to know")
    return [
        {"id": "contract:broken_r131_parts_leave_r13_running", "passed": not failures,
         "failures": failures},
    ]  # fmt: skip


async def _row388_case() -> list[dict[str, Any]]:
    from r13_fakes_c import ist, settings, world

    failures: list[str] = []
    for on in (True, False):
        w = await world(at=ist(2026, 11, 16, 20, 0), s=settings(tryon_enabled=on))
        cards: list[Any] = []
        with collecting_cards(cards):
            got = await w.call("outfit_suggest", day="tomorrow")
        wrong = tryon_card.missing(cards)
        if on and wrong:
            failures.append(wrong)
        if not on and not wrong:
            failures.append("a try-on card while Try-on is off")
        look = got.result["looks"][0]["pieces"] if on and not wrong else []
        mine = {p["slot"]: tuple(p["ids"]) for p in look if p["slot"] not in ("base", "underwear")}
        shown = {s.slot: s.pieces for c in cards for s in c.slots if not s.private} if look else {}
        if on and look and shown != mine:
            failures.append("the card's slots are not the look's")
    return [
        {"id": "contract:row388_what_to_wear_opens_the_tryon_card", "passed": not failures,
         "failures": failures},
    ]  # fmt: skip


async def cases() -> list[dict[str, Any]]:
    out = _built_cases(route_failures) + _refusal_cases(wiring.check_part, route_failures)
    return out + await _broken_case() + await _row388_case()


async def control() -> dict[str, Any]:
    results = _refusal_cases(lambda name, part: part, lambda name, router: [])  # no check at all
    real = tryon_card.show
    tryon_card.show = lambda view, ans: False  # type: ignore[assignment]  # row 388: card left out
    try:
        results += await _row388_case()
    finally:
        tryon_card.show = real  # type: ignore[assignment]
    failed = [r["id"] for r in results if not r["passed"]]
    every = len(failed) == len(results)  # each case must fail under its control
    return {
        "name": "no contract check; the try-on card left out (row 388)",
        "suite_failed": every, "failed_cases": failed,
    }  # fmt: skip

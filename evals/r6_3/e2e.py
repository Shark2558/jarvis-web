# evals/r6_3/e2e.py
"""R6.3 eval, I1's `e2e` suite (BUILT; docs/plans/r6-3-book-content.md "Tests and evals", I0-NOTES
section 5 item 3): the four parts joined, through the REAL app over HTTP (Google sign-in faked,
passkeys, R6's book sessions; the writer's service of part B over the fakes swapped in), on part
A's OWN fact pack of I0's fixture repository (`facts.build` and `pages_index.build`, the join's
two calls; plus the four trial pages the fixture's guide has no card for). No model is called:
the scripted brains of tests/r63_fake_brains.py.

- `trial`: the estimate first (₹100 cap), "yes" refused, YES starts it, the steps, the side by
  side (both brains' five pages), a trial page at the balanced tier; then at the cap (every
  page refused by its checks, full packs) it stops before a call whose worst case would pass
  ₹100, never above it;
- `first_write`: the pick's 422 `yes_needed` with its ₹ words, saved on YES with its terms id, the
  first write's YES on its estimate, sealed, and a page in the owner's reader written by AI;
- `update_changed_only`: a new release id (one file changed) -> `update_ready` naming exactly
  the pages that cite it -> Update with YES -> the brain asked for those pages only, the rest
  carried free;
- `console_only`: every writer route refuses a script holding his token (403 `console_only`),
  another owner (403 `not_primary`) and nobody signed in (401); the pages need a book session;
- `guest_tour`: the tour built from part A's real fact pack of THIS checkout and the real show
  (part D's filler), served through the real routes: a guest gets no T16, no owner-only line and
  no ₹, and speaking an owner-only line is 404 `unknown_line`; the owner's T16 has his honorific.

Negative control (the plan's): the update writing every page (`carry.is_changed` always true):
`update_changed_only` fails.
"""

from __future__ import annotations

import functools
import json
import re
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "src", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.append(str(_p))
from book_app_fakes import (  # noqa: E402
    BEARER,
    CSRF,
    OWNER,
    SECOND_OWNER,
    book,
    book_app,
    open_book,
    owner_uid,
    register_passkey,
    sign_in,
)
from book_show_fakes import FixtureSource  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from r63_fake_brains import FAKE_PATH_DRAFT, claude_like, gemini_like, provider_of, registry  # noqa: E402
from r63_fakes import FIXTURE_FILES, RELEASE, source_zip  # noqa: E402
from r63_fakes_a import DEMO, repo_of  # noqa: E402
from r63_fakes_b import TRIAL_EXTRA, MovableSource, files, hold_payer, seal_r6, service  # noqa: E402
from r63_fakes_d import with_tour  # noqa: E402

from jarvis.buildbook.facts_model import FactPack  # noqa: E402
from jarvis.buildbook.gen import facts, pages_index, write  # noqa: E402
from jarvis.buildbook.gen.repo import Repo  # noqa: E402
from jarvis.buildbook.gen.scrub import default_scrubber  # noqa: E402
from jarvis.buildbook.model import Book  # noqa: E402
from jarvis.buildbook.writer import carry  # noqa: E402
from jarvis.buildbook.writer.http import ROUTES  # noqa: E402
from jarvis.config import LLMBackend, SessionBackend, Settings  # noqa: E402

PART = "e2e"
BUILT = True
W = "/v1/book/writer"
ASKED = re.compile(r"Write the page (pg_[a-z0-9_]+) ")
RUPEE = re.compile(r"₹|\bRs\b|rupee", re.IGNORECASE)
CHANGED_FILE = "src/jarvis/demo/store.py"
Case = dict[str, Any]


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        env="dev",
        llm_backend=LLMBackend.MOCK,
        session_backend=SessionBackend.MEMORY,
        usd_inr_live=False,
    )


def _case(name: str, failures: list[str]) -> Case:
    return {"id": f"{PART}:{name}", "passed": not failures, "failures": failures}


@functools.lru_cache(maxsize=1)
def a_pack() -> FactPack:
    """Part A's own pack of I0's fixture repository (the join's two calls), with the trial's four
    pages the fixture's guide has no card for."""
    with tempfile.TemporaryDirectory(prefix="r63e2e-") as tmp:
        repo = repo_of(Path(tmp), dict(FIXTURE_FILES))
        pack = facts.build(repo, default_scrubber(), modules=DEMO)
        pack = pack.model_copy(update={"release": RELEASE})
        pages = pages_index.build(repo, pack)
    return pack.model_copy(update={"pages": (*pages, *TRIAL_EXTRA)})


def _wire(app: Any, brains: Any, source: Any) -> Any:
    built = service(brains=brains, source=source, uid=owner_uid(OWNER), emails=(OWNER,))
    app.state.book_writer = built.service
    return built


def _asked(*specs: Any) -> list[str]:
    """The page ids the brains were asked to write, in order (from each call's user turn)."""
    out: list[str] = []
    for spec in specs:
        for call in provider_of(spec).calls:
            m = ASKED.search(call.messages[0].text())
            out.append(m.group(1) if m else "?")
    return out


async def _steps(c: AsyncClient, n: int = 40) -> dict[str, Any]:
    view: dict[str, Any] = {}
    for _ in range(n):
        view = (await c.post(f"{W}/step", headers=CSRF)).json()
        if view.get("state") not in ("queued", "running"):
            break
    return view


# ---- the trial -----------------------------------------------------------------------------------
async def _trial() -> list[str]:
    out: list[str] = []
    claude, gemini = claude_like(), gemini_like()
    src = MovableSource(a_pack(), zipped=source_zip(files()))
    async for app in book_app(_settings()):
        _wire(app, registry(claude, gemini), src)
        async with sign_in(app) as c:
            est = (await c.get(f"{W}/estimate", params={"run": "trial"})).json()
            if est.get("cap") != 100 or "$" in json.dumps(est):
                out.append(f"the trial's estimate: {est.get('cap')}")
            no = await c.post(f"{W}/trial", json={"typed": "yes", "estimate_id": est["id"]},
                              headers=CSRF)  # fmt: skip
            if no.status_code != 422 or _asked(claude, gemini):
                out.append("'yes' was not refused, or a brain was called before YES")
            ok = await c.post(f"{W}/trial", json={"typed": "YES", "estimate_id": est["id"]},
                              headers=CSRF)  # fmt: skip
            view = await _steps(c)
            rows = (await c.get(f"{W}/trial/pages")).json().get("rows", [])
            if ok.status_code != 200 or view.get("state") != "done" or len(rows) != 10:
                out.append(f"the trial: {ok.status_code} {view.get('state')} {len(rows)} rows")
            if {r["brain"] for r in rows} != {"anthropic", "gemini"}:
                out.append("the side by side lacks a brain")
            page = (await c.get(f"{W}/trial/pages/01")).json().get("page", {})
            if (page.get("meta") or {}).get("tier") != "balanced":
                out.append("a trial page not at the balanced tier")
    return out + await _trial_cap()


async def _trial_cap() -> list[str]:
    payer = hold_payer(*([FAKE_PATH_DRAFT] * 10))
    src = MovableSource(a_pack(), zipped=source_zip(files(big=True)))
    async for app in book_app(_settings()):
        _wire(app, registry(payer, gemini_like()), src)
        async with sign_in(app) as c:
            est = (await c.get(f"{W}/estimate", params={"run": "trial"})).json()
            await c.post(f"{W}/trial", json={"typed": "YES", "estimate_id": est["id"]},
                         headers=CSRF)  # fmt: skip
            view = await _steps(c)
    calls, inr, hold = len(provider_of(payer).calls), view.get("inr", 0.0), est.get("hold", 0.0)
    # every page fails its checks, so all ten calls would be sent without the cap; a call that
    # settles below its hold (a small pack, the chapter page here) leaves room, so the count is
    # 8 only when every call settles at its worst case (part B's row test): the rule is the cap
    stopped = view.get("state") == "stopped" and "cap" in str(view.get("why", "")).lower()
    if not (stopped and calls < 10 and inr <= 100.0 < inr + hold and hold > 11.0):
        return [f"at the ₹100 cap: {calls} calls, {view.get('state')}, ₹{inr}, hold ₹{hold}"]
    return []


# ---- the pick, the first write, a page in the reader, and the update ----------------------------
async def _pick(c: AsyncClient) -> list[str]:
    pick = {"brain": "anthropic", "caps": {"trial": 100, "first": 1500, "release": 500,
                                           "month": 1000, "limit_pct": 80}}  # fmt: skip
    r = await c.put(f"{W}/pick", json=pick, headers=CSRF)
    body = r.json()
    if r.status_code != 422 or body.get("error") != "yes_needed":
        return [f"the first pick saved without a YES: {r.status_code}"]
    out = [] if any("₹" in w for w in body.get("words", [])) else ["the YES words carry no ₹"]
    r = await c.put(f"{W}/pick", json={**pick, "typed": "YES", "terms_id": body["terms_id"]},
                    headers=CSRF)  # fmt: skip
    return out + ([] if r.status_code == 200 else [f"the pick on YES: {r.status_code}"])


async def _run(c: AsyncClient, kind: str, estimate_id: str | None = None) -> dict[str, Any]:
    if estimate_id is None:
        estimate_id = (await c.get(f"{W}/estimate", params={"run": kind})).json()["id"]
    r = await c.post(f"{W}/{kind}", json={"typed": "YES", "estimate_id": estimate_id},
                     headers=CSRF)  # fmt: skip
    return r.json() if r.status_code == 200 else {"state": f"refused {r.status_code}"}


async def _written(app: Any, c: AsyncClient, page_id: str) -> dict[str, Any]:
    auth = await register_passkey(c)
    owner = await open_book(c, auth, "owner")
    r = await c.get(f"/v1/book/pages/{page_id}", headers=book(owner["token"]))
    return r.json() if r.status_code == 200 else {"status": r.status_code}


async def _first_and_update() -> tuple[list[str], list[str]]:
    first: list[str] = []
    claude = claude_like()
    src = MovableSource(a_pack(), zipped=source_zip(files()))
    async for app in book_app(_settings()):
        built = _wire(app, registry(claude, gemini_like()), src)
        await seal_r6(built)
        async with sign_in(app) as c:
            first += await _pick(c)
            if (await _run(c, "first")).get("state") != "queued":
                first.append("the first write did not start on YES")
            if (await _steps(c)).get("state") != "done":
                first.append("the first write did not finish")
            page = await _written(app, c, "pg_card_c01")
            if not page.get("meta") or page["meta"].get("tier") != "balanced":
                first.append(f"pg_card_c01 in the reader is not written by AI: {page}")
            update = await _update(built, c, src, claude)
    return first, update


async def _update(built: Any, c: AsyncClient, src: MovableSource, claude: Any) -> list[str]:
    before = len(provider_of(claude).calls)
    tree = files({CHANGED_FILE: '"""The demo store, changed."""\n\nKEEP_DAYS = 30\n'})
    new = src.deploy("70" * 20, tree, a_pack())
    await seal_r6(built)
    await built.job.run((built.job._ctx.uid,))
    ready = (await c.get(W)).json().get("update_ready") or {}
    want = {p.id for p in a_pack().pages if CHANGED_FILE in p.refs}
    out = [] if ready.get("release") == new.id else ["no update_ready for the new release"]
    if set(ready.get("pages", ())) != want:
        out.append(f"update_ready names {sorted(ready.get('pages', ()))}, not {sorted(want)}")
    if (await _run(c, "update", ready.get("estimate_id"))).get("state") != "queued":
        out.append("Update did not start on YES")
    await _steps(c)
    asked = set(_asked(claude)[before:])
    if asked != want:
        out.append(f"Update asked the brain for {sorted(asked)}, not only {sorted(want)}")
    return out


# ---- console only, the primary owner -------------------------------------------------------------
async def _console_only() -> list[str]:
    out: list[str] = []
    async for app in book_app(_settings()):
        _wire(app, registry(claude_like(), gemini_like()), MovableSource(a_pack()))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as bare:
            for method, path, *_rest, gate in ROUTES:
                url = path.replace("{nn}", "01").replace("{page_id}", "pg_card_c01")
                body = None if method in ("GET", "DELETE") else {}
                if (await bare.request(method, url, json=body)).status_code != 401:
                    out.append(f"{method} {path} signed out is not 401")
                r = await bare.request(method, url, json=body, headers={**BEARER, **CSRF})
                want = 403 if gate == "console" else 401
                if r.status_code != want:
                    out.append(f"{method} {path} with his token: {r.status_code}, not {want}")
        async with sign_in(app, SECOND_OWNER) as c:
            for method, path, *_rest, gate in ROUTES:
                if gate != "console":
                    continue
                url = path.replace("{nn}", "01")
                r = await c.request(method, url, json=None if method in ("GET", "DELETE") else {},
                                    headers=CSRF)  # fmt: skip
                if r.status_code != 403 or r.json().get("error") != "not_primary":
                    out.append(f"{method} {path} for another owner: {r.status_code}")
    return out


# ---- a guest's tour from part A's real pack of this checkout ------------------------------------
@functools.lru_cache(maxsize=1)
def real_book() -> Book:
    """This checkout's book with its tour (A's real fact pack, D's filler, the real show)."""
    book_, _ = write.assemble(Repo.from_git(ROOT), write.Options())
    return book_


class RealTourSource(FixtureSource):
    def book(self) -> Book:
        return with_tour(super().book(), real_book().tour)


async def _guest_tour() -> list[str]:
    tour = real_book().tour
    if tour is None:
        return ["this checkout's book has no tour"]
    owner_only = [b.id for s in tour.owner.scenes for b in s.beats
                  if "owner" in (s.audience, b.audience)]  # fmt: skip
    out: list[str] = []
    async for app in book_app(_settings(), source=RealTourSource()):
        async with sign_in(app) as c:
            auth = await register_passkey(c)
            guest = book((await open_book(c, auth, "guest"))["token"])
            got = (await c.get("/v1/book/show/script", headers=guest)).json()
            said = " ".join(b["text"] for s in got.get("scenes", []) for b in s["beats"])
            if got.get("kind") != "tour" or any(s.get("n") == 16 for s in got.get("scenes", [])):
                out.append("a guest's script is not the tour without T16")
            if RUPEE.search(said) or got.get("costs"):  # a guest's costs: {}
                out.append("a guest's tour names rupees or carries costs")
            for line in owner_only:
                r = await c.post("/v1/book/show/speak", json={"line_id": line}, headers=guest)
                if (r.status_code, r.json().get("error")) != (404, "unknown_line"):
                    out.append(f"a guest's speak of {line}: {r.status_code}")
    async for app in book_app(_settings(), source=RealTourSource()):  # a fresh console: no lock
        async with sign_in(app) as c:
            auth = await register_passkey(c)
            owner = book((await open_book(c, auth, "owner"))["token"])
            mine = (await c.get("/v1/book/show/script", headers=owner)).json()
            t16 = [
                b["text"] for s in mine.get("scenes", []) if s.get("n") == 16 for b in s["beats"]
            ]
            if not t16 or any("{h}" in t for t in t16):
                out.append("the owner's T16 lacks its words")
    return out + ([] if owner_only == ["t13b03", "t16b01"] else [f"owner-only: {owner_only}"])


CASES: dict[str, Callable[[], Any]] = {
    "trial": _trial,
    "console_only": _console_only,
    "guest_tour": _guest_tour,
}


async def _safe(fn: Callable[[], Any]) -> Any:
    """A case that raises fails with the exception's type and words (it never stops the run)."""
    try:
        return await fn()
    except Exception as exc:  # noqa: BLE001 - an eval case reports, it does not crash the runner
        return [f"raised {type(exc).__name__}: {str(exc)[:200]}"]


async def cases() -> list[Case]:
    got = [_case(name, await _safe(fn)) for name, fn in CASES.items()]
    both = await _safe(_first_and_update)
    first, update = (both, both) if isinstance(both, list) else both
    return [*got, _case("first_write", first), _case("update_changed_only", update)]


async def control() -> dict[str, Any]:
    was = carry.is_changed
    carry.is_changed = lambda ip, old, new: True  # type: ignore[assignment]  # every page "changed"
    try:
        both = await _safe(_first_and_update)
        update = both if isinstance(both, list) else both[1]
    finally:
        carry.is_changed = was  # type: ignore[assignment]
    return {
        "name": "I1: the update writing every page (carry.is_changed always true)",
        "suite_failed": bool(update),
        "failed_cases": [f"{PART}:update_changed_only {update[:2]}"] if update else [],
    }

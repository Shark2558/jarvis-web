# evals/r6_3/contract.py
"""R6.3 eval, I0's own part (`contract`, BUILT; docs/plans/r6-3-book-content.md "Tests and evals",
plan review L12), on in-memory fakes and the scripted brains (no model is ever called):

- `wired`: the writer builds through its ONE join (`buildbook/writer/part.build`) on the real app
  with the server's keyring; `book_write` rides the morning tick after `book_sweep` and the
  5-minute clock LAST; R6's watchdog loop never gets it;
- `routes`: the writer's and the pages' routers answer exactly the 13 rows of
  `buildbook/writer/http.ROUTES` (at I0 each a 503 `not_built_yet`; since I1, B's routes: each
  answers a status its row lists, never `not_built_yet`, never cached);
- `no_run_no_call`: `book_write` with no run, 50 ticks, makes ZERO brain calls on either brain;
- `old_book`: 47ee8fc's real book.json loads with no tour and keeps its bytes;
- `r6_untouched`: R6's sealing files, Privacy rows and `api/book.py` are byte-identical to 47ee8fc
  (M4: the pages files live in their own index), and console.html too.

Negative control (I0's own, L12: B's guard isn't built at I0): the stub job calling the fake brain
once makes `no_run_no_call` fail; a stray route on the writer's router makes `routes` fail.
"""

from __future__ import annotations

import gzip
import hashlib
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "src", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.append(str(_p))
from book_app_fakes import CSRF, book_app, sign_in  # noqa: E402
from r63_fake_brains import claude_like, gemini_like, provider_of, registry  # noqa: E402
from r63_fakes import writer_context  # noqa: E402

import jarvis.api.r6_wiring as r6  # noqa: E402
from jarvis.api import book_pages, book_writer  # noqa: E402
from jarvis.buildbook.model import canonical_bytes, load_book  # noqa: E402
from jarvis.buildbook.writer import http, job, part  # noqa: E402
from jarvis.config import LLMBackend, SessionBackend, Settings  # noqa: E402
from jarvis.llm.base import ChatMessage, Role  # noqa: E402
from jarvis.llm.router import ModelTier  # noqa: E402
from jarvis.llm.write import write_text  # noqa: E402

PART = "contract"
BUILT = True
# 47ee8fc's SHA-256 of the files R6.3 never edits (M4, D11; console.html, D0), under src/jarvis/
UNTOUCHED = dict(
    (f"src/jarvis/{line.split()[1]}", line.split()[0])
    for line in """
9f4c0c68f45e46fe150e65e182f4d2ba1132eb556b3ddee0ba3491e4c85450a2  api/static/console.html
7ebe40dc6928429baaf8ea617e2e13aeb7690f874ed8ed50739a8fe15a86deb4  buildbook/seal_index.py
e87770535b78bd3e6e3845ddac4267232d055ba541841980d9300169efe2ac85  buildbook/seal.py
949354c269f8750488f1662ab6c82dd1b28ee321599563f9a967fa3ec3c3bdbf  buildbook/ports.py
d4345c7c8431fd826ec3e15619a2b1f818fce0bd01e9ce0b533aac67e00a54ff  buildbook/sealer.py
0d9c979d104a180fc9e5a9f838fc00d51ac86e5154dc160d70d378a73b5d3b49  buildbook/seal_notices.py
a7fc7c409ab81af066a905ddf55a2e7fb0fe55a032fe56da3125958a28bd1f27  buildbook/seal_words.py
ddd4fad71ea41c7a7885193fb0722d6180ac85cc0f3a32de92cee7f99a324f73  buildbook/privacy.py
856e2f5276d6cb59f98aa947146a932ed888277acff8682294c0848be809e1fe  api/book.py
""".strip().splitlines()
)
OLD_BOOK = ROOT / "tests" / "fixtures" / "r6_3" / "book-47ee8fc.json.gz"
Check = Callable[[], Any]


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        env="dev",
        llm_backend=LLMBackend.MOCK,
        session_backend=SessionBackend.MEMORY,
        usd_inr_live=False,
    )


def _case(name: str, failures: list[str]) -> dict[str, Any]:
    return {"id": f"{PART}:{name}", "passed": not failures, "failures": failures}


async def _wired() -> list[str]:
    out: list[str] = []
    async for app in book_app(_settings()):
        st = app.state
        if st.book_writer is None or st.book_writer_part is None:
            out.append("the writer is not built through its join")
            break
        st.book_jobs = None
        names = [j.name for j in r6.r6_tick_jobs(app)]
        if names != ["book_seal", "book_sweep", "book_write"]:
            out.append(f"the morning tick's R6 jobs are {names}")
        added = [j.name for j in getattr(st, "clock_jobs_added", None) or []]
        if "book_write" not in added:
            out.append("book_write is not on the 5-minute clock")
    return out


def _stray_routes() -> list[str]:
    want = {(m, p) for m, p, *_ in http.ROUTES}
    got: set[tuple[str, str]] = set()
    for router in (book_writer.router, book_pages.router):
        for r in router.routes:
            got |= {(m, r.path) for m in getattr(r, "methods", ())}  # type: ignore[attr-defined]
    return [f"a route outside the contract: {m} {p}" for m, p in sorted(got - want)] + [
        f"a contract route missing: {m} {p}" for m, p in sorted(want - got)
    ]


async def _routes() -> list[str]:
    out = _stray_routes()
    async for app in book_app(_settings()):
        async with sign_in(app) as c:
            for method, path, _part, _req, _reply, codes, _gate in http.ROUTES:
                url = path.replace("{nn}", "01").replace("{page_id}", "pg_card_c16")
                body = None if method == "GET" else {}
                r = await c.request(method, url, headers=CSRF, json=body)
                built = r.status_code in (200, *codes) and r.json().get("error") != http.NOT_BUILT
                if not built or r.headers.get("cache-control") != "no-store":
                    out.append(f"{method} {path} answered {r.status_code}")  # I1: B's, not I0's 503
    return out


async def _no_run_no_call() -> list[str]:
    claude, gemini = claude_like(), gemini_like()
    built = part.build(writer_context(brains=registry(claude, gemini)))
    for _ in range(50):
        await built.job.run((built.job._ctx.uid,))  # type: ignore[attr-defined]
    calls = len(provider_of(claude).calls) + len(provider_of(gemini).calls)
    return [f"{calls} brain call(s) with no run"] if calls else []


def _old_book() -> list[str]:
    data = gzip.decompress(OLD_BOOK.read_bytes())
    book = load_book(data)
    if book.tour is not None or canonical_bytes(book) != data:
        return ["47ee8fc's book.json does not load unchanged"]
    return []


def _untouched() -> list[str]:
    return [
        f"{rel} was edited"
        for rel, sha in UNTOUCHED.items()
        if hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() != sha
    ]


async def cases() -> list[dict[str, Any]]:
    return [
        _case("wired", await _wired()),
        _case("routes", await _routes()),
        _case("no_run_no_call", await _no_run_no_call()),
        _case("old_book", _old_book()),
        _case("r6_untouched", _untouched()),
    ]


async def _one_call(self: Any, owners: Any) -> dict[str, int]:
    """The control's job: a stub that calls the brain once with no run (it must be caught)."""
    router = self._ctx.brains.router_for("anthropic")
    await write_text(
        router,
        tier=ModelTier.BALANCED,
        system="s",
        system_dynamic=None,
        messages=[ChatMessage(role=Role.USER, content="x")],
        max_tokens=10,
        timeout_s=5.0,
    )
    return {}


async def control() -> dict[str, Any]:
    real_run = job.BookWriteJob.run
    job.BookWriteJob.run = _one_call  # type: ignore[method-assign]
    try:
        called = await _no_run_no_call()
    finally:
        job.BookWriteJob.run = real_run  # type: ignore[method-assign]

    async def stray() -> None:
        return None

    book_writer.router.add_api_route("/stray", stray, methods=["GET"])
    try:
        strayed = _stray_routes()
    finally:
        book_writer.router.routes.pop()
    failed = [n for n, f in (("no_run_no_call", called), ("routes", strayed)) if not f]
    return {
        "name": "the stub job calls the brain once; a stray route on the writer's router",
        "suite_failed": not failed,
        "failed_cases": [f"{PART}:no_run_no_call", f"{PART}:routes"] if not failed else [],
    }

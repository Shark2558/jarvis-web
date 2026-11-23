# tests/r63_fake_server.py -- R6.3 I0 seam 12 (docs/plans/r6-3-book-content.md "The HTTP contract",
# D6, D7, D12, D14, H2): the writer's and the full book's 13 routes answered from an in-memory fake,
# in exactly `buildbook/writer/http.py`'s models, for part C's console while B builds the real ones.
# Imported bare (`from r63_fake_server import ...`).
#
# - `FakeWriter`: the state (both brains offered, no pick, no run, the trial's 5 pages, a pages
#   index of the fixture, the 80 % storage line off unless `storage_warn`). Every grant needs the
#   typed YES on the terms shown: the first pick, a raised cap, a paid or training brain and
#   "update by itself" answer 422 `yes_needed` {terms_id, words} until resent with `typed: "YES"`
#   and that `terms_id`; lowering saves at once. The trial, the first write and Update take
#   `{typed: "YES", estimate_id}` ("yes", "Yes", "YES!" are 422 `not_yes`; another id is 409
#   `estimate_changed`). `step` advances the run one page. Rupees only.
# - `fake_routes(state)`: an APIRouter of the 13 rows; `fake_app()`: the real app (mock brain,
#   token mode) with these routes AHEAD of I0's stubs. The R6 routes (status, open, sections,
#   settings) stay the browser tests' `book_mocks.FakeBook` page routes.
# - `serve(token)`: this server in a child process for a browser test module: (url, stop).
# The fake does NOT check console-only or the primary owner: the wired app at I1 tests those.
from __future__ import annotations

import hashlib
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Header
from fastapi.responses import JSONResponse

from jarvis.buildbook.facts_model import PARTS
from jarvis.buildbook.writer import http
from jarvis.buildbook.writer.model import (
    HEADINGS,
    NOT_WRITTEN,
    SECTION_IDS,
    TRIAL_PAGES,
    Confirmed,
    Page,
    PageMeta,
    PageSection,
    Pick,
    about_inr,
    is_yes,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from r63_fakes import FIXTURE_FACTS, NOW, RELEASE  # noqa: E402

NO_STORE = {"Cache-Control": "no-store"}
BOOK = Header(default=None)  # X-Jarvis-Book
TRIAL_ESTIMATE = "we_" + "1" * 12
FIRST_ESTIMATE = "we_" + "2" * 12
UPDATE_ESTIMATE = "we_" + "3" * 12
OWNER_BOOK = "bk-token-not-a-secret-0123456789abcdef"  # book_mocks.TOKEN: an owner session
GUEST_BOOK = "bk-guest-not-a-secret-0123456789abcdef"


def _ok(model: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json"), status_code=status, headers=NO_STORE)


def _no(status: int, code: str, words: str) -> JSONResponse:
    return JSONResponse({"error": code, "detail": words}, status_code=status, headers=NO_STORE)


def _meta(brain: str, label: str, model: str, inr: float) -> PageMeta:
    return PageMeta(
        brain=brain,
        brain_label=label,
        model=model,
        provider=brain,
        release=RELEASE.id,
        version=RELEASE.version,
        written_at=NOW.isoformat(),
        attempt=1,
        tokens_in=16_000,
        tokens_out=3_000,
        inr=inr,
    )


def page_of(page_id: str, meta: PageMeta | None) -> Page:
    """A page in the six sections: written (with meta) or the generator's text."""
    entry = FIXTURE_FACTS.page(page_id)
    title = entry.title if entry else page_id
    text = "The demo router picks one tier for each request." if meta else NOT_WRITTEN
    sections = tuple(
        PageSection(
            id=s, heading=HEADINGS[s], text=text, refs=(entry.refs if entry and s == "code" else ())
        )
        for s in SECTION_IDS
    )
    kind = entry.kind if entry else "card"
    part = entry.part if entry else "parts"
    return Page(id=page_id, kind=kind, title=title, part=part, sections=sections, meta=meta)


CLAUDE_META = _meta("anthropic", "Claude", "claude-sonnet-5-5", 7.6)


@dataclass
class FakeWriter:
    pick: Pick = field(default_factory=Pick)
    run: http.RunView = field(default_factory=http.RunView)
    trial: http.TrialView = field(default_factory=http.TrialView)
    update_ready: bool = False
    storage_warn: bool = False
    terms: dict[str, Any] = field(default_factory=dict)  # terms_id -> the pick it grants
    calls: list[str] = field(default_factory=list)

    def view(self) -> http.WriterView:
        brains = (
            http.BrainOffer(
                id="anthropic",
                label="Claude",
                trains_on_content=False,
                model_name="claude-sonnet-5-5",
                offered=True,
            ),
            http.BrainOffer(
                id="gemini",
                label="Gemini (free)",
                trains_on_content=True,
                model_name="gemini-3.8-flash",
                offered=True,
            ),
        )
        ready = None
        if self.update_ready:
            ready = {"release": RELEASE.id, "estimate_id": UPDATE_ESTIMATE, "inr_mid": 300}
        return http.WriterView.model_validate(
            {
                "on": True,
                "brains": [b.model_dump() for b in brains],
                "trial": self.trial.model_dump(),
                "pick": self.pick.model_dump(),
                "run": self.run.model_dump(),
                "update_ready": ready,
                "month": {
                    "book_inr": round(self.trial.inr, 2),
                    "limit_inr": 3000.0,
                    "line_inr": 2400.0,
                },
                "storage": {
                    "used_mib": 49.1 if self.storage_warn else 28.6,
                    "pages_mib": 0.5,
                    "limit_mib": 60.0,
                    "warn": self.storage_warn,
                },
            }
        )

    def estimate(self, run: str) -> http.Estimate | None:
        table = {
            "trial": (TRIAL_ESTIMATE, 5, 26, 38, 52, 100, 6, 10),
            "first": (FIRST_ESTIMATE, 152, 779, 1144, 1588, 1500, 96, 156),
            "update": (UPDATE_ESTIMATE, 40, 128, 301, 627, 500, 20, 40),
        }
        if run not in table:
            return None
        eid, pages, low, mid, high, cap, m_lo, m_hi = table[run]
        return http.Estimate(
            id=eid,
            run=run,
            brain=self.pick.brain or "anthropic",
            pages=pages,  # type: ignore[arg-type]
            low=low,
            mid=about_inr(mid),
            high=high,
            hold=11.84,
            cap=cap,
            minutes_low=m_lo,
            minutes_high=m_hi,
            gst_note="Your Anthropic bill may add 18 % GST.",
            sent_to=(
                "Claude (Anthropic) and Gemini (free, Google): JARVIS's "
                "public code and its facts only.",
            ),
        )


def _grants_more(new: http.PickIn, had: Confirmed, paid: set[str]) -> bool:
    caps, old = new.caps.model_dump(), had.caps.model_dump()
    raised = any(caps[k] > old[k] for k in caps)
    switched = new.brain != had.brain and (new.brain in paid or new.brain == "gemini")
    return raised or switched or (new.auto_update and not had.auto_update)


def _terms(pick: http.PickIn) -> str:
    raw = pick.model_dump_json(exclude={"typed", "terms_id"}).encode()
    return "wt_" + hashlib.sha256(raw).hexdigest()[:12]


def _words(pick: http.PickIn) -> tuple[str, ...]:
    c = pick.caps
    out = [
        f"Up to Rs {c.first:,} for the first full write, Rs {c.release:,} a release and "
        f"Rs {c.month:,} a month, and never past {c.limit_pct} % of your monthly limit."
    ]
    if pick.auto_update:
        out.append(
            f"Up to Rs {c.release:,} a release and Rs {c.month:,} a month (your caps), by "
            "itself after each deploy, with no question asked."
        )
    return tuple(out)


def _run_in(state: FakeWriter, body: http.RunIn, want: str, kind: str, total: int) -> JSONResponse:
    if not is_yes(body.typed):
        return _no(422, "not_yes", "Type YES in capitals to go ahead.")
    if body.estimate_id != want:
        return _no(409, "estimate_changed", "The estimate changed. Look at it again first.")
    if state.run.state in ("queued", "running"):
        return _no(409, "running", "A run is going on already.")
    cap = {"trial": 100, "first": state.pick.caps.first, "update": state.pick.caps.release}[kind]
    state.run = http.RunView(kind=kind, state="running", total=total, cap_inr=cap)  # type: ignore[arg-type]
    state.calls.append(kind)
    return _ok(state.run)


def fake_routes(state: FakeWriter) -> APIRouter:  # noqa: C901 - one table of routes
    r = APIRouter()
    w = http.WRITER_PREFIX

    @r.get(w)
    async def view() -> JSONResponse:
        return _ok(state.view())

    @r.get(f"{w}/estimate")
    async def estimate(run: str = "trial") -> JSONResponse:
        got = state.estimate(run)
        return _ok(got) if got else _no(422, "bad_run", "That isn't a run.")

    @r.post(f"{w}/trial")
    async def trial(body: http.TrialIn) -> JSONResponse:
        out = _run_in(state, http.RunIn(**body.model_dump()), TRIAL_ESTIMATE, "trial", 10)
        if out.status_code == 200:
            state.trial = http.TrialView(state="running", total=10)
        return out

    @r.put(f"{w}/pick")
    async def pick(body: http.PickIn) -> JSONResponse:
        if body.brain not in ("anthropic", "gemini"):
            return _no(422, "unknown_brain", "That brain isn't set up on this server.")
        had, tid = state.pick.confirmed, _terms(body)
        if _grants_more(body, had, {"anthropic"}):
            if body.typed is None:
                state.terms[tid] = body
                need = http.YesNeeded(
                    detail="This grants spending: type YES to confirm.",
                    terms_id=tid,
                    words=_words(body),
                )
                return _ok(need, 422)
            if not is_yes(body.typed):
                return _no(422, "not_yes", "Type YES in capitals to go ahead.")
            if body.terms_id != tid or tid not in state.terms:
                return _no(409, "terms_changed", "The terms changed. Look at them again first.")
        granted = Confirmed(
            brain=body.brain,
            caps=body.caps,
            auto_update=body.auto_update,
            terms_id=tid,
            at=NOW.isoformat(),
        )
        state.pick = Pick(
            brain=body.brain,
            caps=body.caps,
            auto_update=body.auto_update,
            picked_at=NOW.isoformat(),
            confirmed=granted,
        )
        return _ok(state.pick)

    @r.post(f"{w}/first")
    async def first(body: http.RunIn) -> JSONResponse:
        if state.pick.brain is None:
            return _no(409, "pick_needed", "Pick the writer and its caps first.")
        return _run_in(state, body, FIRST_ESTIMATE, "first", 152)

    @r.post(f"{w}/update")
    async def update(body: http.RunIn) -> JSONResponse:
        if not state.update_ready:
            return _no(409, "nothing_to_update", "No page changed in this release.")
        return _run_in(state, body, UPDATE_ESTIMATE, "update", 40)

    @r.post(f"{w}/stop")
    async def stop() -> JSONResponse:
        state.run = state.run.model_copy(update={"state": "stopped", "why": "You stopped it."})
        return _ok(state.run)

    @r.post(f"{w}/step")
    async def step() -> JSONResponse:
        if state.run.state != "running":
            return _ok(state.run)
        done = min(state.run.total, state.run.done + 1)
        st = "done" if done == state.run.total else "running"
        state.run = state.run.model_copy(update={"done": done, "state": st, "inr": done * 7.6})
        if state.run.kind == "trial":
            state.trial = http.TrialView(
                state=st,
                done=done,
                total=10,
                inr=round(done * 7.6, 2),
                results=tuple(range(1, done + 1)),
            )
        return _ok(state.run)

    @r.get(f"{w}/trial/pages")
    async def trial_pages() -> JSONResponse:
        rows = []
        for nn in state.trial.results:
            brain = "anthropic" if nn <= 5 else "gemini"
            rows.append(
                http.TrialRow(
                    nn=nn,
                    page=TRIAL_PAGES[(nn - 1) % 5],
                    brain=brain,
                    state="first" if nn != 4 else "redrafted",
                    inr=7.6 if brain == "anthropic" else 0.0,
                    seconds=38.0,
                )
            )
        return _ok(http.TrialPages(rows=tuple(rows)))

    @r.get(f"{w}/trial/pages/{{nn}}")
    async def trial_page(nn: int) -> JSONResponse:
        if nn not in state.trial.results:
            return _no(404, "no_page", "That trial page isn't there.")
        claude = nn <= 5
        meta = (
            _meta("anthropic", "Claude", "claude-sonnet-5-5", 7.6)
            if claude
            else _meta("gemini", "Gemini (free)", "gemini-3.8-flash", 0.0)
        )
        return _ok(http.TrialPageView(nn=nn, page=page_of(TRIAL_PAGES[(nn - 1) % 5], meta)))

    @r.delete(f"{w}/trial")
    async def drop_trial() -> JSONResponse:
        n, state.trial = len(state.trial.results), http.TrialView()
        return _ok(http.Deleted(deleted=n))

    def _session(book: str | None) -> JSONResponse | None:
        if book == GUEST_BOOK:
            return _no(403, "owner_only", "The full book is the owner's.")
        if book != OWNER_BOOK:
            return _no(401, "session_gone", "Open the build book again.")
        return None

    @r.get(http.PAGES_PREFIX)
    async def pages(x_jarvis_book: str | None = BOOK) -> JSONResponse:
        if (no := _session(x_jarvis_book)) is not None:
            return no
        written = {"pg_card_c01"}
        parts = []
        for pid, title in PARTS:
            rows = [
                http.PageRow(
                    id=p.id,
                    kind=p.kind,
                    title=p.title,
                    written=CLAUDE_META if p.id in written else None,
                )
                for p in FIXTURE_FACTS.pages
                if p.part == pid
            ]
            if rows:
                parts.append(
                    http.BookPart(
                        id=pid,
                        title=title,
                        chapters=(http.Chapter(id=pid, title=title, pages=tuple(rows)),),
                    )
                )
        view = http.PagesView(
            release=RELEASE.id, parts=tuple(parts), limitations=http.Shown(shown=80, total=112)
        )
        return _ok(view)

    @r.get(f"{http.PAGES_PREFIX}/{{page_id}}")
    async def one_page(
        page_id: str, x_jarvis_book: str | None = Header(default=None)
    ) -> JSONResponse:
        if (no := _session(x_jarvis_book)) is not None:
            return no
        if FIXTURE_FACTS.page(page_id) is None:
            return _no(404, "no_page", "That page isn't in this release.")
        meta = (
            _meta("anthropic", "Claude", "claude-sonnet-5-5", 7.6)
            if page_id == "pg_card_c01"
            else None
        )
        return _ok(page_of(page_id, meta))

    return r


def fake_app(state: FakeWriter | None = None, **app_kw: Any) -> FastAPI:
    """The real app (mock brain) with the writer's and the pages' fake routes before I0's stubs."""
    from jarvis.api import create_app
    from jarvis.llm.mock_provider import MockProvider

    app = create_app(provider=MockProvider(), **app_kw)
    st = state or FakeWriter()
    app.state.r63_fake = st  # type: ignore[attr-defined]
    app.router.routes[:0] = list(fake_routes(st).routes)
    return app


def serve(token: str) -> tuple[str, Callable[[], None]]:
    """This server in a child process for a browser test module: (url, stop)."""
    import os
    import socket
    import subprocess
    import time
    import urllib.request

    root = Path(__file__).resolve().parents[1]
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    env = {
        **os.environ,
        "PYTHONPATH": str(root / "src"),
        "JARVIS_ENV": "dev",
        "JARVIS_LLM_BACKEND": "mock",
        "JARVIS_SESSION_BACKEND": "memory",
        "JARVIS_AUTH_MODE": "token",
        "JARVIS_API_TOKEN": token,
        "JARVIS_LOG_LEVEL": "WARNING",
        "JARVIS_USD_INR_LIVE": "0",
        "JARVIS_RATE_LIMIT_PER_MINUTE": "6000",
    }
    env.pop("JARVIS_ANTHROPIC_API_KEY", None)
    env.pop("JARVIS_GEMINI_API_KEY", None)
    proc = subprocess.Popen(
        [sys.executable, str(root / "tests" / "r63_fake_server.py"), str(port)],
        cwd=root,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("the R6.3 fake server exited early")
        try:
            with urllib.request.urlopen(url + "/health", timeout=1) as resp:
                if resp.status == 200:
                    break
        except OSError:
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError("the R6.3 fake server did not become healthy")

    def stop() -> None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    return url, stop


__all__ = ["GUEST_BOOK", "OWNER_BOOK", "FakeWriter", "fake_app", "fake_routes", "page_of", "serve"]


def main(argv: list[str]) -> int:
    import uvicorn

    port = int(argv[1]) if len(argv) > 1 else 8767
    uvicorn.run(fake_app(), host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

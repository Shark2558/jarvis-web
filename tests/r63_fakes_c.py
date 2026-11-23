# tests/r63_fakes_c.py -- R6.3 Part C (docs/plans/r6-3-book-content.md D6, D7, D11, D12, D14):
# I0's fake server (tests/r63_fake_server.py) with what the console's tests also need, in the
# contract's own models (buildbook/writer/http.py). Imported bare (`from r63_fakes_c import ...`);
# no Playwright here.
#
# - `FakeWriterC`: I0's `FakeWriter` plus the writer OFF (`off = "no_key"`: `{on: false, why}`),
#   stale estimates handed out first (`stale = {"trial": 1}`: the next estimate has another id, so
#   the run's POST is 409 `estimate_changed` and the console must ask again), a refusal for one
#   route (`refuse = {"first": (409, "already_written", words)}`), and C74 (`new_card`: a card the
#   index gains at the next release, row 380 "grows").
# - The full book: parts -> chapters (a card under its module's chapter) -> pages, one written page
#   (`pg_card_c01`, made-up demo words in the six sections), one changed page waiting for Update,
#   the rest the generator's text; an older kept release (`OLDER`) reads with nothing written.
#   The trial's side by side has a redraft and a refusal with their checks.
# - `/v1/test/r63-c` (test only): POST sets or resets the state; GET answers what the fake saw.
# - `serve_c(token)`: this app in a child process for a browser test module: (url, stop); and the
#   browser tests' helpers (`set_state`, `seen`, `route_c`, `until`).
# Made-up demo data only: no person, no place, no key.
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Header, Request
from fastapi.responses import JSONResponse

from jarvis.buildbook.facts_model import PARTS
from jarvis.buildbook.writer import http
from jarvis.buildbook.writer.model import (
    HEADINGS,
    NOT_WRITTEN,
    SECTION_IDS,
    TRIAL_PAGES,
    Page,
    PageSection,
    Pick,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from r63_fake_server import (  # noqa: E402
    CLAUDE_META,
    GUEST_BOOK,
    OWNER_BOOK,
    FakeWriter,
    fake_app,
)
from r63_fakes import FIXTURE_FACTS, RELEASE  # noqa: E402

NO_STORE = {"Cache-Control": "no-store"}
CONTROL = "/v1/test/r63-c"
STALE_ESTIMATE = "we_" + "9" * 12
WRITTEN, CHANGED = "pg_card_c01", "pg_card_c02"
NEW_CARD = "pg_card_c74"
OLDER = ("aebff3a", "9b97eab")  # book_mocks.SEALED's older kept releases: nothing written there
LIMITATIONS = http.Shown(shown=80, total=112)  # G4: "+32 more in the full book"
CHAPTER_TITLES = {"demo": "The demo"}
WORDS: dict[str, str] = {
    "plain": "The demo router picks one tier for each request, so a quick question stays cheap.\n\n"
    "It never changes tier halfway through an answer.",
    "example": "A made-up household asks for a dentist reminder. The router picks the fast tier "
    "and the reply comes back in 3 tries at most.",
    "how": "- The request arrives at the router.\n- The router reads the setting demo_limit.\n"
    "- One tier answers; the store keeps the note for 30 days.",
    "costs": "Nothing by itself: each answer is billed by the brain that wrote it.",
    "fails": "When no brain answers, the router says so plainly and nothing is retried.",
    "code": "The router and its store.",
}


@dataclass
class FakeWriterC(FakeWriter):
    off: str | None = None  # "no_key" | "no_ai" | "no_brain": GET /v1/book/writer {on: false}
    stale: dict[str, int] = field(default_factory=dict)  # run -> stale estimates still to hand out
    refuse: dict[str, tuple[int, str, str]] = field(default_factory=dict)  # route -> its refusal
    new_card: bool = False
    asked: list[str] = field(
        default_factory=list
    )  # "METHOD path?query" the writer/pages routes saw

    def view(self) -> http.WriterView:
        if self.off:
            return http.WriterView.model_validate({"on": False, "why": self.off})
        return super().view()

    def estimate(self, run: str) -> http.Estimate | None:
        got = super().estimate(run)
        if got is not None and self.stale.get(run, 0) > 0:
            self.stale[run] -= 1
            return got.model_copy(update={"id": STALE_ESTIMATE})
        return got

    def reset(self) -> None:
        fresh = FakeWriterC()
        for f in fields(fresh):
            setattr(self, f.name, getattr(fresh, f.name))


def _ok(model: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json"), status_code=status, headers=NO_STORE)


def _no(status: int, code: str, words: str) -> JSONResponse:
    return JSONResponse({"error": code, "detail": words}, status_code=status, headers=NO_STORE)


def written_page(page_id: str, *, written: bool, changed: bool = False) -> Page:
    """A page in its six sections: the made-up demo words with a meta, or the generator's text."""
    entry = FIXTURE_FACTS.page(page_id)
    title = entry.title if entry else "A new card"
    refs = entry.refs if entry else ("src/jarvis/demo/new.py",)
    sections = tuple(
        PageSection(
            id=s,
            heading=HEADINGS[s],
            text=WORDS[s] if written else f"{title}: {NOT_WRITTEN.lower()}.",
            refs=refs if s == "code" else (),
        )
        for s in SECTION_IDS
    )
    return Page(
        id=page_id,
        kind=entry.kind if entry else "card",
        title=title,
        part=entry.part if entry else "parts",
        chapter=entry.chapter if entry else "demo",
        sections=sections,
        meta=CLAUDE_META if written else None,
        changed=changed,
    )


def pages_view(state: FakeWriterC, release: str) -> http.PagesView:
    current = release not in OLDER
    entries = list(FIXTURE_FACTS.pages)
    ids = [p.id for p in entries] + ([NEW_CARD] if state.new_card and current else [])
    parts = []
    for pid, title in PARTS:
        chapters: dict[str, list[http.PageRow]] = {}
        for page_id in ids:
            page = written_page(page_id, written=current and page_id == WRITTEN)
            if page.part != pid:
                continue
            row = http.PageRow(
                id=page.id,
                kind=page.kind,
                title=page.title,
                written=page.meta,
                changed=current and page_id == CHANGED,
            )
            chapters.setdefault(page.chapter or pid, []).append(row)
        if chapters:
            parts.append(
                http.BookPart(
                    id=pid,
                    title=title,
                    chapters=tuple(
                        http.Chapter(
                            id=cid, title=CHAPTER_TITLES.get(cid, title), pages=tuple(rows)
                        )
                        for cid, rows in chapters.items()
                    ),
                )
            )
    return http.PagesView(release=release, parts=tuple(parts), limitations=LIMITATIONS)


def trial_rows(state: FakeWriterC) -> http.TrialPages:
    rows = []
    for nn in state.trial.results:
        claude = nn <= 5
        page = TRIAL_PAGES[(nn - 1) % 5]
        how: tuple[str, tuple[Any, ...]] = ("first", ())
        if nn == 4:
            how = ("redrafted", ("numbers",))
        if nn == 9:
            how = ("refused", ("refs", "planned"))
        rows.append(
            http.TrialRow(
                nn=nn,
                page=page,
                brain="anthropic" if claude else "gemini",
                state=how[0],  # type: ignore[arg-type]
                checks=how[1],
                inr=7.6 if claude else 0.0,
                seconds=38.0 if claude else 41.5,
            )
        )
    return http.TrialPages(rows=tuple(rows))


def _session(book: str | None) -> JSONResponse | None:
    if book == GUEST_BOOK:
        return _no(403, "owner_only", "The full book is the owner's.")
    if book != OWNER_BOOK:
        return _no(401, "session_gone", "Open the build book again.")
    return None


def _release_of(release: str | None) -> str:
    return release if release and len(release) == 7 and release.isalnum() else RELEASE.id


def c_routes(state: FakeWriterC) -> APIRouter:  # noqa: C901 - one table of routes
    """C's routes, ahead of I0's fake ones: they shadow the rows they answer differently."""
    r = APIRouter()
    w = http.WRITER_PREFIX

    @r.get(http.PAGES_PREFIX)
    async def index(release: str | None = None, x_jarvis_book: str | None = Header(None)) -> Any:
        if (no := _session(x_jarvis_book)) is not None:
            return no
        return _ok(pages_view(state, _release_of(release)))

    @r.get(f"{http.PAGES_PREFIX}/{{page_id}}")
    async def one(
        page_id: str, release: str | None = None, x_jarvis_book: str | None = Header(None)
    ) -> Any:
        if (no := _session(x_jarvis_book)) is not None:
            return no
        rid = _release_of(release)
        known = FIXTURE_FACTS.page(page_id) is not None or (page_id == NEW_CARD and state.new_card)
        if not known:
            return _no(404, "no_page", "That page isn't in this release.")
        current = rid not in OLDER
        page = written_page(page_id, written=current and page_id == WRITTEN)
        return _ok(page.model_copy(update={"changed": current and page_id == CHANGED}))

    @r.get(f"{w}/trial/pages")
    async def side_by_side() -> Any:
        return _ok(trial_rows(state))

    return r


def control_routes(state: FakeWriterC) -> APIRouter:
    r = APIRouter()

    @r.post(CONTROL)
    async def set_state(request: Request) -> Any:
        body = await request.json()
        if body.pop("reset", False):
            state.reset()
        if body.pop("trial_done", False):
            state.trial = http.TrialView(
                state="done", done=10, total=10, inr=38.0, results=tuple(range(1, 11))
            )
            state.run = http.RunView(kind="trial", state="done", done=10, total=10, inr=38.0)
        models = {"pick": Pick, "run": http.RunView, "trial": http.TrialView}
        for key, value in body.items():
            if key == "refuse":
                value = {k: tuple(v) for k, v in value.items()}
            if key in models:
                value = models[key].model_validate(value)
            setattr(state, key, value)
        return {"ok": True}

    @r.get(CONTROL)
    async def seen() -> Any:
        return {
            "calls": state.calls,
            "asked": state.asked,
            "pick": state.pick.model_dump(mode="json"),
            "run": state.run.model_dump(mode="json"),
            "trial": state.trial.model_dump(mode="json"),
        }

    return r


def c_app(state: FakeWriterC | None = None) -> FastAPI:
    st = state or FakeWriterC()
    app = fake_app(st)
    app.router.routes[:0] = [*control_routes(st).routes, *c_routes(st).routes]

    @app.middleware("http")
    async def seen_and_refused(request: Request, call_next: Any) -> Any:
        """Every writer and pages request is noted; a refusal the test set answers first."""
        path = request.url.path
        if path.startswith(("/v1/book/writer", "/v1/book/pages")):
            st.asked.append(f"{request.method} {path}?{request.url.query}")
            name = path.removeprefix(http.WRITER_PREFIX + "/")
            if path.startswith(http.WRITER_PREFIX + "/") and name in st.refuse:
                code, err, words = st.refuse[name]
                return _no(code, err, words)
        return await call_next(request)

    return app


def serve_c(token: str) -> tuple[str, Callable[[], None]]:
    """C's server in a child process for a browser test module: (url, stop)."""
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
    for key in ("JARVIS_ANTHROPIC_API_KEY", "JARVIS_GEMINI_API_KEY"):
        env.pop(key, None)
    proc = subprocess.Popen(
        [sys.executable, str(root / "tests" / "r63_fakes_c.py"), str(port)],
        cwd=root,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("C's fake server exited early")
        try:
            with urllib.request.urlopen(url + "/health", timeout=1) as resp:
                if resp.status == 200:
                    break
        except OSError:
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError("C's fake server did not become healthy")

    def stop() -> None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    return url, stop


# ---- for the browser tests (duck-typed Playwright objects: nothing imported here) --------------
def set_state(url: str, **state: Any) -> None:
    """POST the test-only state route: `reset=True` first, then any FakeWriterC field."""
    req = urllib.request.Request(
        url + CONTROL,
        data=json.dumps(state).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        assert r.status == 200


def seen(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url + CONTROL, timeout=5) as r:
        got: dict[str, Any] = json.loads(r.read())
        return got


def route_c(page: Any) -> None:
    """After `book_mocks.FakeBook(page)`: the writer's and the full book's routes go on to C's
    fake server (Playwright tries the routes registered last first)."""
    for pattern in (
        "**/v1/book/writer",
        "**/v1/book/writer/**",
        "**/v1/book/pages",
        "**/v1/book/pages?*",
        "**/v1/book/pages/**",
    ):
        page.route(pattern, lambda route: route.continue_())


def until(page: Any, check: Callable[[], bool], what: str, timeout_s: float = 20.0) -> None:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if check():
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for {what}")


__all__ = [
    "CHANGED",
    "CONTROL",
    "GUEST_BOOK",
    "NEW_CARD",
    "OLDER",
    "OWNER_BOOK",
    "STALE_ESTIMATE",
    "WRITTEN",
    "FakeWriterC",
    "c_app",
    "pages_view",
    "route_c",
    "seen",
    "serve_c",
    "set_state",
    "until",
    "written_page",
]


def rupee_words(words: Callable[[Any], tuple[str, ...]]) -> Callable[[Any], tuple[str, ...]]:
    """I0's fake writes a grant's words with "Rs "; part B's real words (writer/texts.py, through
    texts.inr) carry the rupee sign, which the console shows as sent. The browser's server uses
    this, so the dialogs and their pictures read as the owner will see them."""
    return lambda pick: tuple(w.replace("Rs ", "₹") for w in words(pick))


def main(argv: list[str]) -> int:
    import r63_fake_server
    import uvicorn

    r63_fake_server._words = rupee_words(r63_fake_server._words)  # this child process only
    port = int(argv[1]) if len(argv) > 1 else 8768
    uvicorn.run(c_app(), host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

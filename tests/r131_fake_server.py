# tests/r131_fake_server.py -- R13.1 I0 (docs/plans/r13-1-try-on.md "The HTTP contract", seam 15):
# every route of `jarvis.wardrobe.tryon.http.ROUTES`, answered from the fakes (`r131_fakes`: R13's
# seeded pilot with photos, a FIXED clock), each reply validated by its model, so Part D's console
# and Part B's stage run end to end before A and C exist. At I1 D's browser tests move to the
# wired app. Nothing here calls Google: "See it on me" (`r131_fake_seeme`, D22: a garment he is
# thinking of buying) answers I0's made-up picture.
#
#   fake_routes(store, clock) -> APIRouter   the 27 routes (owner-only like the real ones; the
#                                            console-only rule is NOT simulated here: the wired app
#                                            at I1 tests it) and Refusal {"error", "detail"}
#   stage_routes() -> APIRouter              GET /r131/stage (a bare page for B's engine, the
#                                            console's CSP) and GET /r131/fixtures/{name}.mjs
#   fake_app(...) -> FastAPI                 the real console app (mock brain) with R13's fake
#                                            routes and these AHEAD of the parts' own
#   serve(token) -> (url, stop)              it in a child process, for a browser test module
#   python tests/r131_fake_server.py <port>  serve it (uvicorn)
#
# Not a test module (pytest does not collect it). Imported bare (`from r131_fake_server import`).
from __future__ import annotations

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from r13_fake_server import fake_routes as r13_routes
from r131_fake_seeme import READY, seeme_routes
from r131_fakes import IST, UID, VIEW_OF, FixedClock, MemoryWardrobeStore, T, seeded

from jarvis.api.auth import require_auth
from jarvis.api.console import CONSOLE_CSP
from jarvis.wardrobe.model import Piece, WardrobeView
from jarvis.wardrobe.tryon import http
from jarvis.wardrobe.tryon import model as m

NO_STORE = {"Cache-Control": "no-store"}
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "r13_1"
RACE_PLAN = "op_0000d20a"  # a confirm of this plan meets D20's race (A's review A-1 F1)
LOCKED_OUT = "{the} is in the laundry: it can't be locked into this plan."  # R13's words
LOOK_SLOTS = (
    ("top", T.striped),
    ("bottom", T.trousers),
    ("outer", T.blazer),
    ("shoes", T.shoes[0]),
    ("belt", T.belt),
    ("watch", T.watch),
    ("base", T.vest),
)


def _ok(model: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json"), status_code=status, headers=NO_STORE)


def _no(status: int, code: str, words: str) -> JSONResponse:
    body = http.Refusal(error=code, detail=words)
    return JSONResponse(body.model_dump(), status_code=status, headers=NO_STORE)


@dataclass
class FakeTryon:
    """What the fake keeps in page memory: never on disk."""

    body: http.BodyVersions = field(default_factory=http.BodyVersions)
    assets: dict[str, http.AssetChoice] = field(default_factory=dict)
    saved: dict[str, http.SavedView] = field(default_factory=dict)
    refuse: str | None = None  # `outfit_plan`'s own refusal of every confirm (D20's race)


def _race(view: WardrobeView, b: http.ConfirmIn) -> str:
    """R13's words for the look's outer layer (else its first piece) gone to the laundry."""
    s = next((x for x in b.slots if x.slot == "outer"), b.slots[0])
    return LOCKED_OUT.format(the="The " + _words(view.pieces[s.piece]))


def _readiness(p: Piece) -> str:
    return m.READY if p.eligible else m.DRAFT_WORDS.get(p.state, "Draft")


def _words(p: Piece) -> str:
    return " ".join(w for w in ((p.colour or "").replace("_", " "), p.type.replace("_", " ")) if w)


def _slot_of(p: Piece) -> str | None:
    t = m.template_of(p.type)
    if t is not None:
        return m.TEMPLATE_SLOT[t]
    return "base" if p.category == "base" and p.type != "sock" else None


def _options(view: WardrobeView, slot: str) -> tuple[http.LookOption, ...]:
    found = [p for p in view.active() if not p.private and _slot_of(p) == slot]
    return tuple(
        http.LookOption(
            piece=p.id,
            words=_words(p),
            readiness=_readiness(p),
            eligible=p.eligible,
            photo=p.photos[0] if p.photos else None,
            template=m.template_of(p.type),
        )
        for p in found[: m.OPTIONS_MAX]
    )


def look_slot(view: WardrobeView, slot: str, pid: str, *, private: bool = False) -> http.LookSlot:
    p = view.pieces[pid]
    if p.private:  # covered only: nothing that names it (D6)
        return http.LookSlot(
            slot=slot,
            piece=pid if private else None,
            private=True,
            words=m.COVERED,
            readiness=_readiness(p),
            eligible=p.eligible,
        )
    t = m.template_of(p.type)
    views = tuple(VIEW_OF[x] for x in p.photos if x in VIEW_OF)
    detail = next((x for x in p.photos if VIEW_OF.get(x) == "detail"), None)
    missing = tuple(v for v in m.useful_views(p.type) if v not in views)
    approx: tuple[m.Approx, ...] = ("template", "texture") if p.photos else ("template",)
    return http.LookSlot(
        slot=slot,
        piece=pid,
        words=_words(p),
        template=t,
        variants=m.VARIANTS.get(t, ()) if t else (),
        rgb=m.rgb_of(p.colour),
        pattern=p.pattern,
        texture_view=("detail" if detail else "front") if p.photos else None,
        photo=detail or (p.photos[0] if p.photos else None),
        views=views,
        missing=missing,  # type: ignore[arg-type]
        readiness=_readiness(p),
        eligible=p.eligible,
        approximate=approx if t else (),
        card_only=t is None,
        removable=slot in m.REMOVABLE_SLOTS,
        options=_options(view, slot),
    )


def _chosen(pieces: str, v: WardrobeView) -> tuple[tuple[str, str], ...] | None:
    """`?pieces=top:wi_...,bottom:wi_...` (D21, the card's slots) -> (slot, piece) pairs."""
    pairs = [x.split(":", 1) for x in pieces.split(",") if x]
    if any(len(x) != 2 or x[1] not in v.pieces for x in pairs):
        return None
    return tuple((s, pid) for s, pid in pairs)


def fake_routes(store: MemoryWardrobeStore, clock: Callable[[], datetime]) -> APIRouter:
    r = APIRouter(dependencies=[Depends(require_auth)])
    st = FakeTryon()
    r.state = st  # type: ignore[attr-defined]  # tests may look

    async def view() -> WardrobeView:
        return await store.view(UID)

    @r.get("/v1/tryon")
    async def tryon() -> JSONResponse:
        ranges = tuple(
            http.RangeView(measure=k, low=lo, high=hi, words=m.range_words(k))
            for k, (lo, hi) in m.RANGES.items()
        )
        words = m.ESTIMATED if st.body.current else m.NO_FIGURE
        return _ok(
            http.TryonView(
                ready=READY,
                files=("body.glb", "garments.glb"),
                body=st.body,
                ranges=ranges,
                assets=tuple(st.assets.values()),
                words=words,
                saved=tuple(
                    http.SavedRef(id=s.id, at=s.at, draft=s.draft) for s in st.saved.values()
                ),
            )
        )

    @r.put("/v1/tryon/body")
    async def body(b: http.BodyIn) -> JSONResponse:
        typed = {k: v for k, v in b.model_dump().items() if v is not None}
        for k, v in typed.items():
            if not m.in_range(k, v):
                return _no(422, "out_of_range", m.range_words(k))
        base = st.body.draft or st.body.current
        values = (
            base.model_dump(include=set(m.MEASURES))
            if base
            else m.estimated(typed.get("height", 172))
        )
        both = {**values, **typed}
        draft = http.BodyView(**both, typed=tuple(typed), at=clock(), weights=m.morph_weights(both))
        st.body = st.body.model_copy(update={"draft": draft})
        return _ok(st.body)

    @r.post("/v1/tryon/body/use")
    async def use() -> JSONResponse:
        if st.body.draft is None:
            return _no(404, "no_draft", "There are no new measurements to use.")
        earlier = ((st.body.current,) if st.body.current else ()) + st.body.earlier
        st.body = http.BodyVersions(current=st.body.draft, earlier=earlier[: m.EARLIER_MAX])
        return _ok(st.body)

    @r.delete("/v1/tryon/body/draft")
    async def drop_draft() -> JSONResponse:
        if st.body.draft is None:
            return _no(404, "no_draft", "There are no new measurements to drop.")
        st.body = st.body.model_copy(update={"draft": None})
        return _ok(st.body)

    @r.get("/v1/tryon/look")
    async def look(
        plan: str = "", day: str = "today", alt: int = 0, private: int = 0, pieces: str = ""
    ) -> JSONResponse:
        v = await view()
        chosen = _chosen(pieces, v) if pieces else LOOK_SLOTS  # row 388: the card's own pieces
        if chosen is None:
            return _no(422, "not_a_piece", "A piece of that look isn't in your wardrobe.")
        slots = tuple(look_slot(v, s, p, private=bool(private)) for s, p in chosen)
        when = clock().astimezone(IST).date() + timedelta(days=1 if day == "tomorrow" else 0)
        return _ok(
            http.TryonLook(
                plan=plan or None, day=when, dress_code="business_formal", slots=slots, tucked=True
            )
        )

    @r.put("/v1/tryon/assets/{piece}")
    async def assets(piece: str, b: http.AssetChoice) -> JSONResponse:
        if piece not in (await view()).pieces or b.piece != piece:
            return _no(404, "not_in", "That piece isn't in your wardrobe.")
        st.assets[piece] = b
        return _ok(b)

    @r.post("/v1/tryon/confirm")
    async def confirm(b: http.ConfirmIn) -> JSONResponse:
        v = await view()
        for s in b.slots:
            p = v.pieces.get(s.piece)
            if p is None or not p.eligible:
                what = _words(p) if p else "piece"
                words = f"The {what} isn't ready: it can't be confirmed for this event."
                return _no(409, "draft", words)
        if st.refuse or b.plan == RACE_PLAN:  # A answers outfit_plan's refusal so (F1)
            return _no(409, "refused", st.refuse or _race(v, b))
        return _ok(http.ToolReply(status="executed", message="Done.", result={"plan": b.plan}))

    @r.get("/v1/tryon/saved")
    async def saved() -> JSONResponse:
        return _ok(http.SavedList(saved=tuple(st.saved.values())))

    @r.post("/v1/tryon/saved")
    async def save(b: http.SavedIn) -> JSONResponse:
        if len(st.saved) >= m.SAVED_MAX:
            return _no(409, "too_many", "You keep at most 10 comparisons: delete one first.")
        sid = m.new_saved_id()
        looks = tuple(
            http.SavedLookView(look=x, readiness=tuple(m.READY for _ in x.slots)) for x in b.looks
        )
        st.saved[sid] = http.SavedView(id=sid, at=clock(), looks=looks)
        return _ok(st.saved[sid])

    @r.get("/v1/tryon/saved/{sid}")
    async def saved_one(sid: str) -> JSONResponse:
        found = st.saved.get(sid)
        return _ok(found) if found else _no(404, "gone", "That comparison isn't there any more.")

    @r.delete("/v1/tryon/saved/{sid}")
    async def saved_drop(sid: str) -> JSONResponse:
        gone = st.saved.pop(sid, None) is not None
        return _ok(http.Deleted(deleted=gone, message="Deleted." if gone else "Already gone."))

    r.include_router(seeme_routes(view, clock))  # the See it on me half (D13, D22)
    return r


_FIXTURE = re.compile(r"^[a-z0-9_]{1,40}\.mjs$")
STAGE_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>R13.1 stage</title></head>
<body><div id="stage" style="width:480px;height:480px"></div>
<script type="module" src="/r131/fixtures/{mod}"></script></body></html>"""


def stage_routes() -> APIRouter:
    """A bare page for B's engine: GET /r131/stage?mod=<a fixture>.mjs, under the console's CSP."""
    r = APIRouter()

    @r.get("/r131/stage")
    async def stage(mod: str = "stage.mjs") -> HTMLResponse:
        name = mod if _FIXTURE.fullmatch(mod) else "stage.mjs"
        return HTMLResponse(
            STAGE_PAGE.format(mod=name), headers={"Content-Security-Policy": CONSOLE_CSP}
        )

    @r.get("/r131/fixtures/{name}")
    async def fixture(name: str) -> Response:
        path = FIXTURES / name
        if not _FIXTURE.fullmatch(name) or not path.is_file():
            return Response(status_code=404)
        return FileResponse(path, media_type="application/javascript", headers=NO_STORE)

    return r


async def fake_state(clock: FixedClock | None = None) -> tuple[MemoryWardrobeStore, FixedClock]:
    return await seeded(clock=clock)


def fake_app(
    wardrobe: MemoryWardrobeStore, clock: Callable[[], datetime], **app_kw: Any
) -> FastAPI:
    """The real app (mock brain) with R13's and R13.1's fake routes AHEAD of the parts' own."""
    from jarvis.api import create_app
    from jarvis.llm.mock_provider import MockProvider

    app = create_app(provider=MockProvider(), **app_kw)
    ours = fake_routes(wardrobe, clock)
    app.state.r131_fake = ours.state  # type: ignore[attr-defined]
    app.router.routes[:0] = [
        *ours.routes,
        *stage_routes().routes,
        *r13_routes(wardrobe, clock).routes,
    ]
    return app


def serve(token: str) -> tuple[str, Callable[[], None]]:
    """This server in a child process for a browser test module: (url, stop). Token sign-in,
    the mock brain, memory sessions, no live rate (as R13 D's `serve_d`)."""
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
        **os.environ, "PYTHONPATH": str(root / "src"), "JARVIS_ENV": "dev",
        "JARVIS_LLM_BACKEND": "mock", "JARVIS_SESSION_BACKEND": "memory",
        "JARVIS_AUTH_MODE": "token", "JARVIS_API_TOKEN": token, "JARVIS_LOG_LEVEL": "WARNING",
        "JARVIS_USD_INR_LIVE": "0", "JARVIS_RATE_LIMIT_PER_MINUTE": "6000",
    }  # fmt: skip
    env.pop("JARVIS_ANTHROPIC_API_KEY", None)
    proc = subprocess.Popen(
        [sys.executable, str(root / "tests" / "r131_fake_server.py"), str(port)],
        cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )  # fmt: skip
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("the R13.1 fake server exited early")
        try:
            with urllib.request.urlopen(url + "/health", timeout=1) as r:
                if r.status == 200:
                    break
        except OSError:
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError("the R13.1 fake server did not become healthy")

    def stop() -> None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    return url, stop


def main(argv: list[str]) -> int:
    import asyncio

    import uvicorn

    port = int(argv[1]) if len(argv) > 1 else 8766
    store, clock = asyncio.run(fake_state())
    uvicorn.run(fake_app(store, clock), host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

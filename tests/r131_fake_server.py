# tests/r131_fake_server.py -- R13.1 I0 (docs/plans/r13-1-try-on.md "The HTTP contract", seam 15):
# every route of `jarvis.wardrobe.tryon.http.ROUTES`, answered from the fakes (`r131_fakes`: R13's
# seeded pilot with photos, a FIXED clock), each reply validated by its model, so Part D's console
# and Part B's stage run end to end before A and C exist. At I1 D's browser tests move to the
# wired app. Nothing here calls Google: "See it on me" answers I0's made-up picture.
#
#   fake_routes(store, clock) -> APIRouter   the 22 routes (owner-only like the real ones; the
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

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from r13_fake_server import fake_routes as r13_routes
from r131_fake_tryon import PNG
from r131_fakes import IST, NOW, PRIVATE, UID, VIEW_OF, FixedClock, MemoryWardrobeStore, T, seeded

from jarvis.api.auth import require_auth
from jarvis.api.console import CONSOLE_CSP
from jarvis.wardrobe.model import Piece, WardrobeView
from jarvis.wardrobe.tryon import http
from jarvis.wardrobe.tryon import model as m

NO_STORE = {"Cache-Control": "no-store"}
READY = "fake: tests/r131_fake_server.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "r13_1"
CONSENT_VERSION = "c1"
CONSENT_WORDS = (
    "What is sent: your photo and the photos of the look's top, trousers and jacket. Never a "
    "private piece, your measurements or anything else.",
    "To whom: Google Cloud's Agent Platform, Gemini 3.1 Flash Image, processed in the United "
    "States.",
    "Every picture shows its price first, under your monthly limit. Delete your photo to withdraw.",
)
LOOK_SLOTS = (
    ("top", T.striped),
    ("bottom", T.trousers),
    ("outer", T.blazer),
    ("shoes", T.shoes[0]),
    ("belt", T.belt),
    ("watch", T.watch),
    ("base", T.vest),
)
TYPICAL, HOLD = 8.9, 11.22


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
    photo: bytes | None = None
    photo_at: datetime | None = None
    consent_at: datetime | None = None
    pictures: dict[str, http.PictureView] = field(default_factory=dict)
    spent: float = 0.0
    on: bool = True
    cap: int = 300


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


def _picture(st: FakeTryon, pieces: tuple[str, ...], view: WardrobeView, plan: str | None) -> Any:
    pid = m.new_picture_id()
    sent = tuple(http.SentPiece(piece=x, words=_words(view.pieces[x])) for x in pieces)
    pic = http.PictureView(
        id=pid,
        made_at=NOW,
        until=NOW + timedelta(days=m.PICTURE_KEEP_DAYS),
        inr=8.52,
        sent=sent,
        plan=plan,
        mime="image/png",
        credentials=m.CREDENTIALS,
    )
    st.pictures[pid] = pic
    st.spent += 8.52
    return pic


def _seeme_view(st: FakeTryon) -> http.SeeMeView:
    return http.SeeMeView(
        ready=READY,
        on=st.on,
        provider=http.ProviderView(
            provider="Google Cloud's Agent Platform",
            model="gemini-3.1-flash-image",
            model_words="Gemini 3.1 Flash Image",
            location="us",
            location_words="processed in the United States",
            max_garments=3,
            retires_on="2027-05-28",
        ),
        photo=http.PhotoView(kept=st.photo is not None, at=st.photo_at, bytes=len(st.photo or b"")),
        consent=http.ConsentView(
            given=st.consent_at is not None,
            at=st.consent_at,
            current=st.consent_at is not None,
            version=CONSENT_VERSION,
            words=CONSENT_WORDS,
        ),
        month=http.MonthView(
            month="2026-11", spent_inr=round(st.spent, 2), cap_inr=st.cap, pictures=len(st.pictures)
        ),
        typical_inr=TYPICAL,
        hold_inr=HOLD,
        pictures=tuple(st.pictures.values()),
    )


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
        draft = http.BodyView(**{**values, **typed}, typed=tuple(typed), at=clock())
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
        plan: str = "", day: str = "today", alt: int = 0, private: int = 0
    ) -> JSONResponse:
        v = await view()
        slots = tuple(look_slot(v, s, p, private=bool(private)) for s, p in LOOK_SLOTS)
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

    @r.get("/v1/seeme")
    async def seeme() -> JSONResponse:
        return _ok(_seeme_view(st))

    @r.post("/v1/seeme/photo")
    async def photo_in(request: Request) -> JSONResponse:
        raw = await request.body()
        if not raw.startswith(b"\xff\xd8"):
            return _no(422, "not_jpeg", "Send your photo as a JPEG.")
        if len(raw) > 700 * 1024:
            return _no(
                413, "too_large", "This photo is too detailed to send: try a plainer background."
            )
        st.photo, st.photo_at = raw, clock()
        return _ok(http.PhotoView(kept=True, at=st.photo_at, bytes=len(raw)))

    @r.get("/v1/seeme/photo")
    async def photo_out() -> Response:
        if st.photo is None:
            return _no(404, "no_photo", "No photo yet.")
        return Response(st.photo, media_type="image/jpeg", headers=http.PICTURE_HEADERS)

    @r.delete("/v1/seeme/photo")
    async def photo_drop() -> JSONResponse:
        gone, st.photo, st.consent_at = st.photo is not None, None, None  # the YES goes with it
        return _ok(http.Deleted(deleted=gone, message="Your photo and your YES are deleted."))

    @r.post("/v1/seeme/consent")
    async def consent(b: http.ConsentIn) -> JSONResponse:
        if b.typed.strip() != m.YES or b.template_version != CONSENT_VERSION:
            return _no(422, "not_yes", "Type YES in capitals to agree; nothing changed.")
        st.consent_at = clock()
        return _ok(_seeme_view(st).consent)

    @r.get("/v1/seeme/estimate")
    async def estimate(plan: str = "", pieces: str = "") -> JSONResponse:
        v = await view()
        asked = [x for x in pieces.split(",") if x] or [T.striped, T.trousers, T.blazer]
        sent = tuple(
            http.SentPiece(piece=x, words=_words(v.pieces[x])) for x in asked if x in v.pieces
        )
        not_sent = (
            http.NotSent(
                slot="shoes", piece=T.shoes[0], words="brown dress shoe", why="not_a_garment"
            ),
        )
        return _ok(
            http.Estimate(
                typical_inr=TYPICAL,
                hold_inr=HOLD,
                tax_pct=18,
                sent=sent,
                not_sent=not_sent,
                cap_left_inr=round(st.cap - st.spent, 2),
                words=f"About ₹9 with GST. ₹{st.spent:.2f} of ₹{st.cap} used.",
            )
        )

    @r.post("/v1/seeme/pictures")
    async def pictures(b: http.PictureIn) -> JSONResponse:
        v = await view()
        if not b.confirm_cost:
            return _no(422, "confirm_cost", "Confirm the price first.")
        if st.consent_at is None:
            return _no(409, "consent_needed", "Type YES first, after reading what is sent.")
        if st.photo is None:
            return _no(422, "no_photo", "Add your photo first.")
        if any(x in PRIVATE or (x in v.pieces and v.pieces[x].private) for x in b.pieces):
            return _no(422, "private_piece", "A private piece is never sent.")
        if b.inr_shown + 0.01 < TYPICAL:
            return _no(409, "price_changed", "The price changed: look at it again.")
        return _ok(_picture(st, b.pieces, v, b.plan))

    @r.get("/v1/seeme/pictures/{pid}")
    async def picture(pid: str) -> Response:
        if pid not in st.pictures:
            return _no(404, "gone", "That picture isn't there any more.")
        return Response(PNG, media_type="image/png", headers=http.PICTURE_HEADERS)

    @r.post("/v1/seeme/pictures/{pid}/keep")
    async def keep(pid: str, b: http.KeepIn) -> JSONResponse:
        pic = st.pictures.get(pid)
        if pic is None:
            return _no(404, "gone", "That picture isn't there any more.")
        until = None if b.keep else NOW + timedelta(days=m.PICTURE_KEEP_DAYS)
        st.pictures[pid] = pic.model_copy(update={"kept": b.keep, "until": until})
        return _ok(st.pictures[pid])

    @r.delete("/v1/seeme/pictures/{pid}")
    async def picture_drop(pid: str) -> JSONResponse:
        gone = st.pictures.pop(pid, None) is not None
        return _ok(http.Deleted(deleted=gone, message="Deleted." if gone else "Already gone."))

    @r.put("/v1/seeme/settings")
    async def seeme_settings(b: http.SeeMeSettingsIn) -> JSONResponse:
        if b.cap_inr is not None and b.cap_inr > st.cap and not b.confirm_cost:
            return _no(422, "confirm_cost", f"Raising the limit to ₹{b.cap_inr} needs your OK.")
        st.on = st.on if b.on is None else b.on
        st.cap = st.cap if b.cap_inr is None else b.cap_inr
        return _ok(_seeme_view(st))

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

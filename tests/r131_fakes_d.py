# tests/r131_fakes_d.py -- R13.1 Part D's fakes (imported bare: `from r131_fakes_d import ...`).
# Every clock is FIXED (r131_fakes.NOW, 17 Nov 2026 09:00 IST); nothing here calls Google, spends
# anything or reads a real photo: every crop is a picture drawn here (stripes on a colour).
#
#   d_routes(state, store, clock) -> APIRouter   D's answers AHEAD of I0's fake server
#                       (tests/r131_fake_server.py): two plans in "Today and tomorrow" (a business
#                       formal one today, a festive one tomorrow), the look by plan, day or pieces
#                       (I0's `look_slot`), drawn crops for the image cards, a recording tools
#                       route, a fake /v1/chat that answers "what should I wear?" with I0's real
#                       `TryOnCard` (row 388), and the test hooks (/v1/test/r131-d: what was sent;
#                       POST .../reset: the figure, his photo, the garments and pictures)
#   _seeme_routes(...)  See it on me as C answers it, ahead of I0's: a repeated request_id replayed
#                       (one picture, one spend); a picture and a garment photo a browser decodes
#   d_app() -> FastAPI  I0's fake app, seeded: the rain jacket in the laundry (AVT-09), a photo on
#                       both watches (AVT-06) and on the blazer, his measurements (178 cm typed)
#   serve_d(token) -> (url, stop)   that server in a child process for a browser test module
#   python tests/r131_fakes_d.py <port>   serve it (uvicorn)
#   ENGINE              the fake engine (tests/fixtures/r13_1/d_engine.mjs): the browser tests route
#                       /static/console-tryon-3d.js to it; it keeps the engine contract
#
# Not a test module (pytest does not collect it).
from __future__ import annotations

import base64
import struct
import sys
import zlib
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from r13_fakes import ev
from r131_fake_seeme import seeme_routes
from r131_fake_server import look_slot
from r131_fakes import IST, NOW, UID, VIEW_OF, FixedClock, T, seeded

from jarvis.api.auth import require_auth
from jarvis.core.models import ChatResponse
from jarvis.llm.base import Usage
from jarvis.tools.reply_cards import TryOnCard, TryOnSlot
from jarvis.wardrobe import http as wh
from jarvis.wardrobe.ports import Commit
from jarvis.wardrobe.tryon import http
from jarvis.wardrobe.tryon import model as m

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "tests" / "fixtures" / "r13_1" / "d_engine.mjs"
NO_STORE = {"Cache-Control": "no-store"}
PLAN, FESTIVE = "op_0000d001", "op_0000d002"
SHOE, SHOE2 = T.shoes
FORMAL: tuple[tuple[str, str], ...] = (
    ("top", T.striped), ("bottom", T.trousers), ("outer", T.blazer), ("shoes", SHOE),
    ("belt", T.belt), ("watch", T.watch), ("base", T.vest),
)  # fmt: skip
FESTIVE_LOOK: tuple[tuple[str, str], ...] = (
    ("top", T.kurta), ("bottom", T.pyjama), ("shoes", SHOE), ("watch", T.watch2), ("base", T.vest),
)  # fmt: skip
WATCH_PHOTO, WATCH2_PHOTO, BLAZER_PHOTO = "wh_00000000c001", "wh_00000000c002", "wh_00000000d001"
MORE_PHOTOS = {T.watch: (WATCH_PHOTO,), T.watch2: (WATCH2_PHOTO,), T.blazer: (BLAZER_PHOTO,)}
CROP_RGB = {
    "wh_00000000a001": (215, 200, 170), "wh_00000000a002": (200, 186, 156),
    "wh_00000000b001": (30, 42, 80), "wh_00000000b002": (40, 56, 100),
    WATCH_PHOTO: (140, 140, 144), WATCH2_PHOTO: (110, 75, 50), BLAZER_PHOTO: (64, 66, 70),
}  # fmt: skip
VIEW_OF.update({WATCH_PHOTO: "front", WATCH2_PHOTO: "front", BLAZER_PHOTO: "front"})
CARD = TryOnCard(
    day=NOW.date().isoformat(),
    plan=PLAN,
    code="business_formal",
    slots=[
        *(TryOnSlot(slot=s, pieces=(p,)) for s, p in FORMAL if s not in ("shoes", "base")),
        TryOnSlot(slot="shoes", pieces=(SHOE, SHOE2)),
        TryOnSlot(slot="base", private=True),
    ],
)


def png(rgb: tuple[int, int, int], w: int = 48, h: int = 48) -> bytes:
    """A drawn crop: the colour with a lighter stripe every 8 rows (never a photo)."""
    light = tuple(min(255, c + 60) for c in rgb)
    rows = b"".join(
        b"\x00" + bytes(light if (y // 4) % 2 else rgb) * w for y in range(h)
    )  # filter 0 per row

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    head = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", head)
        + chunk(b"IDAT", zlib.compress(rows))
        + (chunk(b"IEND", b""))
    )


# ---- the door's three proposed lines (INTEGRATION-D "Needs I1", item 1) -------------------------
# tests/test_r131_seams.py lets only the door (console-r7-send.js, I0's) name /v1/seeme/photo,
# /pictures and /garments, but the door has no call for the paid press, Keep, the deletes or the
# garment list. I1 applies exactly this; until then the browser tests serve the door with it
# applied (`patched_door`), and `tests/test_r131_d_door.py` holds it to every pin of the door.
DOOR = ROOT / "src" / "jarvis" / "api" / "static" / "console-r7-send.js"
DOOR_LAST = (
    "if (M) M.part('send', Object.freeze({ canAsk, ask, attach, vault, wardrobe, tag, thumb, drop, "
    "person, garment, picture, garmentPhoto, myPhoto, sentToday: readCount, line }));"
)
DOOR_ADD = (
    "// R13.1 D (I1): See it on me's press (ids and the rupees he confirmed), Keep, the deletes "
    "and the garment list: ids checked, JSON only\n"
    "const SEE = /^t[pg]_[0-9a-f]{12}$/, seeme = (p, o) => window.JarvisConsole.api('/v1/seeme/' "
    "+ p, o), make = (b) => seeme('pictures', { body: b }), garments = () => seeme('garments');\n"
    "const keep = (id, on) => (SEE.test(String(id)) && id[1] === 'p' ? seeme('pictures/' + id + "
    "'/keep', { body: { keep: on === true } }) : no()), forget = (id) => (id === 'photo' ? "
    "seeme('photo', { method: 'DELETE' }) : SEE.test(String(id)) ? seeme((id[1] === 'p' ? "
    "'pictures/' : 'garments/') + id, { method: 'DELETE' }) : no());\n"
)
DOOR_NEW_LAST = DOOR_LAST.replace(
    "myPhoto, sentToday", "myPhoto, make, keep, forget, garments, sentToday"
)


def patched_door() -> str:
    """The door with the three proposed lines (unchanged once I1 has applied them)."""
    s = DOOR.read_text(encoding="utf-8")
    if "make, keep, forget, garments" in s:
        return s
    if DOOR_LAST not in s:
        raise AssertionError("the door's last line moved: update DOOR_LAST")
    return s.replace(DOOR_LAST, DOOR_ADD + DOOR_NEW_LAST)


# ---- I0's hook: two lines proposed for I1 (INTEGRATION-D "Fix (review D-1)", M7) ---------------
# With Try-on off, R13's plan rows must look as R13's: no "Show in 3D". Hiding it on the section's
# `hidden` races the tab's own reads, so D says Try-on's state (`state()`: on, off or unknown) and
# fires `jarvis:tryon-state` when it changes; the hook draws the button only while it is "on" and
# draws again on the event. The browser tests serve the hook with them applied (`patched_hook`).
HOOK = ROOT / "src" / "jarvis" / "api" / "static" / "console-helpers-wardrobe.js"
HOOK_PLAN = (
    "  if (!p.cancelled) box.append(acts(btn('Show in 3D', () => tryOn(p.id)))); "
    "// R13.1 D1: free (See it on me is for a garment to buy, D22)"
)
HOOK_PLAN_NEW = (
    "  if (!p.cancelled && UI.tryon && UI.tryon.state && UI.tryon.state() === 'on') "
    "box.append(acts(btn('Show in 3D', () => tryOn(p.id)))); // R13.1 D1: free, while Try-on is on"
)
HOOK_READY = "  document.addEventListener('jarvis:ready', () => { if (UI.host) load(); });"
HOOK_STATE = (
    "  document.addEventListener('jarvis:tryon-state', () => { if (UI.host && UI.outfits) "
    "draw(); }); // R13.1: Show in 3D follows it"
)


def patched_hook() -> str:
    """I0's hook with the two proposed lines (unchanged once I1 has applied them)."""
    s = HOOK.read_text(encoding="utf-8")
    if "jarvis:tryon-state" in s:
        return s
    if s.count(HOOK_PLAN) != 1 or s.count(HOOK_READY) != 1:
        raise AssertionError("the hook's lines moved: update HOOK_PLAN / HOOK_READY")
    return s.replace(HOOK_PLAN, HOOK_PLAN_NEW).replace(HOOK_READY, HOOK_READY + "\n" + HOOK_STATE)


def _ok(model: Any) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json"), headers=NO_STORE)


# ---- See it on me as C's server answers, ahead of I0's fake (review D-1 M1, L2) ----------------
# C answers a repeated request_id with the first outcome (D13.6, `done {request_id: outcome}`), so
# a retry after a lost answer makes and pays for nothing new; I0's fake makes a new picture each
# time, so D keeps the replay in front of it. A picture, and a garment photo a test sent with I0's
# SOF-only `jpeg()`, read back as drawn images a browser can decode (a 48 px shirt, drawn here).
GARMENT_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABALDA4MChAODQ4SERATGCgaGBYWGDEjJR0oOjM9PDkzODdASFxOQERXRTc4"
    "UG1RV19iZ2hnPk1xeXBkeFxlZ2P/2wBDARESEhgVGC8aGi9jQjhCY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2Nj"
    "Y2NjY2NjY2NjY2NjY2NjY2NjY2P/wAARCAAwADADASIAAhEBAxEB/8QAGwAAAgIDAQAAAAAAAAAAAAAABQYABwECBAP/"
    "xAA1EAABAgQEAwMKBwAAAAAAAAABAgMABAUREhMhUQYxQRVhshY1NmV0gYKj4vAUIjJxocHR/8QAGAEAAwEBAAAAAAAA"
    "AAAAAAAAAAMEAQL/xAAbEQADAAMBAQAAAAAAAAAAAAAAAQIREiETMf/aAAwDAQACEQMRAD8AcowtaW0KWtQSlIuVE2AG"
    "8aTEw1KsLffWG2kC6lHpCFXuInaqMhpJZlgblN9V66E/5vvpBMugbwPcvNy01i/DzDT2H9WWsKt+9o2fmGZZAXMPNtJJ"
    "sFOKCRfbWKypVQcpk+3NNDFh0Ui5AUk8x99QI969V1VedzAkoZQMLaCem56XP9DaO/LpmxY7Trb7YcZcQ4hXJSFAg+8R"
    "vFb0SuP0dxWFOawvVTRVbXcHofvaz/ITzFRlUzEsvEhWhB5pOx744qHJqeToWhLiFIWkKSoWKSLgjaEuucMtSEvNzrTp"
    "yUhJbb6glQBBOwB06692rrAjiv0dmvg8aYIbTBrhXMSJEioWH6Fw8mrSiZgvlsJfKHBbmnCDp33P892r1Ly7UqwhhhAb"
    "aQLJSOkAOB/M73tCvCmGOJrbbwMlcJAjiv0dmvg8aYLxx1aR7SpzspmZeZb82G9rEHl7o5njNZV0SG/yH9Y/I+qJ5D+s"
    "fkfVFHpIvVnXwP5ne9oV4UwxwOodK7Ik1y+dnYnCvFhw9ALcztBGJ6eXkYvh/9k="
)


def _seeme_routes(state: dict[str, Any], store: Any, clock: Any) -> list[Any]:
    """I0's See it on me half (`seeme_routes`, the same code), served by D's own instance with
    the replay and the drawn read-backs in front of it."""

    async def view() -> Any:
        return await store.view(UID)

    seeme = seeme_routes(view, clock)
    at = {(m, x.path): x.endpoint for x in seeme.routes for m in getattr(x, "methods", ())}
    make, picture = at["POST", "/v1/seeme/pictures"], at["GET", "/v1/seeme/pictures/{pid}"]
    garment = at["GET", "/v1/seeme/garments/{gid}"]
    r = APIRouter(dependencies=[Depends(require_auth)])

    @r.post("/v1/seeme/pictures")
    async def pictures(b: http.PictureIn) -> Response:
        if b.request_id not in state["done"]:
            out = await make(b)
            if out.status_code >= 400:  # a refusal is not an outcome: nothing was made
                return out
            state["done"][b.request_id] = bytes(out.body).decode()
        return Response(state["done"][b.request_id], media_type="application/json")

    @r.get("/v1/seeme/pictures/{pid}")
    async def picture_out(pid: str) -> Response:
        out = await picture(pid)
        if out.status_code != 200:
            return out
        drawn = png((90, 110, 160), 96, 128)
        return Response(drawn, media_type="image/png", headers=http.PICTURE_HEADERS)

    @r.get("/v1/seeme/garments/{gid}")
    async def garment_out(gid: str) -> Response:
        out = await garment(gid)
        if out.status_code != 200 or b"\xff\xc4" in bytes(out.body):  # a JPEG a browser made
            return out
        return Response(GARMENT_JPEG, media_type="image/jpeg", headers=http.PICTURE_HEADERS)

    return [*r.routes, *seeme.routes]


def _plan(pid: str, day: Any, hour: int, code: str, look: tuple[tuple[str, str], ...]) -> Any:
    picks = tuple(
        wh.SlotPick(slot=s, piece=p, words="a private basic" if s == "base" else "")
        for s, p in look
    )
    starts = datetime.combine(day, time(hour), tzinfo=IST)
    why = (f"{code.replace('_', ' ').capitalize()} for the event",)
    return wh.PlanView(
        id=pid, day=day, starts=starts, dress_code=code, tentative=False,
        look=wh.Look(pieces=picks, reasons=why), manual=False,
    )  # fmt: skip


def chat_reply(message: str, session: str | None) -> ChatResponse:
    """The fake brain's answer: "what should I wear" gets row 388's card beside the words."""
    asks = "wear" in message.lower()
    words = (
        "The striped navy shirt, charcoal trousers and the blazer, Sir." if asks else "Noted, Sir."
    )
    return ChatResponse(
        session_id=session or "s_r131d0001", reply=words, tool_calls=1 if asks else 0,
        trace_id="t_r131d", model="mock", brain="", usage=Usage(input_tokens=0, output_tokens=0),
        cost_usd=0.0, latency_ms=5, turn_count=1, cards=[CARD] if asks else [],
    )  # fmt: skip


def _look_routes(r: APIRouter, store: Any, clock: Any) -> None:
    plans = {PLAN: FORMAL, FESTIVE: FESTIVE_LOOK}

    @r.get("/v1/tryon/look")
    async def look(
        plan: str = "", day: str = "today", alt: int = 0, private: int = 0, pieces: str = ""
    ) -> JSONResponse:
        v = await store.view(UID)
        if pieces:
            pairs = [x.split(":", 1) for x in pieces.split(",") if x]
            if any(len(x) != 2 or x[1] not in v.pieces for x in pairs):
                return JSONResponse(
                    {
                        "error": "not_a_piece",
                        "detail": "A piece of that look isn't in your wardrobe.",
                    },
                    422,
                )
            chosen = tuple((s, p) for s, p in pairs)
        elif plan:
            if plan not in plans:
                return JSONResponse(
                    {"error": "gone", "detail": "That plan isn't there any more."}, 404
                )
            chosen = plans[plan]
        else:
            chosen = FESTIVE_LOOK if (day == "tomorrow") != bool(alt) else FORMAL
        slots = tuple(look_slot(v, s, p, private=bool(private)) for s, p in chosen)
        when = clock().astimezone(IST).date() + timedelta(days=1 if day == "tomorrow" else 0)
        code = "festive" if chosen is FESTIVE_LOOK else "business_formal"
        return _ok(http.TryonLook(plan=plan or None, day=when, dress_code=code, slots=slots,
                                  tucked=code != "festive"))  # fmt: skip


def d_routes(state: dict[str, Any], store: Any, clock: Any) -> APIRouter:
    r = APIRouter(dependencies=[Depends(require_auth)])

    @r.get("/v1/test/r131-d", include_in_schema=False)
    async def seen() -> JSONResponse:
        return JSONResponse(state)

    @r.post("/v1/test/r131-d/reset", include_in_schema=False)
    async def reset(request: Request) -> JSONResponse:
        b = await request.json()
        fake = request.app.state.r131_fake
        fake.body = _body() if b.get("figure", True) else http.BodyVersions()
        fake.saved.clear()
        fake.assets.clear()
        for k in ("tools", "chats", "done"):
            state[k].clear()
        return JSONResponse({"reset": True})

    @r.get("/v1/outfits")
    async def outfits() -> JSONResponse:
        today, tomorrow = NOW.date(), NOW.date() + timedelta(days=1)
        return _ok(wh.OutfitsView(
            ready="fake: tests/r131_fakes_d.py",
            today=(_plan(PLAN, today, 10, "business_formal", FORMAL),),
            tomorrow=(_plan(FESTIVE, tomorrow, 19, "festive", FESTIVE_LOOK),),
            weather="Weather unknown: I assumed indoors.",
        ))  # fmt: skip

    @r.post("/v1/wardrobe/tools/{tool}")
    async def tool(tool: str, body: wh.ToolCall) -> JSONResponse:
        state["tools"].append({"tool": tool, "arguments": body.arguments})
        return _ok(wh.ToolReply(status="executed", message="Done, Sir."))

    @r.get("/v1/wardrobe/photos/{pid}")
    async def crop(pid: str) -> Response:
        if pid not in CROP_RGB:
            return JSONResponse({"detail": "Not found."}, status_code=404)
        return Response(png(CROP_RGB[pid]), media_type="image/png", headers=NO_STORE)

    @r.post("/v1/chat")
    async def chat(request: Request) -> JSONResponse:
        b = await request.json()
        state["chats"].append({"message": b.get("message"), "channel": b.get("channel", "text")})
        return _ok(chat_reply(str(b.get("message") or ""), b.get("session_id")))

    _look_routes(r, store, clock)
    return r


def _body() -> http.BodyVersions:
    values = m.estimated(178)
    cur = http.BodyView(**values, typed=("height",), at=NOW, weights=m.morph_weights(values))
    return http.BodyVersions(current=cur)


async def d_store() -> tuple[Any, FixedClock]:
    """I0's seeded pilot, then the rain jacket into the laundry and photos on both watches and
    the blazer (drawn crops)."""
    store, clk = await seeded()

    async def fn(view: Any, tx: Any) -> Commit:
        recs = tuple(
            view.pieces[p].model_copy(update={"photos": ids}) for p, ids in MORE_PHOTOS.items()
        )
        return Commit(events=(ev(T.rain_jacket, "deposited", clk()),), records=recs)

    await store.transact(UID, fn)
    return store, clk


def d_state() -> dict[str, Any]:
    return {"tools": [], "chats": [], "done": {}}


def d_app() -> Any:
    import asyncio

    from r131_fake_server import fake_app

    store, clock = asyncio.run(d_store())
    app = fake_app(store, clock)
    state = d_state()
    ahead = [*d_routes(state, store, clock).routes, *_seeme_routes(state, store, clock)]
    app.router.routes[:0] = ahead
    app.state.r131_fake.body = _body()
    app.state.r131_d = state
    return app


def serve_d(token: str) -> tuple[str, Any]:
    """This server in a child process: (url, stop). Token sign-in, the mock brain, memory
    sessions, no live rate (as I0's `serve`, which runs its own file)."""
    import os
    import socket
    import subprocess
    import time
    import urllib.request

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    env = {
        **os.environ, "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT / "tests"))),
        "JARVIS_ENV": "dev", "JARVIS_LLM_BACKEND": "mock", "JARVIS_SESSION_BACKEND": "memory",
        "JARVIS_AUTH_MODE": "token", "JARVIS_API_TOKEN": token, "JARVIS_LOG_LEVEL": "WARNING",
        "JARVIS_USD_INR_LIVE": "0", "JARVIS_RATE_LIMIT_PER_MINUTE": "6000",
    }  # fmt: skip
    env.pop("JARVIS_ANTHROPIC_API_KEY", None)
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), str(port)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )  # fmt: skip
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
            raise RuntimeError("D's fake server exited early:\n" + err[-2000:])
        try:
            with urllib.request.urlopen(url + "/health", timeout=1) as r:
                if r.status == 200:
                    break
        except OSError:
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError("D's fake server did not become healthy")

    def stop() -> None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    return url, stop


def main(argv: list[str]) -> int:
    import uvicorn

    port = int(argv[1]) if len(argv) > 1 else 8767
    uvicorn.run(d_app(), host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

# tests/r13_fakes_d.py -- R13 Part D's fakes (imported bare: `from r13_fakes_d import ...`). Every
# clock is fixed (r13_fakes' IST helpers); nothing here talks to Google or spends anything.
#
#   FakeData(name, items)          one part's WardrobeData (count, export, delete), recording
#   parts_with(*data)              the app's `r13_parts` with those data sources on A, B and C
#   d_routes(state) -> APIRouter   D's browser-test answers AHEAD of I0's fake server
#                                  (tests/r13_fake_server.py): a review queue, a plan, the tools
#                                  route recording every call (status "executed"), fingerprints
#                                  of three pilot pieces, the tag estimate with AI tagging on
#   d_app() -> FastAPI             I0's fake app with D's routes first; wardrobe_add registers a
#                                  piece in I0's store, a saved fingerprint is offered next time;
#                                  D's two split-out modules served until I1 lists them
#                                  (asset_routes)
#   python tests/r13_fakes_d.py <port>   serve it (uvicorn; JARVIS_* as the browser tests set)
#   serve_d(token) -> (url, stop)  start that server for a browser test module, healthy
#   Picture(w, h)                  a drawn picture (a surface, stripes, a QR, a face, a
#                                  silhouette): .png(), and y4m(path, pictures) for Chromium's fake
#                                  camera. Generated test patterns only: never a photo or a face.
#
# Not a test module (pytest does not collect it).
from __future__ import annotations

import base64
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from r13_fakes import PILOT, UID, ev, ist, piece
from r13_record import record

from jarvis.api.auth import require_auth
from jarvis.wardrobe import http
from jarvis.wardrobe.ports import Commit, WardrobePart

NOW = ist(2026, 11, 16, 9, 0)  # Monday 16 Nov 2026, 09:00 IST: I0's fake store seeds the pilot
# D's fake server answers from 09:30: a phone's event, corrected by `at + (now - sent)` (D4.1),
# then lands after the seeded registrations, never on their very instant
SERVED_AT = ist(2026, 11, 16, 9, 30)


@dataclass
class FakeData:
    """One part's `WardrobeData`: `items` documents for `UID`; delete empties them. `row` is the
    Privacy row it says it belongs to (the contract's field proposed for I1); None: by name."""

    name: str
    items: list[dict[str, Any]] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    fail: bool = False
    row: str | None = None

    async def count(self, uid: str) -> int:
        if self.fail:
            raise RuntimeError("the store could not be read")
        return len(self.items) if uid == UID else 0

    async def export(self, uid: str) -> dict[str, Any]:
        return {"items": list(self.items) if uid == UID else []}

    async def delete(self, uid: str) -> int:
        n = len(self.items) if uid == UID else 0
        self.deleted.append(uid)
        if uid == UID:
            self.items.clear()
        return n


def parts_with(*data: FakeData) -> dict[str, WardrobePart]:
    """`app.state.r13_parts` with each data source on its owner (pieces and photos A, laundry B,
    outfits C; anything else on A)."""
    owner = {"laundry": "laundry", "outfits": "styling"}
    by: dict[str, list[FakeData]] = {"catalog": [], "laundry": [], "styling": []}
    for d in data:
        by[owner.get(d.name, "catalog")].append(d)
    return {
        name: WardrobePart(name, data=tuple(ds), ready="ready")  # type: ignore[arg-type]
        for name, ds in by.items()
    }


# ---- the browser tests' server ------------------------------------------------------------------
P = [p.id for p in PILOT]
SHIRT, WHITE, NAVY, VEST1, VEST2, BELT, WATCH = P[0], P[1], P[2], P[8], P[9], P[19], P[20]
DRAWER, RACK = "wl_00000001", "wl_00000002"
LABELS = {"abcdefgh": NAVY, "qrstuvwx": VEST1}  # his two printed labels (QR payload jw1:<code>)


def _fingerprint(seed: int) -> str:
    raw = bytes((seed * 7 + i * 13) % 256 for i in range(1280))
    return base64.b64encode(raw).decode()


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) from a JPEG's SOF marker, as the server reads it (never decoded)."""
    i = 2
    while data[:2] == b"\xff\xd8" and i + 9 < len(data):
        if data[i] != 0xFF:
            return None
        marker, size = data[i + 1], int.from_bytes(data[i + 2 : i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2):
            h = int.from_bytes(data[i + 5 : i + 7], "big")
            return int.from_bytes(data[i + 7 : i + 9], "big"), h
        i += 2 + size
    return None


def d_routes(state: dict[str, Any], store: Any = None, clock: Any = None) -> APIRouter:
    # the models are imported at module level: FastAPI resolves these (postponed) annotations there
    r = APIRouter(dependencies=[Depends(require_auth)])
    ok = lambda m: JSONResponse(m.model_dump(mode="json"), headers={"Cache-Control": "no-store"})  # noqa: E731
    saved: list[tuple[str, str]] = []  # (piece, fingerprint) posted by "Remember how it looks"

    async def register(args: dict[str, Any]) -> str:
        made = state.setdefault("clients", {})  # A: a piece's id is keyed by its client id
        if args.get("client_id") in made:
            return str(made[args["client_id"]])
        pid = f"wi_{0xF0 + len(state['added']):012x}"
        state["added"].append(pid)
        if args.get("client_id"):
            made[args["client_id"]] = pid
        if store is not None:
            colour = args.get("colour") if isinstance(args.get("colour"), str) else None
            rec = piece(pid, str(args.get("type") or "shirt"), colour=colour)
            rec = rec.model_copy(update={"private": bool(args.get("private"))})

            async def fn(view: Any, tx: Any) -> Commit:
                return Commit(events=(ev(pid, "registered", clock()),), records=(rec,))

            await store.transact(UID, fn)
        return pid

    @r.post("/v1/wardrobe/tools/{tool}")
    async def tool(tool: str, body: http.ToolCall) -> JSONResponse:
        state["tools"].append({"tool": tool, "arguments": body.arguments})
        record("panel", tool, body.arguments)  # I1's replay corpus (a no-op unless asked for)
        result: dict[str, object] = {}
        if tool == "wardrobe_add":  # A's shape: {pieces: [...]} -> {status, ids, new}
            pieces = body.arguments.get("pieces")
            items = [p for p in pieces if isinstance(p, dict)] if isinstance(pieces, list) else []
            ids = [await register(p) for p in items]
            result = {"status": "done", "ids": ids, "new": ids}
        return ok(http.ToolReply(status="executed", message="Done, Sir.", result=result))

    @r.put("/v1/wardrobe/settings")  # A's settings route, proposed for I1 (INTEGRATION-D section 6)
    async def wardrobe_settings(request: Request) -> JSONResponse:
        state.setdefault("settings", []).append(await request.json())
        return JSONResponse({"status": "saved"}, headers={"Cache-Control": "no-store"})

    @r.get("/v1/wardrobe/fingerprints")
    async def prints(model: str = "mnv2-int8-1") -> JSONResponse:
        items = [
            http.FingerprintView(piece=pid, view="front", v=_fingerprint(i))
            for i, pid in enumerate((SHIRT, WHITE, NAVY))
        ]
        items += [http.FingerprintView(piece=pid, view="front", v=v) for pid, v in saved]
        return ok(http.Fingerprints(model=model, items=tuple(items)))  # type: ignore[arg-type]

    @r.post("/v1/wardrobe/fingerprints")
    async def keep_print(body: http.FingerprintIn) -> JSONResponse:
        state["fingerprints"].append(body.piece)
        saved.append((body.piece, body.v))
        return ok(http.FingerprintSaved(piece=body.piece, view=body.view, model=body.model))

    @r.post("/v1/wardrobe/photos")
    async def photo(request: Request, piece: str, view: str) -> JSONResponse:
        body = await request.body()
        size = jpeg_size(body)
        state["photos"].append({"piece": piece, "view": view, "bytes": len(body), "size": size})
        return ok(http.PhotoSaved(photo="wh_00000000000a", piece=piece, view=view, bytes=len(body)))  # type: ignore[arg-type]

    @r.get("/v1/test/r13-d", include_in_schema=False)
    async def seen() -> JSONResponse:  # what the fake server was sent (the browser tests read it)
        return JSONResponse(state)

    @r.get("/v1/wardrobe/tag/estimate")
    async def estimate(piece: str) -> JSONResponse:
        return ok(http.TagEstimate(inr=0.01, month_inr=0.02, cap_inr=30, allowed=True))

    @r.post("/v1/wardrobe/tag")
    async def tag(request: Request, piece: str) -> JSONResponse:
        state["tags"].append({"piece": piece, "bytes": len(await request.body())})
        s = http.TagSuggestion(category="tops", type="shirt", colour="navy", pattern="striped")
        return ok(http.TagReply(piece=piece, suggestion=s, inr=0.01, month_inr=0.03))

    @r.get("/v1/laundry/review")
    async def review() -> JSONResponse:
        e = http.ReviewEntry(
            id="rv_1", kind="hold", pieces=(VEST1, VEST2), candidates=(VEST1, VEST2),
            words="Which of these went into the basket?", opened_at=NOW,
        )  # fmt: skip
        return ok(http.ReviewView(ready="fake", entries=(e,), open=1))

    @r.get("/v1/outfits")
    async def outfits() -> JSONResponse:
        look = http.Look(
            pieces=(
                http.SlotPick(slot="top", piece=SHIRT, words="a light blue shirt"),
                http.SlotPick(slot="bottom", piece=P[4], words="charcoal trousers", locked=True),
                http.SlotPick(slot="belt", piece=BELT, words="a black belt"),
                http.SlotPick(slot="watch", piece=WATCH, words="a grey watch"),
                http.SlotPick(slot="base", piece=VEST1, words="a private basic"),
            ),
            reasons=("Business formal for the 10:00 event", "Light blue goes with charcoal"),
            gaps=("Press the white shirt for Wednesday",),
        )
        plan = http.PlanView(
            id="pl_1", day=datetime(2026, 11, 17).date(), starts=ist(2026, 11, 17, 10, 0),
            dress_code="business formal", tentative=False, look=look, manual=False,
        )  # fmt: skip
        return ok(
            http.OutfitsView(
                ready="fake", tomorrow=(plan,),
                weather="Weather for your home area: rain likely from 15:00.",
            )
        )  # fmt: skip

    return r


# D's two console modules split out at REVIEW-D-1 (each imported on first use by its parent).
# Until I1 lists them in `api/console.APP_ASSETS` (INTEGRATION-D section 6), this test server
# serves them the way the app serves an asset; once listed, the app's own route answers and this
# one steps aside.
NEW_ASSETS = ("console-vision-r13.js", "console-wardrobe-words.js")


def asset_routes() -> APIRouter:
    from fastapi.responses import FileResponse

    from jarvis.api.console import APP_ASSETS

    static = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "api" / "static"
    r = APIRouter()
    for name in (n for n in NEW_ASSETS if n not in APP_ASSETS):

        async def serve(name: str = name) -> FileResponse:
            heads = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
            return FileResponse(static / name, media_type="application/javascript", headers=heads)

        r.add_api_route(f"/static/{name}", serve, methods=["GET"], include_in_schema=False)
    return r


def d_state() -> dict[str, Any]:
    return {"tools": [], "fingerprints": [], "photos": [], "tags": [], "added": []}


async def with_labels(store: Any) -> None:
    """His two printed labels in the fake index (No. 1 on the navy shirt, No. 2 on a vest), as
    I0's seeded store writes its pairs and places."""
    from jarvis.storage.docs import Set
    from jarvis.wardrobe.model import WardrobeLabel

    path = f"jarvis_wardrobe/{UID}"
    view = store._view_of(UID, await store.docs.get(path) or {})  # noqa: SLF001 - the fakes' set-up
    labels = {
        code: WardrobeLabel.model_validate({"code": code, "number": n, "piece": pid})
        for n, (code, pid) in enumerate(LABELS.items(), start=1)
    }
    pieces = dict(view.pieces)
    for code, pid in LABELS.items():
        pieces[pid] = pieces[pid].model_copy(update={"label_code": code})
    fresh = view.model_copy(update={"labels": labels, "pieces": pieces})
    await store.docs.write([Set(path, fresh.to_json())])


def d_app() -> Any:
    import asyncio

    from r13_fake_server import fake_app, fake_state

    store, clock = asyncio.run(fake_state())
    asyncio.run(with_labels(store))
    clock.set(SERVED_AT)
    app = fake_app(store, clock)
    state = d_state()
    app.router.routes[:0] = [*asset_routes().routes, *d_routes(state, store, clock).routes]
    app.state.r13_d = state
    return app


# ---- No-AI: I1's runner step, and a Telegram gateway -------------------------------------------
async def run_taking(route: Any, result: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """The runner step proposed for I1 (INTEGRATION-D section 6, `offline/no_ai.py`): each call in
    order, a `TakeCall` filled from the result before it; a value that is not an id ends the turn
    (that result's words are the reply). Every call here answers `result`."""
    ran: list[tuple[str, dict[str, Any]]] = []
    before: dict[str, Any] = {}
    for call in route.calls:
        args = dict(call.arguments)
        for arg, key in getattr(call, "take", ()):
            value = before.get(key)
            if not isinstance(value, str) or not value:
                return ran
            args[arg] = value
        ran.append((call.tool, args))
        before = result
    return ran


async def telegram_gateway(*, personal: bool) -> tuple[Any, list[str]]:
    """A gateway with fake No-AI tools behind Telegram's rules, paired, the personal switch set."""
    from telegram_fakes import Clock

    from jarvis.core.guardrails import ActionRisk, ConfirmationGate
    from jarvis.storage.docs import MemoryDocs
    from jarvis.telegram.rules import wrap_rules
    from jarvis.telegram.store import TelegramStore
    from jarvis.tools import AuditLog, Gateway, Policy, ToolRegistry
    from jarvis.tools.base import Tool

    seen: list[str] = []
    reads = {"wardrobe_find", "wardrobe_count", "laundry_status", "outfit_suggest"}
    reg = ToolRegistry()

    def tool(name: str) -> Tool:
        async def run(a: dict[str, Any]) -> dict[str, Any]:
            seen.append(name)
            return {"found": True, "best": NAVY} if name == "wardrobe_find" else {"message": "ok"}

        risk = ActionRisk.READ_ONLY if name in reads else ActionRisk.REVERSIBLE
        return Tool(name, f"fake {name}", {"type": "object", "properties": {}}, risk, run)

    for name in sorted(reads | {"wardrobe_edit", "laundry_move", "wear_log", "belongings_where"}):
        reg.register(tool(name))
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    store = TelegramStore(MemoryDocs(), prefix="t_", clock=Clock())
    code, _ = await store.start_pairing(UID)
    await store.finish_pairing(code, tg_user_id=1, chat_id=2)
    await store.set_settings(UID, allow_private_reads=True, allow_personal_reads=personal)
    gw.rules = wrap_rules(None, store)
    return gw, seen


# ---- drawn pictures (standard library only: CI's browser job has no Pillow) ----------------------
class Picture:
    def __init__(self, w: int, h: int, bg: tuple[int, int, int] = (232, 228, 220)) -> None:
        self.w, self.h = w, h
        self.px = bytearray(bytes(bg) * (w * h))

    def put(self, x: int, y: int, rgb: tuple[int, int, int]) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[(y * self.w + x) * 3 : (y * self.w + x) * 3 + 3] = bytes(rgb)

    def rect(self, x0: int, y0: int, w: int, h: int, rgb: Any) -> Picture:
        for y in range(max(0, y0), min(self.h, y0 + h)):
            for x in range(max(0, x0), min(self.w, x0 + w)):
                self.put(x, y, rgb(x, y) if callable(rgb) else rgb)
        return self

    def ellipse(self, cx: float, cy: float, rx: float, ry: float, rgb: Any) -> Picture:
        for y in range(max(0, int(cy - ry)), min(self.h, int(cy + ry) + 1)):
            for x in range(max(0, int(cx - rx)), min(self.w, int(cx + rx) + 1)):
                if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1:
                    self.put(x, y, rgb(x, y) if callable(rgb) else rgb)
        return self

    def shirt(self, x0: int, y0: int, s: float) -> Picture:  # navy and white stripes, laid flat
        def stripes(x: int, y: int) -> tuple[int, int, int]:
            return (28, 36, 78) if (x // max(2, int(14 * s))) % 2 else (240, 240, 236)

        self.rect(x0 + int(40 * s), y0, int(120 * s), int(240 * s), stripes)
        self.rect(x0, y0, int(40 * s), int(90 * s), stripes)
        return self.rect(x0 + int(160 * s), y0, int(40 * s), int(90 * s), stripes)

    def face(self, cx: float, cy: float, s: float) -> Picture:  # a drawn face (UltraFace finds it)
        self.ellipse(cx, cy + s * 0.05, s * 0.42, s * 0.55, (70, 45, 30))
        self.ellipse(cx, cy + s * 0.12, s * 0.36, s * 0.47, (224, 172, 140))
        for dx in (-0.14, 0.14):
            self.ellipse(cx + s * dx, cy, s * 0.07, s * 0.035, (250, 250, 250))
            self.ellipse(cx + s * dx, cy, s * 0.03, s * 0.03, (40, 30, 20))
        self.ellipse(cx, cy + s * 0.15, s * 0.04, s * 0.08, (200, 140, 110))
        return self.ellipse(cx, cy + s * 0.32, s * 0.11, s * 0.035, (170, 70, 70))

    def figure(self, cx: float, top: float, s: float) -> Picture:  # a dark silhouette (SSD: person)
        ink = (30, 28, 34)
        self.ellipse(cx, top + 30 * s, 24 * s, 30 * s, ink)
        self.ellipse(cx, top + 115 * s, 52 * s, 70 * s, ink)
        self.rect(int(cx - 38 * s), int(top + 165 * s), int(32 * s), int(110 * s), ink)
        self.rect(int(cx + 6 * s), int(top + 165 * s), int(32 * s), int(110 * s), ink)
        self.ellipse(cx - 58 * s, top + 120 * s, 14 * s, 60 * s, ink)
        return self.ellipse(cx + 58 * s, top + 120 * s, 14 * s, 60 * s, ink)

    def qr(self, x0: int, y0: int, text: str, k: int = 6) -> Picture:  # a quiet zone, black modules
        import segno

        rows = segno.make(text, error="m", micro=False).matrix
        n = len(rows)
        self.rect(x0, y0, (n + 8) * k, (n + 8) * k, (255, 255, 255))
        for j, row in enumerate(rows):
            for i, on in enumerate(row):
                if on:
                    self.rect(x0 + (i + 4) * k, y0 + (j + 4) * k, k, k, (0, 0, 0))
        return self

    def png(self) -> bytes:
        import struct
        import zlib

        rows = b"".join(
            b"\x00" + bytes(self.px[y * self.w * 3 : (y + 1) * self.w * 3]) for y in range(self.h)
        )

        def chunk(kind: bytes, data: bytes) -> bytes:
            body = kind + data
            return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

        head = struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0)
        idat = chunk(b"IDAT", zlib.compress(rows, 6))
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + idat + chunk(b"IEND", b"")

    def i420(self) -> bytes:
        w, h, px = self.w, self.h, self.px
        y_plane = bytearray(w * h)
        u_plane, v_plane = bytearray((w // 2) * (h // 2)), bytearray((w // 2) * (h // 2))
        for i in range(w * h):
            r, g, b = px[i * 3], px[i * 3 + 1], px[i * 3 + 2]
            y_plane[i] = max(0, min(255, round(0.257 * r + 0.504 * g + 0.098 * b + 16)))
        for y in range(0, h, 2):
            for x in range(0, w, 2):
                i = (y * w + x) * 3
                r, g, b = px[i], px[i + 1], px[i + 2]
                j = (y // 2) * (w // 2) + x // 2
                u_plane[j] = max(0, min(255, round(-0.148 * r - 0.291 * g + 0.439 * b + 128)))
                v_plane[j] = max(0, min(255, round(0.439 * r - 0.368 * g - 0.071 * b + 128)))
        return bytes(y_plane + u_plane + v_plane)


def y4m(path: Any, pictures: list[Picture], fps: int = 10) -> Any:
    """Chromium's fake camera clip: the pictures as I420 frames, looped by the browser."""
    w, h = pictures[0].w, pictures[0].h
    with open(path, "wb") as f:
        f.write(f"YUV4MPEG2 W{w} H{h} F{fps}:1 Ip A1:1 C420jpeg\n".encode())
        for pic in pictures:
            f.write(b"FRAME\n" + pic.i420())
    return path


def serve_d(token: str) -> tuple[str, Any]:
    """This file's server for a browser test module: (url, stop)."""
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
        [sys.executable, str(root / "tests" / "r13_fakes_d.py"), str(port)],
        cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )  # fmt: skip
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("the R13 D fake server exited early")
        try:
            with urllib.request.urlopen(url + "/health", timeout=1) as r:
                if r.status == 200:
                    break
        except OSError:
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError("the R13 D fake server did not become healthy")

    def stop() -> None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    return url, stop


def main(argv: list[str]) -> int:
    import uvicorn

    port = int(argv[1]) if len(argv) > 1 else 8766
    uvicorn.run(d_app(), host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

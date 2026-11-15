# tests/r13_fakes_d.py -- R13 Part D's fakes (imported bare: `from r13_fakes_d import ...`). Every
# clock is fixed (r13_fakes' IST helpers); nothing here talks to Google or spends anything.
#
#   FakeData(name, items)          one part's WardrobeData (count, export, delete), recording
#   parts_with(*data)              the app's `r13_parts` with those data sources on A, B and C
#   d_routes(state) -> APIRouter   D's browser-test answers AHEAD of I0's fake server
#                                  (tests/r13_fake_server.py): a review queue, a plan, the tools
#                                  route recording every call (status "executed"), fingerprints
#                                  of three pilot pieces, the tag estimate with AI tagging on
#   d_app() -> FastAPI             I0's fake app with D's routes first
#   python tests/r13_fakes_d.py <port>   serve it (uvicorn; JARVIS_* as the browser tests set)
#
# Not a test module (pytest does not collect it).
from __future__ import annotations

import base64
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from r13_fakes import PILOT, UID, ist

from jarvis.wardrobe.ports import WardrobePart

NOW = ist(2026, 11, 16, 9, 0)  # Monday 16 Nov 2026, 09:00 IST: the browser tests' page clock too


@dataclass
class FakeData:
    """One part's `WardrobeData`: `items` documents for `UID`; delete empties them."""

    name: str
    items: list[dict[str, Any]] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    fail: bool = False

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


def d_routes(state: dict[str, Any]) -> Any:
    from fastapi import APIRouter, Depends, Request
    from fastapi.responses import JSONResponse

    from jarvis.api.auth import require_auth
    from jarvis.wardrobe import http

    r = APIRouter(dependencies=[Depends(require_auth)])
    ok = lambda m: JSONResponse(m.model_dump(mode="json"), headers={"Cache-Control": "no-store"})  # noqa: E731

    @r.post("/v1/wardrobe/tools/{tool}")
    async def tool(tool: str, body: http.ToolCall) -> JSONResponse:
        state["tools"].append({"tool": tool, "arguments": body.arguments})
        result: dict[str, object] = {"piece": "wi_0000000000ff"} if tool == "wardrobe_add" else {}
        return ok(http.ToolReply(status="executed", message="Done, Sir.", result=result))

    @r.get("/v1/wardrobe/fingerprints")
    async def prints(model: str = "mnv2-int8-1") -> JSONResponse:
        items = tuple(
            http.FingerprintView(piece=pid, view="front", v=_fingerprint(i))
            for i, pid in enumerate((SHIRT, WHITE, NAVY))
        )
        return ok(http.Fingerprints(model=model, items=items))  # type: ignore[arg-type]

    @r.post("/v1/wardrobe/fingerprints")
    async def keep_print(body: http.FingerprintIn) -> JSONResponse:
        state["fingerprints"].append(body.piece)
        return ok(http.FingerprintSaved(piece=body.piece, view=body.view, model=body.model))

    @r.post("/v1/wardrobe/photos")
    async def photo(request: Request, piece: str, view: str) -> JSONResponse:
        body = await request.body()
        state["photos"].append({"piece": piece, "view": view, "bytes": len(body)})
        return ok(http.PhotoSaved(photo="wh_00000000000a", piece=piece, view=view, bytes=len(body)))  # type: ignore[arg-type]

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


def d_state() -> dict[str, Any]:
    return {"tools": [], "fingerprints": [], "photos": [], "tags": []}


def d_app() -> Any:
    import asyncio

    from fastapi.responses import JSONResponse
    from r13_fake_server import fake_app, fake_state

    store, clock = asyncio.run(fake_state())
    app = fake_app(store, clock)
    state = d_state()
    app.router.routes[:0] = d_routes(state).routes
    app.state.r13_d = state

    @app.get("/v1/test/r13-d", include_in_schema=False)
    async def seen() -> JSONResponse:  # what the fake server was sent (the browser tests read it)
        return JSONResponse(state)

    return app


def main(argv: list[str]) -> int:
    import uvicorn

    port = int(argv[1]) if len(argv) > 1 else 8766
    uvicorn.run(d_app(), host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

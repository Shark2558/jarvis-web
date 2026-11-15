# tests/r13_fake_server.py -- R13 I0 (docs/plans/r13-wardrobe.md "The HTTP contract", plan review
# H5): every route of `jarvis.wardrobe.http.ROUTES`, answered from the fakes (`r13_fakes`: the
# in-memory store seeded with the pilot set, a FIXED clock), each reply validated by its model, so
# Part D's console and browser tests run end to end before A, B and C exist. At I1 D's browser
# tests move to the wired app.
#
#   fake_routes(store, clock) -> APIRouter     the 23 routes (owner-only like the real ones)
#   fake_app(...) -> FastAPI                   the real console app (mock brain) with these routes
#                                              ahead of the parts' own
#   python tests/r13_fake_server.py <port>     serve it (uvicorn; JARVIS_* as the browser tests set)
#
# Not a test module (pytest does not collect it). Imported bare (`from r13_fake_server import ...`).
from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from r13_fakes import UID, FixedClock, MemoryWardrobeStore, ev, ist, seeded_store

from jarvis.api.auth import require_auth
from jarvis.wardrobe import http
from jarvis.wardrobe.model import Event, Piece, WardrobeView
from jarvis.wardrobe.ports import Commit, Refused
from jarvis.wardrobe.states import STATE_WORDS, wearable_pair, wearable_set

NO_STORE = {"Cache-Control": "no-store"}
READY = "fake: tests/r13_fake_server.py"


def _ok(model: http.Ready | Any, status: int = 200) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json"), status_code=status, headers=NO_STORE)


def _err(status: int, words: str) -> JSONResponse:
    return JSONResponse({"detail": words}, status_code=status, headers=NO_STORE)


def piece_view(p: Piece, view: WardrobeView) -> http.PieceView:
    place = view.places.get(p.place or "")
    pair = next((x.id for x in view.pairs.values() if p.id in x.pieces), None)
    sets = tuple(s.id for s in view.sets.values() if any(x.piece == p.id for x in s.parts))
    return http.PieceView(
        id=p.id, category=p.category, type=p.type, label=p.label, colour=p.colour,
        second=p.second, pattern=p.pattern, locked=p.locked, features=dict(p.features),
        size=(p.size.v, p.size.ok) if p.size else None,
        brand=(p.brand.v, p.brand.ok) if p.brand else None,
        fabric=tuple((f.v, f.ok) for f in p.fabric), care=tuple((c.v, c.ok) for c in p.care),
        formality=p.formality, occasions=p.occasions, weather=p.weather, mess_ok=p.mess_ok,
        delicate=p.delicate, private=p.private, state=p.state, state_words=STATE_WORDS[p.state],
        eligible=p.eligible, place=p.place, place_words=place.label if place else "",
        place_at=p.place_at, expected_back=p.expected_back, hold=p.hold, wears=p.wears,
        last_worn=p.last_worn, label_code=p.label_code, photos=p.photos, pair=pair, sets=sets,
    )  # fmt: skip


def wardrobe_view(view: WardrobeView, *, show_private: bool = False) -> http.WardrobeView:
    active = view.active()
    shown = [p for p in active if show_private or not p.private]
    state = {p.id: p.state for p in view.pieces.values()}
    pairs = tuple(
        http.PairView(
            id=x.id, pieces=x.pieces, wearable=wearable_pair([state.get(i) for i in x.pieces]),
            missing=tuple(i for i in x.pieces if state.get(i) != "ready"),
        )
        for x in view.pairs.values()
    )  # fmt: skip
    sets = []
    for s in view.sets.values():
        whole, alone = wearable_set([(state.get(x.piece), x.alone) for x in s.parts])
        sets.append(
            http.SetView(
                id=s.id, label=s.label, parts=tuple((x.piece, x.alone) for x in s.parts),
                wearable=whole, alone=tuple(s.parts[i].piece for i in alone),
            )
        )  # fmt: skip
    by_cat: dict[str, list[Piece]] = {}
    for p in active:
        by_cat.setdefault(p.category, []).append(p)
    counts = http.Counts(
        owned=len(active), ready=sum(p.eligible for p in active),
        review=sum(p.state == "review" for p in active),
        pairs_complete=sum(x.wearable for x in pairs), pairs=len(pairs),
        sets_complete=sum(x.wearable for x in sets), sets=len(sets),
        by_category=tuple(
            http.CountRow(category=c, owned=len(ps), ready=sum(p.eligible for p in ps))  # type: ignore[arg-type]
            for c, ps in sorted(by_cat.items())
        ),
        places_without_baseline=sum(pl.baseline_at is None for pl in view.places.values()),
    )  # fmt: skip
    return http.WardrobeView(
        ready=READY, rev=view.rev, pieces=tuple(piece_view(p, view) for p in shown[:200]),
        private_hidden=len(active) - len(shown), counts=counts, pairs=pairs, sets=tuple(sets),
        places=tuple(
            http.PlaceView(id=pl.id, label=pl.label, kind=pl.kind, baseline_at=pl.baseline_at)
            for pl in view.places.values()
        ),
        labels=tuple(
            http.LabelView(code=lb.code, number=lb.number, piece=lb.piece)
            for lb in view.labels.values()
        ),
    )  # fmt: skip


def _event(e: http.EventIn, now: datetime) -> Event:
    at = e.stated_at or (datetime.combine(e.day, datetime.min.time()) if e.day else None)
    return ev(
        e.piece, e.kind, e.at or at or now, sent=e.sent, verified=e.verified, how=e.how,
        score=e.score, source=e.source, via=e.via, to=e.to, place=e.place, plan=e.plan,
        due=e.due, batch=e.batch, load=e.load, client_id=e.client_id, note=e.note,
    )  # fmt: skip


def fake_routes(store: MemoryWardrobeStore, clock: Callable[[], datetime]) -> APIRouter:
    r = APIRouter(dependencies=[Depends(require_auth)])
    photos: dict[str, bytes] = {}

    @r.get("/v1/r13")
    async def status() -> JSONResponse:
        parts = tuple(http.Ready(part=p, ready=READY) for p in ("catalog", "laundry", "styling"))
        return _ok(
            http.R13Status(version="v13.0.0", parts=(*parts, http.Ready(part="phone", ready=READY)))
        )

    @r.get("/v1/wardrobe")
    async def view(request: Request) -> JSONResponse:
        private = request.query_params.get("private") == "1"
        return _ok(wardrobe_view(await store.view(UID), show_private=private))

    @r.get("/v1/wardrobe/pieces/{pid}")
    async def piece(pid: str) -> JSONResponse:
        v = await store.view(UID)
        p = v.piece(pid)
        if p is None:
            return _err(404, "That piece isn't in your wardrobe.")
        hist = await store.history(UID, pid)
        rows = tuple(
            http.EventView(id=h.event.id, kind=h.event.kind, at=h.event.at, source=h.event.source,
                           verified=h.event.verified, mark=h.mark, to=h.event.to, note=h.event.note)
            for h in hist[-50:]
        )  # fmt: skip
        return _ok(
            http.PieceDetail(piece=piece_view(p, v), history=rows, step=STATE_WORDS[p.state])
        )

    @r.post("/v1/wardrobe/scan")
    async def scan(body: http.ScanRequest) -> JSONResponse:
        events = tuple(_event(e, clock()) for e in body.events)

        async def fn(view: WardrobeView, tx: Any) -> Commit:
            return Commit(events=events)

        try:
            got = await store.transact(UID, fn)
        except Refused as exc:
            return _err(422, str(exc))
        by_client = {e.id: e.client_id or e.id for e in events}
        marks = {by_client.get(k, k): m for k, m in got.marks.items()}
        n_dup = sum(m in ("duplicate", "known") for m in got.marks.values())
        reply = http.ScanReply(
            applied=sum(m == "applied" for m in got.marks.values()), duplicates=n_dup,
            review=len(got.needed), already_done=got.already, marks=marks,
            message="Already done." if got.already else "Saved.",
            view=wardrobe_view(got.view) if got.already else None,
        )  # fmt: skip
        return _ok(reply)

    @r.post("/v1/wardrobe/photos")
    async def photo(request: Request, piece: str, view: str) -> JSONResponse:
        body = await request.body()
        if request.headers.get("content-type") != "image/jpeg" or not body.startswith(b"\xff\xd8"):
            return _err(422, "Only a JPEG photo of a saved piece can be kept.")
        if len(body) > 200 * 1024:
            return _err(413, "That photo is too large.")
        pid = "wh_" + f"{len(photos) + 1:012x}"
        photos[pid] = body
        return _ok(http.PhotoSaved(photo=pid, piece=piece, view=view, bytes=len(body)))  # type: ignore[arg-type]

    @r.delete("/v1/wardrobe/photos/{pid}")
    async def unphoto(pid: str) -> JSONResponse:
        gone = photos.pop(pid, None) is not None
        return _ok(http.Deleted(deleted=gone, message="Deleted." if gone else "Not found."))

    @r.get("/v1/wardrobe/photos/{pid}")
    async def get_photo(pid: str) -> Response:
        if pid not in photos:
            return _err(404, "Not found.")
        return Response(photos[pid], media_type="image/jpeg", headers=NO_STORE)

    @r.get("/v1/wardrobe/fingerprints")
    async def prints(model: str = "mnv2-int8-1") -> JSONResponse:
        return _ok(http.Fingerprints(model=model))  # type: ignore[arg-type]

    @r.post("/v1/wardrobe/fingerprints")
    async def keep_print(body: http.FingerprintIn) -> JSONResponse:
        return _ok(http.FingerprintSaved(piece=body.piece, view=body.view, model=body.model))

    @r.post("/v1/wardrobe/tag")
    async def tag(piece: str) -> JSONResponse:
        empty = http.TagSuggestion()
        return _ok(http.TagReply(piece=piece, suggestion=empty, inr=0.01, month_inr=0.01))

    @r.get("/v1/wardrobe/tag/estimate")
    async def estimate(piece: str) -> JSONResponse:
        return _ok(
            http.TagEstimate(
                inr=0.01, month_inr=0.0, cap_inr=30, allowed=False, why="AI tagging is off."
            )
        )

    @r.get("/v1/wardrobe/labels.svg")
    async def labels() -> Response:
        svg = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>'
        heads = {**NO_STORE, "Content-Security-Policy": "default-src 'none'"}
        heads |= {"X-Content-Type-Options": "nosniff", "Content-Disposition": "attachment"}
        return Response(svg, media_type="image/svg+xml", headers=heads)

    @r.post("/v1/wardrobe/labels")
    async def assign(body: http.LabelAssign) -> JSONResponse:
        return _ok(http.LabelView(code=body.code, number=1, piece=body.piece))

    @r.get("/v1/wardrobe/backup")
    async def backup() -> Response:
        return Response(b"JWB1-fake", media_type="application/octet-stream", headers=NO_STORE)

    counts = http.RestoreCounts(
        added=0, already_there=0, superseded=0, back_from_bin=0, purged_since=0, events=0
    )

    @r.post("/v1/wardrobe/restore/check")
    async def restore_check() -> JSONResponse:
        return _ok(http.RestoreCheck(token="t" * 16, counts=counts, message="Nothing to add."))

    @r.post("/v1/wardrobe/restore")
    async def restore() -> JSONResponse:
        return _ok(http.RestoreDone(counts=counts, chunks=0, message="Nothing to add."))

    @r.get("/v1/wardrobe/pilot")
    async def pilot() -> JSONResponse:
        zero = dict.fromkeys(http.Pilot.model_fields, 0)
        return _ok(http.Pilot(**zero))

    @r.post("/v1/wardrobe/tools/{tool}")
    async def tool(tool: str, body: http.ToolCall) -> JSONResponse:
        return _ok(http.ToolReply(status="error", message="The fake server runs no tool."))

    @r.get("/v1/laundry")
    async def laundry() -> JSONResponse:
        v = await store.view(UID)
        of = lambda s: tuple(p.id for p in v.active() if p.state == s)  # noqa: E731
        return _ok(
            http.LaundryView(
                ready=READY, basket=of("in_laundry"), drying=of("drying"), prep=of("needs_prep")
            )
        )

    @r.get("/v1/laundry/review")
    async def review() -> JSONResponse:
        return _ok(http.ReviewView(ready=READY, open=0))

    @r.get("/v1/outfits")
    async def outfits() -> JSONResponse:
        return _ok(http.OutfitsView(ready=READY, weather="Weather unknown: I assumed indoors."))

    @r.get("/v1/outfits/calendars")
    async def calendars() -> JSONResponse:
        return _ok(
            http.Calendars(why="Your Calendar permission is Ask first: allow it, or plan by hand.")
        )

    @r.put("/v1/outfits/settings")
    async def settings(body: http.OutfitSettings) -> JSONResponse:
        return _ok(http.SettingsView(calendar_chosen=body.calendar is not None, fields=body.fields,
                                     lead_h=body.lead_h, plan_alerts=body.plan_alerts,
                                     auto_swap=body.auto_swap))  # fmt: skip

    return r


async def fake_state(clock: FixedClock | None = None) -> tuple[MemoryWardrobeStore, FixedClock]:
    return await seeded_store(now=clock or FixedClock(ist(2026, 11, 16, 9, 0)))


def fake_app(
    wardrobe: MemoryWardrobeStore, clock: Callable[[], datetime], **app_kw: Any
) -> FastAPI:
    """The real app (mock brain) with the fake R13 routes AHEAD of the parts' own."""
    from jarvis.api import create_app
    from jarvis.llm.mock_provider import MockProvider

    app = create_app(provider=MockProvider(), **app_kw)
    routes = fake_routes(wardrobe, clock).routes
    app.router.routes[:0] = routes
    return app


def main(argv: list[str]) -> int:
    import asyncio

    import uvicorn

    port = int(argv[1]) if len(argv) > 1 else 8765
    store, clock = asyncio.run(fake_state())
    uvicorn.run(fake_app(store, clock), host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

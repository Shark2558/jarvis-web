# tests/r131_fake_seeme.py -- R13.1 I0 (docs/plans/r13-1-try-on.md "The HTTP contract", D13, D22):
# the "See it on me" half of `tests/r131_fake_server.py`, every `/v1/seeme` route answered from page
# memory with its contract model. See it on me pictures him in a garment he is thinking of BUYING
# (the owner, 17 Nov 2026): he gives its photo (POST /v1/seeme/garments?type=&colour=), JARVIS
# suggests his own pieces to pair with it (GET /v1/seeme/pair), and a picture shows the new
# garment with at most two of his. The new garment is never a wardrobe piece. Nothing here calls
# Google: a picture is I0's made-up PNG.
#
#   FakeSeeMe                          what the fake keeps (never on disk)
#   seeme_routes(view, clock)          the routes (owner-only; console-only is not simulated)
#
# Not a test module. Imported bare (`from r131_fake_seeme import ...`).
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from r131_fake_tryon import PNG
from r131_fakes import NOW, PRIVATE, T

from jarvis.api.auth import require_auth
from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.tryon import http
from jarvis.wardrobe.tryon import model as m

NO_STORE = {"Cache-Control": "no-store"}
READY = "fake: tests/r131_fake_server.py"
CONSENT_VERSION = "c2"
CONSENT_WORDS = (
    "What is sent: your photo, the photo you give of a garment you are thinking of buying, and the "
    "photos of up to two of your own pieces worn with it. Never a private piece, your measurements "
    "or anything else.",
    "To whom: Google Cloud's Agent Platform, Gemini 3.1 Flash Image, processed in the United "
    "States.",
    "Every picture shows its price first, under your monthly limit. Delete your photo to withdraw.",
)
TYPICAL, HOLD, BILLED = 8.9, 11.22, 8.52
PAIRS = {"top": (T.trousers,), "bottom": (T.striped,), "outer": (T.striped, T.trousers)}
MAX_PHOTO = 700 * 1024


def _ok(model: Any) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json"), headers=NO_STORE)


def _no(status: int, code: str, words: str) -> JSONResponse:
    body = http.Refusal(error=code, detail=words)
    return JSONResponse(body.model_dump(), status_code=status, headers=NO_STORE)


def _words(view: WardrobeView, pid: str) -> str:
    p = view.pieces[pid]
    return " ".join(w for w in ((p.colour or "").replace("_", " "), p.type.replace("_", " ")) if w)


@dataclass
class FakeSeeMe:
    """What the fake keeps in page memory: never on disk."""

    photo: bytes | None = None
    photo_at: datetime | None = None
    consent_at: datetime | None = None
    pictures: dict[str, http.PictureView] = field(default_factory=dict)
    garments: dict[str, http.GarmentView] = field(default_factory=dict)
    garment_bytes: dict[str, bytes] = field(default_factory=dict)
    spent: float = 0.0
    on: bool = True
    cap: int = 300

    def view(self) -> http.SeeMeView:
        consent = http.ConsentView(
            given=self.consent_at is not None, at=self.consent_at,
            current=self.consent_at is not None, version=CONSENT_VERSION, words=CONSENT_WORDS,
        )  # fmt: skip
        return http.SeeMeView(
            ready=READY, on=self.on, provider=PROVIDER, consent=consent,
            photo=http.PhotoView(kept=self.photo is not None, at=self.photo_at,
                                 bytes=len(self.photo or b"")),
            month=http.MonthView(month="2026-11", spent_inr=round(self.spent, 2), cap_inr=self.cap,
                                 pictures=len(self.pictures)),
            typical_inr=TYPICAL, hold_inr=HOLD, pictures=tuple(self.pictures.values()),
        )  # fmt: skip

    def new(self, gid: str) -> http.NewGarment:
        g = self.garments[gid]
        return http.NewGarment(id=g.id, words=g.words)


PROVIDER = http.ProviderView(
    provider="Google Cloud's Agent Platform", model="gemini-3.1-flash-image",
    model_words="Gemini 3.1 Flash Image", location="us",
    location_words="processed in the United States", max_garments=3, retires_on="2027-05-28",
)  # fmt: skip


def _refused(st: FakeSeeMe, b: http.PictureIn, v: WardrobeView) -> JSONResponse | None:
    if not b.confirm_cost:
        return _no(422, "confirm_cost", "Confirm the price first.")
    if st.consent_at is None:
        return _no(409, "consent_needed", "Type YES first, after reading what is sent.")
    if st.photo is None:
        return _no(422, "no_photo", "Add your photo first.")
    if b.garment not in st.garments:
        return _no(404, "no_garment", "Add the new garment's photo first.")
    if any(x in PRIVATE or (x in v.pieces and v.pieces[x].private) for x in b.pieces):
        return _no(422, "private_piece", "A private piece is never sent.")
    if b.inr_shown + 0.01 < TYPICAL:
        return _no(409, "price_changed", "The price changed: look at it again.")
    return None


def _picture(st: FakeSeeMe, b: http.PictureIn, v: WardrobeView) -> http.PictureView:
    pid = m.new_picture_id()
    sent = tuple(http.SentPiece(piece=x, words=_words(v, x)) for x in b.pieces)
    pic = http.PictureView(
        id=pid, made_at=NOW, garment=st.new(b.garment),
        until=NOW + timedelta(days=m.PICTURE_KEEP_DAYS), inr=BILLED, sent=sent, mime="image/png",
        credentials=m.CREDENTIALS,
    )  # fmt: skip
    st.pictures[pid], st.spent = pic, st.spent + BILLED
    return pic


def _photo_routes(r: APIRouter, st: FakeSeeMe, clock: Callable[[], datetime]) -> None:
    @r.post("/v1/seeme/photo")
    async def photo_in(request: Request) -> JSONResponse:
        raw = await request.body()
        if not raw.startswith(b"\xff\xd8"):
            return _no(422, "not_jpeg", "Send your photo as a JPEG.")
        if len(raw) > MAX_PHOTO:
            return _no(413, "too_large", "This photo is too detailed to send: try a plainer one.")
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
        return _ok(st.view().consent)


def _garment_routes(
    r: APIRouter, st: FakeSeeMe, view: Callable[[], Awaitable[WardrobeView]],
    clock: Callable[[], datetime],
) -> None:  # fmt: skip
    @r.post("/v1/seeme/garments")
    async def garment_in(request: Request, type: str = "", colour: str = "") -> JSONResponse:
        try:
            asked = http.GarmentIn(type=type, colour=colour)
        except ValueError:
            return _no(
                422, "not_a_garment", "Choose a top, a bottom or an outer layer, and a colour."
            )
        raw = await request.body()
        if not raw.startswith(b"\xff\xd8"):
            return _no(422, "not_jpeg", "Send the garment's photo as a JPEG.")
        if len(raw) > MAX_PHOTO:
            return _no(413, "too_large", "This photo is too detailed to send: try a plainer one.")
        if len(st.garments) >= m.GARMENT_MAX:
            return _no(409, "too_many", f"You have {m.GARMENT_MAX} garment photos: delete one.")
        gid, at = m.new_garment_id(), clock()
        st.garments[gid] = http.GarmentView(
            id=gid, type=asked.type, colour=asked.colour, at=at, bytes=len(raw),
            words=m.new_garment_words(asked.colour, asked.type),
            until=at + timedelta(days=m.PICTURE_KEEP_DAYS),
        )  # fmt: skip
        st.garment_bytes[gid] = raw
        return _ok(st.garments[gid])

    @r.get("/v1/seeme/garments")
    async def garments() -> JSONResponse:
        return _ok(http.GarmentList(garments=tuple(st.garments.values())))

    @r.get("/v1/seeme/garments/{gid}")
    async def garment_out(gid: str) -> Response:
        if gid not in st.garment_bytes:
            return _no(404, "no_garment", "That garment's photo isn't there any more.")
        return Response(
            st.garment_bytes[gid], media_type="image/jpeg", headers=http.PICTURE_HEADERS
        )

    @r.delete("/v1/seeme/garments/{gid}")
    async def garment_drop(gid: str) -> JSONResponse:
        gone = st.garments.pop(gid, None) is not None and st.garment_bytes.pop(gid, b"") != b""
        return _ok(http.Deleted(deleted=gone, message="Deleted." if gone else "Already gone."))

    @r.get("/v1/seeme/pair")
    async def pair(garment: str = "") -> JSONResponse:
        g = st.garments.get(garment)
        if g is None:
            return _no(404, "no_garment", "Add the new garment's photo first.")
        v = await view()
        mine = tuple(http.SentPiece(piece=x, words=_words(v, x)) for x in PAIRS.get(g.slot, ()))
        words = "With your " + " and ".join(p.words for p in mine) + "." if mine else ""
        return _ok(http.Pairing(garment=g.id, pieces=mine, words=words))


def _picture_routes(
    r: APIRouter, st: FakeSeeMe, view: Callable[[], Awaitable[WardrobeView]]
) -> None:
    @r.get("/v1/seeme/estimate")
    async def estimate(garment: str = "", pieces: str = "") -> JSONResponse:
        v = await view()
        asked = [x for x in pieces.split(",") if x in v.pieces][: m.PAIR_MAX]
        sent = tuple(http.SentPiece(piece=x, words=_words(v, x)) for x in asked)
        new = st.new(garment) if garment in st.garments else None
        return _ok(http.Estimate(
            typical_inr=TYPICAL, hold_inr=HOLD, tax_pct=18, sent=sent, garment=new,
            cap_left_inr=round(st.cap - st.spent, 2),
            words=f"About ₹9 with GST. ₹{st.spent:.2f} of ₹{st.cap} used.",
        ))  # fmt: skip

    @r.post("/v1/seeme/pictures")
    async def pictures(b: http.PictureIn) -> JSONResponse:
        v = await view()
        refused = _refused(st, b, v)
        return refused if refused is not None else _ok(_picture(st, b, v))

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


def seeme_routes(
    view: Callable[[], Awaitable[WardrobeView]], clock: Callable[[], datetime]
) -> APIRouter:
    r = APIRouter(dependencies=[Depends(require_auth)])
    st = FakeSeeMe()
    r.state = st  # type: ignore[attr-defined]  # tests may look

    @r.get("/v1/seeme")
    async def seeme() -> JSONResponse:
        return _ok(st.view())

    _photo_routes(r, st, clock)
    _garment_routes(r, st, view, clock)
    _picture_routes(r, st, view)

    @r.put("/v1/seeme/settings")
    async def seeme_settings(b: http.SeeMeSettingsIn) -> JSONResponse:
        if b.cap_inr is not None and b.cap_inr > st.cap and not b.confirm_cost:
            return _no(422, "confirm_cost", f"Raising the limit to ₹{b.cap_inr} needs your OK.")
        st.on = st.on if b.on is None else b.on
        st.cap = st.cap if b.cap_inr is None else b.cap_inr
        return _ok(st.view())

    return r

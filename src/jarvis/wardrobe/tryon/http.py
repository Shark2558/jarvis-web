# src/jarvis/wardrobe/tryon/http.py
"""R13.1's HTTP contract (docs/plans/r13-1-try-on.md "The HTTP contract"; plan review L6, L11).

The request and reply models of every R13.1 route, written at I0 before the parts start: A's
`api/tryon.py` and C's `api/seeme.py` answer exactly these, D's console draws exactly these, and
`tests/r131_fake_server.py` serves them from the fakes for D's browser tests. A change here is a
seam change with a line in that part's INTEGRATION file.

Every route is the signed-in owner's (`require_auth`), rate-limited (R13's 30 changes and 60 reads
a minute; `POST /v1/seeme/pictures` 6 a minute), `Cache-Control: no-store`, CSRF as every cookie
write, and answers a refusal as `Refusal` (`{"error": <code>, "detail": <plain words>}`, so the
console can branch on `err.code`). Routes with `console=True` pass a signed-in browser only
(`api/book_gate.console_only`'s rule: never a bearer token, a tool, chat or a script).

The models live in `http_figure.py` (the base and A) and `http_seeme.py` (C), re-exported here.
`ROUTES` lists each route: (method, path, part, request model or body type, reply model or media
type, the error statuses it may answer, console only).
"""

from __future__ import annotations

from jarvis.wardrobe.http_views import Deleted, ToolReply
from jarvis.wardrobe.tryon.http_figure import (
    AssetChoice,
    BodyIn,
    BodyVersions,
    BodyView,
    ConfirmIn,
    ConfirmSlot,
    Inr,
    LookOption,
    LookSlot,
    PictureIdT,
    RangeView,
    Refusal,
    RequestIdT,
    SavedIdT,
    SavedIn,
    SavedList,
    SavedLook,
    SavedLookView,
    SavedRef,
    SavedView,
    TryonLook,
    TryonView,
)
from jarvis.wardrobe.tryon.http_seeme import (
    SEEME_ERRORS,
    ConsentIn,
    ConsentView,
    Estimate,
    KeepIn,
    MonthView,
    NotSent,
    PhotoView,
    PictureIn,
    PictureView,
    ProviderView,
    SeeMeSettingsIn,
    SeeMeView,
    SentPiece,
)

_E = (401, 403, 429)  # every route: not signed in, not his console (console routes), too many
_P = "/v1/seeme/pictures"
ROUTES: tuple[tuple[str, str, str, object, object, tuple[int, ...], bool], ...] = (
    ("GET", "/v1/tryon", "tryon", None, TryonView, (*_E, 503), False),
    ("PUT", "/v1/tryon/body", "tryon", BodyIn, BodyVersions, (*_E, 422, 503), False),
    ("POST", "/v1/tryon/body/use", "tryon", None, BodyVersions, (*_E, 404, 503), False),
    ("DELETE", "/v1/tryon/body/draft", "tryon", None, BodyVersions, (*_E, 404, 503), False),
    ("GET", "/v1/tryon/look", "tryon", None, TryonLook, (*_E, 404, 422, 503), False),
    ("PUT", "/v1/tryon/assets/{piece}", "tryon", AssetChoice, AssetChoice, (*_E, 404, 422), False),
    ("POST", "/v1/tryon/confirm", "tryon", ConfirmIn, ToolReply, (*_E, 404, 409, 422), False),
    ("GET", "/v1/tryon/saved", "tryon", None, SavedList, (*_E, 503), False),
    ("POST", "/v1/tryon/saved", "tryon", SavedIn, SavedView, (*_E, 409, 422), False),
    ("GET", "/v1/tryon/saved/{id}", "tryon", None, SavedView, (*_E, 404), False),
    ("DELETE", "/v1/tryon/saved/{id}", "tryon", None, Deleted, (*_E, 404), False),
    ("GET", "/v1/seeme", "seeme", None, SeeMeView, (*_E, 503), False),
    ("POST", "/v1/seeme/photo", "seeme", "image/jpeg", PhotoView, (*_E, 413, 422, 503), True),
    ("GET", "/v1/seeme/photo", "seeme", None, "image/jpeg", (*_E, 404), True),
    ("DELETE", "/v1/seeme/photo", "seeme", None, Deleted, _E, True),
    ("POST", "/v1/seeme/consent", "seeme", ConsentIn, ConsentView, (*_E, 409, 422), True),
    ("GET", "/v1/seeme/estimate", "seeme", None, Estimate, (*_E, 404, 409, 422, 503), False),
    ("POST", _P, "seeme", PictureIn, PictureView, (*_E, 402, 409, 422, 502, 503), True),
    ("GET", f"{_P}/{{id}}", "seeme", None, "image/", (*_E, 404), True),
    ("POST", f"{_P}/{{id}}/keep", "seeme", KeepIn, PictureView, (*_E, 404, 409), True),
    ("DELETE", f"{_P}/{{id}}", "seeme", None, Deleted, (*_E, 404), True),
    ("PUT", "/v1/seeme/settings", "seeme", SeeMeSettingsIn, SeeMeView, (*_E, 409, 422), True),
)
PICTURE_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'",
    "X-Content-Type-Options": "nosniff",
    "Cross-Origin-Resource-Policy": "same-origin",
}  # his photo and a picture, read back by his console only (D10, D12)

__all__ = [
    "Inr",
    "PictureIdT",
    "RequestIdT",
    "SavedIdT",
    "PICTURE_HEADERS",
    "ROUTES",
    "SEEME_ERRORS",
    "AssetChoice",
    "BodyIn",
    "BodyVersions",
    "BodyView",
    "ConfirmIn",
    "ConfirmSlot",
    "ConsentIn",
    "ConsentView",
    "Deleted",
    "Estimate",
    "KeepIn",
    "LookOption",
    "LookSlot",
    "MonthView",
    "NotSent",
    "PhotoView",
    "PictureIn",
    "PictureView",
    "ProviderView",
    "RangeView",
    "Refusal",
    "SavedIn",
    "SavedList",
    "SavedLook",
    "SavedLookView",
    "SavedRef",
    "SavedView",
    "SeeMeSettingsIn",
    "SeeMeView",
    "SentPiece",
    "ToolReply",
    "TryonLook",
    "TryonView",
]

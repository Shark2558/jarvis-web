# src/jarvis/api/book_writer.py
"""R6.3 D6, D7, D12 (docs/plans/r6-3-book-content.md "The HTTP contract"): the writer's console
routes under `/v1/book/writer`, exactly `buildbook/writer/http.ROUTES` (gate "console").

Every route: signed in (`require_auth`; CSRF on writes), `book_gate.console_only` (a signed-in
browser: never a bearer token, never a guest's show-only browser), the PRIMARY owner only (another
owner e-mail is 403 `not_primary`, L11), a guest book session's `X-Jarvis-Book` refused (403
`owner_only`), `no-store`, the per-owner limits of `http.LIMITS` (reads 30, writes 10, step 6 a
minute), every refusal `http.Refusal` in plain words (`yes_needed` as `http.YesNeeded`: the
terms id and the rupee words). The service (`app.state.book_writer`) is read per request; every
grant of spending is his typed YES on the rupees shown (H2), checked there. Nothing logged here
carries a value or text.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from jarvis.api.auth import require_auth, session_email
from jarvis.api.book_gate import BookRefused, console_only, need, now, owner_session
from jarvis.api.book_http import TOKEN_HEADER, book_json
from jarvis.buildbook.writer import http
from jarvis.buildbook.writer.http import ROUTES, WRITER_PREFIX  # by name: A's route scan (M9)
from jarvis.buildbook.writer.texts import REFUSED, WriterRefused

NOT_BUILT_WORDS = "The Book's writer isn't built on this server yet."
BODY_MAX = 4_096
MINUTE_S = 60.0
router = APIRouter(prefix=WRITER_PREFIX, dependencies=[Depends(require_auth)])
Handler = Callable[[Request], Awaitable[JSONResponse]]


class Window:
    """At most `per_minute` calls an owner in any minute (the Book's clock)."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._seen: dict[str, list[float]] = {}

    def allow(self, uid: str, at: float) -> bool:
        recent = [t for t in self._seen.get(uid, []) if at - t < MINUTE_S]
        if len(recent) >= self.per_minute:
            self._seen[uid] = recent
            return False
        self._seen[uid] = [*recent, at]
        return True


def limited(request: Request, name: str, uid: str) -> None:
    windows: dict[str, Window] = request.app.state.book_writer_limits
    if not windows[name].allow(uid, now(request).timestamp()):
        raise BookRefused(429, "rate_limited", REFUSED["rate_limited"])


def service_of(request: Request) -> Any:
    svc = need(request, "book_writer")
    if getattr(svc, "ready", None) != "ok":
        raise BookRefused(503, http.NOT_BUILT, NOT_BUILT_WORDS)
    return svc


def primary(request: Request, svc: Any) -> str:
    """The primary owner's id (L11); another owner's browser is 403 `not_primary`."""
    email = session_email(request, request.app.state.settings)
    owners = tuple(e.lower() for e in svc.ctx.owner_emails)
    if email is not None and owners and email.lower() != owners[0]:
        raise BookRefused(403, "not_primary", REFUSED["not_primary"])
    return str(svc.ctx.uid)


async def no_guest(request: Request, uid: str) -> None:
    token = request.headers.get(TOKEN_HEADER)
    if token is not None:
        await owner_session(request, uid, token)  # a guest's session: 403 owner_only


def answer(model: BaseModel) -> JSONResponse:
    return book_json(model.model_dump(mode="json"))


def refused(no: WriterRefused) -> JSONResponse:
    if no.code == "yes_needed":
        body = http.YesNeeded(
            detail=no.detail, terms_id=no.extra["terms_id"], words=tuple(no.extra["words"])
        )
        return book_json(body.model_dump(mode="json"), 422)
    return book_json({"error": no.code, "detail": no.detail}, no.status)


async def body_of(request: Request, model: type[BaseModel], bad: str) -> Any:
    raw = await request.body()
    if len(raw) > BODY_MAX:
        raise BookRefused(422, bad, REFUSED.get(bad, REFUSED["not_yes"]))
    try:
        return model.model_validate_json(raw or b"{}")
    except ValidationError as exc:
        where = {str(p) for e in exc.errors() for p in e.get("loc", ())}
        code = "estimate_changed" if "estimate_id" in where else bad
        status = 409 if code == "estimate_changed" else 422
        raise BookRefused(status, code, REFUSED.get(code, REFUSED["not_yes"])) from None


def route(kind: str, act: Callable[[Any, str, Request], Awaitable[BaseModel]]) -> Handler:
    async def handler(request: Request) -> JSONResponse:
        console_only(request)
        svc = service_of(request)
        uid = primary(request, svc)
        await no_guest(request, uid)
        limited(request, kind, uid)
        try:
            return answer(await act(svc, uid, request))
        except WriterRefused as no:
            return refused(no)

    return handler


async def _view(svc: Any, uid: str, request: Request) -> BaseModel:
    return await svc.view(uid)  # type: ignore[no-any-return]


async def _estimate(svc: Any, uid: str, request: Request) -> BaseModel:
    kind = request.query_params.get("run", "")
    if kind not in ("trial", "first", "update"):
        raise BookRefused(422, "not_yes", "Ask for the estimate of trial, first or update.")
    return await svc.estimate(uid, kind)  # type: ignore[no-any-return]


async def _trial(svc: Any, uid: str, request: Request) -> BaseModel:
    return await svc.start_trial(uid, await body_of(request, http.TrialIn, "not_yes"))  # type: ignore[no-any-return]


async def _pick(svc: Any, uid: str, request: Request) -> BaseModel:
    return await svc.pick(uid, await body_of(request, http.PickIn, "bad_cap"))  # type: ignore[no-any-return]


async def _first(svc: Any, uid: str, request: Request) -> BaseModel:
    return await svc.first(uid, await body_of(request, http.RunIn, "not_yes"))  # type: ignore[no-any-return]


async def _update(svc: Any, uid: str, request: Request) -> BaseModel:
    return await svc.update(uid, await body_of(request, http.RunIn, "not_yes"))  # type: ignore[no-any-return]


async def _stop(svc: Any, uid: str, request: Request) -> BaseModel:
    return await svc.stop(uid)  # type: ignore[no-any-return]


async def _step(svc: Any, uid: str, request: Request) -> BaseModel:
    return await svc.step(uid)  # type: ignore[no-any-return]


async def _rows(svc: Any, uid: str, request: Request) -> BaseModel:
    return await svc.trial_rows(uid)  # type: ignore[no-any-return]


async def _one(svc: Any, uid: str, request: Request) -> BaseModel:
    raw = request.path_params.get("nn", "")
    if not str(raw).isdigit() or not 1 <= int(raw) <= 10:
        raise BookRefused(404, "no_trial", REFUSED["no_trial"])
    return await svc.trial_page(uid, int(raw))  # type: ignore[no-any-return]


async def _delete(svc: Any, uid: str, request: Request) -> BaseModel:
    return await svc.delete_trial(uid)  # type: ignore[no-any-return]


W = WRITER_PREFIX
ACTS: dict[tuple[str, str], tuple[str, Callable[[Any, str, Request], Awaitable[BaseModel]]]] = {
    ("GET", W): ("reads", _view),
    ("GET", f"{W}/estimate"): ("reads", _estimate),
    ("POST", f"{W}/trial"): ("writes", _trial),
    ("PUT", f"{W}/pick"): ("writes", _pick),
    ("POST", f"{W}/first"): ("writes", _first),
    ("POST", f"{W}/update"): ("writes", _update),
    ("POST", f"{W}/stop"): ("writes", _stop),
    ("POST", f"{W}/step"): ("step", _step),
    ("GET", f"{W}/trial/pages"): ("reads", _rows),
    ("GET", f"{W}/trial/pages/{{nn}}"): ("reads", _one),
    ("DELETE", f"{W}/trial"): ("writes", _delete),
}
for _method, _path, _part, _req, _reply, _codes, _gate in ROUTES:
    if _path.startswith(W):
        _kind, _act = ACTS[(_method, _path)]
        router.add_api_route(
            _path.removeprefix(W), route(_kind, _act), methods=[_method], name=_path
        )


def install_book_writer(app: FastAPI) -> None:
    """Mounted by `r6_wiring.install_r6_routes` after `install_book` (its refusal handler)."""
    app.state.book_writer_limits = {k: Window(v) for k, v in http.LIMITS.items()}
    app.include_router(router)


__all__ = ["NOT_BUILT_WORDS", "Window", "install_book_writer", "router"]

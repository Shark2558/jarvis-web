# evals/r13_1/seeme.py
"""R13.1 eval, Part C (See it on me), through the PORT (docs/plans/r13-1-try-on.md "Tests and
evals"; BRIEF-C section 4). Every case runs on C's Gemini adapter (recorded answers through
httpx.MockTransport) AND on I0's one-garment fake (`ScriptedTryOn(max_garments=1)`, which chains
inside itself). No call reaches Google.

Cases: zero calls without a current YES, and "yes", "Yes", "YES!" refused; a moved rate keeps
consent, a model or location change asks again; the cap's boundary (on the adapter: settled at
₹8.52 with a hold of ₹11.22, the 34th fits and the 35th is refused); 10 presses at once reserve
exactly one; released on every non-200 and on "never sent", kept on a timeout after sending, a cut
200 and a blocked 200; settled from usage, at the hold without; a text part read nowhere; a private
piece and one without a front crop refused before any call; No-AI and the end date; a bearer token
(console only); `price_changed` and an idempotent request id; D22 (the new garment and at most two
of his, never his, a 21st garment photo, the pairing never private); AVT-12's exact pieces.

Controls, each of which must turn its own case red (`control()`): the atomic reserve replaced by
read-then-write; the consent check off; the private check moved to the console only; the ₹ hashed
into the consent; the garment added to the wardrobe; and AVT-12's own (M8): the piece list taken
from the look, not from what was sent.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

import httpx
from r131_fake_gemini import (
    CUT,
    INSTRUCTION,
    FakeGoogle,
    FakeTokens,
    blocked_answer,
    picture_answer,
    project_of,
)
from r131_fake_tryon import ScriptedTryOn, Step
from r131_fakes import UID, T, ist, jpeg
from r131_fakes_c import FakeBilling, OffMode, YieldingDocs, ask, ready_world

from jarvis.llm.tryon import TryOnMaybeBilled, TryOnNotBilled
from jarvis.wardrobe.seeme import consent as cmod
from jarvis.wardrobe.seeme import make as makemod
from jarvis.wardrobe.seeme import pair as pairmod
from jarvis.wardrobe.seeme.cap import CapHold, Month, TryonCap, decode, encode
from jarvis.wardrobe.seeme.texts import SeeMeRefused

PART = "seeme"
BUILT = True
Prov = tuple[Any, Callable[[], int]]
Mk = Callable[..., Prov]
SCRIPTS = {  # billed or not: (the adapter's recorded answer, the fake's step, kept at the hold?)
    "status_500": ([500], Step(error=TryOnNotBilled("status_500")), False),
    "never_sent": ([httpx.ConnectError("no")], Step(error=TryOnNotBilled("not_sent")), False),
    "timeout_after_sending": ([httpx.ReadTimeout("x")], Step(error=TryOnMaybeBilled("t")), True),
    "cut_200": ([CUT], Step(error=TryOnMaybeBilled("cut")), True),
    "blocked_200": ([blocked_answer()], Step(blocked="safety"), True),
}
SLOT = {"trousers": "bottom", "blazer": "outer", "kurta": "top", "shirt": "top"}


def gemini(script: list[Any] | None = None) -> Prov:
    from jarvis.llm.tryon_gemini import GeminiTryOn

    google = FakeGoogle(script or [picture_answer()])
    p = GeminiTryOn(model="gemini-3.1-flash-image", location="us", tokens=FakeTokens(),
                    project=project_of(), http=google.client())  # fmt: skip
    return p, lambda: len(google.seen)


def fake1(steps: list[Step] | None = None) -> Prov:
    p = ScriptedTryOn(max_garments=1, script=steps or ())
    return p, lambda: len(p.calls)


PROVIDERS: dict[str, Mk] = {"gemini": gemini, "fake1": fake1}


async def _press(svc: Any, gid: str, pieces: tuple[str, ...] = (), n: int = 1) -> Any:
    shown = (await svc.estimate(UID, gid, list(pieces))).typical_inr
    return await svc.press(UID, ask(gid, pieces, inr=shown, n=n))


async def _code(coro: Awaitable[Any]) -> str:
    try:
        await coro
    except SeeMeRefused as exc:
        return exc.code
    return "made"


def _want(ok: bool, why: str) -> list[str]:
    return [] if ok else [why]


DAY: dict[str, float] = {
    "rate": 95.24
}  # the day's rate, as a case moves it (C4's control reads it)


def _set_rate(billing: FakeBilling, rate: float) -> None:
    billing.fx.inr_per_usd = DAY["rate"] = rate


# ---- consent -------------------------------------------------------------------------------------
async def c_no_call_without_yes(mk: Mk) -> list[str]:
    p, calls = mk()
    sw, svc, g = await ready_world(provider=p, consent=False)
    out = _want(await _code(svc.press(UID, ask(g.id, inr=99.0))) == "consent_needed", "sent")
    for typed in ("yes", "Yes", "YES!"):
        refused = await _code(svc.give_consent(UID, typed, cmod.VERSION)) == "not_yes"
        out += _want(refused, f"{typed!r} accepted")
    return out + _want(calls() == 0, f"{calls()} calls without a YES")


async def c_moved_rate_keeps_consent(mk: Mk) -> list[str]:
    p, _ = mk()
    billing = FakeBilling()
    sw, svc, g = await ready_world(provider=p, billing=billing)
    _set_rate(billing, 96.10)
    out = _want((await svc.overview(UID)).consent.current, "a moved rate asked again")
    for model, where in (("gemini-3.1-flash-image", "eu"), ("gemini-nano-banana-2.1", "us")):
        other = ScriptedTryOn(max_garments=1, model=model, location=where).describe()
        out += _want(not await svc.kit.consent.current(UID, other), f"{model} {where} kept it")
    _set_rate(billing, 95.24)
    return out


# ---- money ---------------------------------------------------------------------------------------
async def c_the_caps_boundary(mk: Mk) -> list[str]:
    p, _ = mk()
    sw, svc, g = await ready_world(provider=p)
    n, last = 0, "made"
    while last == "made" and n < 60:
        n += 1
        last = await _code(_press(svc, g.id, (T.jeans,), n=n))
        sw.w.clock.set(sw.w.clock() + timedelta(minutes=11))
    month = await svc.kit.cap.month(UID)
    each = month.spent_inr / max(1, month.pictures)
    hold = (await svc.estimate(UID, g.id, [T.jeans])).hold_inr
    fits = int((300 - hold) / each + 1e-9) + 1  # the n-th fits while (n-1) x settle + hold <= cap
    out = _want((last, month.pictures) == ("cap_reached", fits), f"{month.pictures} made, {last}")
    if mk is gemini:
        out += _want((round(each, 2), hold, fits) == (8.52, 11.22, 34), "not 8.52 / 11.22 / 34")
    return out


class _Slow:
    """The provider, a little slow (a real call takes seconds): the presses overlap for real."""

    def __init__(self, p: Any) -> None:
        self.p = p

    def describe(self) -> Any:
        return self.p.describe()

    def estimate(self, n: int) -> tuple[float, float]:
        got: tuple[float, float] = self.p.estimate(n)
        return got

    async def make(self, a: Any) -> Any:
        await asyncio.sleep(0.01)
        return await self.p.make(a)


async def c_ten_at_once(mk: Mk) -> list[str]:
    p, calls = mk()
    sw, svc, g = await ready_world(provider=_Slow(p), docs=YieldingDocs())
    shown = (await svc.estimate(UID, g.id, [])).typical_inr
    presses = (_code(svc.press(UID, ask(g.id, inr=shown, n=k))) for k in range(10))
    got = await asyncio.gather(*presses)
    made, busy = got.count("made"), got.count("busy")
    return _want((made, busy) == (1, 9) and calls() >= 1, f"{made} made, {busy} busy")


async def c_billed_or_not(mk: Mk) -> list[str]:
    out: list[str] = []
    for name, (recorded, step, kept) in SCRIPTS.items():
        p, _ = mk(recorded) if mk is gemini else mk([step])
        sw, svc, g = await ready_world(provider=p)
        code = await _code(_press(svc, g.id, (T.jeans,)))
        m = await svc.kit.cap.month(UID)
        want = (await svc.estimate(UID, g.id, [T.jeans])).hold_inr if kept else 0.0
        ok = code != "made" and (m.spent_inr, m.held_inr) == (want, 0.0)
        out += _want(ok, f"{name}: {code}, spent {m.spent_inr}, held {m.held_inr}")
    return out


async def c_settled_from_usage_or_the_hold(mk: Mk) -> list[str]:
    if mk is not gemini:  # the fake's model is not priced: always at the hold
        p, _ = mk()
        sw, svc, g = await ready_world(provider=p)
        hold = (await svc.estimate(UID, g.id, [])).hold_inr
        pic = await _press(svc, g.id)
        return _want(pic.inr == hold, f"settled {pic.inr}, not the hold {hold}")
    out: list[str] = []
    for answer, want in ((picture_answer(), 8.52), (picture_answer(usage=None), 11.22)):
        sw, svc, g = await ready_world(provider=gemini([answer])[0])
        pic = await _press(svc, g.id, (T.jeans,))
        out += _want(pic.inr == want, f"settled {pic.inr}, not {want}")
    return out


# ---- untrusted words, private pieces, the gates --------------------------------------------------
@contextmanager
def _logs() -> Iterator[list[str]]:
    found: list[str] = []

    class Grab(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            found.append(record.getMessage() + str(record.__dict__))

    grab, root = Grab(), logging.getLogger()
    root.addHandler(grab)
    try:
        yield found
    finally:
        root.removeHandler(grab)


async def c_text_read_nowhere(mk: Mk) -> list[str]:
    p, calls = gemini([picture_answer(text=INSTRUCTION)]) if mk is gemini else mk()
    with _logs() as lines:
        sw, svc, g = await ready_world(provider=p)
        drawn = jpeg(600, 800, 4)[:-2] + INSTRUCTION.encode() + b"\xff\xd9"  # text in its bytes
        g2 = await svc.add_garment(UID, "trousers", "khaki", drawn)
        pic = await _press(svc, g2.id)
    out = _want(not any(INSTRUCTION in x for x in lines), "in a log")
    out += _want(INSTRUCTION not in pic.model_dump_json(), "in the reply")
    docs = sw.docs._data.values()  # noqa: SLF001 - every document's plain fields
    plain = [str({k: v for k, v in d.items() if k != "blob"}) for d in docs]
    out += _want(not any(INSTRUCTION in x for x in plain), "in a document")
    if isinstance(p, ScriptedTryOn):
        out += _want(p.calls[0].garments == ("new khaki trousers",), "words not the fixed ones")
    return out + _want(calls() > 0, "no call")


async def c_private_and_no_front_refused(mk: Mk) -> list[str]:
    p, calls = mk()
    sw, svc, g = await ready_world(provider=p)
    await sw.w.edit(T.jeans, private=True)  # made private (its old crop still on file here)
    code = await _code(svc.press(UID, ask(g.id, (T.jeans,), inr=99.0)))
    out = _want(code == "private_piece", f"private: {code}")
    trousers = await svc.add_garment(UID, "trousers", "khaki", jpeg(300, 300))
    code = await _code(svc.press(UID, ask(trousers.id, (T.shirt,), inr=99.0, n=2)))
    return out + _want(code == "no_photo", f"no front: {code}") + _want(not calls(), "a call")


async def c_gates_before_any_call(mk: Mk) -> list[str]:
    out: list[str] = []
    for name, kw, want in (("no_ai", {"mode": OffMode()}, "no_ai"),
                           ("end_date", {"at": ist(2027, 5, 28, 0, 30)}, "retired")):  # fmt: skip
        p, calls = mk()
        sw, svc, g = await ready_world(provider=p, **kw)
        code = await _code(svc.press(UID, ask(g.id, inr=99.0)))
        out += _want((code, calls()) == (want, 0), f"{name}: {code}, {calls()} calls")
    p, calls = mk()
    sw, svc, g = await ready_world(provider=p, at=ist(2027, 5, 27, 23, 30))
    return out + _want(await _code(_press(svc, g.id)) == "made", "refused the day before its end")


async def c_price_changed_and_idempotent(mk: Mk) -> list[str]:
    p, calls = mk()
    billing = FakeBilling()
    sw, svc, g = await ready_world(provider=p, billing=billing)
    shown = (await svc.estimate(UID, g.id, [])).typical_inr
    billing.fx.inr_per_usd = 120.0
    code = await _code(svc.press(UID, ask(g.id, inr=shown)))
    out = _want(code == "price_changed" and calls() == 0, f"a moved price: {code}")
    billing.fx.inr_per_usd = 95.24
    first = await svc.press(UID, ask(g.id, inr=shown, n=5))
    made = calls()
    again = await svc.press(UID, ask(g.id, inr=shown, n=5))
    month = await svc.kit.cap.month(UID)
    return out + _want(again.id == first.id and calls() == made and month.pictures == 1, "twice")


async def c_bearer_token_is_refused(mk: Mk) -> list[str]:
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from jarvis.api import seeme as routes
    from jarvis.api.auth import require_auth
    from jarvis.api.identity import current_user
    from jarvis.wardrobe.ports import WardrobePart

    p, calls = mk()
    sw, svc, g = await ready_world(provider=p)
    app = FastAPI()
    app.state.settings = sw.ctx.s
    app.state.r13_parts = {"seeme": WardrobePart("seeme", services={"seeme": svc})}
    app.include_router(routes.router)
    app.dependency_overrides[require_auth] = lambda: None  # a valid bearer token, not a browser
    app.dependency_overrides[current_user] = lambda: UID
    body = {"garment": g.id, "pieces": [], "confirm_cost": True, "inr_shown": 99.0,
            "request_id": "tq_" + "9" * 16}  # fmt: skip
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        got = await c.post("/v1/seeme/pictures", json=body, headers={"Authorization": "Bearer x"})
    refused = got.status_code == 403 and got.json().get("error") == "console_only"
    return _want(refused and not calls(), f"{got.status_code}, {calls()} calls")


# ---- D22 and AVT-12 ------------------------------------------------------------------------------
async def c_d22_the_garment_and_never_his(mk: Mk) -> list[str]:
    p, _ = mk()
    sw, svc, g = await ready_world(provider=p)
    before = await sw.rev()
    pair = await svc.pair(UID, g.id)
    pic = await _press(svc, g.id, tuple(x.piece for x in pair.pieces))
    await svc.delete_garment(UID, g.id)
    out = _want(pic.garment.id == g.id and len(pic.sent) <= 2, "not the new garment")
    out += _want(await sw.rev() == before, "the garment changed his wardrobe")
    for n in range(20):
        await svc.add_garment(UID, "shirt", "navy", jpeg(300, 300 + n))
    code = await _code(svc.add_garment(UID, "shirt", "navy", jpeg(300, 300)))
    out += _want(code == "too_many", f"a 21st: {code}")
    view = await sw.w.store.view(UID)
    model = (await svc.kit.garments.listed(UID, keep_days=30, kept=set())).garments[0]
    for kind, colour in (("trousers", "khaki"), ("blazer", "navy"), ("kurta", "maroon")):
        asked = model.model_copy(update={"type": kind, "colour": colour, "slot": SLOT[kind]})
        got = await svc.kit.pairer.pair(UID, asked)
        bad = [x.piece for x in got.pieces if view.pieces[x.piece].private]
        out += _want(not bad and len(got.pieces) <= 2, f"pairing {kind}: {bad}")
    return out


async def c_avt12_the_exact_pieces(mk: Mk) -> list[str]:
    p, _ = mk()
    sw, svc, g = await ready_world(provider=p)
    pic = await _press(svc, g.id, (T.trousers,))  # the pairing offers the jeans: he chose these
    out = _want([s.piece for s in pic.sent] == [T.trousers], f"sent {pic.sent}")
    out += _want(pic.label.startswith("Generated 2D style preview"), "no 2D label")
    return out + _want(T.jeans in {n.piece for n in pic.not_sent}, "the offered jeans unlisted")


CASES: dict[str, Callable[[Mk], Awaitable[list[str]]]] = {
    "no_call_without_yes": c_no_call_without_yes,
    "moved_rate_keeps_consent": c_moved_rate_keeps_consent,
    "the_caps_boundary": c_the_caps_boundary,
    "ten_at_once": c_ten_at_once,
    "billed_or_not": c_billed_or_not,
    "settled_from_usage_or_the_hold": c_settled_from_usage_or_the_hold,
    "text_read_nowhere": c_text_read_nowhere,
    "private_and_no_front_refused": c_private_and_no_front_refused,
    "gates_before_any_call": c_gates_before_any_call,
    "price_changed_and_idempotent": c_price_changed_and_idempotent,
    "bearer_token_is_refused": c_bearer_token_is_refused,
    "d22_the_garment_and_never_his": c_d22_the_garment_and_never_his,
    "avt12_the_exact_pieces": c_avt12_the_exact_pieces,
}


async def _one(name: str, prov: str) -> dict[str, Any]:
    try:
        failures = await CASES[name](PROVIDERS[prov])
    except Exception as exc:  # noqa: BLE001 - a case that breaks fails, by its class name
        failures = [f"raised {type(exc).__name__}"]
    return {"id": f"{PART}:{name}@{prov}", "passed": not failures, "failures": failures}


async def cases(only: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    return [await _one(n, p) for n in (only or tuple(CASES)) for p in PROVIDERS]


# ---- the controls: each must turn its own case red -----------------------------------------------
async def _racy_reserve(self: TryonCap, uid: str, request_id: str, hold_inr: float,
                        cap_inr: int) -> Any:  # fmt: skip
    """C1: read, then write later: two presses can both see no hold."""
    from jarvis.storage.docs import Set

    key = self.month_of(self.now())
    path = self.path(uid, key)
    m = decode(await self.docs.get(path), key)
    done = self._check(m, request_id, hold_inr, cap_inr)  # noqa: SLF001 - the control's own copy
    if done is not None:
        return done
    holds = {**m.holds, request_id: {"inr": hold_inr, "at": self.now().isoformat()}}
    new = Month(key, m.spent_inr, m.held_inr + hold_inr, holds, m.done, m.pictures, m.blocked)
    await asyncio.sleep(0)  # a network write takes a round trip too
    await self.docs.write([Set(path, encode(uid, new, self.now()))])
    return CapHold(uid, request_id, hold_inr, key)


async def _always_current(self: Any, uid: str, desc: Any) -> bool:
    return True  # C2: the consent check off


def _lax(real: Any) -> Any:
    async def check(ctx: Any, uid: str, view: Any, pid: str, *, taken: set[str]) -> Any:
        p = view.piece(pid)  # C3: the private check left to the console (the server forgets it)
        if p is not None and p.private:
            open_ = p.model_copy(update={"private": False})
            view = view.model_copy(update={"pieces": {**view.pieces, pid: open_}})
        return await real(ctx, uid, view, pid, taken=taken)

    return check


def _priced_text(real: Any) -> Any:
    return lambda desc: real(desc) + f"|inr={DAY['rate']}"  # C4: the day's ₹ in the hash


def _into_the_wardrobe(real: Any) -> Any:
    async def keep(self: Any, uid: str, call: Any, result: Any) -> Any:
        from r13_fakes import ev

        from jarvis.wardrobe.model import Piece, new_id
        from jarvis.wardrobe.ports import Commit

        g = call.garment  # C5: the new garment registered as a piece of his
        piece = Piece.model_validate({"i": new_id("wi"), "c": "tops", "t": g.type, "co": g.colour})

        async def fn(view: Any, tx: Any) -> Commit:
            return Commit(
                events=(ev(piece.id, "registered", self.kit.ctx.now()),), records=(piece,)
            )

        await self.kit.ctx.store().transact(uid, fn)
        return await real(self, uid, call, result)

    return keep


def _from_the_look(mine: Any) -> Any:
    from jarvis.wardrobe.tryon.http import SentPiece

    return (SentPiece(piece=T.jeans, words="blue jeans"),)  # M8: the look's pieces, not his


CONTROLS: tuple[tuple[str, str, Any, str, Callable[[Any], Any]], ...] = (
    ("a read-then-write reserve", "ten_at_once", TryonCap, "reserve", lambda r: _racy_reserve),
    ("the consent check off", "no_call_without_yes", cmod.Consent, "current",
     lambda r: _always_current),
    ("the private check in the console only", "private_and_no_front_refused", pairmod, "check",
     _lax),
    ("the ₹ hashed into the consent", "moved_rate_keeps_consent", cmod, "template_text",
     _priced_text),
    ("the garment added to the wardrobe", "d22_the_garment_and_never_his", makemod.Press,
     "_keep", _into_the_wardrobe),
    ("AVT-12: the pieces from the look, not what was sent", "avt12_the_exact_pieces", makemod,
     "sent_of", _from_the_look),
)  # fmt: skip


async def control() -> dict[str, Any]:
    failed: list[str] = []
    every = True
    for _, case, owner, attr, patch in CONTROLS:
        real = getattr(owner, attr)
        setattr(owner, attr, patch(real))
        try:
            got = await cases((case,))
        finally:
            setattr(owner, attr, real)
        red = [r["id"] for r in got if not r["passed"]]
        failed += red
        every = every and len(red) == len(got)  # red on the adapter AND on the one-garment fake
    return {"name": "; ".join(c[0] for c in CONTROLS), "suite_failed": every,
            "failed_cases": failed}  # fmt: skip

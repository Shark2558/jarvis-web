# evals/r13_1/e2e.py
"""R13.1 eval, I1's suite (`e2e`, BUILT): his workbook's end-to-end tests, the avatar halves
(docs/plans/r13-1-try-on.md "Tests and evals"), and See it on me's life, through the REAL app on
fakes (`wired.py`: every wardrobe part joined, the real gateway and routes, a fixed clock, C's
real adapter on recorded Google answers).

meeting_outfit_update   one planned piece to the laundry, the viewer reopened: the figure and the
                        checklist name the same ids, and never the piece in the laundry
layer_and_rotate        shirt, blazer, belt, watch, shoes: the blazer opens, the shoes swap, the
                        back is a view he can add, every approximation named
private_items_and_photos  a look with private layers covered, a saved (shared) look with no
                        private id, then OPS-05: his figure gone, the catalog as it was and usable
see_it_on_me_life       his photo, his YES, a new garment, the pairing, the estimate, ONE picture
                        (the new garment and his piece sent, nothing else), 30 days, gone by
                        `seeme_daily`; the garment never in his wardrobe
what_to_wear_388        row 388: a typed and a spoken "what should I wear?" through the mock
                        brain: ONE try-on card under the reply, its pieces the look's, and the
                        figure's look for the card is exactly those pieces

Control (plan): the look built from a stale view: meeting_outfit_update fails.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import mock

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
for _p in (ROOT / "tests", ROOT / "src"):  # appended: never ahead of what is already imported
    if str(_p) not in sys.path:
        sys.path.append(str(_p))


def _wired() -> ModuleType:
    """`wired.py` by path under a unique name: no evals/r13_1 on sys.path."""
    found = sys.modules.get("r13_1_wired")
    if found is not None:
        return found
    spec = importlib.util.spec_from_file_location("r13_1_wired", HERE / "wired.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["r13_1_wired"] = module
    spec.loader.exec_module(module)
    return module


_W = _wired()
World, running, seed, want, b64 = _W.World, _W.running, _W.seed, _W.want, _W.b64
from r13_fakes_a import jpeg  # noqa: E402
from r131_fake_gemini import PNG_OUT  # noqa: E402

from jarvis.llm.base import ToolCall  # noqa: E402
from jarvis.privacy.service import CONFIRM_WORD  # noqa: E402
from jarvis.wardrobe.tryon import looks as looks_mod  # noqa: E402

PART = "e2e"
BUILT = True
Case = Callable[[], Awaitable[list[str]]]
COVERED = ("base", "underwear")


async def _meeting(w: World) -> str:
    got = await w.ok("outfit_plan", action="save", day="tomorrow", occasion="meeting",
                     start="10:00", end="12:00")  # fmt: skip
    return str(got["plan"]["id"])


def _drawn(look: dict[str, Any]) -> dict[str, str]:
    return {s["slot"]: s["piece"] for s in look["slots"] if s.get("piece")}


async def _checklist(w: World, plan: str) -> dict[str, str]:
    """R13's own panel for the plan ("Today and tomorrow"): each slot's first id."""
    entry = next(e for e in (await w.get("/v1/outfits"))["tomorrow"] if e["id"] == plan)
    out: dict[str, str] = {}
    for p in entry["look"]["pieces"]:
        if p["slot"] not in COVERED:
            out.setdefault(p["slot"], p["piece"])
    return out


async def meeting_outfit_update() -> list[str]:
    async with running() as w:
        ids = await seed(w)
        plan = await _meeting(w)
        before = await w.get(f"/v1/tryon/look?plan={plan}")
        out = want(_drawn(before).get("belt") == ids["belt"], "the plan's look wears the belt")
        await w.ok("laundry_move", step="basket", pieces=[ids["belt"]])
        w.clock.advance(minutes=6)
        after = await w.get(f"/v1/tryon/look?plan={plan}")  # the viewer reopened
        figure, checklist = _drawn(after), await _checklist(w, plan)
        out += want(ids["belt"] not in figure.values(), "the belt in the laundry left the figure")
        out += want(figure == checklist, f"figure and checklist differ: {figure} {checklist}")
        belt = next((s for s in after["slots"] if s["slot"] == "belt"), None)
        out += want(belt is None or belt["readiness"] == "Ready", f"the belt slot: {belt}")
        return out + want(bool(figure), "the figure names pieces")


async def layer_and_rotate() -> list[str]:
    async with running() as w:
        ids = await seed(w)
        for name in ("shirt", "blazer", "watch", "black_l", "brown_l"):
            got = await w.crop(ids[name], "front", jpeg())
            assert got.status_code == 200, got.text
        plan = await _meeting(w)
        look = await w.get(f"/v1/tryon/look?plan={plan}")
        slots = {s["slot"]: s for s in look["slots"]}
        out = want({"top", "outer", "belt", "watch", "shoes"} <= set(slots), f"{set(slots)}")
        out += want(slots["outer"]["piece"] == ids["blazer"], "the blazer is the outer layer")
        out += want("open" in slots["outer"]["variants"] and look["open"], "the blazer opens")
        offered = {o["piece"] for o in slots["shoes"]["options"]}
        worn = slots["shoes"]["piece"]
        other = next(p for p in (("black_l", "black_r"), ("brown_l", "brown_r"))
                     if worn not in (ids[p[0]], ids[p[1]]))  # fmt: skip
        out += want(bool(offered & {ids[n] for n in other}), f"the other pair: {offered}")
        rest = {k: v for k, v in _drawn(look).items() if k != "shoes"}
        q = ",".join([*(f"{k}:{v}" for k, v in rest.items()), *(f"shoes:{ids[n]}" for n in other),
                      "base:", "underwear:"])  # fmt: skip
        new = await w.get(f"/v1/tryon/look?pieces={q}&plan={plan}")
        moved = _drawn(new)
        out += want(moved.pop("shoes", None) in {ids[n] for n in other}, "the shoes swapped")
        out += want(moved == rest, f"the rest stayed: {moved}")
        back = "back" in slots["top"]["missing"] and "back" in slots["outer"]["missing"]
        out += want(back, "turning to the back: the shirt's and blazer's back views are asked for")
        for s in new["slots"]:
            if s.get("template"):
                ok = s["approximate"][:1] == ["template"] and len(s["approximate"]) >= 2
                out += want(ok, f"{s['slot']}: every approximation named ({s['approximate']})")
        return out


async def private_items_and_photos() -> list[str]:
    async with running() as w:
        ids = await seed(w)
        plan = await _meeting(w)
        look = await w.get(f"/v1/tryon/look?plan={plan}")
        covered = [s for s in look["slots"] if s["slot"] in COVERED]
        out = want(len(covered) == 2, f"both private layers in the look: {covered}")
        text = json.dumps(look)
        out += want(all(ids[n] not in text for n in ("vest", "briefs")), "no private id served")
        out += want(all(not s.get("template") and s.get("rgb") is None for s in covered),
                    "a private layer is never drawn")  # fmt: skip
        mine = await w.get(f"/v1/tryon/look?plan={plan}&private=1")
        named = {s.get("piece") for s in mine["slots"] if s["slot"] in COVERED}
        out += want(named == {ids["vest"], ids["briefs"]}, "with Show private basics: named")
        slots = [{"slot": k, "piece": v} for k, v in _drawn(look).items()]
        saved = await w.send("POST", "/v1/tryon/saved", json={"looks": [{"slots": slots}]})
        out += want(saved.status_code == 200, f"a look saved to share: {saved.status_code}")
        listed = json.dumps(await w.get("/v1/tryon/saved"))
        out += want(all(ids[n] not in listed for n in ("vest", "briefs")), "none in what's kept")
        await w.send("PUT", "/v1/tryon/body", json={"height": 178})
        await w.crop(ids["shirt"], "front", jpeg())
        before = await w.get("/v1/wardrobe?private=1")
        out += await _ops05(w)
        after = await w.get("/v1/wardrobe?private=1")
        out += want((after["rev"], after["pieces"]) == (before["rev"], before["pieces"]),
                    "the catalog is as it was, its photos too")  # fmt: skip
        figure = await w.get("/v1/tryon")
        out += want(figure["body"]["current"] is None and figure["body"]["draft"] is None,
                    "his figure is gone")  # fmt: skip
        out += want((await w.get("/v1/tryon/saved"))["saved"] == [], "saved looks gone")
        again = await w.ok("outfit_suggest", day="tomorrow")
        return out + want(bool(again["looks"]), "the wardrobe still suggests")


async def _ops05(w: World) -> list[str]:
    svc = w.app.state.privacy
    row = next(c for c in (await svc.view(w.uid)).categories if c.id == "tryon_all")
    got = await svc.delete(w.uid, "tryon_all", rev=row.rev, confirm=CONFIRM_WORD, proof=None,
                           fresh_left_s=60)  # fmt: skip
    return want(got.deleted >= 1 and got.remaining == 0, f"OPS-05 deleted {got}")


def _images(w: World) -> list[bytes]:
    import base64

    out = []
    for n in range(len(w.google.seen)):
        for part in w.google.body(n)["contents"][0]["parts"]:
            if "inlineData" in part:
                out.append(base64.b64decode(part["inlineData"]["data"]))
    return out


async def see_it_on_me_life() -> list[str]:
    async with running() as w:
        ids = await seed(w)
        (ids["jeans"],) = await w.add({"type": "jeans", "label": "Blue jeans", "colour": "blue"})
        await w.crop(ids["jeans"], "front", jpeg(extra=b"QXJEANSCROP"))  # today is casual
        rev = (await w.get("/v1/wardrobe?private=1"))["rev"]
        with w.signed_in():
            out = await _picture(w, ids)
        made = await w.get("/v1/seeme")
        out += want(len(made["pictures"]) == 1 and made["month"]["spent_inr"] > 0, "kept, paid")
        w.clock.advance(days=30, hours=1)
        for job in w.app.state.r13_parts["seeme"].daily_jobs:
            await job.run([w.uid])
        left = await w.get("/v1/seeme")
        out += want(left["pictures"] == [], f"gone after 30 days: {left['pictures']}")
        out += want(left["month"]["month"] == "2026-12", "a new month")
        pieces = await w.get("/v1/wardrobe?private=1")
        out += want(pieces["rev"] == rev, "the new garment never entered his wardrobe")
        return out + want(len(w.google.seen) == 1, f"one request: {len(w.google.seen)}")


async def _picture(w: World, ids: dict[str, str]) -> list[str]:
    person = jpeg(600, 1200, extra=b"QXHISPHOTO")
    got = await w.send("POST", "/v1/seeme/photo", content=person,
                       headers={"Content-Type": "image/jpeg"})  # fmt: skip
    out = want(got.status_code == 200, f"his photo: {got.status_code} {got.text[:120]}")
    view = await w.get("/v1/seeme")
    yes = {"typed": "YES", "template_version": view["consent"]["version"]}
    got = await w.send("POST", "/v1/seeme/consent", json=yes)
    out += want(got.status_code == 200, f"his YES: {got.status_code} {got.text[:120]}")
    got = await w.send("POST", "/v1/seeme/garments?type=shirt&colour=navy",
                       content=jpeg(600, 800, extra=b"QXNEWSHIRT"),
                       headers={"Content-Type": "image/jpeg"})  # fmt: skip
    out += want(got.status_code == 200, f"the new garment: {got.status_code} {got.text[:120]}")
    garment = got.json()["id"]
    pairing = await w.get(f"/v1/seeme/pair?garment={garment}")
    sent = [p["piece"] for p in pairing["pieces"]]
    out += want(sent == [ids["jeans"]], f"R13's pick, his jeans: {pairing}")
    est = await w.get(f"/v1/seeme/estimate?garment={garment}&pieces={','.join(sent)}")
    body = {"garment": garment, "pieces": sent, "confirm_cost": True,
            "inr_shown": est["typical_inr"], "request_id": "tq_" + "1" * 16}  # fmt: skip
    got = await w.send("POST", "/v1/seeme/pictures", json=body)
    out += want(got.status_code == 200, f"the picture: {got.status_code} {got.text[:160]}")
    pic = got.json()
    shown = await w.send("GET", f"/v1/seeme/pictures/{pic.get('id')}")
    out += want(shown.content == PNG_OUT, "the picture is Google's, as it came")
    until = w.clock() + timedelta(days=30)
    out += want(pic.get("until", "")[:10] == until.date().isoformat(), f"30 days: {pic}")
    images = _images(w)
    out += want(len(images) == 3, f"his photo, the garment and one crop: {len(images)}")
    marks = (b"QXHISPHOTO", b"QXNEWSHIRT", b"QXJEANSCROP")
    return out + want(all(any(m in i for i in images) for m in marks), "exactly those sent")


def _card(reply: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in reply.get("cards", []) if c.get("kind") == "tryon"]


async def what_to_wear_388() -> list[str]:
    out: list[str] = []
    for channel in ("text", "voice"):
        async with running() as w:
            await seed(w)
            call = ToolCall(id="t1", name="outfit_suggest", arguments={"day": "tomorrow"})
            w.brain.script_tool_calls([call], "Here is tomorrow's look, Sir.")
            reply = await w.chat("What should I wear tomorrow?", channel=channel)
            cards = _card(reply)
            out += want(len(cards) == 1, f"{channel}: one try-on card under the reply: {cards}")
            if not cards:
                continue
            card = cards[0]
            look = (await w.ok("outfit_suggest", day="tomorrow"))["looks"][0]["pieces"]
            mine = {p["slot"]: list(p["ids"]) for p in look if p["slot"] not in COVERED}
            shown = {s["slot"]: s["pieces"] for s in card["slots"] if not s.get("private")}
            out += want(shown == mine, f"{channel}: the card's pieces are the look's")
            q = ",".join(f"{s['slot']}:{p}" for s in card["slots"] for p in s["pieces"] or [""])
            fig = await w.get(f"/v1/tryon/look?pieces={q}&day={card['day']}&code={card['code']}")
            drawn = {s["slot"]: s["piece"] for s in fig["slots"] if s.get("piece")}
            first = {k: v[0] for k, v in mine.items()}
            out += want(drawn == first, f"{channel}: the figure wears exactly the card: {drawn}")
    return out


CASES: dict[str, Case] = {
    "meeting_outfit_update": meeting_outfit_update,
    "layer_and_rotate": layer_and_rotate,
    "private_items_and_photos": private_items_and_photos,
    "see_it_on_me_life": see_it_on_me_life,
    "what_to_wear_388": what_to_wear_388,
}


async def _run(names: list[str] | None = None) -> list[dict[str, Any]]:
    out = []
    for name, case in CASES.items():
        if names is not None and name not in names:
            continue
        try:
            failures = await case()
        except Exception as exc:  # noqa: BLE001 - a case that breaks is a failed case
            failures = [f"raised {type(exc).__name__}: {str(exc)[:200]}"]
        out.append({"id": f"{PART}:{name}", "passed": not failures, "failures": failures})
    return out


async def cases() -> list[dict[str, Any]]:
    return await _run()


def _stale_view() -> Any:
    """The look built from a stale view: each owner's FIRST read of R13's records, kept."""
    real = looks_mod.Looks.read
    first: dict[str, Any] = {}

    async def read(self: Any, uid: str) -> Any:
        if uid not in first:
            first[uid] = await real(self, uid)
        return first[uid]

    return mock.patch.object(looks_mod.Looks, "read", read)


async def control() -> dict[str, Any]:
    with _stale_view():
        got = await _run(["meeting_outfit_update"])
    failed = [r["id"] for r in got if not r["passed"]]
    return {
        "name": "the look built from a stale view",
        "suite_failed": f"{PART}:meeting_outfit_update" in failed,
        "failed_cases": failed,
    }


__all__ = ["BUILT", "CASES", "PART", "cases", "control"]

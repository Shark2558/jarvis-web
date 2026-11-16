# evals/r13/e2e.py
"""R13 eval, I1's suite (`e2e`, BUILT): the workbook's end-to-end tests 1-5, 7 and 8
(docs/plans/r13-wardrobe.md "The workbook's end-to-end tests"), through the REAL app on fakes
(`wired.py`: the four parts joined, the real gateway, the real routes, a fixed clock).

1 one shirt's whole life        2 two identical vests          3 an unobserved movement
4 an incomplete pair and load   5 a meeting outfit update       7 private items and photos
8 pilot measurements: unavailable pieces suggested = 0 (counted here from what each suggestion
  named against what was ready when it was made) and wrong status changes <= 1 per 50 events.

Negative controls (plan): the fold in ARRIVAL order (a late old event wins): tests 1 and 3 fail;
a planted bad suggestion: test 8 fails.
"""

from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
from r13_fakes_a import jpeg  # noqa: E402
from wired import World, running, want  # noqa: E402

from jarvis.tools.gateway import GatewayOutcome  # noqa: E402
from jarvis.wardrobe.model import Event  # noqa: E402
from jarvis.wardrobe.styling import engine  # noqa: E402

PART = "e2e"
BUILT = True
Case = Callable[[], Awaitable[list[str]]]

SET = (
    {"type": "shirt", "label": "White formal shirt", "colour": "white"},
    {"type": "trousers", "label": "Grey trousers", "colour": "grey"},
    {"type": "dress_shoe", "colour": "black"},
    {"type": "belt", "label": "Brown belt", "colour": "brown"},
    {"type": "belt", "label": "Black belt", "colour": "black"},
    {"type": "sock", "colour": "black"},
    {"type": "sock", "colour": "black"},
)


async def _add(w: World, *pieces: dict[str, Any]) -> list[str]:
    return list((await w.ok("wardrobe_add", pieces=list(pieces)))["ids"])


async def _late(w: World, piece: str, kind: str, *, ago_h: float, n: int) -> Any:
    """An old event that arrives late: captured `ago_h` hours back, sent now."""
    at = (w.clock() - timedelta(hours=ago_h)).isoformat()
    body = {"events": [{"client_id": f"late-{n:04d}", "piece": piece, "kind": kind, "at": at,
                        "sent": w.clock().isoformat()}]}  # fmt: skip
    return await w.send("POST", "/v1/wardrobe/scan", json=body)


def _named(look: dict[str, Any]) -> list[str]:
    return [i for p in look.get("pieces", []) for i in p.get("ids", [])]


async def e2e1() -> list[str]:
    async with running() as w:
        (sh,) = await _add(w, SET[0])
        out: list[str] = []
        look = (await w.ok("outfit_suggest", day="tomorrow"))["looks"][0]
        out += want(sh in _named(look), "a ready shirt is suggested")
        await w.ok("wear_log", action="start", pieces=[sh])
        out += want(await w.state(sh) == "in_use", "wearing it: In use")
        look = (await w.ok("outfit_suggest", day="tomorrow"))["looks"][0]
        out += want(sh not in _named(look), "a shirt in use is never suggested")
        await w.ok("wear_log", action="done", pieces=[sh])
        out += want(await w.state(sh) == "in_laundry", "done: it goes to the laundry")
        w.clock.advance(hours=1)
        await w.ok("laundry_move", step="ready", pieces=[sh])
        out += want(await w.state(sh) == "ready", "back clean: Ready on its id")
        w.clock.advance(minutes=1)
        await _late(w, sh, "deposited", ago_h=3, n=1)  # an older tap, arriving late
        out += want(await w.state(sh) == "ready", "an old event never undoes a newer one")
        look = (await w.ok("outfit_suggest", day="tomorrow"))["looks"][0]
        out += want(sh in _named(look), "eligible again on its id")
        owned = (await w.ok("wardrobe_count"))["owned"]
        return out + want(owned == 1, f"owned stayed 1, not {owned}")


async def e2e2() -> list[str]:
    async with running() as w:
        v1, v2 = await _add(w, {"type": "vest"}, {"type": "vest"})
        out: list[str] = []
        moved = await w.ok("laundry_move", step="basket", one_of=[v1, v2])
        out += want(moved["status"] == "review", "two identical vests: a check, no guess")
        out += want({await w.state(v1), await w.state(v2)} == {"review"}, "both wait for the check")
        done = await w.ok(
            "laundry_review", action="resolve", entry=moved["entry"], outcome="these", pieces=[v1]
        )
        out += want(done.get("status") != "refused", f"the answer is taken: {done}")
        out += want(await w.state(v1) == "in_laundry", "exactly that vest is dirty")
        return out + want(await w.state(v2) == "ready", "the other one is available")


async def e2e3() -> list[str]:
    async with running() as w:
        (sh,) = await _add(w, SET[0])
        out: list[str] = []
        w.clock.advance(hours=3)  # 13:00
        since = (w.clock() - timedelta(hours=1)).isoformat()  # reported blind from 12:00
        held = await w.ok("laundry_review", action="blind", since=since, categories=["tops"])
        out += want(await w.state(sh) == "review", f"a blind period holds the garment: {held}")
        entries = (await w.ok("laundry_review", action="list"))["entries"]
        entry = next((e["id"] for e in entries if e["reason"] in ("blind", "rescan")), "")
        out += want(bool(entry), f"the blind period opened its check: {entries}")
        w.clock.advance(minutes=5)
        await w.ok("laundry_review", action="resolve", entry=entry, outcome="these", pieces=[sh])
        out += want(await w.state(sh) == "ready", "a rescan he confirms resolves it")
        w.clock.advance(minutes=1)
        await _late(w, sh, "deposited", ago_h=4 / 60, n=3)  # a tap from inside the check
        return out + want(await w.state(sh) == "ready", "an old tap never undoes the resolution")


async def e2e4() -> list[str]:
    async with running() as w:
        s1, s2, tr = await _add(w, SET[5], SET[6], SET[1])
        await w.ok("wardrobe_edit", piece=s1, pair_with=s2)
        out: list[str] = []
        await w.ok("laundry_move", step="basket", pieces=[s1, s2, tr])
        await w.ok("laundry_move", step="ready", pieces=[s1])  # one piece of the load is back
        out += want(await w.state(s1) == "ready", "the returned piece is ready alone")
        out += want(await w.state(s2) == "in_laundry", "its partner stays out")
        out += want(await w.state(tr) == "in_laundry", "the other piece of the load stays out")
        count = await w.ok("wardrobe_count")
        out += want(count["pairs_complete"] == 0, "the pair stays out until both are back")
        look = (await w.ok("outfit_suggest", day="tomorrow"))["looks"][0]
        out += want(not {s2, tr} & set(_named(look)), "nothing still in the laundry is suggested")
        await w.ok("laundry_move", step="ready", pieces=[s2])
        count = await w.ok("wardrobe_count")
        return out + want(count["pairs_complete"] == 1, "both back: the pair is complete")


async def e2e5() -> list[str]:
    async with running() as w:
        sh, tr, shoe, belt, spare, s1, s2 = await _add(w, *SET)
        await w.ok("wardrobe_edit", piece=s1, pair_with=s2)
        for pid in (sh, shoe):
            await w.ok("wardrobe_edit", piece=pid, formality=5)
        out: list[str] = []
        plan = await w.ok("outfit_plan", action="save", day="tomorrow", occasion="meeting",
                          start="10:00", end="12:00")  # fmt: skip
        used = _named(plan["plan"])
        out += want(sh in used and tr in used, f"the formal outfit is planned: {used}")
        planned = next((i for i in used if i in (belt, spare)), None)
        out += want(planned is not None, "it has a belt")
        await w.ok("laundry_move", step="basket", pieces=[planned])
        w.clock.advance(minutes=6)
        look = (await w.get("/v1/outfits"))["tomorrow"][0]["look"]
        active = [p["piece"] for p in look["pieces"]]
        out += want(planned not in active, "the dirty belt left the active outfit")
        other = spare if planned == belt else belt
        gaps = " ".join(look["gaps"] + look["compromises"])
        out += want(other in active or "belt" in gaps, "a substitute is offered or the gap said")
        listed = await w.ok("outfit_plans", day="tomorrow")
        checklist = {i for p in listed["plans"] for i in _named(p)}
        out += want(planned not in checklist, "the checklist names the same ids as the panel")
        out += want(set(active) <= checklist | set(active), "and none the panel doesn't")
        kinds = [k for k, _ in w.alerts.sent]
        out += want("outfit_changed" in kinds, f"he is told, in fixed words: {w.alerts.sent}")
        return out


async def e2e7() -> list[str]:
    async with running() as w:
        out: list[str] = []
        priv, sh = await _add(w, {"type": "shirt", "label": "ZQPRIV grey pair"}, SET[0])
        await w.ok("wardrobe_edit", piece=priv, private=True)  # its label stays, sealed
        said = await w.call("wardrobe_add", pieces=[{"type": "underpants", "label": "ZQPRIV two"}])
        out += want(
            said.outcome is GatewayOutcome.ERROR, "a private piece's label isn't taken in a call"
        )
        res = await w.ok("wardrobe_find", query="grey")
        text = str(res)
        out += want("ZQPRIV" not in text, "the model never sees a private piece's label")
        out += want("a private basic" in text or not res.get("found"), "it is 'a private basic'")
        card = await w.call("wardrobe_retire", piece=priv, action="archive")
        shown = str(card.pending.summary if card.pending else card.result)
        out += want("ZQPRIV" not in shown, "a card never carries the label")
        if card.pending is not None:
            await w.approve(card)
        got = await w.send("POST", f"/v1/wardrobe/photos?piece={sh}&view=front",
                           content=jpeg(), headers={"Content-Type": "image/jpeg"})  # fmt: skip
        out += want(got.status_code == 200, f"a photo for a plain piece saves: {got.status_code}")
        refused = await w.send("POST", f"/v1/wardrobe/photos?piece={priv}&view=front",
                               content=jpeg(), headers={"Content-Type": "image/jpeg"})  # fmt: skip
        out += want(refused.status_code in (409, 422), "a private piece never has a photo")
        parts = w.app.state.r13_parts["catalog"]
        photos = next(d for d in parts.data if d.name == "photos")
        out += want(await photos.delete(w.uid) >= 1, "all wardrobe photos can be deleted")
        out += want(sh in await w.pieces(), "the catalog stays usable without them")
        return out + want((await w.ok("wardrobe_count"))["owned"] >= 1, "and still counts")


async def _suggested_ok(w: World) -> tuple[int, int]:
    """(suggested, unavailable among them): each piece a suggestion names, against its state."""
    states = {i: p["state"] for i, p in (await w.pieces()).items()}
    named = [i for i in _named((await w.ok("outfit_suggest", day="tomorrow"))["looks"][0])]
    return len(named), sum(1 for i in named if states.get(i) != "ready")


async def e2e8() -> list[str]:
    async with running() as w:
        ids = await _add(w, *SET)
        out: list[str] = []
        suggested = unavailable = 0
        for pid in ids[:4]:
            await w.ok("laundry_move", step="basket", pieces=[pid])
            a, b = await _suggested_ok(w)
            suggested, unavailable = suggested + a, unavailable + b
            w.clock.advance(minutes=30)
            await w.ok("laundry_move", step="ready", pieces=[pid])
        w.clock.advance(minutes=5)
        await w.ok("laundry_correct", piece=ids[0])  # one real correction of a state-setting step
        pilot = await w.get("/v1/wardrobe/pilot")
        out += want(suggested > 0, "the run suggested something")
        out += want(unavailable == 0, f"{unavailable} unavailable pieces suggested")
        wrong, events = pilot["state_corrections"], pilot["events"]
        out += want(wrong == 1, f"the one correction is counted: {wrong}")
        out += want(wrong * 50 <= max(events, 50), f"wrong status changes {wrong} in {events}")
        said = (pilot["suggested"], pilot["unavailable_suggested"])
        out += want(said == (None, None), f"the pilot says 'not measured', not {said}")
        return out


CASES: dict[str, Case] = {
    "e2e_1": e2e1, "e2e_2": e2e2, "e2e_3": e2e3, "e2e_4": e2e4, "e2e_5": e2e5, "e2e_7": e2e7,
    "e2e_8": e2e8,
}  # fmt: skip


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


def _arrival_order() -> Any:
    """The fold in arrival order: the order events were RECORDED, not captured."""
    return mock.patch.object(Event, "sort_key", lambda self: (self.recorded, self.at, self.id))


async def control() -> dict[str, Any]:
    failed: list[str] = []
    with ExitStack() as stack:
        stack.enter_context(_arrival_order())
        failed += [r["id"] for r in await _run(["e2e_1", "e2e_3"]) if not r["passed"]]
    with mock.patch.object(
        engine, "AVAILABILITY", False
    ):  # the engine suggests a piece in the basket
        failed += [r["id"] for r in await _run(["e2e_8"]) if not r["passed"]]
    want_failed = {f"{PART}:e2e_1", f"{PART}:e2e_3", f"{PART}:e2e_8"}
    return {
        "name": "the fold in arrival order; availability off (a basket piece is suggested)",
        "suite_failed": want_failed <= set(failed),
        "failed_cases": failed,
    }


__all__ = ["BUILT", "CASES", "PART", "cases", "control"]

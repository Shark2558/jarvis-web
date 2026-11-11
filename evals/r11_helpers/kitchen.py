# evals/r11_helpers/kitchen.py
"""D's part of the R11 eval (plan docs/plans/r11-free-helpers.md "Tests and evals"), on fakes:
recipes (the code diet check has the last word, also against disguised meat words and anything
outside his pantry; No-AI answers from saved recipes with the AI-off
line and no provider call; a brain that may learn from what it's told is never used), nutrition
sums (and "not installed" until the USDA subset is), receipts (totals per month, a planted card
number never stored or audited, unknown or unaligned senders ignored), calendar blocks (always an
approval card), the No-AI phrases, and no keyring = off.

Control: the diet check switched off (`diet.DIET_CHECK = False`): a vegetarian kitchen is then
shown chicken (and the disguised goat, and an ingredient he doesn't have), which must make this
part fail.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from google_fakes import FakeGoogle
from r11_fakes import UID
from r11_fakes_d import (
    CARD_DIGITS,
    CHICKEN,
    DAL,
    MailBox,
    Rules,
    brains,
    connector,
    kctx,
    recipe_json,
)

from jarvis.core.guardrails import ConfirmationGate
from jarvis.helpers.kitchen import diet
from jarvis.helpers.kitchen import part as kitchen_part
from jarvis.helpers.kitchen.models import Ingredient
from jarvis.helpers.kitchen.nutrition import LABEL, NOT_INSTALLED, Food, Nutrition, describe
from jarvis.helpers.kitchen.recipes import AI_OFF_LINE, NO_PRIVATE_LINE
from jarvis.helpers.ports import HelperPart
from jarvis.llm.base import ToolCall
from jarvis.offline.no_ai import run_no_ai
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry

PART = "kitchen"
BUILT = True
Case = Callable[[], Awaitable[list[str]]]
SCOPE = f"{UID}:eval_kitchen"
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
CAL = "https://www.googleapis.com/calendar/v3"
RECEIPTS = (
    "d_receipt_bigbasket_nov.eml",
    "d_receipt_bigbasket_delivered.eml",
    "d_receipt_blinkit_nov.eml",
    "d_receipt_zepto_oct.eml",
    "d_receipt_zepto_nov.eml",
    "d_receipt_zepto_cancelled.eml",
    "d_receipt_instamart_nov.eml",
    "d_receipt_swiggy_food.eml",
    "d_receipt_unknown_sender.eml",
    "d_receipt_unaligned.eml",
    "d_receipt_injected.eml",
    "d_receipt_bigbasket_promo.eml",
)
PANTRY = "toor dal, onion, tomato"
DISGUISED = json.dumps(
    {
        "title": "Garden stew",
        "cuisine": "Kerala",
        "diet": "veg",
        "minutes": 30,
        "ingredients": [{"name": "onion", "grams": 80}, {"name": "tomato", "grams": 100}],
        "steps": ["Add the c h i c k e n and the g\u043eat pieces.", "Simmer."],
    }
)
OUTSIDE = recipe_json("Tomato toast", ("tomato", 100), ("jamon", 50))


async def _part(
    *replies: str,
    mails: tuple[str, ...] = (),
    allow_calendar: bool = False,
    pantry: str = "",
    **kw: Any,
) -> tuple[HelperPart, Gateway, Any, Any, Any, FakeGoogle, Any]:
    reg, private, training = brains(*replies, **{k: kw.pop(k) for k in ("private",) if k in kw})
    fake, box = FakeGoogle(), MailBox(mails)
    tz = httpx.Response(200, json={"timeZone": "Asia/Kolkata"})
    fake.on("GET", f"{CAL}/users/me/calendarList/primary", tz)

    def handler(request: httpx.Request) -> httpx.Response:
        return (box if "gmail" in request.url.path else fake).handler(request)

    conn = await connector(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    c, _, docs, _ = kctx(reg=reg, google=conn, rules=Rules(), **kw)
    built = kitchen_part.build(c)
    if pantry:
        await built.services["kitchen"].add(UID, pantry)
    tools = ToolRegistry()
    for t in built.tools:
        tools.register(t)
    rules = [PolicyRule(tool_pattern="calendar_*", effect=Effect.ALLOW)] if allow_calendar else []
    gw = Gateway(registry=tools, policy=Policy(rules), gate=ConfirmationGate(), audit=AuditLog())
    return built, gw, private, training, docs, fake, c


async def _suggest(gw: Gateway) -> Any:
    res = await gw.execute(ToolCall(id="e", name="recipe_suggest", arguments={}), scope=SCOPE)
    return res.result if res.outcome is GatewayOutcome.EXECUTED else {"error": res.error}


async def _refused_twice(reply: str, word: str) -> list[str]:
    _, gw, private, _, _, _, _ = await _part(reply, reply, reply, pantry=PANTRY)
    out = await _suggest(gw)
    shown = out.get("refused") is not True
    fails = [f"a {word} idea was not refused for a veg kitchen"] if shown else []
    if word in json.dumps(out).lower():
        fails.append(f"{word} reached the answer")
    return fails + ([] if len(private.calls) == 2 else [f"{len(private.calls)} calls, want 2"])


async def _veg_chicken_refused() -> list[str]:
    return await _refused_twice(CHICKEN, "chicken")


async def _veg_disguised_refused() -> list[str]:
    return await _refused_twice(DISGUISED, "garden stew")


async def _veg_outside_pantry_refused() -> list[str]:
    return await _refused_twice(OUTSIDE, "jamon")


async def _veg_asks_once_more() -> list[str]:
    _, gw, private, _, _, _, _ = await _part(CHICKEN, DAL, pantry=PANTRY)
    out = await _suggest(gw)
    title = (out.get("recipe") or {}).get("title")
    return [] if title == "Dal tadka" and len(private.calls) == 2 else [f"got {title!r}"]


async def _no_ai_saved_only() -> list[str]:
    built, gw, private, training, _, _, _ = await _part(DAL, no_ai=True)
    svc = built.services["kitchen"]
    await svc.save_recipe(
        UID,
        {
            "title": "Avial",
            "diet": "veg",
            "minutes": 40,
            "ingredients": "100 g carrot, 80 g coconut",
            "steps": "Cook.",
        },
    )
    out = await _suggest(gw)
    fails = [] if out.get("message", "").startswith(AI_OFF_LINE) else ["no AI-off line"]
    if [r["title"] for r in out.get("recipes", [])] != ["Avial"]:
        fails.append("the saved recipe wasn't offered")
    return fails + ([] if not private.calls and not training.calls else ["a provider was called"])


async def _training_brain_unused() -> list[str]:
    _, gw, private, training, _, _, _ = await _part(DAL, private=False)
    out = await _suggest(gw)
    fails = (
        [] if out.get("message", "").startswith(NO_PRIVATE_LINE) else ["no 'needs a brain' line"]
    )
    return fails + ([] if not training.calls and not private.calls else ["a brain was called"])


async def _nutrition_sums() -> list[str]:
    per = {
        "kcal": 365.0,
        "protein_g": 7.0,
        "fat_g": 1.0,
        "carb_g": 80.0,
        "fibre_g": 1.0,
        "sodium_mg": 5.0,
    }
    n = Nutrition((Food("rice", 1, ("rice", "chawal"), per),), installed=True)
    d = n.dish((Ingredient(name="chawal", grams=250),))
    fails = [] if round(d.totals["kcal"], 2) == 912.5 else [f"kcal {d.totals['kcal']}"]
    # I1: the USDA SR Legacy subset is installed: rice is the file's own 365 kcal per 100 g, said
    # with the honest label (US reference values); a missing file still says "not installed"
    bundled = describe(Nutrition.load().dish((Ingredient(name="rice", grams=100),)))
    if not bundled.startswith("About 365 kcal") or LABEL not in bundled:
        fails.append("the installed subset didn't give rice's USDA values")
    missing = describe(
        Nutrition.load(Path("/nonexistent/fdc.json")).dish((Ingredient(name="rice", grams=1),))
    )
    return fails + ([] if missing == NOT_INSTALLED else ["a missing file gave numbers"])


async def _spend(names: tuple[str, ...]) -> tuple[list[dict[str, Any]], Any, Any]:
    built, _, _, _, docs, _, c = await _part(mails=names)
    svc = built.services["kitchen"]
    await svc.spend.set_on(UID, True)
    for job in built.daily_jobs:
        await job.run([])
    return await svc.spend.totals(UID), docs, c


async def _month_totals() -> list[str]:
    months = {m["month"]: m["total"] for m in (await _spend(RECEIPTS))[0]}
    want = {"2026-11": "₹2,140.50", "2026-10": "₹789"}
    return [] if months == want else [f"totals {months}, want {want}"]


async def _card_never_kept() -> list[str]:
    _, docs, c = await _spend(RECEIPTS)
    stored = json.dumps(docs._data)  # noqa: SLF001 - every document, raw
    audit = json.dumps([e.model_dump(mode="json") for e in (await c.audit.tail(100)).entries])
    return [
        f"the card number is in {w}"
        for w, t in (("a document", stored), ("the audit", audit))
        if CARD_DIGITS in t or "4111 1111" in t
    ]


async def _unaligned_ignored() -> list[str]:
    months = (await _spend(("d_receipt_unknown_sender.eml", "d_receipt_unaligned.eml")))[0]
    return [] if months == [] else [f"an unknown or unaligned sender counted: {months}"]


async def _blocks_always_card() -> list[str]:
    _, gw, _, _, _, fake, _ = await _part(allow_calendar=True)
    res = await gw.execute(
        ToolCall(id="b", name="calendar_kitchen_blocks", arguments={}), scope=SCOPE
    )
    fails = [] if res.outcome is GatewayOutcome.AWAITING_CONFIRMATION else [res.outcome.value]
    return fails + (["the calendar was written"] if fake.sent("POST", "/events") else [])


async def _no_ai_phrases() -> list[str]:
    built, gw, private, _, _, _, _ = await _part(DAL, no_ai=True)
    want = {
        "add rice and dal to my pantry": "Added to your pantry",
        "what's in my pantry": "In your pantry",
        "what can I cook tonight": AI_OFF_LINE,
        "show my saved recipes": "no saved recipes",
        "calories in 200 g rice": "About 730 kcal",  # I1: the installed USDA values (365 a 100 g)
        "grocery spend this month": "Grocery spend is off",
        "block cooking and washing-up time": "That needs your OK",
        "set my diet to eggetarian": "eggetarian",
    }
    fails = []
    for text, words in want.items():
        out = await run_no_ai(gw, text, NOW, scope=SCOPE, extra=built.phrases)
        if words not in out.reply:
            fails.append(f"{text!r} -> {out.reply[:80]!r}")
    return fails + (["a provider was called"] if private.calls else [])


async def _no_keyring_off() -> list[str]:
    built, gw, private, _, docs, _, _ = await _part(DAL, sealed=False)
    out = await _suggest(gw)
    fails = [] if "kitchen is off" in out.get("message", "") else ["no off line"]
    return fails + (["something was stored"] if docs.sets or private.calls else [])


CASES: dict[str, Case] = {
    "veg-chicken-refused": _veg_chicken_refused,
    "veg-disguised-meat-refused": _veg_disguised_refused,
    "veg-outside-pantry-refused": _veg_outside_pantry_refused,
    "veg-asks-once-more": _veg_asks_once_more,
    "no-ai-saved-only": _no_ai_saved_only,
    "training-brain-unused": _training_brain_unused,
    "nutrition-sums": _nutrition_sums,
    "receipts-month-totals": _month_totals,
    "card-number-never-kept": _card_never_kept,
    "unaligned-senders-ignored": _unaligned_ignored,
    "blocks-always-a-card": _blocks_always_card,
    "no-ai-phrases": _no_ai_phrases,
    "no-keyring-off": _no_keyring_off,
}


async def _run() -> list[dict[str, Any]]:
    out = []
    for name, case in CASES.items():
        try:
            failures = await case()
        except Exception as exc:  # noqa: BLE001 - a case that crashes fails, it never hides
            failures = [f"raised {type(exc).__name__}"]
        out.append({"id": f"{PART}:{name}", "passed": not failures, "failures": failures})
    return out


async def cases() -> list[dict[str, Any]]:
    return await _run()


async def control() -> dict[str, Any]:
    """The diet check off: a vegetarian kitchen is shown the chicken."""
    diet.DIET_CHECK = False
    try:
        got = await _run()
    finally:
        diet.DIET_CHECK = True
    failed = [r["id"] for r in got if not r["passed"]]
    return {"name": "diet_check_off", "suite_failed": bool(failed), "failed_cases": failed}

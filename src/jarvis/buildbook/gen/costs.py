# src/jarvis/buildbook/gen/costs.py
"""R6 D2: the Subscriptions & costs section. Every amount is in ₹ per unit at billing.fx's
DEFAULT_RATE (and its date), read with the rest from the code as ASTs:

    model   llm/pricing.py PRICES: input and output per 1M tokens; free brains at ₹0
    voice   Settings defaults: Chirp 3 HD and Studio per 1M characters, speech per minute, and
            the free monthly characters and seconds JARVIS may use
    search  web/allowance.py MONTHLY_CREDITS (JARVIS stops there: ₹0)
    maps    quota/ledger.py _TABLE, Google's global price list (JARVIS stops at the allowance)
    cloud   the free tiers JARVIS runs inside (`FREE_TIER`, as the R6 plan lists them)

A checkout without billing/fx.py (the test fixture) is priced at `FALLBACK_RATE`, and a module that
isn't there gives no items; a module that IS there but can't be read (not Python, a value that
isn't a literal, a row of the wrong shape) fails the build, so the book never quietly drops or
misprices what the code says.
"""

from __future__ import annotations

import ast
import re
from typing import Any, Literal

from jarvis.buildbook.gen.code import module_path, settings_defaults, top_expr, top_value, tree
from jarvis.buildbook.gen.repo import GenError, Repo
from jarvis.buildbook.sections import CostItem, Costs

FALLBACK_RATE: tuple[float, str] = (95.24, "2026-11-01")  # billing.fx at R6
FREE_TIER: tuple[tuple[str, str, str, str], ...] = (
    ("cloud_run", "Cloud Run", "month", "2 million requests a month"),
    ("firestore", "Firestore", "month", "1 GiB stored"),
    ("secret_manager", "Secret Manager", "month", "6 secret versions"),
    ("cloud_scheduler", "Cloud Scheduler", "month", "3 jobs"),
    ("github_actions", "GitHub Actions", "month", "2,000 minutes a month"),
)
CostKind = Literal["model", "voice", "search", "maps", "cloud", "other"]
FREE_BRAIN = "free of charge; Google may learn from what it is told"
_PER = {"month": "a month", "day": "a day"}
PRICE_FIELDS = ("input_per_mtok", "output_per_mtok")
VOICE_KEYS = (
    "voice_price_chirp3_hd_usd_per_m",
    "voice_price_studio_usd_per_m",
    "voice_price_stt_usd_per_min",
)


def _id(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60]


def model_label(model: str) -> str:
    """A model id in words: "claude-opus-5-5" -> "Claude Opus 5.5"."""
    words: list[str] = []
    for part in model.split("-"):
        if re.fullmatch(r"[\d.]+", part) and words and re.fullmatch(r"[\d.]+", words[-1]):
            words[-1] = f"{words[-1]}.{part}"
        else:
            words.append(part if re.fullmatch(r"[\d.]+", part) else part.capitalize())
    return " ".join(words)


def rate(repo: Repo) -> tuple[float, str]:
    rel = module_path(repo, "billing.fx")
    module = tree(repo, rel)
    if module is None:
        return FALLBACK_RATE  # a checkout without billing/fx.py (the fixture)
    value, when = top_value(module, "DEFAULT_RATE"), top_value(module, "DEFAULT_AS_OF")
    if isinstance(value, (int, float)) and value > 0 and isinstance(when, str):
        return float(value), when
    raise GenError(f"{rel}: DEFAULT_RATE and DEFAULT_AS_OF must be literals (a rate, a date)")


def _price(call: ast.expr | None) -> tuple[float, float] | None:
    """`Price(in, out, ...)` or `Price(input_per_mtok=in, output_per_mtok=out, ...)`."""
    if not isinstance(call, ast.Call):
        return None
    named = {k.arg: k.value for k in call.keywords if k.arg}
    args = list(call.args[:2])
    for i, key in enumerate(PRICE_FIELDS):
        if len(args) <= i and key in named:
            args.append(named[key])
    try:
        values = [ast.literal_eval(a) for a in args]
    except ValueError:
        return None
    if len(values) < 2 or not all(isinstance(v, (int, float)) for v in values):
        return None
    return float(values[0]), float(values[1])


def model_prices(repo: Repo) -> dict[str, tuple[float, float]]:
    """PRICES = {"model": Price(input, output, ...)} -> {model: (input, output)} US$ per 1M."""
    rel = module_path(repo, "llm.pricing")
    module = tree(repo, rel)
    if module is None:
        return {}
    node = top_expr(module, "PRICES")
    if not isinstance(node, ast.Dict):
        raise GenError(f"{rel}: PRICES isn't a literal table")
    out: dict[str, tuple[float, float]] = {}
    for key, call in zip(node.keys, node.values, strict=True):
        price = _price(call)
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)) or price is None:
            raise GenError(f"{rel}: a PRICES entry isn't a model id and Price(input, output)")
        out[key.value] = price
    return out


def _inr(usd: float, fx: float) -> float:
    return round(usd * fx, 2)


def _models(repo: Repo, fx: float) -> list[CostItem]:
    out = []
    for model, (usd_in, usd_out) in model_prices(repo).items():
        if model == "mock":
            continue
        label, mid = model_label(model), _id(model)
        if usd_in == 0 and usd_out == 0:
            out.append(
                CostItem(
                    id=mid, label=label, kind="model", unit="1M tokens", inr=0, free=FREE_BRAIN
                )
            )
            continue
        for side, short, usd in (("input", "in", usd_in), ("output", "out", usd_out)):
            out.append(
                CostItem(
                    id=f"{mid}_{short}",
                    label=f"{label}, {side}",
                    kind="model",
                    unit=f"1M {side} tokens",
                    inr=_inr(usd, fx),
                )
            )
    return out


def _voice(repo: Repo, fx: float) -> list[CostItem]:
    s: dict[str, Any] = settings_defaults(repo)
    if not s:
        return []  # no Settings in this checkout (the fixture)
    missing = [k for k in VOICE_KEYS if not isinstance(s.get(k), (int, float))]
    if missing:
        raise GenError(f"jarvis/config.py: no literal Settings default for {', '.join(missing)}")
    chars, secs = s.get("voice_tts_free_chars"), s.get("voice_stt_free_seconds")
    free_chars = f"{chars:,} characters a month" if isinstance(chars, int) and chars else ""
    free_secs = f"{secs // 60:,} minutes a month" if isinstance(secs, int) and secs else ""
    table = (
        (
            "voice_chirp3_hd",
            "Cloud voice (Chirp 3: HD)",
            "voice_price_chirp3_hd_usd_per_m",
            "1M characters",
            free_chars,
        ),
        (
            "voice_studio",
            "Cloud voice (Studio)",
            "voice_price_studio_usd_per_m",
            "1M characters",
            free_chars,
        ),
        (
            "speech_to_text",
            "Speech recognition",
            "voice_price_stt_usd_per_min",
            "minute",
            free_secs,
        ),
    )
    return [
        CostItem(
            id=cid, label=label, kind="voice", unit=unit, inr=_inr(float(s[key]), fx), free=free
        )
        for cid, label, key, unit, free in table
    ]


def _search(repo: Repo) -> list[CostItem]:
    rel = module_path(repo, "web.allowance")
    module = tree(repo, rel)
    if module is None:
        return []
    credits = top_value(module, "MONTHLY_CREDITS")
    if not isinstance(credits, int):
        raise GenError(f"{rel}: MONTHLY_CREDITS isn't a literal number")
    return [
        CostItem(
            id="web_search",
            label="Tavily web search",
            kind="search",
            unit="search credit",
            inr=0,
            free=f"{credits:,} credits a month",
        )
    ]


def _maps(repo: Repo) -> list[CostItem]:
    rel = module_path(repo, "quota.ledger")
    module = tree(repo, rel)
    if module is None:
        return []
    table = top_value(module, "_TABLE")
    if not isinstance(table, tuple) or not all(isinstance(r, tuple) and len(r) == 5 for r in table):
        raise GenError(f"{rel}: _TABLE isn't a literal table of (id, label, unit, per, free)")
    out = []
    for sid, label, unit, per, free in table:
        allowance = free.get("global") if isinstance(free, dict) else None
        if isinstance(allowance, int):
            words = f"{allowance:,} {unit} {_PER.get(per, per)}"
            kind: CostKind = "maps" if sid.startswith("maps") else "other"
            out.append(
                CostItem(
                    id=_id(sid), label=label, kind=kind, unit=unit.rstrip("s"), inr=0, free=words
                )
            )
    return out


def costs(repo: Repo) -> Costs:
    fx, when = rate(repo)
    cloud = [
        CostItem(id=i, label=lb, kind="cloud", unit=u, inr=0, free=f) for i, lb, u, f in FREE_TIER
    ]
    items = [*_models(repo, fx), *_voice(repo, fx), *_search(repo), *_maps(repo), *cloud]
    return Costs(usd_inr=fx, rate_date=when, items=tuple(items))


__all__ = ["FALLBACK_RATE", "FREE_TIER", "costs", "model_label", "model_prices", "rate"]

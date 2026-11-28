# src/jarvis/buildbook/gen/facts_values.py
"""R6.3 D2, D9 (docs/plans/r6-3-book-content.md, "The tour's facts"): the named facts the tour and
the pages quote, each read from the code at CI with the source it was read from, never typed.

`tour_values(repo, ctx)` gives every key of `facts_model.FACT_TOUR_KEYS` whose source the
checkout holds (`facts.all_or_none` then keeps all 30 or none): the release (label, version,
its IST day as "24 Nov 2026", the plan's title), the guide's counts, the counter's Python figure
in words, the layers, the brain's everyday model in words, the constants and settings the table
names, the keyring's purposes, the services, the try-on's measures and its price a picture in ₹
(`llm/tryon.py` at the configured model and location, x the book's rate x (1 + GST)), the lock's
pins, the rate, the roadmap's next two rows.
`hosting_values(repo)`: the deploy script's region, size and instances, `verified=False` (D2:
a hosting fact stays Unverified until a live check sets it).
"""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from jarvis.buildbook.facts_model import FactValue
from jarvis.buildbook.gen import costs, libs, plans
from jarvis.buildbook.gen.code import literal_args, top_expr, top_value, tree
from jarvis.buildbook.gen.facts_code import number
from jarvis.buildbook.gen.fallback import VERSION_FILE, version_of
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.gen.scrub import Scrubber
from jarvis.buildbook.gen.show import human_date

IST = timezone(timedelta(hours=5, minutes=30))
CONFIG = "src/jarvis/config.py"
SECTIONS = "src/jarvis/buildbook/sections.py"
KEYRING = "src/jarvis/keyring.py"
TRYON = "src/jarvis/llm/tryon.py"
MEASURES = "src/jarvis/wardrobe/tryon/model.py"
VAULT = "src/jarvis/vault/models.py"
EMERGENCY = "src/jarvis/sos/message.py"
DEPLOY = "deploy/cloudrun.sh"
MODULES_FILE = "src/jarvis/buildbook/gen/modules.py"
LOC_FILE = "src/jarvis/buildbook/gen/loc.py"
SECONDS_A_MINUTE = 60
ROADMAP_KEYS = ("roadmap.next", "roadmap.after")  # the guide §11's first two rows
TRYON_GARMENTS = 1  # "a garment you're thinking of buying": one crop beside his photo
# (tour key, file, constant) read from the constants the pack already holds
CONSTANT_KEYS: tuple[tuple[str, str, str], ...] = (
    ("undo.keep_days", "src/jarvis/undo/models.py", "RETENTION_DAYS"),
    ("approvals.max_new_cards", "src/jarvis/tools/budget.py", "MAX_NEW_CARDS"),
    ("memory.facts_per_turn", "src/jarvis/recall/models.py", "MAX_FACTS_PER_TURN"),
    ("sos.hold_s", "src/jarvis/sos/service.py", "HOLD_S"),
    ("sos.countdown_s", "src/jarvis/sos/service.py", "WEB_COUNTDOWN_S"),
)
SETTING_KEYS: tuple[tuple[str, str], ...] = (
    ("memory.learn_a_day", "memory_learn_daily_cap"),
    ("vault.unlock_minutes", "vault_unlock_minutes"),
    ("sos.max_contacts", "sos_max_contacts"),
)
_FLAG = {
    "hosting.cpu": re.compile(r"--cpu[ =](\S+)"),
    "hosting.memory": re.compile(r"--memory[ =](\S+)"),
    "hosting.min_instances": re.compile(r"--min-instances[ =](\d+)"),
    "hosting.max_instances": re.compile(r"--max-instances[ =](\d+)"),
    "hosting.timeout_s": re.compile(r"--timeout[ =](\d+)"),
}
_REGION = re.compile(r"^REGION=\"\$\{REGION:-([a-z0-9-]+)\}\"", re.MULTILINE)
Scalar = str | int | float | bool


@dataclass(frozen=True)
class Context:
    """What `facts.build` has already read, so nothing is read twice."""

    scrub: Scrubber
    constants: Mapping[str, FactValue]
    defaults: Mapping[str, Scalar]  # setting name -> its literal default
    cards: int
    modules: int
    others: int
    services: int
    python_code: str  # loc.in_thousands(...)
    roadmap: Sequence[str]
    guide: str  # the guide's path when it exists, else ""


def _v(value: Scalar, source: str, *, verified: bool = True) -> FactValue:
    return FactValue(value=value, source=source, verified=verified)


def release_values(repo: Repo, scrub: Scrubber) -> dict[str, FactValue]:
    out = {"release.label": _v(plans.release_label(repo), VERSION_FILE)}
    version = version_of(repo.text(VERSION_FILE))
    if version:
        out["release.version"] = _v(version, VERSION_FILE)
    day = _ist_day(repo.committed_at)
    if day:
        out["release.date"] = _v(day, "the commit's date")
    exact = _plan_with_version(repo, version) if version else None
    own = (exact,) if exact else plans.plan_paths(repo)[:1]
    title = _plan_title(repo.text(own[0]) or "") if own else ""
    if own and title and (exact or plans.label_of(own[0]) == plans.own_label(repo)):
        out["release.new"] = _v(scrub.clean(title), own[0])
    return out


def _plan_with_version(repo: Repo, version: str) -> str | None:
    """R6.3.1: the plan whose title names this exact version (`v6.3.2`), so a follow-up release
    the version labels with its parent ("R6.3") is told by its own plan, not the parent's."""
    for path in plans.plan_paths(repo):
        head = next((ln for ln in (repo.text(path) or "").splitlines() if ln.startswith("# ")), "")
        if f"`{version}`" in head or f"({version})" in head:
            return path
    return None


def _ist_day(stamp: str) -> str:
    """The commit's day in IST, as the book writes a day ("24 Nov 2026", `show.human_date`)."""
    try:
        when = datetime.fromisoformat(stamp).astimezone(IST)
    except ValueError:
        return ""
    return human_date(when.date().isoformat())


def _plan_title(text: str) -> str:
    """ "# Release R6.3 — The Build Book: ... (`v6.3.0`)" -> "The Build Book: ..."."""
    head = next((ln[2:] for ln in text.splitlines() if ln.startswith("# ")), "")
    words = plans.plain_md(head)
    after = words.split(" — ", 1)[1] if " — " in words else ""
    return re.sub(r"\s*\(v\d+\.\d+\.\d+\)\s*$", "", after).strip()


def _count_values(ctx: Context) -> dict[str, FactValue]:
    out: dict[str, FactValue] = {}
    if ctx.guide:
        out["cards.count"] = _v(ctx.cards, ctx.guide)
        out["modules.count"] = _v(ctx.modules, MODULES_FILE)
        out["modules.else_count"] = _v(ctx.others, MODULES_FILE)
    if ctx.services:
        out["services.count"] = _v(ctx.services, "src/jarvis/buildbook/gen/services.py")
    out["loc.python_code"] = _v(ctx.python_code, LOC_FILE)
    for n, row in enumerate(ctx.roadmap[: len(ROADMAP_KEYS)]):
        out[ROADMAP_KEYS[n]] = _v(ctx.scrub.clean(row), f"{ctx.guide} §11 row {n + 1}")
    return out


def _code_values(repo: Repo, ctx: Context) -> dict[str, FactValue]:
    out: dict[str, FactValue] = {}
    for key, rel, name in CONSTANT_KEYS:
        got = ctx.constants.get(f"{ctx.scrub.clean(rel)}:{name}")
        if got is not None:
            out[key] = _v(got.value, got.source)
    for key, setting in SETTING_KEYS:
        if setting in ctx.defaults:
            out[key] = _v(ctx.defaults[setting], f"{CONFIG}:{setting}")
    offline = ctx.defaults.get("home_offline_after_s")
    if isinstance(offline, int) and not isinstance(offline, bool):
        minutes = round(offline / SECONDS_A_MINUTE)
        out["home.offline_minutes"] = _v(minutes, f"{CONFIG}:home_offline_after_s")
    model = ctx.defaults.get("model_balanced")
    if isinstance(model, str):
        out["brain.balanced_model"] = _v(costs.model_label(model), f"{CONFIG}:model_balanced")
    out.update(_module_values(repo))
    return out


def _top(repo: Repo, rel: str, name: str) -> Any:
    """A top-level literal of a module the checkout holds (None: no module, no literal)."""
    module = tree(repo, rel)
    return top_value(module, name) if module is not None else None


def _module_values(repo: Repo) -> dict[str, FactValue]:
    out: dict[str, FactValue] = {}
    layers = _top(repo, SECTIONS, "LAYERS")
    if isinstance(layers, tuple):
        floors = [row for row in layers if isinstance(row, tuple) and row and row[0] != "X"]
        out["layers.count"] = _v(len(floors), f"{SECTIONS}:LAYERS")
    purposes = _top(repo, KEYRING, "PURPOSES")
    if isinstance(purposes, tuple):
        out["keys.purposes"] = _v(len(purposes), f"{KEYRING}:PURPOSES")
    reminders = _top(repo, VAULT, "REMINDER_CHOICES")
    if isinstance(reminders, tuple) and reminders:
        out["vault.reminder_days_first"] = _v(reminders[0], f"{VAULT}:REMINDER_CHOICES")
    emergency = _top(repo, EMERGENCY, "EMERGENCY")
    if isinstance(emergency, str):
        out["sos.emergency"] = _v(emergency, f"{EMERGENCY}:EMERGENCY")
    measured = tree(repo, MEASURES)
    measures = literal_args(measured, "Measure") if measured is not None else ()
    if measures:
        out["tryon.measures"] = _v(len(measures), f"{MEASURES}:Measure")
    return out


def _money_values(repo: Repo, ctx: Context) -> dict[str, FactValue]:
    rate, _ = costs.rate(repo)
    out = {"costs.rate": _v(rate, "src/jarvis/buildbook/gen/costs.py:rate")}
    pins = libs.locked(repo)
    if pins:
        out["libs.python_pins"] = _v(len(pins), libs.LOCK)
    cap = ctx.defaults.get("tryon_month_cap_inr")
    if isinstance(cap, int) and not isinstance(cap, bool):
        out["seeme.month_cap_inr"] = _v(f"₹{cap}", f"{CONFIG}:tryon_month_cap_inr")
    usd = tryon_usd(repo, ctx.defaults)
    tax = ctx.defaults.get("tryon_tax_pct")
    if usd is not None and isinstance(tax, (int, float)):
        inr = usd * rate * (1 + tax / 100)
        out["seeme.inr_a_picture"] = _v(f"₹{round(inr)}", f"{TRYON}:TRYON_PRICES")
    return out


def tryon_usd(repo: Repo, defaults: Mapping[str, Scalar]) -> float | None:
    """One typical picture at the configured (model, location), as `llm/tryon.typical_usd` prices
    it: his photo and one garment in, one 1K picture and THINKING_TYPICAL text tokens out."""
    module = tree(repo, TRYON) if repo.has(TRYON) else None
    key = (defaults.get("tryon_model"), defaults.get("tryon_location"))
    table = top_expr(module, "TRYON_PRICES") if module else None
    if module is None or not isinstance(table, ast.Dict):
        return None
    pairs = [(top_value_of(k), v) for k, v in zip(table.keys, table.values, strict=True)]
    expr = next((v for k, v in pairs if k == key), None)
    if isinstance(expr, ast.Name):
        expr = top_expr(module, expr.id)
    price = _price(module, expr)
    thinking, prompt = top_value(module, "THINKING_TYPICAL"), top_value(module, "PROMPT_TOKENS")
    if price is None or not isinstance(thinking, int) or not isinstance(prompt, int):
        return None
    inp, text, image, per_image = price
    tokens_in = (1 + TRYON_GARMENTS) * per_image + prompt
    return (tokens_in * inp + per_image * image + thinking * text) / 1_000_000


def top_value_of(node: ast.expr | None) -> object:
    try:
        return ast.literal_eval(node) if node is not None else None
    except ValueError:
        return None


def _price(module: ast.Module, call: ast.expr | None) -> tuple[float, float, float, int] | None:
    """TryOnPrice(input_per_m, text_per_m, image_per_m, tokens_per_image=its class default)."""
    if not isinstance(call, ast.Call):
        return None
    names = ("input_per_m", "text_per_m", "image_per_m", "tokens_per_image")
    got: dict[str, float | None] = dict(zip(names, (number(a) for a in call.args), strict=False))
    got.update({k.arg: number(k.value) for k in call.keywords if k.arg in names})
    if "tokens_per_image" not in got:
        cls = next(
            (n for n in module.body if isinstance(n, ast.ClassDef) and n.name == "TryOnPrice"), None
        )
        field = (
            top_expr(ast.Module(body=cls.body, type_ignores=[]), "tokens_per_image")
            if cls
            else None
        )
        got["tokens_per_image"] = number(field)
    values = [got.get(n) for n in names]
    if any(v is None for v in values):
        return None
    inp, text, image, per = (float(v or 0) for v in values)
    return inp, text, image, int(per)


def tour_values(repo: Repo, ctx: Context) -> dict[str, FactValue]:
    return {
        **release_values(repo, ctx.scrub),
        **_count_values(ctx),
        **_code_values(repo, ctx),
        **_money_values(repo, ctx),
    }


def hosting_values(repo: Repo) -> dict[str, FactValue]:
    text = repo.text(DEPLOY) or ""
    out: dict[str, FactValue] = {}
    region = _REGION.search(text)
    if region:
        out["hosting.region"] = _v(region.group(1), DEPLOY, verified=False)
    for key, pattern in _FLAG.items():
        m = pattern.search(text)
        if m:
            value: Scalar = int(m.group(1)) if m.group(1).isdigit() else m.group(1)
            out[key] = _v(value, DEPLOY, verified=False)
    return out


__all__ = ["CONSTANT_KEYS", "Context", "SETTING_KEYS", "hosting_values", "tour_values", "tryon_usd"]

# src/jarvis/buildbook/gen/facts.py
"""R6.3 D2 (docs/plans/r6-3-book-content.md): the fact pack, computed at CI from the release's own
code, never typed. Standard library only, deterministic (every collection sorted, never a set
iterated as it comes), every path SCRUBBED (`scrub.clean`, H6: 46 Android paths hold the owner's
handle; the join's `Scrubber.verify` refuses the pack otherwise).

`build(repo, scrub, *, modules=MODULES, services_table=None) -> FactPack`:

    values       the tour's keys, all 30 or none (`gen/facts_values.py`, `all_or_none`),
                 every literal module constant as `path:NAME` (H5), every setting's default as
                 `settings.<name>`, A's own counts, and the hosting facts with `verified=False`
                 (D2)
    index        every tracked path, every top-level function and class of `src/` as
                 `path:symbol`, every constant, setting, collection and route
    routes       every router's routes by AST (M9, `gen/facts_routes.py`)
    settings     every `Settings` field with its default and bounds (`gen/facts_code.py`)
    collections  the Firestore collections the code names
    modules      the module map (`gen/modules.py`; a card in no module or in two is a GenError)
    cards        the guide's cards, "Where in the code" resolved (`gen/refs.py`) and scrubbed
    screens      the console's panels and the show
    services     the coverage checker's inventory (`gen/services.py`, M7); with no table, the
                 services the cards name
    loc          the counter's rows (D2a, `gen/loc.py`)
    limitations  ALL of them (G4): the licence notes, then every plan's, in the book's order

The join (`gen/write.py`) sets `release` and `pages` and checks the pack: they stay unset here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from jarvis.buildbook.facts_model import (
    FACT_TOUR_KEYS,
    CardFact,
    FactIndex,
    FactPack,
    FactValue,
    ModuleFact,
    Route,
    Setting,
)
from jarvis.buildbook.gen import (
    code,
    facts_code,
    facts_guide,
    facts_routes,
    facts_values,
    libs,
    licences,
    loc,
    plans,
)
from jarvis.buildbook.gen import modules as modules_mod
from jarvis.buildbook.gen import services as services_mod
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.gen.scrub import Scrubber
from jarvis.buildbook.model import MAX_LIMITATIONS
from jarvis.buildbook.sections import Limitation

CONFIG_FILE = "src/jarvis/config.py"


def _services(
    repo: Repo, table: Mapping[str, Any] | None, cards: tuple[facts_guide.Card, ...]
) -> tuple[tuple[str, ...], bool]:
    """(the services, whether they are the coverage checker's inventory, M7). A checkout without
    its table (a fixture): the services the cards name, as the guide writes them."""
    if table is not None:
        return services_mod.inventory(repo.root, table).names, True
    names = code.inventory_names(repo)
    if names is not None:
        return names, True
    field = "Outside services"
    named = {s for c in cards for s in facts_guide.service_items(c.fields.get(field, ""))}
    return tuple(sorted(named)), False


def _guide(
    repo: Repo,
    scrub: Scrubber,
    table: tuple[modules_mod.Module, ...],
    cards: tuple[facts_guide.Card, ...],
    known: tuple[str, ...],
) -> tuple[tuple[ModuleFact, ...], tuple[CardFact, ...]]:
    if not repo.has(facts_guide.GUIDE):
        return (), ()
    modules_mod.check((c.id for c in cards), table)
    mods = tuple(ModuleFact(id=m.id, title=m.title, cards=m.cards) for m in table)
    return mods, facts_guide.card_facts(repo, scrub, cards, table, known)


def limitations(repo: Repo, read: tuple[plans.Plan, ...]) -> tuple[Limitation, ...]:
    """Every limitation (G4) in the book's order: the licence notes, then the plans' (the book
    keeps the first `MAX_LIMITATIONS`)."""
    if repo.has(licences.TABLE):
        lookup = licences.table_lookup(repo)
    else:
        lookup = lambda _name: libs.NOT_STATED  # noqa: E731 - no table: nothing to flag
    label = plans.release_label(repo)
    notes = libs.licence_limits(libs.libraries(repo, lookup), label)
    return (*notes, *plans.limitations(read, cap=None))


def _values(constants: dict[str, FactValue], settings: tuple[Setting, ...]) -> dict[str, FactValue]:
    out = dict(constants)
    for s in settings:
        if s.default is not None:
            out[f"settings.{s.name}"] = FactValue(value=s.default, source=f"{CONFIG_FILE}:{s.name}")
    return out


def _own(pack: dict[str, Any]) -> dict[str, FactValue]:
    """A's own counts, each from what the pack itself holds."""
    src = "src/jarvis/buildbook/gen/facts.py"
    limits = len(pack["limitations"])
    counts = {
        "routes.count": len(pack["routes"]),
        "settings.count": len(pack["settings"]),
        "collections.count": len(pack["collections"]),
        "screens.count": len(pack["screens"]),
        "constants.count": len(pack["constants"]),
        "limitations.count": limits,
        "limitations.shown": min(limits, MAX_LIMITATIONS),
    }
    return {k: FactValue(value=v, source=src) for k, v in counts.items()}


def build(
    repo: Repo,
    scrub: Scrubber,
    *,
    modules: tuple[modules_mod.Module, ...] = modules_mod.MODULES,
    services_table: Mapping[str, Any] | None = None,
) -> FactPack:
    trees = facts_code.parse_src(repo)
    constants = facts_code.constants(trees, scrub)
    settings = facts_code.settings(repo, scrub)
    routes = facts_routes.routes(trees, scrub)
    guide = facts_guide.guide_cards(repo)
    services, inventoried = _services(repo, services_table, guide)
    mods, cards = _guide(repo, scrub, modules, guide, services if inventoried else ())
    rows = loc.count(repo)
    rows = tuple(r.model_copy(update={"module": scrub.clean(r.module)}) for r in rows)
    read = plans.read_plans(repo, scrub)
    pack: dict[str, Any] = {
        "routes": routes,
        "settings": settings,
        "collections": facts_code.collections(repo),
        "modules": mods,
        "cards": cards,
        "screens": facts_guide.screens(repo, routes, scrub),
        "services": services,
        "loc": rows,
        "limitations": limitations(repo, read),
        "constants": constants,
    }
    values = {**_values(constants, settings), **_own(pack)}
    values.update(_tour(repo, scrub, pack, settings, modules))
    values.update(facts_values.hosting_values(repo))
    return FactPack(
        values=dict(sorted(values.items())),
        index=_index(repo, scrub, trees, pack),
        **{k: v for k, v in pack.items() if k != "constants"},
    )


def _tour(
    repo: Repo,
    scrub: Scrubber,
    pack: Mapping[str, Any],
    settings: tuple[Setting, ...],
    table: tuple[modules_mod.Module, ...],
) -> dict[str, FactValue]:
    text = repo.text(facts_guide.GUIDE) or ""
    ctx = facts_values.Context(
        scrub=scrub,
        constants=pack["constants"],
        defaults={s.name: s.default for s in settings if s.default is not None},
        cards=len(pack["cards"]),
        modules=len(pack["modules"]),
        others=len(modules_mod.others(table)) if pack["modules"] else 0,
        services=len(pack["services"]),
        python_code=loc.in_thousands(loc.python_code(pack["loc"])),
        roadmap=facts_guide.roadmap(text),
        guide=facts_guide.GUIDE if repo.has(facts_guide.GUIDE) else "",
    )
    return all_or_none(facts_values.tour_values(repo, ctx))


def all_or_none(tour: dict[str, FactValue]) -> dict[str, FactValue]:
    """The tour's 30 keys, every one or none: a checkout without every source (a fixture) gives
    none, so it builds no tour (part D: some but not all is a GenError); a key whose source this
    repository lost drops the tour, never the book, and test_r63_a_facts_real fails in CI."""
    return tour if set(FACT_TOUR_KEYS) <= set(tour) else {}


def _index(
    repo: Repo, scrub: Scrubber, trees: Mapping[str, Any], pack: Mapping[str, Any]
) -> FactIndex:
    routes: tuple[Route, ...] = pack["routes"]
    return FactIndex(
        paths=tuple(sorted({scrub.clean(f) for f in repo.files})),
        symbols=facts_code.symbols(trees, scrub),
        constants=tuple(sorted(pack["constants"])),
        settings=tuple(sorted(s.name for s in pack["settings"])),
        collections=tuple(pack["collections"]),
        routes=tuple(sorted({f"{r.method} {r.path}" for r in routes})),
    )


__all__ = ["all_or_none", "build", "limitations"]

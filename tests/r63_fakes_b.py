# tests/r63_fakes_b.py -- part B's own fixture data (R6.3, docs/plans/r6-3-book-content.md D4, D6),
# kept for the checks and the packs (R6.3.1 D8: the writer's service fakes went with the writer).
# Imported bare (`from r63_fakes_b import ...`). Everything here is fixed and in memory.
#
#   TRIAL_FACTS                    the fixture's facts with the five trial pages added (D6)
#   files(changed, big=)           the fixture's files; `big=True` adds a 150 KB docstring to a
#                                  cited file, so every pack fills its 96,000-byte cap
from __future__ import annotations

from r63_fakes import FIXTURE_FACTS, FIXTURE_FILES

from jarvis.buildbook.facts_model import IndexedPage

_ROUTER, _STORE = "src/jarvis/demo/router.py", "src/jarvis/demo/store.py"


def _trial(pid: str, kind: str, part: str, title: str) -> IndexedPage:
    return IndexedPage(id=pid, kind=kind, title=title, part=part, refs=(_ROUTER,), sources=("C01",))  # type: ignore[arg-type]


TRIAL_EXTRA = (
    _trial("pg_card_c16", "card", "parts", "Demo router, again"),
    _trial("pg_module_wardrobe", "module", "modules", "Wardrobe"),
    _trial("pg_screen_vitals", "screen", "screens", "Vitals"),
    _trial("pg_service_telegram", "service", "services", "Telegram"),
)
TRIAL_FACTS = FIXTURE_FACTS.model_copy(update={"pages": (*FIXTURE_FACTS.pages, *TRIAL_EXTRA)})
BIG_DOC = "\n".join(f"Line {n:05d} of a long, made-up module docstring." for n in range(3_500))


def files(changed: dict[str, str] | None = None, *, big: bool = False) -> dict[str, str]:
    out = dict(FIXTURE_FILES)
    if big:
        out[_ROUTER] = f'"""{BIG_DOC}"""\n\n' + out[_ROUTER].split("\n", 1)[1]
    out.update(changed or {})
    return out


__all__ = ["BIG_DOC", "TRIAL_EXTRA", "TRIAL_FACTS", "files"]

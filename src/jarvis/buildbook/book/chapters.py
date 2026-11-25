# src/jarvis/buildbook/book/chapters.py
"""R6.4 D5 (docs/plans/r6-4-book-look.md): the full book's narrated chapters, from a pages index.

A chapter is what the chapter player tells in one go:

- a **story** chapter: one `pg_chapter_<id>` page ("What JARVIS is"), id `story_<id>`;
- a **module** chapter: the `pg_module_<id>` page, then its parts' cards in the module map's order
  (the index's own order, `gen/modules.MODULES`: a card page's `chapter` is its module), then the
  screens and outside services `HOMES` gives that module, in the index's order. Id `module_<id>`.

The title is the lead page's title. 8 + 18 = 26 chapters on this tree. Every page is in at most one
chapter; a page `HOMES` doesn't place stays readable in the reader, just not narrated. Pure: the
same pages give the same chapters, from an `IndexedPage` index (the generator) or a compiled
`Page` list (a release sealed before narration, `writer/chapters.py`). Standard library only.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

CHAPTER_ID = r"^(?:story|module)_[a-z0-9_]{1,40}$"
ChapterKind = Literal["story", "module"]
LEADS: dict[str, ChapterKind] = {"pg_chapter_": "story", "pg_module_": "module"}

# Each screen and outside service, by page id, and the module whose chapter tells it (one place;
# a page in no row here is read, not narrated). Chosen by what the page is about: the cards that
# cite or name it, and the panel it is drawn in.
HOMES: dict[str, str] = {
    # screens (the console's panels and the show)
    "pg_screen_chat": "brain",
    "pg_screen_brief": "helpers",
    "pg_screen_approvals": "approvals",
    "pg_screen_activity": "activity",
    "pg_screen_history": "brain",
    "pg_screen_memory": "memory",
    "pg_screen_vault": "vault",
    "pg_screen_things": "memory",
    "pg_screen_notes": "memory",
    "pg_screen_privacy": "privacy",
    "pg_screen_home": "home",
    "pg_screen_faces": "people",
    "pg_screen_voice": "voice",
    "pg_screen_integrations": "integrations",
    "pg_screen_media": "integrations",
    "pg_screen_vitals": "vitals",
    "pg_screen_connectors": "integrations",
    "pg_screen_people": "people",
    "pg_screen_book": "book",
    "pg_screen_construct": "console",
    "pg_screen_helpers": "helpers",
    "pg_screen_camera": "home",
    "pg_screen_show": "book",
    # outside services
    "pg_service_anthropic": "brain",
    "pg_service_cloud_run": "delivery",
    "pg_service_cloud_scheduler": "delivery",
    "pg_service_firestore": "console",
    "pg_service_frankfurter": "vitals",
    "pg_service_frigate": "home",
    "pg_service_gemini": "brain",
    "pg_service_github": "integrations",
    "pg_service_gmail": "integrations",
    "pg_service_google_agent_platform": "wardrobe",
    "pg_service_google_calendar": "integrations",
    "pg_service_google_cloud_speech_to_text": "voice",
    "pg_service_google_cloud_text_to_speech": "voice",
    "pg_service_google_contacts": "integrations",
    "pg_service_google_drive": "integrations",
    "pg_service_google_maps_platform": "integrations",
    "pg_service_google_photos_picker": "integrations",
    "pg_service_google_tasks": "integrations",
    "pg_service_google_sign_in": "console",
    "pg_service_home_assistant": "home",
    "pg_service_mosquitto": "home",
    "pg_service_ndma_sachet": "helpers",
    "pg_service_ollama": "brain",
    "pg_service_open_meteo": "helpers",
    "pg_service_openai_compatible": "brain",
    "pg_service_redis": "console",
    "pg_service_tailscale": "home",
    "pg_service_tavily": "integrations",
    "pg_service_telegram": "integrations",
    "pg_service_web_push": "alerts",
    "pg_service_youtube_data_api": "integrations",
}


class PageLike(Protocol):
    """What a chapter needs of a page: `IndexedPage` and `writer/model.Page` both have it."""

    @property
    def id(self) -> str: ...
    @property
    def kind(self) -> str: ...
    @property
    def title(self) -> str: ...
    @property
    def chapter(self) -> str: ...


@dataclass(frozen=True)
class ChapterPlan:
    id: str
    title: str
    kind: ChapterKind
    pages: tuple[str, ...]


def chapter_id(lead_page: str) -> str | None:
    """`pg_chapter_what` -> `story_what`, `pg_module_vault` -> `module_vault`, else None."""
    for prefix, kind in LEADS.items():
        if lead_page.startswith(prefix):
            return f"{kind}_{lead_page.removeprefix(prefix)}"
    return None


def chapters(
    pages: Sequence[PageLike], homes: Mapping[str, str] = HOMES
) -> tuple[ChapterPlan, ...]:
    """Every chapter of `pages` (an index, in its order): the story chapters, then the modules."""
    story = [ChapterPlan(cid, p.title, "story", (p.id,)) for p in pages
             if p.kind == "chapter" and (cid := chapter_id(p.id))]  # fmt: skip
    out: list[ChapterPlan] = []
    for lead in (p for p in pages if p.kind == "module"):
        cid, module = chapter_id(lead.id), lead.id.removeprefix("pg_module_")
        if cid is None:
            continue
        cards = [p.id for p in pages if p.kind == "card" and p.chapter == module]
        placed = [
            p.id for p in pages if p.kind in ("screen", "service") and homes.get(p.id) == module
        ]
        out.append(ChapterPlan(cid, lead.title, "module", (lead.id, *cards, *placed)))
    return (*story, *out)


def find(found: Iterable[ChapterPlan], cid: str) -> ChapterPlan | None:
    return next((c for c in found if c.id == cid), None)


def pages_in(found: Iterable[ChapterPlan]) -> frozenset[str]:
    return frozenset(p for c in found for p in c.pages)


__all__ = [
    "CHAPTER_ID",
    "HOMES",
    "LEADS",
    "ChapterKind",
    "ChapterPlan",
    "PageLike",
    "chapter_id",
    "chapters",
    "find",
    "pages_in",
]

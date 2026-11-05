# src/jarvis/tools/r1_tools.py
"""R1 builder D's tools in one place: package tracking, mail read aloud, groceries, family
calendars. Registration is the integrator's (I1):

    # src/jarvis/tools/setup.py, inside `if google is not None:` after the tasks_tools loop
    from jarvis.tools.r1_tools import r1_tools
    for t in r1_tools(google, docs=docs, s=s, marks=marks):
        reg.register(t)

(`build_gateway` needs a `docs: Docs | None` parameter for that; with `docs=None` pass nothing and
skip the call -- the groceries and family tools keep their state on the Docs port.)
`build_family_service` / `build_grocery_service` give the API and the brief the same services.
"""

from __future__ import annotations

from jarvis.config import Settings
from jarvis.family.service import FamilyService
from jarvis.family.store import FamilyStore
from jarvis.family.tools import family_tools
from jarvis.groceries.service import GroceryClient, GroceryService
from jarvis.groceries.store import GroceryStore
from jarvis.groceries.tools import grocery_tools
from jarvis.integrations.google import GoogleConnector
from jarvis.packages.tools import packages_tools
from jarvis.storage.docs import Docs
from jarvis.tools.base import Tool
from jarvis.tools.gmail_digest import digest_tools
from jarvis.tools.task_marks import OutsideTasks


def build_family_service(google: GoogleConnector, docs: Docs, s: Settings) -> FamilyService:
    return FamilyService(
        google, FamilyStore(docs, prefix=s.firestore_prefix), default_tz=s.user_timezone
    )


def build_grocery_service(
    google: GoogleConnector, docs: Docs, s: Settings, marks: OutsideTasks | None = None
) -> GroceryService:
    return GroceryService(
        GroceryClient(google),
        GroceryStore(docs, prefix=s.firestore_prefix),
        marks if marks is not None else OutsideTasks(docs, prefix=s.firestore_prefix),
    )


def r1_tools(
    google: GoogleConnector,
    *,
    docs: Docs,
    s: Settings,
    marks: OutsideTasks | None = None,
) -> list[Tool]:
    """gmail_track_packages, gmail_unread_digest, grocery_list / _add / _remove and the three
    family_* tools. `marks`: the same OutsideTasks the to-do tools use (so a grocery line written
    from outside content is marked in the one set the provenance rule reads)."""
    return [
        *packages_tools(google),
        *digest_tools(google),
        *grocery_tools(build_grocery_service(google, docs, s, marks)),
        *family_tools(build_family_service(google, docs, s)),
    ]


__all__ = ["build_family_service", "build_grocery_service", "r1_tools"]

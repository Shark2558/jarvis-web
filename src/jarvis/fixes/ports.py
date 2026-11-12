# src/jarvis/fixes/ports.py
"""The plug-in contract of R11.1 (docs/plans/r11-1-observations.md "The I0 seams").

Four parts are built in parallel. Each owns a package with a `part.py` whose
`build(ctx: FixContext) -> FixPart` gets what it may use and hands back what the app wires for it;
no part edits a wiring file.

| Part     | Observations            | Package                  | Routes under        |
|----------|-------------------------|--------------------------|---------------------|
| `plan`   | O1, O2 (+ series), O12  | `jarvis.series`          | `/v1/series`        |
| `files`  | O3, O4                  | `jarvis.understand`      | `/v1/input`         |
| `photos` | O5, O6, O7 (+ folder)   | `jarvis.facegroups`      | `/v1/facegroups`    |
| `look`   | O8, O9 (the alternative), O10, O11 | `jarvis.picture` | `/v1/picture`      |

- `FixPart`: its tools (registered through the gateway; names inside its `TOOL_FAMILIES`), its
  jobs for the helpers' 5-minute clock (`clock_jobs`, run for the configured owners) and for the
  morning tick (`daily_jobs`), its privacy rows, the services its own routes read from
  `app.state.r111_parts[<part>].services`, and one plain status word (`ready`).
- `FixContext`: the settings, the document store and the audit chain, plus `state(name)`: a LATE
  read of `app.state.<name>` (None when it is not there), because the gateway, the Brain, the
  documents, faces and photos services and the helpers' sender are built around this wiring.
  A part reads them when it is called, never at build time, and treats None as "switched off".
  `notifier()` is the app's one notifier (kinds `series_checkin` and `faces_to_name` are R11.1's).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import TYPE_CHECKING, Any, Literal, get_args

if TYPE_CHECKING:
    from jarvis.config import Settings
    from jarvis.notify.ports import Notifier
    from jarvis.privacy.ports import PrivacySource
    from jarvis.storage.docs import Docs
    from jarvis.ticks import TickJob
    from jarvis.tools.audit import AuditTrail
    from jarvis.tools.base import Tool

PartName = Literal["plan", "files", "photos", "look"]
PARTS: tuple[PartName, ...] = get_args(PartName)
NOT_BUILT = "not built yet"

# The tool names a part may register (fnmatch patterns). `files` adds no tool: reading a file
# stays `doc_*` (jarvis.documents, which Part B owns) and "understood as" is a route.
TOOL_FAMILIES: Mapping[PartName, tuple[str, ...]] = {
    "plan": ("calendar_create_events", "calendar_undo_events", "series_*", "gmail_inbox_summary"),
    "files": (),
    "photos": ("faces_groups", "faces_group_*", "photos_import_*"),
    "look": ("picture_*",),
}
ROUTE_PREFIX: Mapping[PartName, str] = {
    "plan": "/v1/series",
    "files": "/v1/input",
    "photos": "/v1/facegroups",
    "look": "/v1/picture",
}
# Firestore collections (all `{prefix}<name>/...`); the guide's card C61 lists every one.
COLLECTIONS: Mapping[PartName, tuple[str, ...]] = {
    "plan": ("series", "series_told"),
    "files": (),
    "photos": ("photo_imports", "face_groups"),
    "look": (),
}


def tool_allowed(part: PartName, tool: str) -> bool:
    return any(fnmatchcase(tool, pattern) for pattern in TOOL_FAMILIES[part])


@dataclass(frozen=True)
class FixPart:
    name: PartName
    tools: tuple[Tool, ...] = ()
    clock_jobs: tuple[TickJob, ...] = ()
    daily_jobs: tuple[TickJob, ...] = ()
    privacy: tuple[PrivacySource, ...] = ()
    services: Mapping[str, Any] = field(default_factory=dict)
    ready: str = NOT_BUILT


@dataclass(frozen=True)
class FixContext:
    s: Settings
    docs: Docs | None
    audit: AuditTrail | None
    state: Callable[[str], Any]
    # the one way to tell the owner anything (the alert policy decides ring / hold / drop); read
    # late like `state`. None in a test that sends nothing.
    notifier: Callable[[], Notifier] | None = None

    @property
    def prefix(self) -> str:
        return self.s.firestore_prefix


__all__ = [
    "COLLECTIONS",
    "NOT_BUILT",
    "PARTS",
    "ROUTE_PREFIX",
    "TOOL_FAMILIES",
    "FixContext",
    "FixPart",
    "PartName",
    "tool_allowed",
]

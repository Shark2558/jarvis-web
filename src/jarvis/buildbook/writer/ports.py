# src/jarvis/buildbook/writer/ports.py
"""R6.3 I0 seam 6 (docs/plans/r6-3-book-content.md D5, D11, D13): how part B's writer plugs into
the app. `api/r6_wiring.py` builds ONE `WriterContext` with the server's keyring (no keyring: no
writer) and calls `writer/part.py`'s `build(ctx) -> WriterPart`; a part that raises, or whose job
is not `book_write`, is left out (`book_writer_off = "setup_failed"`) and the rest of the Book
runs on. What the wiring then does with the part:

- `service` goes on `app.state.book_writer` (B's routes read it per request);
- `job` (`book_write`) joins R6's morning-tick jobs after `book_sweep`, and the ONE 5-minute clock
  through `tick_wiring.add_clock_job`, LAST (M3: Home on or off, only the time the others leave);
  it is never put on the home watchdog by R6's loop (that would run it twice with Home on);
- `privacy` rows join R6's Privacy rows (before Faces, which stays last).

The context names what the writer may use and nothing else (D4: no memory, vault, mail, contacts,
tools or brain core; the brains only through `jarvis.llm.write`). R6's index (`vault`) is read,
never written (M4).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from jarvis.buildbook.ports import BookSource, BookVault
from jarvis.keyring import Keyring
from jarvis.llm.brains import BrainRegistry
from jarvis.notify.ports import Notifier
from jarvis.privacy.ports import PrivacySource
from jarvis.storage.docs import Docs
from jarvis.ticks import TickJob


class Billing(Protocol):
    """`billing.service.Billing`, seen through what the writer uses (D8)."""

    async def record(self, uid: str, brain_id: str, cost_usd: float) -> float: ...

    async def usage(self, uid: str) -> Any: ...


@dataclass(frozen=True)
class WriterContext:
    docs: Docs
    keyring: Keyring
    brains: BrainRegistry
    billing: Billing
    source: BookSource  # R6's ReleaseSource: book.json, source.zip and facts() (in the image)
    vault: BookVault  # R6's sealed index: read only (what is sealed, its size), never written
    notifier: Notifier | None
    audit: Any  # the gateway's audit chain (`append(agent=, tool=, risk=, outcome=, args=)`)
    prefix: str
    limit_mb: int  # book_max_total_mb
    uid: str  # identity.primary_user_id (L11): the writer serves the primary owner only
    owner_emails: tuple[str, ...]
    honorific: str
    timezone: str
    clock: Callable[[], datetime]  # book_now: tests and evals move it


@dataclass(frozen=True)
class WriterPart:
    service: Any  # B's writer service: app.state.book_writer
    job: TickJob  # `book_write`
    privacy: tuple[PrivacySource, ...] = ()
    ready: str = "ok"


__all__ = ["Billing", "WriterContext", "WriterPart"]

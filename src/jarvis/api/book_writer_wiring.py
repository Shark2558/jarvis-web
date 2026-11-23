# src/jarvis/api/book_writer_wiring.py
"""R6.3 I0 seam 6 (docs/plans/r6-3-book-content.md D5, D13): part B's writer on the app, kept out of
`api/r6_wiring.py` (its 300-line guard). `wire_writer` builds ONE `WriterContext` (the server's
keyring, the brains, billing, R6's source and sealed index read-only, the primary owner) and calls
B's join `buildbook/writer/part.build(ctx)`. A part that raises, or whose job isn't `book_write`, is
left out (`app.state.book_writer_off = "setup_failed"`) and the rest of the Book runs on.
"""

from __future__ import annotations

from fastapi import FastAPI

from jarvis.api.book_http import book_now
from jarvis.api.identity import primary_user_id
from jarvis.buildbook.writer import part as writer_part
from jarvis.buildbook.writer.model import JOB_NAME
from jarvis.buildbook.writer.ports import FactSource, WriterContext
from jarvis.config import Settings
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier
from jarvis.storage.docs import Docs
from jarvis.tools.audit import AuditTrail

log = get_logger(__name__)


def writer_context(
    app: FastAPI,
    s: Settings,
    docs: Docs,
    audit: AuditTrail,
    *,
    keyring: Keyring,
    source: FactSource,
    notifier: Notifier | None,
) -> WriterContext:
    st = app.state
    return WriterContext(
        docs=docs,
        keyring=keyring,
        brains=st.brains,
        billing=st.billing,
        source=source,
        vault=st.book_vault,
        notifier=notifier,
        audit=audit,
        prefix=s.firestore_prefix,
        limit_mb=s.book_max_total_mb,
        uid=primary_user_id(s),
        owner_emails=tuple(s.owner_emails),
        honorific=s.user_honorific,
        timezone=s.user_timezone,
        clock=lambda: book_now(app),
    )


def wire_writer(
    app: FastAPI,
    s: Settings,
    docs: Docs,
    audit: AuditTrail,
    *,
    keyring: Keyring,
    source: FactSource,
    notifier: Notifier | None,
) -> None:
    st = app.state
    ctx = writer_context(app, s, docs, audit, keyring=keyring, source=source, notifier=notifier)
    try:
        built = writer_part.build(ctx)
        if built.job.name != JOB_NAME:
            raise RuntimeError("the writer's job must be book_write")
    except Exception as exc:  # noqa: BLE001 - optional part: the rest of the Book runs on
        log.error("The book writer is OFF: its setup failed", extra={"error": type(exc).__name__})
        st.book_writer, st.book_writer_part, st.book_writer_off = None, None, "setup_failed"
        return
    st.book_writer_part, st.book_writer, st.book_writer_off = built, built.service, None


__all__ = ["wire_writer", "writer_context"]

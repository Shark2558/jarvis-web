# src/jarvis/buildbook/writer/part.py
"""R6.3 seam 6: part B's ONE join, `build(ctx) -> WriterPart` (`writer/ports.py`). PART B replaces
this stub with its service (the routes' `app.state.book_writer`), its `book_write` job and its
Privacy row. I0's stub: a service that says it is not built yet, the do-nothing job, a zero row.
"""

from __future__ import annotations

from jarvis.buildbook.writer.job import BookWriteJob
from jarvis.buildbook.writer.ports import WriterContext, WriterPart
from jarvis.buildbook.writer.privacy import WriterSource

NOT_BUILT = "not built yet"


class NotBuilt:
    """I0's stand-in service: the routes answer 503 `not_built_yet` until B's is here."""

    ready = NOT_BUILT


def build(ctx: WriterContext) -> WriterPart:
    return WriterPart(
        service=NotBuilt(), job=BookWriteJob(ctx), privacy=(WriterSource(),), ready=NOT_BUILT
    )


__all__ = ["NOT_BUILT", "NotBuilt", "build"]

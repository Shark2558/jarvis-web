# src/jarvis/buildbook/writer/serve.py
"""R6.3.1 D7 (docs/plans/r6-3-1-book-at-build.md): the full book of a KEPT release, read from the
pages and flows files sealed with it (R6's vault: the sealer seals them with the release's book
and code), for `GET /v1/book/pages` and `GET /v1/book/pages/{id}` (`api/book_pages.py`). No
per-owner pages store: every page was compiled at build time, so serving one calls no AI.

- No release asked: the server's own (`source.current()`); a release the vault doesn't keep is
  `no_page`, one sealed before v6.3.2 (no pages file) is `no_pages`, and a vault that can't be
  read, or a file that fails its check, is `unavailable` (logged by type only).
- The two files are opened once per release and kept in a small cache keyed by their SHA-256,
  so a Privacy delete (the release leaves R6's index, read on every call) is never outlived.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from jarvis.buildbook.ports import BookError, BookSource, BookVault
from jarvis.buildbook.writer import pages
from jarvis.buildbook.writer.http import PagesView
from jarvis.buildbook.writer.model import PagesFile
from jarvis.buildbook.writer.texts import PagesRefused
from jarvis.logging import get_logger

log = get_logger(__name__)
CACHED = 4  # releases' files kept open (three kept releases and one being read)
Flows = dict[str, dict[str, Any]]


class BookPages:
    """`app.state.book_pages`: one owner's kept releases' full books (the primary owner's)."""

    def __init__(self, source: BookSource, vault: BookVault) -> None:
        self._source, self._vault = source, vault
        self._open: OrderedDict[tuple[str, ...], tuple[PagesFile, Flows]] = OrderedDict()

    async def _kept(self, uid: str, rid: str | None) -> Any:
        current = self._source.current()
        rid = rid or (current.id if current is not None else None)
        try:
            kept = await self._vault.releases(uid)
        except BookError as exc:
            log.error("full book index unreadable", extra={"error": type(exc).__name__})
            raise PagesRefused("unavailable") from None
        found = next((r for r in kept if r.id == rid), None)
        if found is None:
            raise PagesRefused("no_page")
        if not found.has("pages"):
            raise PagesRefused("no_pages")
        return found

    async def _read(self, uid: str, rid: str, has_flows: bool) -> tuple[PagesFile, Flows]:
        try:
            f = pages.decode_file(await self._vault.read(uid, rid, "pages"))
            raw = await self._vault.read(uid, rid, "flows") if has_flows else b"{}"
            flows = pages.decode_flows(raw)
        except (BookError, LookupError, ValueError) as exc:
            log.error("full book unreadable", extra={"error": type(exc).__name__})
            raise PagesRefused("unavailable") from None
        if f.release != rid:
            log.error("full book names another release")
            raise PagesRefused("unavailable")
        return f, flows

    async def files(self, uid: str, rid: str | None) -> tuple[PagesFile, Flows]:
        sealed = await self._kept(uid, rid)
        has_flows = sealed.has("flows")
        key = (uid, sealed.id, sealed.file("pages").sha256,
               sealed.file("flows").sha256 if has_flows else "")  # fmt: skip
        if key not in self._open:
            self._open[key] = await self._read(uid, sealed.id, has_flows)
            while len(self._open) > CACHED:
                self._open.popitem(last=False)
        self._open.move_to_end(key)
        return self._open[key]

    async def index(self, uid: str, rid: str | None) -> PagesView:
        f, _ = await self.files(uid, rid)
        return pages.view(f)

    async def page(self, uid: str, page_id: str, rid: str | None) -> dict[str, Any]:
        f, flows = await self.files(uid, rid)
        found = pages.page_for(page_id, f)
        if found is None:
            raise PagesRefused("no_page")
        return pages.served(found, flows)


__all__ = ["CACHED", "BookPages"]

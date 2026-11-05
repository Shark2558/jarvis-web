# src/jarvis/drive/service.py
"""Google Drive, chosen folders only — end to end (slice 12 D1; Layer 6 → 5).

Integrations (the owner, on screen):
  view(uid, owner_email)   JARVIS's address to share with; the folders offered to the owner (their
                           own: first those the owner OWNS — strangers can't make those — then a
                           bounded list matched on the sharer), each with its Use switch and
                           whether JARVIS can read it now; how many folders other accounts shared
                           (a count only, with `others_more` when the list was cut short — never
                           their names or addresses).
  set_use(uid, email, id, on)  Use on: Drive is asked for THAT folder now (not a listing): it
                           must be a folder, not trashed, the same id, and the owner's own
                           (`jarvis.drive.live.owned_by` against the owner's verified address,
                           which is stored with it). Use off: always allowed, at once.

The tools (the model, inside a turn; every call re-checks the switched-on folders — ≤ 60 s cache —
and a folder that fails is OFF for every tool, though kept; then every id is checked against them):
  folders(uid)             the switched-on folders JARVIS can read now
  list_folder(uid, f, page) one folder's direct contents, ≤ 25 a page (only items whose parents
                           include it: a page token may not be bound to its query)
  search(uid, query)       Drive fullText: first files the owner owns, then everyone's; only hits
                           inside the folders (≤ 10). A hit whose check fails is not shown and
                           the search goes on; when some couldn't be checked, the note says so.
  read(uid, file, part)    one ~4,000-character part, fenced: Google Docs / Slides → text/plain,
                           Sheets → text/csv (the first sheet only; the result says so), PDF /
                           DOCX / TXT / MD / CSV ≤ 10 MB → the app's ONE sandboxed extractor
                           (`DocumentService.extract`, injected: a chat upload and a Drive file
                           never extract at once). A shortcut is followed to its target, which is
                           checked again. Extracted text is kept in memory for 10 minutes (≤ 8
                           files, keyed by id + modifiedTime); nothing from Drive is stored.

Everything Drive returns — names included — is other people's words: fenced with the per-call
nonce (`jarvis.tools.external`), and the tools are untrusted (`trusted_output` False) so the round
is tainted. Errors are plain English (`DriveError` family); Google's text never appears.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from jarvis.config import Settings
from jarvis.documents.chunking import pages_label, split
from jarvis.documents.extract import Extracted
from jarvis.documents.limits import DocumentRejected
from jarvis.drive.client import DriveClient, check_id
from jarvis.drive.guard import NOT_IN_ROOTS, ParentsGuard, WalkBudget
from jarvis.drive.kinds import (
    EMPTY,
    EXPORTS,
    SHEET_NOTE,
    TOO_BIG,
    UNSUPPORTED,
    blob_kind,
    kind_word,
    refusal_words,
)
from jarvis.drive.live import RootChecks
from jarvis.drive.ports import (
    DRIVE_ID,
    MAX_FILE_BYTES,
    MAX_ROOTS,
    SHEET_MIME,
    DriveError,
    DriveFile,
    DriveNotFound,
    DriveUnavailable,
    NotInRoots,
)
from jarvis.drive.roots import Root, RootsStore, owner_address
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs
from jarvis.tools.external import wrap_external

log = get_logger(__name__)

Extractor = Callable[[bytes, str], Awaitable[Extracted]]
InboxSource = Callable[[str], Awaitable[str | None]]  # uid -> the DigiLocker inbox folder id

LIST_PAGE = 25
SEARCH_LIMIT = 10
SEARCH_PAGES = 2  # pages (of 25) looked at per search query: the owner's files, then everyone's
SEARCH_LOOKUPS = 60  # uncached folder look-ups one search may make (the rest: not shown)
OFFER_PAGES = 4  # pages (of 25) of shared folders looked at per list: ≤ 100 each
PART_CHARS = 4_000  # chunk cost (JSON characters) of one drive_read part
PART_TEXT_LIMIT = 6_000  # the fenced text after fence-like text is replaced (fits the gateway)
NAME_SHOWN = 120
TEXT_CACHE_S = 600.0
TEXT_CACHE_FILES = 8

FOLDER_NOT_FILE = "That is a folder: use drive_list to see what is in it."
BROKEN_SHORTCUT = "That shortcut points to something JARVIS can't open."
NOT_SET_UP = (
    "No Drive folders are switched on yet. The owner shares a folder with JARVIS and switches "
    "on Use in Integrations → Google Drive."
)
SOME_OFF = (
    "{n} switched-on Drive folder(s) can't be read right now (no longer shared with JARVIS from "
    "the owner's account, or in the trash): the owner can check Integrations → Google Drive."
)
NO_INBOX = "JARVIS couldn't check the DigiLocker folder just now, so nothing was read from Drive."
IS_INBOX = (
    "That folder is the DigiLocker import folder, which JARVIS's Drive tools never read. "
    "Switch the import off first, or pick another folder."
)
NO_READER = "JARVIS can't read Drive files on this server right now."
MATCHED = "Read one with drive_read and its id."
NO_MATCH = "Nothing in the chosen folders matched. Try other words, or drive_list a folder."
UNCHECKED = (
    "Some results couldn't be checked against the chosen folders (Drive had too many to look "
    "through, or some couldn't be read), so they are not shown."
)
UNCHECKED_NONE = (
    "No result could be confirmed inside the chosen folders. " + UNCHECKED + " Try more "
    "specific words, or drive_list a folder."
)
_REFUSED = {
    "gone": (
        "not_offered",
        "That folder isn't shared with JARVIS. Share it with JARVIS's address first.",
        409,
    ),
    "trashed": ("not_offered", "That folder is in the trash in Google Drive.", 409),
    "not_folder": ("not_a_folder", "That isn't a folder. Share a folder, then switch it on.", 422),
    "not_owner": (
        "not_offered",
        "Not offered: that folder was shared with JARVIS by another account, not yours.",
        403,
    ),
}


class DriveRejected(ValueError):
    """An Integrations change that is not allowed (plain words for the owner)."""

    def __init__(self, code: str, detail: str, *, status: int = 422) -> None:
        super().__init__(detail)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class _Text:
    chunks: tuple[str, ...]
    pages: tuple[tuple[int | None, int | None], ...]
    truncated: bool


@dataclass
class _Scan:
    """One search's running state across its queries."""

    budget: WalkBudget
    hits: list[dict[str, Any]] = field(default_factory=list)
    seen: set[str] = field(default_factory=set)
    unchecked: bool = False
    deny: tuple[str, ...] = ()


def _name(f: DriveFile) -> str:
    return wrap_external(f.name, source="Google Drive name", limit=NAME_SHOWN)


def _item(f: DriveFile) -> dict[str, Any]:
    out: dict[str, Any] = {"id": f.id, "name": _name(f), "kind": kind_word(f.mime)}
    if f.modified:
        out["modified"] = f.modified[:10]
    if f.size is not None:
        out["size_kb"] = max(1, f.size // 1024)
    if f.is_shortcut and f.target_mime:
        out["points_to"] = kind_word(f.target_mime)
    return out


def _address(value: str | None) -> str | None:
    try:
        return owner_address(value)
    except ValueError:
        return None


class DriveService:
    def __init__(
        self,
        client: DriveClient,
        roots: RootsStore,
        *,
        extract: Extractor | None = None,
        guard: ParentsGuard | None = None,
        checks: RootChecks | None = None,
        inbox: InboxSource | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client
        self.roots = roots
        self.extract = extract  # the app's DocumentService.extract (one slot for the whole app)
        self.guard = guard or ParentsGuard(client, clock=clock)
        self.checks = checks or RootChecks(client, clock=clock)
        self.inbox = inbox  # R2 D9: the vault inbox id; no Drive tool may read it
        self._clock = clock
        self._texts: OrderedDict[tuple[str, str], tuple[float, _Text]] = OrderedDict()

    async def aclose(self) -> None:
        await self.client.aclose()
        await self.client.tokens.aclose()

    async def _live(self, uid: str) -> tuple[list[Root], int]:
        """The switched-on roots JARVIS may read now, and how many are switched on but OFF."""
        chosen = await self.roots.load(uid)
        live = await self.checks.live(chosen)
        return live, len(chosen) - len(live)

    async def _deny(self, uid: str) -> tuple[str, ...]:
        """The ids no Drive tool may read through: the DigiLocker inbox. When it can't be read
        the answer is unknown, so the call fails (nothing is read): fail closed."""
        if self.inbox is None:
            return ()
        try:
            found = await self.inbox(uid)
        except Exception as exc:  # noqa: BLE001 - storage trouble: read nothing
            log.warning("drive: inbox unreadable", extra={"reason": type(exc).__name__})
            raise DriveError(NO_INBOX) from None
        return (found,) if found else ()

    async def offered_folders(self, owner_email: str | None) -> list[DriveFile]:
        """The owner's own folders shared with JARVIS (what Integrations offers)."""
        offered, _, _ = await self._offered(_address(owner_email))
        return offered

    # ---- Integrations ------------------------------------------------------------------------

    async def view(self, uid: str, owner_email: str | None) -> dict[str, Any]:
        email = await self.client.tokens.email()
        offered, others, more = await self._offered(_address(owner_email))
        chosen = await self.roots.load(uid)
        inbox = (await self._deny(uid)) if self.inbox is not None else ()
        readable = {r.id: not await self.checks.problem_of(r, fresh=True) for r in chosen}
        folders = [
            {
                "id": f.id,
                "name": f.name,
                "confirmed": f.id in readable,
                "readable": readable.get(f.id, True),
                **({"inbox": True} if f.id in inbox else {}),
            }
            for f in offered
        ]
        shown = {f.id for f in offered}
        folders += [
            {
                "id": r.id,
                "name": r.name,
                "confirmed": True,
                "readable": readable[r.id],
                **({"inbox": True} if r.id in inbox else {}),
            }
            for r in chosen
            if r.id not in shown
        ]
        out: dict[str, Any] = {
            "service_email": email,
            "folders": folders,
            "others": others,
            "others_more": more,
            "max_folders": MAX_ROOTS,
        }
        if self.inbox is not None:
            out["inbox_wired"] = True  # the console then also asks /v1/vault/inbox (R2 D9)
        return out

    async def _offered(self, mine: str | None) -> tuple[list[DriveFile], int, bool]:
        """The owner's folders shared with JARVIS (owned first), how many other shares there
        are, and whether that list was cut short."""
        offered: dict[str, DriveFile] = {}
        others: set[str] = set()
        owned_failed = False
        if mine is not None:
            try:
                owned, _ = await self._folder_pages(mine, best_effort=False)
            except DriveUnavailable:
                raise
            except DriveError:  # e.g. the query refused: the bounded list below still runs
                log.warning("drive owned-folders list failed")
                owned, owned_failed = [], True
            for f in owned:
                if self.checks.owns(f, mine):
                    offered[f.id] = f
                else:
                    others.add(f.id)
        shared, more = await self._folder_pages(None, best_effort=not owned_failed)
        for f in shared:
            if f.id in offered:
                continue
            if mine is not None and self.checks.owns(f, mine):
                offered[f.id] = f
            else:
                others.add(f.id)
        return list(offered.values()), len(others), more

    async def _folder_pages(
        self, owner: str | None, *, best_effort: bool
    ) -> tuple[list[DriveFile], bool]:
        """≤ OFFER_PAGES pages of shared folders; True when there may be more. `best_effort`:
        a page Drive won't give (a flood of very long names, say) ends the list, not the view."""
        out: list[DriveFile] = []
        token: str | None = None
        for _ in range(OFFER_PAGES):
            try:
                page = await self.client.shared_folders(owner=owner, page_token=token)
            except DriveUnavailable:
                raise
            except DriveError:
                if not best_effort:
                    raise
                log.warning("drive shared-folders list cut short")
                return out, True
            out.extend(page.files)
            token = page.next_token
            if token is None:
                return out, False
        return out, True

    async def set_use(self, uid: str, owner_email: str | None, folder_id: str, on: bool) -> None:
        if not isinstance(folder_id, str) or not DRIVE_ID.fullmatch(folder_id):
            raise DriveRejected("bad_id", "That isn't a Google Drive folder id.")
        if not on:
            await self.roots.remove(uid, folder_id)
            self.checks.forget(folder_id)
            self.guard.forget()
            return
        if folder_id in await self._deny(uid):
            raise DriveRejected("is_inbox", IS_INBOX, status=409)
        mine = _address(owner_email)
        if mine is None:
            raise DriveRejected(
                "no_owner_email",
                "Sign in with Google in the browser to choose Drive folders.",
                status=403,
            )
        try:
            f: DriveFile | None = await self.client.get(folder_id)
        except DriveNotFound:
            f = None
        why = self.checks.remember(folder_id, mine, f)
        if why or f is None:
            code, detail, status = _REFUSED.get(why, _REFUSED["gone"])
            raise DriveRejected(code, detail, status=status)
        try:
            await self.roots.confirm(uid, folder_id, f.name, email=mine)
        except ValueError as exc:
            raise DriveRejected("too_many", str(exc), status=409) from None
        self.guard.forget()

    # ---- the tools -----------------------------------------------------------------------------

    async def folders(self, uid: str) -> dict[str, Any]:
        live, off = await self._live(uid)
        if not live and not off:
            return {"folders": [], "note": NOT_SET_UP}
        note = "Use drive_list with a folder id to see inside, drive_search to find files."
        if off:
            note = SOME_OFF.format(n=off) + (" " + note if live else "")
        return {
            "folders": [
                {
                    "id": r.id,
                    "name": wrap_external(r.name, source="Google Drive name", limit=NAME_SHOWN),
                }
                for r in live
            ],
            "note": note,
        }

    async def _resolve(self, uid: str, file_id: str) -> DriveFile:
        """The item, checked; a shortcut is followed to its target, which is checked again."""
        live, _ = await self._live(uid)
        roots = {r.id for r in live}
        deny = await self._deny(uid)
        item = await self.guard.check(file_id, roots, deny=deny)
        if item.is_shortcut:
            if item.target_id is None:
                raise DriveError(BROKEN_SHORTCUT)
            item = await self.guard.check(item.target_id, roots, deny=deny)
            if item.is_shortcut:
                raise DriveError(BROKEN_SHORTCUT)
        return item

    async def list_folder(
        self, uid: str, folder_id: str, page: str | None = None
    ) -> dict[str, Any]:
        folder = await self._resolve(uid, folder_id)
        if not folder.is_folder:
            raise DriveError("That is a file, not a folder: use drive_read to read it.")
        got = await self.client.children(folder.id, page_token=page, page_size=LIST_PAGE)
        deny = await self._deny(uid)
        inside = [f for f in got.files if folder.id in f.parents and f.id not in deny]
        if len(inside) != len(got.files):  # a page token from another listing, or the inbox
            log.warning("drive list: items from elsewhere dropped")
        return {
            "folder": folder.id,
            "folder_name": _name(folder),
            "items": [_item(f) for f in inside],
            "next_page": got.next_token,
        }

    async def search(self, uid: str, query: str) -> dict[str, Any]:
        live, _ = await self._live(uid)
        roots = {r.id for r in live}
        if not roots:
            return {"query": query, "results": [], "note": NOT_SET_UP}
        scan = _Scan(WalkBudget(SEARCH_LOOKUPS))  # one search costs a bounded number of calls
        scan.deny = await self._deny(uid)
        owners: list[str | None] = [*sorted({r.email for r in live if r.email}), None]
        failed: DriveError | None = None
        answered = 0
        for owner in owners:
            try:
                await self._scan(query, owner, roots, scan)
                answered += 1
            except DriveUnavailable:
                raise
            except DriveError as exc:  # one query Drive wouldn't answer: the others still run
                log.warning("drive search query failed", extra={"owned": owner is not None})
                failed, scan.unchecked = exc, True
        if not answered and failed is not None:
            raise failed
        unchecked = scan.unchecked or scan.budget.ran_out
        if scan.hits:
            note = MATCHED + (" " + UNCHECKED if unchecked else "")
        else:
            note = UNCHECKED_NONE if unchecked else NO_MATCH
        return {"query": query, "results": scan.hits, "note": note}

    async def _scan(self, query: str, owner: str | None, roots: set[str], scan: _Scan) -> None:
        """≤ SEARCH_PAGES pages of one query's hits, each checked (`owner`: that address's own
        files; None: everyone's). A hit whose check fails is not shown: fail closed, go on."""
        token: str | None = None
        for _ in range(SEARCH_PAGES):
            if len(scan.hits) >= SEARCH_LIMIT:
                return
            page = await self.client.search(query, owner=owner, page_token=token)
            scan.unchecked |= page.incomplete
            for f in page.files:
                if len(scan.hits) >= SEARCH_LIMIT:
                    return
                if f.id in scan.seen or f.trashed:
                    continue
                scan.seen.add(f.id)
                try:
                    if scan.deny:
                        inside = await self.guard.inside(f, roots, scan.budget, scan.deny)
                    else:
                        inside = await self.guard.inside(f, roots, scan.budget)
                except DriveUnavailable:
                    raise
                except DriveError:
                    scan.unchecked = True
                    continue
                if inside:  # outside the chosen folders: never shown, not even its name
                    scan.hits.append(_item(f))
            token = page.next_token
            if token is None:
                return
        scan.unchecked = scan.unchecked or len(scan.hits) < SEARCH_LIMIT

    async def read(self, uid: str, file_id: str, part: int = 1) -> dict[str, Any]:
        f = await self._resolve(uid, file_id)
        if f.is_folder:
            raise DriveError(FOLDER_NOT_FILE)
        text = await self._text(f)
        parts = max(1, len(text.chunks))
        if not 1 <= part <= parts:
            raise ValueError(f"part must be 1-{parts} for this file")
        body = text.chunks[part - 1].strip() if text.chunks else ""
        first, last = text.pages[part - 1] if text.pages else (None, None)
        pages = pages_label(first, last)
        source = f"Google Drive file, part {part} of {parts}" + (f", {pages}" if pages else "")
        out: dict[str, Any] = {
            "file": f.id,
            "name": _name(f),
            "kind": kind_word(f.mime),
            "part": part,
            "parts": parts,
            "pages": pages,
            "more": part < parts,
            "truncated": text.truncated,
            "text": wrap_external(body or "(no text)", source=source, limit=PART_TEXT_LIMIT),
        }
        if f.mime == SHEET_MIME:
            out["note"] = SHEET_NOTE
        return out

    # ---- text --------------------------------------------------------------------------------

    async def _text(self, f: DriveFile) -> _Text:
        key = (f.id, f.modified or "")
        hit = self._texts.get(key)
        if hit is not None and hit[0] > self._clock():
            self._texts.move_to_end(key)
            return hit[1]
        text = await self._fetch_text(f)
        self._texts[key] = (self._clock() + TEXT_CACHE_S, text)
        while len(self._texts) > TEXT_CACHE_FILES:
            self._texts.popitem(last=False)
        return text

    async def _fetch_text(self, f: DriveFile) -> _Text:
        if f.mime in EXPORTS:
            data = await self.client.export(f.id, EXPORTS[f.mime])
            kind = "csv" if EXPORTS[f.mime] == "text/csv" else "txt"
        else:
            blob = blob_kind(f)
            if blob is None:
                raise DriveError(UNSUPPORTED)
            kind = blob
            if f.size is not None and f.size > MAX_FILE_BYTES:
                raise DriveError(TOO_BIG)
            data = await self.client.download(f.id)
        out = await self._extract(data, kind)
        chunks, cut = split(out.text, out.page_starts, cost=PART_CHARS)
        return _Text(
            tuple(c.text for c in chunks),
            tuple((c.page, c.page_end) for c in chunks),
            out.truncated or cut,
        )

    async def _extract(self, data: bytes, kind: str) -> Extracted:
        """Through the app's one extraction slot (`DocumentService.extract`); its refusals are
        said in Drive's words (`jarvis.drive.kinds.refusal_words`), never its own."""
        if not data:
            raise DriveError(EMPTY)
        if self.extract is None:  # not wired: fail closed
            log.warning("drive: no extractor wired")
            raise DriveError(NO_READER)
        try:
            return await self.extract(data, kind)
        except DocumentRejected as exc:
            raise DriveError(refusal_words(exc.code)) from None


# ---- wiring (the app) --------------------------------------------------------------------------


def drive_configured(s: Settings) -> bool:
    return bool(s.drive)


def build_drive_service(
    s: Settings, docs: Docs, *, extract: Extractor, inbox: InboxSource | None = None
) -> DriveService | None:
    """None unless `JARVIS_DRIVE=on`: then no tools, and /v1/drive says not configured. No
    network here: the token and address are fetched on first use. `extract`: the app's
    `DocumentService.extract`, so Drive files share the one extraction slot."""
    if not drive_configured(s):
        return None
    from jarvis.drive.token import MetadataTokens

    roots = RootsStore(docs, prefix=s.firestore_prefix)
    return DriveService(DriveClient(MetadataTokens()), roots, extract=extract, inbox=inbox)


__all__ = [
    "NOT_IN_ROOTS",
    "NOT_SET_UP",
    "DriveNotFound",
    "DriveRejected",
    "InboxSource",
    "DriveService",
    "Extractor",
    "NotInRoots",
    "build_drive_service",
    "check_id",
    "drive_configured",
    "kind_word",
]

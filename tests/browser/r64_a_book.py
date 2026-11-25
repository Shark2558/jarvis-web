# tests/browser/r64_a_book.py -- R6.4 A (docs/plans/r6-4-book-look.md D3, D4): a small full book for the reader's
# browser tests, in the routes' own shapes (buildbook/writer/http.py: PagesView, Page + flow, ChaptersView, SearchView;
# docs/plans/r6-4-integration/I0-NOTES.md section 5): two story chapters, two modules (Memory, 2 pages; Vault, narrated,
# 5 pages with a flowchart), two screens and a service in no chapter. `install(fake)` hands it to book_mocks.FakeBook.
# Made-up demo words only (the approved mockup's): no person, no place, no key.
# ruff: noqa: E501 -- the demo words
from __future__ import annotations

import copy
from typing import Any

from book_mocks import RELEASE

RID = RELEASE["id"]
META = {"written_by": "Workshop · Mark XXIV", "written_on": "2026-11-24", "release": RID, "version": "v6.4.0"}
HEADINGS = {"plain": "In plain words", "example": "Example (made up)", "how": "How it works",
            "costs": "What it costs", "fails": "When it fails", "code": "Where in the code"}  # fmt: skip
VAULT_FLOW: dict[str, Any] = {
    "title": "A document, attached or kept in the vault",
    "dir": "down",
    "nodes": [
        {"id": "file", "label": "You add a file", "kind": "person", "rank": 0, "col": 0},
        {"id": "kind", "label": "Right kind and size?", "kind": "guard", "rank": 1, "col": 0, "ref": "src/jarvis/documents/limits.py"},
        {"id": "refused", "label": "Refused in plain words", "kind": "step", "rank": 1, "col": 1},
        {"id": "read", "label": "Text taken out apart", "kind": "step", "rank": 2, "col": 0, "ref": "src/jarvis/api/documents.py"},
        {"id": "chat", "label": "Text kept with the chat", "kind": "store", "rank": 3, "col": 0},
        {"id": "vault", "label": "Sealed in the vault", "kind": "store", "rank": 2, "col": 2, "ref": "src/jarvis/api/vault.py"},
        {"id": "inbox", "label": "DigiLocker Drive folder", "kind": "service", "rank": 1, "col": 2, "ref": "src/jarvis/api/vault_inbox.py"},
        {"id": "confirm", "label": "You confirm the expiry", "kind": "person", "rank": 3, "col": 3},
        {"id": "unlock", "label": "Passkey or fresh sign-in", "kind": "guard", "rank": 4, "col": 2},
        {"id": "audit", "label": "Audit line written", "kind": "guard", "rank": 5, "col": 2},
        {"id": "open", "label": "One-time download", "kind": "step", "rank": 6, "col": 2},
    ],
    "edges": [
        {"from": "file", "to": "kind"}, {"from": "kind", "to": "refused", "style": "side"},
        {"from": "kind", "to": "read", "label": "attach"}, {"from": "read", "to": "chat"},
        {"from": "kind", "to": "vault", "label": "keep"}, {"from": "inbox", "to": "vault", "style": "side"},
        {"from": "vault", "to": "confirm", "label": "expiry found", "style": "side"},
        {"from": "vault", "to": "unlock", "label": "open"}, {"from": "unlock", "to": "audit"}, {"from": "audit", "to": "open"},
    ],
}  # fmt: skip
VAULT = {
    "plain": "This module is how documents reach JARVIS. Attaching files to a message lets JARVIS read them for that conversation; each file itself is thrown away and only its text stays with the chat.\n\nThe vault is different: a locked cupboard for papers you keep. Each file is sealed with its own key, JARVIS reminds you before something expires, and nothing opens until you prove it’s you.",
    "example": "Lakshmi drags her car insurance PDF and 2 photos of a dented bumper onto a message and asks what the policy covers. JARVIS reads all 3 and answers. She then adds the policy to the vault; it finds an expiry date of 31 March 2027 and asks her to confirm it.",
    "how": "The paperclip in `console-attach.js` sends each file to `POST /v1/attachments`, where `upload` judges its kind by its name and its bytes together. A message carries at most 10 files, 40 MB together and 4 pictures.\n\nOpening a vault file needs `unlock`: your passkey when you have one, otherwise a fresh Google sign-in, and `download` sends the file only after its audit line is written.",
    "costs": "Taking text out of a file and keeping the vault cost nothing: both run on JARVIS’s own server with no outside service.",
    "fails": "A file that is too big, unreadable or of the wrong kind is refused in plain words (`DocumentRejected`). When the reader is busy, the upload is refused with a retry after 30 seconds. If the vault’s unlock can’t be written to the audit trail, nothing opens.",
}
REFS = ["src/jarvis/api/documents.py", "src/jarvis/api/vault.py", "src/jarvis/api/static/console-attach.js"]


def _words(title: str) -> dict[str, str]:
    return {
        "plain": f"{title} in plain words: the demo part keeps one job and does it the same way every time.",
        "example": "A made-up household asks for a reminder, and it comes back in 3 tries at most.",
        "how": "The request arrives at `demo_router`, which reads the setting `demo_limit` and answers.",
        "costs": "Nothing by itself: each answer is billed by the brain that wrote it.",
        "fails": "When nothing answers, it says so plainly. Nothing is retried.",
    }


def page(pid: str, kind: str, title: str, part: str, chapter: str = "", words: dict[str, str] | None = None,
         flow: dict[str, Any] | None = None, refs: list[str] | None = None, written: bool = True) -> dict[str, Any]:  # fmt: skip
    """GET /v1/book/pages/{id}: the six sections in order, who wrote it, the optional `flow`."""
    w = words or _words(title)
    code = refs if refs is not None else ["src/jarvis/demo/router.py"]
    sections = [{"id": s, "heading": h, "text": w.get(s, "") if s != "code" else "\n".join(f"`{r}`" for r in code),
                 "refs": code if s == "code" else []} for s, h in HEADINGS.items()]  # fmt: skip
    return {"id": pid, "kind": kind, "title": title, "part": part, "chapter": chapter, "sections": sections,
            "meta": META if written else None, "flow": flow}  # fmt: skip


C42 = dict(_words("Document vault"), costs="₹0 for the vault: sealing, reading dates and reminders are all code on JARVIS’s own server.")
PAGES: dict[str, dict[str, Any]] = {
    p["id"]: p
    for p in (
        page("pg_chapter_what", "chapter", "What JARVIS is", "plain"),
        page("pg_chapter_example", "chapter", "The running example", "plain"),
        page("pg_module_memory", "module", "Memory and knowledge", "modules"),
        page("pg_card_c10", "card", "Long-term memory", "parts", "memory"),
        page("pg_module_vault", "module", "Vault and documents", "modules", words=VAULT, flow=VAULT_FLOW, refs=REFS),
        page("pg_card_c07", "card", "Attached documents", "parts", "vault"),
        page("pg_card_c42", "card", "Document vault", "parts", "vault", words=C42),
        page("pg_card_c43", "card", "DigiLocker import folder", "parts", "vault", written=False),
        page("pg_screen_chat", "screen", "Chat", "screens"),
        page("pg_screen_vault", "screen", "The Vault screen", "screens"),
        page("pg_service_drive", "service", "Google Drive", "services"),
    )
}


def _rows(*ids: str) -> list[dict[str, Any]]:
    return [{"id": i, "kind": PAGES[i]["kind"], "title": PAGES[i]["title"], "written": PAGES[i]["meta"]} for i in ids]


INDEX = {
    "release": RID,
    "parts": [
        {"id": "plain", "title": "JARVIS in plain words", "chapters": [{"id": "plain", "title": "JARVIS in plain words", "pages": _rows("pg_chapter_what", "pg_chapter_example")}]},
        {"id": "modules", "title": "Modules", "chapters": [{"id": "modules", "title": "Modules", "pages": _rows("pg_module_memory", "pg_module_vault")}]},
        {"id": "parts", "title": "Parts", "chapters": [
            {"id": "memory", "title": "Memory and knowledge", "pages": _rows("pg_card_c10")},
            {"id": "vault", "title": "Vault and documents", "pages": _rows("pg_card_c07", "pg_card_c42", "pg_card_c43")}]},
        {"id": "screens", "title": "Screens", "chapters": [{"id": "screens", "title": "Screens", "pages": _rows("pg_screen_chat", "pg_screen_vault")}]},
        {"id": "services", "title": "Outside services", "chapters": [{"id": "services", "title": "Outside services", "pages": _rows("pg_service_drive")}]},
    ],
    "limitations": {"shown": 0, "total": 0},
}  # fmt: skip
VAULT_PAGES = ["pg_module_vault", "pg_card_c07", "pg_card_c42", "pg_card_c43", "pg_screen_vault"]
CHAPTERS = {
    "release": RID,
    "label": "R6.4",  # R6.4 I1: the sealed release's label, for the chip
    "chapters": [
        {"id": "story_what", "title": "What JARVIS is", "kind": "story", "pages": ["pg_chapter_what"], "minutes": 0, "narrated": False},
        {"id": "story_example", "title": "The running example", "kind": "story", "pages": ["pg_chapter_example"], "minutes": 0, "narrated": False},
        {"id": "module_memory", "title": "Memory and knowledge", "kind": "module", "pages": ["pg_module_memory", "pg_card_c10"], "minutes": 0, "narrated": False},
        {"id": "module_vault", "title": "Vault and documents", "kind": "module", "pages": VAULT_PAGES, "minutes": 9, "narrated": True, "lines": 80},
    ],
}  # fmt: skip
HOSTILE = '<img src=x onerror="window.__pwned=1">Vault'


def search(q: str) -> tuple[int, Any]:
    """GET /v1/book/pages/search: 'expiry' finds two pages (one title is hostile markup, drawn as text); else none."""
    if len(q.strip()) < 2:
        return 422, {"error": "bad_query", "detail": "Type at least 2 characters."}
    if not q.lower().startswith("expir"):
        return 200, {"release": RID, "q": q, "total": 0, "results": []}
    s1 = "…it finds an expiry date of 31 March 2027 and asks her to confirm it."
    s2 = "JARVIS reminds you before a document expires <b>soon</b>, and the brain never sees the file…"
    a, b = s2.index("expires"), s2.index("expires") + len("expires")
    return 200, {"release": RID, "q": q, "total": 26, "results": [
        {"id": "pg_module_vault", "title": "Vault and documents", "kind": "module", "snippet": s1, "marks": [[s1.index("expiry"), s1.index("expiry") + 6]]},
        {"id": "pg_card_c42", "title": HOSTILE, "kind": "card", "snippet": s2, "marks": [[a, b], [a + 2, b], [500, 600]]},
    ]}  # fmt: skip


def install(fake: Any) -> None:
    """The small book on a FakeBook: contents, chapters, every page, the search."""
    fake.pages_answer = (200, copy.deepcopy(INDEX))
    fake.chapters_answer = (200, copy.deepcopy(CHAPTERS))
    fake.page_answers = {pid: (200, copy.deepcopy(p)) for pid, p in PAGES.items()}
    fake.search_answer = search

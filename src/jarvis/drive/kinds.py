# src/jarvis/drive/kinds.py
"""What JARVIS can read from Drive, and how it says what went wrong (slice 12 D1).

Google Docs / Slides are exported as text/plain, Sheets as text/csv (Google exports only the
first sheet, and the read says so); PDF / DOCX / TXT / MD / CSV ≤ 10 MB are downloaded and go
through the app's one sandboxed extractor (slice 10, `DocumentService.extract`).

The extractor's refusals were written for chat uploads ("… and attach it again"); a Drive file
can't be attached again, so each refusal is said here in Drive's own words, keyed by its code.
The extractor's text itself never reaches the owner or the model from a Drive read.
"""

from __future__ import annotations

from jarvis.drive.ports import (
    DOC_MIME,
    FOLDER_MIME,
    GOOGLE_PREFIX,
    SHEET_MIME,
    SHORTCUT_MIME,
    SLIDES_MIME,
    DriveFile,
)

EXPORTS = {DOC_MIME: "text/plain", SLIDES_MIME: "text/plain", SHEET_MIME: "text/csv"}
BLOBS = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
    "text/markdown": "md",
    "text/x-markdown": "md",
    "text/csv": "csv",
}
_EXT = {".pdf": "pdf", ".docx": "docx", ".txt": "txt", ".md": "md", ".csv": "csv"}
KINDS = {
    FOLDER_MIME: "folder",
    DOC_MIME: "Google Doc",
    SHEET_MIME: "Google Sheet",
    SLIDES_MIME: "Google Slides",
    "application/pdf": "PDF",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word",
    "text/plain": "text",
    "text/markdown": "Markdown",
    "text/csv": "CSV",
    SHORTCUT_MIME: "shortcut",
}
UNSUPPORTED = (
    "JARVIS can read Google Docs, Sheets (the first sheet only) and Slides, and PDF, Word "
    "(.docx), text, Markdown and CSV files from Drive — not this kind of file."
)
SHEET_NOTE = "Only the first sheet of this spreadsheet was read (Google exports just that one)."
TOO_BIG = "That file is over 10 MB, so JARVIS can't read it."
EMPTY = "That file is empty."
BUSY = "JARVIS is still reading another file. Try again in a minute."
NOT_READ = "JARVIS couldn't read that Drive file."
_WORDS = {
    "busy": BUSY,
    "empty": EMPTY,
    "encrypted": (
        "That Drive file is password-protected, so JARVIS can't read it. A copy without the "
        "password, in the same folder, would work."
    ),
    "no_text": (
        "No text found in that Drive file. It looks like a scan or a picture of text, and JARVIS "
        "can't read scans yet."
    ),
    "unreadable": "JARVIS couldn't read that Drive file. It may be damaged.",
    "too_complex": (
        "That Drive file is too large or unusual to read safely. A copy saved as plain text or a "
        "simpler PDF, in the same folder, would work."
    ),
    "too_slow": (
        "That Drive file took too long to read. A copy saved as text, in the same folder, would "
        "work."
    ),
    "unsupported": "That Drive file's contents don't match its type, so JARVIS can't read it.",
    "too_large": TOO_BIG,
}


def kind_word(mime: str) -> str:
    return KINDS.get(mime) or ("Google file" if mime.startswith(GOOGLE_PREFIX) else "file")


def blob_kind(f: DriveFile) -> str | None:
    """The extractor's kind for a downloaded file, or None when JARVIS can't read it."""
    if f.mime in BLOBS:
        return BLOBS[f.mime]
    low = f.name.lower()
    if f.mime in ("application/octet-stream", "") or f.mime.startswith("text/"):
        return next((k for ext, k in _EXT.items() if low.endswith(ext)), None)
    return None


def refusal_words(code: str) -> str:
    """The extractor's refusal `code`, said for a Drive file (never "attach it again")."""
    return _WORDS.get(code, NOT_READ)


__all__ = [
    "BLOBS",
    "BUSY",
    "EMPTY",
    "EXPORTS",
    "KINDS",
    "SHEET_NOTE",
    "TOO_BIG",
    "UNSUPPORTED",
    "blob_kind",
    "kind_word",
    "refusal_words",
]

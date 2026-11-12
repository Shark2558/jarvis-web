# src/jarvis/documents/archive.py
"""A zip file, or a folder the console packed into one bundle, read member by member (R11.1,
docs/plans/r11-1-observations.md D11; Layer 2 input). Pure and synchronous; in the app it runs
only inside the extraction worker. Nothing is ever written to disk: a member is inflated into
memory (zipfile stops at its declared size and checks its CRC), read as its own kind by the same
readers a lone file gets, and dropped.

Refused whole, from the central directory alone, before any member is inflated:
  - a password (any encrypted member);
  - a bomb: more than 1,000 entries, more than `Limits.archive_max_total` unpacked in all, or a
    member over 1 MB packed more than 100 times;
  - a path that points outside (absolute, a drive letter, a `..` step, a control character);
  - an archive inside the archive (.zip, .7z, .rar, .tar, .gz, ...): never opened;
  - more readable files than `Limits.archive_max_files` (never half-read).
Then each member: over 10 MB, a kind JARVIS doesn't read, damaged, password-protected or with
contents that don't match its name -> named under "Not read:" with the reason, and the rest are
still read. At most `Limits.max_pictures` pictures are taken. The character cap and the time
budget cover the whole archive. Member names are other people's words: they appear only in the
text, which reaches a model only inside a fence (`documents.note`, `DocumentService.read_part`).
"""

from __future__ import annotations

import dataclasses
import io
import re
import zipfile
from pathlib import PurePosixPath

from jarvis.documents.extract import (
    Clock,
    Extracted,
    Limits,
    Picture,
    _cap,
    _read,
    _unreadable,
    bomb_check,
    normalise,
    sniff,
    too_complex,
    zip_infos,
)
from jarvis.documents.limits import (
    ARCHIVE_SUFFIXES,
    EXTENSIONS,
    KIND_LABELS,
    MAX_FILE_BYTES,
    NAME_LIMIT,
    DocumentRejected,
)

MAX_NAMED = 20  # members named under "Not read:" before "and N more"
_JUNK = re.compile(r"(^|/)(__MACOSX/|\._|\.DS_Store$|Thumbs\.db$|desktop\.ini$)")
_DRIVE = re.compile(r"^[A-Za-z]:")
_UNSEEN = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_REASONS = {
    "encrypted": "password-protected",
    "no_text": "no text found in it",
    "empty": "empty",
    "too_complex": "too large or unusual",
    "too_slow": "took too long to read",
    "too_large": "too large",
    "bad_picture": "could not be read",
    "unreadable": "could not be read",
    "unsupported": "its contents don't match its name",
}


def _words(kind: str) -> tuple[str, str]:
    """(what to call it at the start of a sentence, and inside one)."""
    return ("Folder", "folder") if kind == "folder" else ("Zip file", "zip")


def _unsafe(detail: str) -> DocumentRejected:
    return DocumentRejected("unsafe_archive", detail)


def _escapes(name: str) -> bool:
    flat = name.replace("\\", "/")
    if flat.startswith("/") or _DRIVE.match(flat) or _UNSEEN.search(name):
        return True
    return any(step == ".." for step in flat.split("/"))


def _shown(name: str) -> str:
    """A member's path as one visible line (it is someone else's text: fenced where it is used)."""
    flat = " ".join(_UNSEEN.sub("", name.replace("\\", "/")).split())
    return flat if len(flat) <= NAME_LIMIT else "…" + flat[-(NAME_LIMIT - 1) :]


def _suffix(name: str) -> str:
    return PurePosixPath(name.replace("\\", "/")).suffix.lower()


def _guard(infos: list[zipfile.ZipInfo], kind: str, limits: Limits) -> None:
    """Every refusal the central directory alone can justify (nothing inflated yet)."""
    start, inside = _words(kind)
    if any(i.flag_bits & 0x1 for i in infos):
        raise DocumentRejected(
            "encrypted",
            f"This {inside} is password-protected. Zip the files again without a password and "
            "attach that.",
        )
    try:
        bomb_check(infos, limits, inside, total=limits.archive_max_total)
    except DocumentRejected:
        mb = limits.archive_max_total // (1024 * 1024)
        raise DocumentRejected(
            "too_complex",
            f"This {inside} unpacks to too much to open safely (more than {mb} MB in all, or "
            "packed like a zip bomb). Attach fewer or smaller files.",
        ) from None
    if any(_escapes(i.filename) for i in infos):
        raise _unsafe(
            f"This {inside} has a file whose path points outside the {inside}, which is not safe "
            "to open. Zip the files again and attach that."
        )
    if any(not i.is_dir() and i.filename.lower().endswith(ARCHIVE_SUFFIXES) for i in infos):
        raise _unsafe(
            f"This {inside} has another archive inside it. JARVIS never opens an archive inside "
            f"{'a folder' if kind == 'folder' else 'an archive'}: unzip it and attach the files "
            "you need."
        )
    del start


class _Bundle:
    """What was read and what was not, as the text the model gets."""

    def __init__(self, kind: str, limits: Limits) -> None:
        self.kind, self.limits = kind, limits
        self.read: list[tuple[str, str, str]] = []  # (name, label, text)
        self.unread: list[tuple[str, str]] = []  # (name, why)
        self.pictures: list[Picture] = []
        self.used = 0
        self.sheets = self.rows = 0
        self.cut = False

    def left(self) -> int:
        return self.limits.max_chars - self.used

    def skip(self, name: str, why: str) -> None:
        self.unread.append((_shown(name), why))

    def add(self, name: str, kind: str, out: Extracted) -> None:
        inside = _words(self.kind)[1]
        if out.pictures:
            if len(self.pictures) >= self.limits.max_pictures:
                n = self.limits.max_pictures
                self.skip(name, f"only {n} pictures are read from one {inside}")
                return
            self.pictures.append(dataclasses.replace(out.pictures[0], name=_shown(name)))
            body = "(a picture: shown with this message to a brain that can see)"
            self.read.append((_shown(name), "picture", body))
            self.used += len(body)
            return
        label = KIND_LABELS.get(kind, kind)
        self.read.append((_shown(name), label, out.text))
        self.used += len(out.text) + len(name) + 24
        self.sheets += out.sheets or 0
        self.rows += out.rows or 0
        self.cut = self.cut or out.truncated

    def _unread_line(self) -> str:
        named = "; ".join(f"{n} ({why})" for n, why in self.unread[:MAX_NAMED])
        more = len(self.unread) - MAX_NAMED
        return "Not read: " + named + (f"; and {more:,} more." if more > 0 else ".")

    def done(self) -> Extracted:
        start, inside = _words(self.kind)
        if not self.read:
            why = " " + self._unread_line() if self.unread else ""
            raise DocumentRejected("no_text", f"Nothing in this {inside} could be read.{why}"[:480])
        total = len(self.read)
        head = f"{start}: {total:,} file{'' if total == 1 else 's'} read"
        head += f", {len(self.unread):,} not read." if self.unread else "."
        parts = [head]
        for n, (name, label, text) in enumerate(self.read, 1):
            title = f"File {n} of {total}: {name}"
            parts.append(f"{title} ({label})\n{text}" if label != "picture" else f"{title} {text}")
        if self.unread:
            parts.append(self._unread_line())
        text, cut = _cap(normalise("\n\n".join(parts)), self.limits)
        return Extracted(
            kind=self.kind,
            text=text,
            truncated=self.cut or cut,
            sheets=self.sheets or None,
            rows=self.rows or None,
            files=total,
            skipped=len(self.unread),
            pictures=tuple(self.pictures),
        )


def _member(
    zf: zipfile.ZipFile, info: zipfile.ZipInfo, kind: str, limits: Limits, deadline: float, c: Clock
) -> Extracted:
    """One member read as its own kind (raises DocumentRejected with that kind's reason)."""
    if info.file_size > MAX_FILE_BYTES:
        raise DocumentRejected("too_large", "too large")
    try:
        raw = zf.read(info)
    except MemoryError:
        raise
    except Exception as exc:  # noqa: BLE001 — a bad CRC, an unknown compression method
        raise _unreadable() from exc
    sniff(raw, kind)
    try:
        return _read(raw, kind, limits, deadline, c)
    except MemoryError:
        raise too_complex() from None


def _candidates(infos: list[zipfile.ZipInfo], bundle: _Bundle) -> list[tuple[zipfile.ZipInfo, str]]:
    """The members worth reading, with their kinds; the others are noted as not read."""
    wanted: list[tuple[zipfile.ZipInfo, str]] = []
    for info in infos:
        if info.is_dir() or _JUNK.search(info.filename.replace("\\", "/")):
            continue
        kind = EXTENSIONS.get(_suffix(info.filename))
        if kind is None or kind == "zip":
            bundle.skip(info.filename, "not a kind JARVIS reads")
        else:
            wanted.append((info, kind))
    return wanted


def read_archive(
    data: bytes, kind: str, limits: Limits, deadline: float, clock: Clock
) -> Extracted:
    infos = zip_infos(data)
    _guard(infos, kind, limits)
    inside = _words(kind)[1]
    bundle = _Bundle(kind, limits)
    wanted = _candidates(infos, bundle)
    if len(wanted) > limits.archive_max_files:
        raise DocumentRejected(
            "too_complex",
            f"This {inside} holds {len(wanted):,} files JARVIS could read; it reads up to "
            f"{limits.archive_max_files} from one {inside}. Attach fewer files.",
        )
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info, member_kind in wanted:
                if clock() > deadline:
                    bundle.skip(info.filename, "ran out of time")
                    bundle.cut = True
                    continue
                if bundle.left() <= 0:
                    n = limits.max_chars
                    bundle.skip(info.filename, f"the limit of {n:,} characters was reached")
                    bundle.cut = True
                    continue
                sub = dataclasses.replace(limits, max_chars=bundle.left())
                try:
                    out = _member(zf, info, member_kind, sub, deadline, clock)
                except DocumentRejected as exc:
                    why = "over 10 MB" if exc.code == "too_large" and member_kind != "image" else ""
                    bundle.skip(info.filename, why or _REASONS.get(exc.code, "could not be read"))
                    continue
                bundle.add(info.filename, member_kind, out)
    except DocumentRejected:
        raise
    except MemoryError:
        raise too_complex() from None
    except Exception as exc:  # noqa: BLE001
        raise _unreadable() from exc
    return bundle.done()


__all__ = ["read_archive"]

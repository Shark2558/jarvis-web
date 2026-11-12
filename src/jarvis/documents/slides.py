# src/jarvis/documents/slides.py
"""PowerPoint decks as text (R11.1, docs/plans/r11-1-observations.md D11; Layer 2 input). Pure
and synchronous; in the app it runs only inside the extraction worker.

A .pptx is a zip of XML parts. After `extract.office_guard` (not a bomb, no document type
definition, UTF-8 only) each slide's XML is parsed with lxml (already in the image for Word
files) with entities, DTDs and the network off, and only its words are taken:

    Slide N of M          in the deck's own order (`ppt/presentation.xml`; by number when that
    <a line a paragraph>  part is missing or damaged), a table row as "a | b | c"
    Notes: <the notes>    the notes page THIS slide links to (never one outside the deck)

Nothing is rendered, no picture or embedded object is opened, no macro is run. Caps: `MAX_SLIDES`
slides, `Limits.max_chars`, the time budget between slides. A slide whose XML is damaged says so
and the rest are still read.
"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
from typing import Any

from jarvis.documents.extract import (
    Clock,
    Extracted,
    Limits,
    _cap,
    _no_text,
    _unreadable,
    normalise,
    office_guard,
    too_complex,
    too_slow,
)
from jarvis.documents.limits import MAX_SLIDES, DocumentRejected

_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
_PARA, _TEXT, _BREAK, _FIELD = _A + "p", _A + "t", _A + "br", _A + "fld"
_ROW, _CELL = _A + "tr", _A + "tc"
_SLIDE = re.compile(r"ppt/slides/slide(\d{1,6})\.xml")
_NOTES = re.compile(r"ppt/notesSlides/[^/]{1,80}\.xml")
BAD_SLIDE = "(this slide could not be read)"
NO_WORDS = "(no words on this slide)"


def _parse(xml: bytes) -> Any:
    from lxml import etree  # BSD; python-docx already needs it

    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        remove_comments=True,
        remove_pis=True,
    )
    return etree.fromstring(xml, parser)


def _para(p: Any, *, fields: bool) -> str:
    bits: list[str] = []
    for el in p.iter(_TEXT, _BREAK):
        if el.tag == _BREAK:
            bits.append(" ")
        elif fields or not any(a.tag == _FIELD for a in el.iterancestors()):
            bits.append(el.text or "")
    return " ".join("".join(bits).split())


def _inside(el: Any, tag: str) -> bool:
    return any(a.tag == tag for a in el.iterancestors())


def _lines(root: Any, *, fields: bool = True) -> list[str]:
    """The words of one slide (or notes page), a line a paragraph, a table row as "a | b"."""
    out: list[str] = []
    for el in root.iter(_ROW, _PARA):
        if el.tag == _ROW:
            if _inside(el, _ROW):
                continue  # a table inside a cell: its words are that cell's
            cells = [
                " ".join(t for t in (_para(p, fields=fields) for p in tc.iter(_PARA)) if t)
                for tc in el.iterchildren(_CELL)
            ]
            line = " | ".join(cells) if any(cells) else ""
        elif _inside(el, _CELL):
            continue
        else:
            line = _para(el, fields=fields)
        if line:
            out.append(line)
    return out


def _target(base: str, target: str) -> str:
    return posixpath.normpath(posixpath.join(base, target.replace("\\", "/")))


def _rels(zf: zipfile.ZipFile, part: str, names: set[str], kind: str) -> dict[str, str]:
    """{relationship id: part it points to inside the deck} for relationships of `kind`."""
    folder, _, leaf = part.rpartition("/")
    rels = f"{folder}/_rels/{leaf}.rels"
    if rels not in names:
        return {}
    try:
        root = _parse(zf.read(rels))
    except Exception:  # noqa: BLE001 — damaged relationships: this part has none
        return {}
    found: dict[str, str] = {}
    for rel in root.iter(_REL):
        if str(rel.get("Type", "")).endswith("/" + kind) and rel.get("TargetMode") != "External":
            found[str(rel.get("Id", ""))] = _target(folder, str(rel.get("Target", "")))
    return found


def _order(zf: zipfile.ZipFile, names: set[str]) -> list[str]:
    """The slides in the deck's own order; by number when the deck doesn't say."""
    by_number = sorted(
        (n for n in names if _SLIDE.fullmatch(n)),
        key=lambda n: int(_SLIDE.fullmatch(n).group(1)),  # type: ignore[union-attr]
    )
    main = "ppt/presentation.xml"
    if main not in names:
        return by_number
    try:
        root = _parse(zf.read(main))
    except Exception:  # noqa: BLE001
        return by_number
    rels = _rels(zf, main, names, "slide")
    listed = [rels.get(str(el.get(_R_ID, "")), "") for el in root.iter(_P + "sldId")]
    known = set(by_number)
    ordered = list(dict.fromkeys(n for n in listed if n in known))
    return ordered or by_number


def _slide(zf: zipfile.ZipFile, part: str, names: set[str]) -> list[str]:
    try:
        lines = _lines(_parse(zf.read(part)))
    except MemoryError:
        raise
    except Exception:  # noqa: BLE001 — one damaged slide never sinks the deck
        return [BAD_SLIDE]
    notes = next(
        (t for t in _rels(zf, part, names, "notesSlide").values() if _NOTES.fullmatch(t)), ""
    )
    if notes in names:
        try:
            said = _lines(_parse(zf.read(notes)), fields=False)
        except MemoryError:
            raise
        except Exception:  # noqa: BLE001
            said = []
        if said:
            lines.append("Notes: " + "\n".join(said))
    return lines


def read_deck(data: bytes, limits: Limits, deadline: float, clock: Clock) -> Extracted:
    infos = office_guard(data, limits, kind="pptx", folder="ppt/")
    names = {i.filename for i in infos}
    parts: list[str] = []
    used = words = 0
    more = False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            slides = _order(zf, names)
            more = len(slides) > MAX_SLIDES
            for n, part in enumerate(slides[:MAX_SLIDES], 1):
                if clock() > deadline or used > limits.max_chars:
                    more = True
                    break
                lines = _slide(zf, part, names)
                words += sum(1 for line in lines if line != BAD_SLIDE)
                body = "\n".join(lines) if lines else NO_WORDS
                parts.append(f"Slide {n} of {len(slides)}\n{body}")
                used += len(parts[-1]) + 2
    except DocumentRejected:
        raise
    except MemoryError:
        raise too_complex() from None
    except Exception as exc:  # noqa: BLE001 — a bad CRC, an unknown compression method
        raise _unreadable() from exc
    if not words:
        if more:
            raise too_slow()
        raise _no_text("pptx")
    text, cut = _cap(normalise("\n\n".join(parts)), limits)
    return Extracted(kind="pptx", text=text, truncated=more or cut, slides=len(slides))


__all__ = ["read_deck"]

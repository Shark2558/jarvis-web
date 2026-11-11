# src/jarvis/helpers/house/xmlsafe.py
"""Outside XML (NDMA SACHET's CAP 1.2 and RSS) read in two layers (D13; security review M1).

`parse_xml(raw, limit=)` after the fetcher's bounded read (`fetch._read`), and its size again:
- (a) the bytes: a UTF-8 BOM is dropped, any other BOM (UTF-16, UTF-32) or any NUL byte is
  refused, the rest must decode as strict UTF-8, an XML declaration may only say utf-8, and the
  decoded text may not hold `<!DOCTYPE` or `<!ENTITY` in any case. BOM-less UTF-16 (`3C 00 21
  00 ...`) is caught here by its NULs: it used to decode as "UTF-8" and reach expat's own
  encoding detection.
- (b) the parser (`expat_tree`): the standard library's expat, fed the decoded text (so expat is
  told it is UTF-8 and never guesses), building an ElementTree with `{namespace}tag` names. Its
  DOCTYPE, entity-declaration, external-entity, unparsed-entity and notation handlers all raise,
  and parameter entities are never parsed, so a DTD is refused by the parser itself even if the
  text check were bypassed. The element count is bounded while parsing. No new dependency.
"""

from __future__ import annotations

import codecs
import re
import xml.etree.ElementTree as ET
from typing import NoReturn
from xml.parsers import expat

MAX_ELEMENTS = 5000
Builder = ET.TreeBuilder
_OTHER_BOMS = (
    codecs.BOM_UTF32_LE,
    codecs.BOM_UTF32_BE,
    codecs.BOM_UTF16_LE,
    codecs.BOM_UTF16_BE,
)
_DECL = re.compile(r"^\s*<\?xml\b[^>]*?\?>", re.I)
_ENCODING = re.compile(r"\bencoding\s*=\s*([\"'])([^\"']*)\1", re.I)


class UnsafeXml(ValueError):
    """XML JARVIS will not parse (a DTD, an entity, too large, not UTF-8, or broken)."""


def _refuse(*_: object) -> NoReturn:
    raise UnsafeXml("The XML has a DOCTYPE or an ENTITY.")


def _text_of(raw: bytes, limit: int) -> str:
    """Layer (a): the bytes as strict UTF-8 text, or UnsafeXml."""
    if not raw or len(raw) > limit:
        raise UnsafeXml("The XML is empty or too large.")
    body = raw[len(codecs.BOM_UTF8) :] if raw.startswith(codecs.BOM_UTF8) else raw
    if body.startswith(_OTHER_BOMS) or b"\x00" in body:
        raise UnsafeXml("The XML isn't UTF-8.")
    try:
        text = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise UnsafeXml("The XML isn't UTF-8.") from exc
    declared = _DECL.match(text)
    if declared is not None and "encoding" in declared.group(0).lower():
        named = _ENCODING.search(declared.group(0))
        if named is None or named.group(2).strip().lower() != "utf-8":
            raise UnsafeXml("The XML declares another encoding.")
    low = text.lower()
    if "<!doctype" in low or "<!entity" in low:
        raise UnsafeXml("The XML has a DOCTYPE or an ENTITY.")
    return text


def _name(raw: str) -> str:
    """expat's "namespace}tag" as ElementTree's "{namespace}tag"."""
    return "{" + raw if "}" in raw else raw


def make_parser(builder: ET.TreeBuilder) -> expat.XMLParserType:
    """Layer (b): an expat parser feeding `builder`, with every DTD handler raising."""
    parser = expat.ParserCreate(encoding="utf-8", namespace_separator="}")
    parser.buffer_text = True
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    count = [0]

    def start(tag: str, attrs: dict[str, str]) -> None:
        count[0] += 1
        if count[0] > MAX_ELEMENTS:
            raise UnsafeXml("The XML is too large.")
        builder.start(_name(tag), {_name(k): v for k, v in attrs.items()})

    parser.StartElementHandler = start
    parser.EndElementHandler = lambda tag: builder.end(_name(tag))
    parser.CharacterDataHandler = builder.data
    parser.StartDoctypeDeclHandler = _refuse
    parser.EntityDeclHandler = _refuse
    parser.UnparsedEntityDeclHandler = _refuse
    parser.ExternalEntityRefHandler = _refuse
    parser.NotationDeclHandler = _refuse
    return parser


def expat_tree(text: str) -> ET.Element:
    """Layer (b) alone: the element tree of `text`, refusing any DTD, or UnsafeXml."""
    builder = Builder()
    try:
        make_parser(builder).Parse(text, True)
    except expat.ExpatError as exc:
        raise UnsafeXml("The XML is broken.") from exc
    return builder.close()


def parse_xml(raw: bytes, *, limit: int) -> ET.Element:
    return expat_tree(_text_of(raw, limit))


__all__ = ["MAX_ELEMENTS", "Builder", "UnsafeXml", "expat_tree", "make_parser", "parse_xml"]

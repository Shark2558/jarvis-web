# src/jarvis/voice/speakable.py
"""What may be read aloud (slice 9 D6; Layer 8, Response & Output). The server's authority: the
console splits a reply into chunks, but every chunk passes through here before a voice reads it.

Strips markdown (headings, emphasis, quotes, list markers, rules, HTML tags), fenced code (never
spoken; an unclosed fence hides the rest), tables, long inline code, URLs ("the link on screen"),
emoji and control / bidi / zero-width characters; collapses whitespace; caps the result at
`MAX_SPEAK_CHARS` at a sentence end, else at a word (with "…"). Nothing left with a letter or a
digit → "" (the caller answers `nothing_to_say`). Pure and deterministic: no I/O, no logging.
"""

from __future__ import annotations

import re
import unicodedata

MAX_SPEAK_CHARS = 600
LINK_WORDS = "the link on screen"
CODE_WORDS = "the code on screen"
INLINE_CODE_MAX = 30  # longer inline code is not read out character by character

_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?^[ \t]*\1[ \t]*$", re.S | re.M)
_OPEN_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,}).*\Z", re.S | re.M)
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_QUOTE = re.compile(r"^\s*(>\s?)+")
_ITEM = re.compile(r"^\s*(?:[-*+•]|\d{1,3}[.)])\s+")

_INLINE_CODE = re.compile(r"`+([^`\n]*)`+")
_IMAGE = re.compile(r"!\[([^\]\n]*)\]\([^)\n]*\)")
_LINK = re.compile(r"\[([^\]\n]+)\]\([^)\n]*\)")
_AUTOLINK = re.compile(r"<(?:https?://|www\.)[^>\s]+>", re.I)
_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>()\[\]{}\"']+", re.I)
_URL_TAIL = ".,;:!?'\""
_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>")
_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_ITALIC_STAR = re.compile(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])")
_ITALIC_UNDER = re.compile(r"(?<!\w)_(?=\S)(.+?)(?<=\S)_(?!\w)")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_STRAY = re.compile(r"[*`|~]+|(?<!\w)#+(?=\s|$)")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,!?;:…])")
_REPEAT_PUNCT = re.compile(r"([.!?])(?:\s+[.!?,;:])+")
_SPACES = re.compile(r"\s+")
_HAS_WORD = re.compile(r"\w")

_ENDS = ".!?:;,…"
_SENTENCE_END = re.compile(r"[.!?…](?=\s)")
_EMOJI_EXTRA = frozenset({0xFE0E, 0xFE0F, 0x20E3})  # variation selectors, keycap
_EMOJI_SKIN = range(0x1F3FB, 0x1F400)
_SYMBOLS_FROM = 0x2190  # "So" symbols from here on are pictographs/dingbats; ° © ® ™ stay


def _clean_chars(text: str) -> str:
    """Control chars → space; format (bidi, zero-width), private-use, unassigned and emoji →
    gone. Line/paragraph separators become newlines."""
    out: list[str] = []
    for ch in text:
        cp = ord(ch)
        cat = unicodedata.category(ch)
        if ch in "\n\t":
            out.append(ch)
        elif cat in ("Zl", "Zp"):
            out.append("\n")
        elif cat == "Cc":
            out.append(" ")
        elif cat in ("Cf", "Co", "Cs", "Cn"):
            continue
        elif cp in _EMOJI_EXTRA or cp in _EMOJI_SKIN or (cat == "So" and cp >= _SYMBOLS_FROM):
            continue
        else:
            out.append(ch)
    return "".join(out)


def _inline_code(m: re.Match[str]) -> str:
    body = m.group(1).strip()
    return body if len(body) <= INLINE_CODE_MAX else CODE_WORDS


def _url(m: re.Match[str]) -> str:
    raw = m.group(0)
    tail = len(raw) - len(raw.rstrip(_URL_TAIL))
    return LINK_WORDS + (raw[-tail:] if tail else "")


def _inline(text: str) -> str:
    text = _INLINE_CODE.sub(_inline_code, text)
    text = _IMAGE.sub(lambda m: m.group(1), text)
    text = _LINK.sub(lambda m: m.group(1), text)
    text = _AUTOLINK.sub(LINK_WORDS, text)
    text = _URL.sub(_url, text)
    text = _TAG.sub(" ", text)
    for rx in (_BOLD, _STRIKE):
        text = rx.sub(lambda m: m.group(2) if m.lastindex == 2 else m.group(1), text)
    text = _ITALIC_STAR.sub(lambda m: m.group(1), text)
    text = _ITALIC_UNDER.sub(lambda m: m.group(1), text)
    text = _STRAY.sub(" ", text)
    text = _SPACES.sub(" ", text).strip()
    text = _REPEAT_PUNCT.sub(r"\1", text)  # "Done. ." left by a removed emoji; "..." stays
    return _SPACE_BEFORE_PUNCT.sub(r"\1", text)


def _segments(text: str) -> list[str]:
    """Headings, list items and paragraphs (soft-wrapped lines joined), in order; tables and
    horizontal rules dropped."""
    segs: list[str] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            segs.append(" ".join(para))
            para.clear()

    for line in text.split("\n"):
        if not line.strip() or _RULE.match(line):
            flush()
            continue
        if _TABLE_ROW.match(line) or _TABLE_RULE.match(line):
            flush()
            continue
        if h := _HEADING.match(line):
            flush()
            segs.append(h.group(1))
            continue
        line = _QUOTE.sub("", line)
        if _ITEM.match(line):
            flush()
            segs.append(_ITEM.sub("", line, count=1))
            continue
        para.append(line.strip())
    flush()
    return segs


def _cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    best = 0
    for m in _SENTENCE_END.finditer(text[: limit + 1]):  # +1: the lookahead may see text[limit]
        if m.end() <= limit:
            best = m.end()
    if best >= limit // 3:
        return text[:best].strip()
    window = text[: limit - 1]
    cut = window.rfind(" ")
    if cut <= 0:
        return window + "…"
    return window[:cut].rstrip(" ,;:-–—") + "…"


def speakable(text: str, *, max_chars: int = MAX_SPEAK_CHARS) -> str:
    """Plain words for a voice to read; "" when nothing in `text` is worth saying."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _FENCE.sub("\n", text)
    text = _OPEN_FENCE.sub("", text)
    text = _clean_chars(text)
    segs = [s for s in (_inline(x) for x in _segments(text)) if _HAS_WORD.search(s)]
    if not segs:
        return ""
    if len(segs) > 1:
        segs = [s if s[-1] in _ENDS else s + "." for s in segs]
    return _cap(" ".join(segs), max_chars)


__all__ = ["CODE_WORDS", "LINK_WORDS", "MAX_SPEAK_CHARS", "speakable"]

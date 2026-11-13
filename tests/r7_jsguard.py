# tests/r7_jsguard.py -- R7 Part B (D13, security review M2): the static guard for a use case.
# It FAILS CLOSED: the source is cut into tokens by a small lexer (comments, strings, template
# literals with their `${...}` parts, regular expressions, numbers, names, punctuation) and then
#   - text it cannot read is refused (an unterminated string, template or comment; a character
#     that is not ASCII outside a string; a backslash outside a string, i.e. an escaped name);
#   - a computed member access `a[k]` is refused unless k is ONE plain string or number literal
#     (and a string key is checked against the banned names like a dotted name);
#   - every banned name is refused wherever it appears, however it is reached (the plan's D13 list,
#     the ways to pixels, bytes, the global object, dynamic code and the camera);
#   - `JarvisVision` may only be followed by `.use`; the engine's and the camera's own members
#     (`register`, `run`, `stream`, `start`, `frame` ...) are refused as members;
#   - `import` is refused except the one allowed form; `export` is refused.
# No new dependency: a JavaScript parser would be a runtime or dev dependency this repo does not
# carry, and a conservative lexer that says "no" to what it cannot read is the stricter choice.
from __future__ import annotations

import re
from dataclasses import dataclass

# ---- the plan's D13 list (labels are what a failing test prints) ---------------------------------
D13_APIS: tuple[str, ...] = (
    *("drawImage", "getImageData", "toBlob", "createImageBitmap", "captureStream"),
    *("fetch", "XMLHttpRequest", "sendBeacon", "WebSocket", "JarvisConsole.api", "JarvisChat"),
    *("import(", "localStorage", "sessionStorage", "indexedDB", "caches"),
)
# the ways around it: another route to pixels, bytes, the global object, dynamic code, the camera
AROUND: tuple[str, ...] = (
    *("toDataURL", "convertToBlob", "transferToImageBitmap", "readPixels", "texImage2D"),
    *("texSubImage2D", "ImageCapture", "VideoFrame", "MediaStreamTrackProcessor"),
    *("OffscreenCanvas", "Image", "Audio", "Request", "BroadcastChannel", "MessageChannel"),
    *("WebTransport", "Worker", "SharedWorker", "ServiceWorker", "EventSource"),
    *("srcObject", "JarvisCamera", "JarvisAttach", "JarvisMobile", "parts.send", "postMessage"),
    *("eval", "Function", "Reflect", "Proxy", "globalThis", "self", "window", "top", "parent"),
    *("frames", "opener", "this[", "document.cookie", "navigator.", "open(", "export", "with"),
    *("constructor", "__proto__", "prototype", "getPrototypeOf", "setPrototypeOf"),
    *("getOwnPropertyDescriptor", "getOwnPropertyDescriptors", "mediaDevices"),
    *("getUserMedia", "getDisplayMedia", "innerHTML", "outerHTML", "insertAdjacentHTML"),
    *("srcdoc", "defaultView", "contentWindow", "contentDocument", "ownerDocument"),
)
# the engine and the camera are not a use case's to call: only `JarvisVision.use` is its API
MEMBER_BANS: tuple[str, ...] = (
    *("register", "run", "stream"),  # JarvisVision's other members (v7.0.2: sealed, driver is R8's)
    *("locked", "live", "lock", "unlock", "start", "stop", "frame", "photo"),  # JarvisCamera's
    *("onChange", "facing", "useFacing", "phrases"),
)
LABELS = {  # a banned name is reported as the plan words it
    "JarvisConsole": "JarvisConsole.api",
    "navigator": "navigator.",
    "cookie": "document.cookie",
}
IDENT_BANS = frozenset(
    {*(a for a in (*D13_APIS, *AROUND) if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", a)), *LABELS}
) - {"import", "open"}
ALLOWED_IMPORT = ["import", "{", "use", "}", "from", "./console-vision.js"]
# a word after which `[` or `/` starts a value, not an access or a division
VALUE_WORDS = frozenset(
    "return typeof in of case else yield await new void delete throw do instanceof const let var "
    "export default extends".split()
)
PUNCT3 = ("...", "?.")


class Unreadable(ValueError):
    """The source cannot be lexed: the guard refuses it."""


@dataclass(frozen=True)
class Tok:
    kind: str  # name | num | str | tmpl | re | p
    text: str  # a string's inner text (raw), a name, a number or the punctuation
    escaped: bool = False


def _skip_blank(src: str, i: int) -> int:
    while i < len(src):
        if src[i].isspace():
            i += 1
        elif src.startswith("//", i):
            i = src.find("\n", i)
            i = len(src) if i < 0 else i
        elif src.startswith("/*", i):
            end = src.find("*/", i + 2)
            if end < 0:
                raise Unreadable("a comment that never closes")
            i = end + 2
        else:
            break
    return i


def _string(src: str, i: int) -> tuple[Tok, int]:
    quote, j, escaped = src[i], i + 1, False
    while j < len(src) and src[j] != quote:
        if src[j] == "\n":
            raise Unreadable("a string that never closes")
        if src[j] == "\\":
            escaped, j = True, j + 1
        j += 1
    if j >= len(src):
        raise Unreadable("a string that never closes")
    return Tok("str", src[i + 1 : j], escaped), j + 1


def _template(src: str, i: int) -> tuple[list[Tok], int]:
    """A template literal: one `tmpl` token, then the tokens of each `${...}` inside it."""
    j, inner = i + 1, []
    while j < len(src) and src[j] != "`":
        if src[j] == "\\":
            j += 2
        elif src.startswith("${", j):
            sub, j = _lex(src, j + 2, in_template=True)
            inner.extend(sub)
        else:
            j += 1
    if j >= len(src):
        raise Unreadable("a template that never closes")
    return [Tok("tmpl", ""), *inner], j + 1


def _regex(src: str, i: int) -> tuple[Tok, int]:
    j, in_class = i + 1, False
    while j < len(src):
        c = src[j]
        if c == "\n":
            break
        if c == "\\":
            j += 1
        elif c == "[":
            in_class = True
        elif c == "]":
            in_class = False
        elif c == "/" and not in_class:
            j += 1
            while j < len(src) and (src[j].isalpha()):
                j += 1
            return Tok("re", ""), j
        j += 1
    raise Unreadable("a regular expression that never closes")


def _starts_value(prev: Tok | None) -> bool:
    if prev is None:
        return True
    if prev.kind == "name":
        return prev.text in VALUE_WORDS
    return prev.kind == "p" and prev.text not in (")", "]", "}")


def _lex(src: str, i: int, in_template: bool = False) -> tuple[list[Tok], int]:
    out: list[Tok] = []
    depth = 0
    while True:
        i = _skip_blank(src, i)
        if i >= len(src):
            if in_template:
                raise Unreadable("a template substitution that never closes")
            return out, i
        c = src[i]
        prev = out[-1] if out else None
        if c in "'\"":
            tok, i = _string(src, i)
            out.append(tok)
        elif c == "`":
            toks, i = _template(src, i)
            out.extend(toks)
        elif re.match(r"[A-Za-z_$#]", c):
            m = re.compile(r"#?[A-Za-z_$][A-Za-z0-9_$]*").match(src, i)
            if m is None:
                raise Unreadable("a stray #")
            out.append(Tok("name", m.group()))
            i = m.end()
        elif c.isdigit() or (c == "." and src[i + 1 : i + 2].isdigit()):
            m = re.compile(r"\.?\d[A-Za-z0-9_.]*").match(src, i)
            assert m is not None
            out.append(Tok("num", m.group()))
            i = m.end()
        elif c == "/" and _starts_value(prev):
            tok, i = _regex(src, i)
            out.append(tok)
        elif c == "\\" or ord(c) > 126:
            raise Unreadable("a backslash or a non-ASCII character outside a string")
        else:
            if c == "{":
                depth += 1
            elif c == "}":
                if in_template and depth == 0:
                    return out, i + 1
                depth -= 1
            two = src[i : i + 3] if src.startswith("...", i) else src[i : i + 2]
            if two in PUNCT3 and not (two == "?." and src[i + 2 : i + 3].isdigit()):
                out.append(Tok("p", two))
                i += len(two)
            else:
                out.append(Tok("p", c))
                i += 1


def tokens(src: str) -> list[Tok]:
    """The tokens of `src`; raises Unreadable for text the guard cannot read."""
    out, _ = _lex(src, 0)
    return out


def _is_access(prev: Tok | None) -> bool:
    """A `[` here opens a computed member access (not an array literal or a pattern)."""
    if prev is None:
        return False
    if prev.kind == "name":
        return prev.text not in VALUE_WORDS
    return prev.kind in ("num", "str", "tmpl", "re") or prev.text in (")", "]", "}", "?.")


def _close(toks: list[Tok], at: int) -> int:
    depth = 0
    for j in range(at, len(toks)):
        if toks[j].kind == "p" and toks[j].text == "[":
            depth += 1
        elif toks[j].kind == "p" and toks[j].text == "]":
            depth -= 1
            if depth == 0:
                return j
    raise Unreadable("a bracket that never closes")


def _bracket_problems(toks: list[Tok], i: int) -> list[str]:
    end = _close(toks, i)
    inner = toks[i + 1 : end]
    prev = toks[i - 1] if i else None
    after = toks[end + 1] if end + 1 < len(toks) else None
    literal = len(inner) == 1 and (
        inner[0].kind == "num" or (inner[0].kind == "str" and not inner[0].escaped)
    )
    if prev is not None and prev.kind == "name" and prev.text == "this":
        return ["this["]
    keyed = prev is not None and prev.text in ("{", ",") and after is not None
    keyed = keyed and after.kind == "p" and after.text in (":", "(")
    if (_is_access(prev) or keyed) and not literal:
        return ["computed member access"]
    if literal and inner[0].kind == "str":
        return _name_problems(inner[0].text, member=True)
    return []


def _name_problems(name: str, member: bool) -> list[str]:
    found = []
    if name in IDENT_BANS:
        found.append(LABELS.get(name, name))
    if member and name in MEMBER_BANS:
        found.append(name)
    return found


def _import_problems(toks: list[Tok], i: int) -> list[str]:
    nxt = toks[i + 1] if i + 1 < len(toks) else None
    if nxt is not None and nxt.text == "(":
        return ["import("]
    shape = [t.text for t in toks[i : i + 6]]
    return [] if shape == ALLOWED_IMPORT else ["import"]


def problems_of(toks: list[Tok]) -> list[str]:
    found: list[str] = []
    for i, tok in enumerate(toks):
        prev = toks[i - 1] if i else None
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        member = prev is not None and prev.kind == "p" and prev.text in (".", "?.")
        if tok.kind == "p" and tok.text == "[":
            found += _bracket_problems(toks, i)
        elif tok.kind == "name" and tok.text == "import":
            found += _import_problems(toks, i)
        elif tok.kind == "name" and tok.text == "open" and nxt is not None and nxt.text == "(":
            found.append("open(")
        elif tok.kind == "name" and tok.text == "parts" and nxt is not None:
            after = toks[i + 2] if i + 2 < len(toks) else None
            if nxt.text in (".", "?.") and after is not None and after.text == "send":
                found.append("parts.send")
        elif tok.kind == "name" and tok.text in ("setTimeout", "setInterval"):
            first = toks[i + 2] if i + 2 < len(toks) else None
            if nxt is not None and nxt.text == "(" and first is not None:
                if first.kind in ("str", "tmpl"):
                    found.append(f"{tok.text}(string)")
        elif tok.kind == "name" and tok.text == "JarvisVision":
            dot = nxt is not None and nxt.text in (".", "?.")
            after = toks[i + 2] if i + 2 < len(toks) else None
            if not (dot and after is not None and after.text == "use"):
                found.append("JarvisVision (only JarvisVision.use is a use case's)")
        if tok.kind == "name":
            found += _name_problems(tok.text, member)
    return found


def use_case_problems(source: str) -> list[str]:
    """What a use case's source does that D13 forbids; `["unreadable: ..."]` for text the guard
    cannot read (it fails closed). Empty only when every token passed."""
    try:
        found = problems_of(tokens(source))
    except Unreadable as exc:
        return [f"unreadable: {exc}"]
    return list(dict.fromkeys(found))

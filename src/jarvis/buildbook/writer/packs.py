# src/jarvis/buildbook/writer/packs.py
"""R6.3 D4 (plan review M8, L7, H5): one reading pack a page, from the release's `source.zip` and
`facts.json` only (both public, both in the image). Nothing from Firestore, the vault, memory,
mail, contacts, photos, cameras, Book settings or logs: this module is handed the zip's text and
the fact pack, and imports nothing that could reach more (the static guards).

A pack holds the page's catalogue card(s), the docstrings, signatures, constants and route
decorators of the files it cites (never a whole file), the matching plan sections (by C-id or
path, newest first), and its slice of the fact pack with the references the page may cite. It is
capped at `PACK_CAP_BYTES` UTF-8 bytes with the prompt's own words (`PROMPT_RESERVE`): plan text
goes first, then signatures, never the card. Never read: `.claude/**`, `tests/**`, `evals/**`,
`.env*` / `*.env` / `*.env.*`, key-shaped files, `gen/fake_secrets.txt`, `gen/redact.json`,
`*.lock`, binaries. Every block goes through the scrubber and is fenced as data
(`buildbook.prompt.fence`); the same pack goes to every brain. A member's path is the repository's:
R6's snapshot root `JARVIS-source-<id>/` is taken off first (`member_name`, review I1 H-1), and a
`.claude` folder is never read at any depth.
"""

from __future__ import annotations

import ast
import io
import re
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from jarvis.buildbook.facts_model import FactPack, IndexedPage
from jarvis.buildbook.gen.scrub import Scrubber
from jarvis.buildbook.prompt import fence
from jarvis.buildbook.writer import fill
from jarvis.buildbook.writer.model import PACK_CAP_BYTES

GUIDE = "docs/architecture/JARVIS-Architecture.md"
PLANS = "docs/plans/"
PROMPT_RESERVE = 2_000  # the marker line and the page's instructions (prompts.first)
NEVER_DIRS = (".claude/", "tests/", "evals/")
NEVER_FILES = ("gen/fake_secrets.txt", "gen/redact.json")
KEY_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".der", ".crt", ".gpg")
KEY_NAMES = ("id_rsa", "id_ed25519", "id_ecdsa", "credentials.json", "service-account.json")
BINARY = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".gz", ".zip", ".woff", ".woff2",
          ".ttf", ".pdf", ".wasm", ".bin", ".onnx", ".jar", ".so", ".pyc")  # fmt: skip
MEMBER_CAP = 2_000_000  # a member over this is never read whole into a pack
TRIM_MIN = 200  # a trimmed block shorter than this is left out
HEAD_LINES, FUNC_LINES, PLAN_SECTIONS = 30, 40, 6
_CARD = re.compile(r"^#### (C\d{2}) · .*?(?=^#{2,4} |\Z)", re.M | re.S)
_PLAN_HEAD = re.compile(r"^## ", re.M)
_COMMENT = re.compile(r"^\s*(?://|#|/\*|\*|<!--)")
_FUNC = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+\w+\s*\(|^\s*fun\s+\w+\s*\(")
_UPPER = re.compile(r"^[A-Z][A-Z0-9_]*$")
_ROOT = re.compile(r"^JARVIS-source-[^/]+/")  # R6's snapshot root (gen/snapshot.py `_zip`)
_WORD = re.compile(r"\w+")  # a run of word characters (`_mentioned`)


@dataclass(frozen=True)
class Pack:
    page_id: str
    body: str  # the fenced blocks, scrubbed
    allowed: tuple[str, ...]  # the references the page may cite (H5)


def member_name(name: str) -> str:
    """A `source.zip` member's repository path: R6's root folder `JARVIS-source-<id>/` taken off
    (a member without it is kept as it is)."""
    return _ROOT.sub("", name, count=1)


def readable(path: str) -> bool:
    """May a pack read this tracked file at all (D4, M8, L7)?"""
    name = path.rsplit("/", 1)[-1].lower()
    low = path.lower()
    if low.startswith(NEVER_DIRS) or ".claude" in low.split("/")[:-1]:
        return False
    if any(low.endswith(f) for f in NEVER_FILES):
        return False
    if name.startswith(".env") or name.endswith(".env") or ".env." in name:
        return False
    if name.endswith(".lock") or name.endswith(KEY_SUFFIXES) or name.startswith(KEY_NAMES):
        return False
    return not name.endswith(BINARY)


def read_source(zipped: bytes) -> dict[str, str]:
    """The readable text files of a release's `source.zip` (UTF-8, no NUL byte)."""
    out: dict[str, str] = {}
    with zipfile.ZipFile(io.BytesIO(zipped)) as zf:
        for info in zf.infolist():
            name = member_name(info.filename)
            if info.is_dir() or not readable(name) or info.file_size > MEMBER_CAP:
                continue
            raw = zf.read(info)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if "\x00" not in text:
                out[name] = text
    return out


# ---- what a pack quotes --------------------------------------------------------------------------
def cards(guide: str, ids: Sequence[str]) -> dict[str, str]:
    found = {m.group(1): m.group(0).strip() for m in _CARD.finditer(guide)}
    return {cid: found[cid] for cid in ids if cid in found}


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    lines = [f"@{ast.unparse(d)}" for d in node.decorator_list]
    head = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    ret = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
    lines.append(f"{head} {node.name}({ast.unparse(node.args)}){ret}")
    doc = ast.get_docstring(node)
    return lines + ([f'    """{doc.split(chr(10) + chr(10))[0]}"""'] if doc else [])


def _py_lines(node: ast.stmt) -> list[str]:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return _signature(node)
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        doc = ast.get_docstring(node)
        out = [f"class {node.name}({bases})"] + ([f'    """{doc}"""'] if doc else [])
        methods = [n for n in node.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
        return out + [f"    {line}" for m in methods for line in _signature(m)]
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        if isinstance(target, ast.Name) and _UPPER.match(target.id):
            value = ast.unparse(node.value)
            return [f"{target.id} = {value}"] if len(value) <= 120 else []
    return []


def summary(path: str, text: str) -> str:
    """What a pack quotes of one cited file: never the whole file (D4)."""
    if path.endswith(".py"):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return "\n".join(text.splitlines()[:HEAD_LINES])
        doc = ast.get_docstring(tree)
        lines = [doc] if doc else []
        return "\n".join(lines + [line for node in tree.body for line in _py_lines(node)])
    rows = text.splitlines()
    head = [r for r in rows[:HEAD_LINES] if _COMMENT.match(r)]
    funcs = [r.strip() for r in rows if _FUNC.match(r)][:FUNC_LINES]
    return "\n".join(head + funcs) if head or funcs else "\n".join(rows[:HEAD_LINES])


def plan_sections(tree: Mapping[str, str], marks: Sequence[str]) -> list[tuple[str, str]]:
    """Plan sections naming a C-id or a path of the page, newest plan first (by path)."""
    found: list[tuple[str, str]] = []
    if not marks:
        return found
    alts = "|".join(re.escape(m) for m in marks)
    named = re.compile(rf"(?<![\w/.])(?:{alts})(?![\w])")  # one pattern: any mark (review M-4)
    for path in sorted(
        (p for p in tree if p.startswith(PLANS) and p.endswith(".md")), reverse=True
    ):
        text = tree[path]
        cuts = [m.start() for m in _PLAN_HEAD.finditer(text)] + [len(text)]
        for n, (a, b) in enumerate(zip(cuts, cuts[1:], strict=False)):
            part = text[a:b]
            if named.search(part):
                found.append((f"plan:{path}#{n}", part.strip()))
            if len(found) >= PLAN_SECTIONS:
                return found
    return found


# ---- the page's slice of the fact pack, and what it may cite (H5) --------------------------------
COMMON_KEYS = ("cards.count", "modules.count", "services.count")


def _mentioned(names: Sequence[str], texts: Sequence[str]) -> list[str]:
    """The names standing alone in the texts (no word character either side). The texts' word
    runs are read once; a name that is one word is looked up there, any other by its regex."""
    joined = "\n".join(texts)
    words = set(_WORD.findall(joined))

    def alone(n: str) -> bool:
        if _WORD.fullmatch(n):
            return n in words
        return re.search(rf"(?<![\w]){re.escape(n)}(?![\w])", joined) is not None

    return [n for n in names if alone(n)]


def fact_lines(page: IndexedPage, facts: FactPack, cited: Sequence[str]) -> list[str]:
    settings = _mentioned([s.name for s in facts.settings], cited)
    keys = sorted(
        k
        for k in facts.values
        if k.startswith("release.")
        or k in COMMON_KEYS
        or any(k.startswith(f"{ref}:") for ref in page.refs)
        or k in {f"settings.{s}" for s in settings}
    )
    out = []
    for k in keys:
        v = facts.values[k]
        note = " (Unverified: a sentence using it says so)" if not v.verified else ""
        out.append(f"{k} = {fill.show(v.value)}{note}")
    return out


def allowed(page: IndexedPage, facts: FactPack, cited: Sequence[str]) -> tuple[str, ...]:
    ix = facts.index
    own = tuple(page.refs)
    named = [n for n in (*ix.symbols, *ix.constants) if n.split(":", 1)[0] in own]
    routes = [f"{r.method} {r.path}" for r in facts.routes if r.module in own]
    extra = _mentioned(ix.settings, cited) + _mentioned(ix.collections, cited)
    return tuple(dict.fromkeys((*own, *named, *routes, *extra)))


# ---- assembly under the cap --------------------------------------------------------------------
Block = tuple[str, str]


def _size(block: Block) -> int:
    return len(fence(*block).encode("utf-8"))


def _trim(block: Block, room: int) -> Block | None:
    """The block cut at a line so its fenced form fits `room` bytes (None: too little room)."""
    over = _size((block[0], "")) + 1
    keep = room - over
    if keep < TRIM_MIN:
        return None
    raw = block[1].encode("utf-8")[:keep].decode("utf-8", "ignore")
    cut = raw.rsplit("\n", 1)[0] if "\n" in raw else raw
    return (block[0], cut) if cut.strip() else None


def fit(fixed: list[Block], optional: list[Block], budget: int) -> list[Block]:
    """The fixed blocks, then the optional ones in order while they fit (the last one trimmed)."""
    out, used = list(fixed), sum(_size(b) for b in fixed)
    for block in optional:
        size = _size(block)
        if used + size <= budget:
            out.append(block)
            used += size
            continue
        cut = _trim(block, budget - used)
        if cut is not None:
            out.append(cut)
        break
    return out


def _clean(scrub: Scrubber, text: str, cache: dict[str, str] | None) -> str:
    if cache is None:
        return scrub.clean(text)
    if text not in cache:
        cache[text] = scrub.clean(text)
    return cache[text]


def build(
    page: IndexedPage,
    facts: FactPack,
    tree: Mapping[str, str],
    scrub: Scrubber,
    *,
    reserve: int = PROMPT_RESERVE,
    cache: dict[str, str] | None = None,
) -> Pack:
    """One page's pack (D4): scrubbed, fenced, at most the cap with the prompt's own words
    (`reserve` bytes: the marker line and the page's instructions). `cache` (text -> scrubbed
    text, one release's) scrubs a block that many pages quote once (review M-4)."""
    cited = [summary(ref, tree[ref]) for ref in page.refs if ref in tree]
    sigs = [(f"code:{ref}", summary(ref, tree[ref])) for ref in page.refs if ref in tree]
    cids = [s for s in page.sources if re.fullmatch(r"C\d{2}", s)]
    card = [(f"card:{c}", t) for c, t in cards(tree.get(GUIDE, ""), cids).items()]
    may = allowed(page, facts, cited)
    head = f"Page {page.id}: {page.title} ({page.kind}, part {page.part})"
    fixed: list[Block] = [
        ("page", head),
        *card,
        ("facts", "\n".join(fact_lines(page, facts, cited)) or "(none)"),
        ("may_cite", "\n".join(may)),
    ]
    plans = plan_sections(tree, (*cids, *page.refs))
    clean = [[(i, _clean(scrub, t, cache)) for i, t in group] for group in (fixed, sigs, plans)]
    blocks = fit(clean[0], clean[1] + clean[2], PACK_CAP_BYTES - reserve)
    return Pack(page_id=page.id, body="".join(fence(*b) for b in blocks), allowed=may)


__all__ = [
    "GUIDE",
    "PROMPT_RESERVE",
    "Pack",
    "allowed",
    "build",
    "cards",
    "fact_lines",
    "fit",
    "member_name",
    "plan_sections",
    "read_source",
    "readable",
    "summary",
]

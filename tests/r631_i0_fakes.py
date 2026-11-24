# tests/r631_i0_fakes.py -- R6.3.1 I0's fakes (docs/plans/r6-3-1-book-at-build.md D1-D6). Imported
# bare (`from r631_i0_fakes import ...`). Self-contained on purpose: nothing from the runtime
# writer's fakes (r63_fakes*, r63_fake_brains), which builder E removes with the writer (D8).
#
#   FILES / make_repo(tmp)     a tiny committed git repository: a demo router and store, a setting,
#                              an Android file whose folder the scrubber would remove
#   PACK                       its fact pack: six indexed pages (a chapter, a module, two cards,
#                              a screen citing the scrubbed Android path, a service)
#   GOOD_BODY                  five sections that pass the six checks against PACK
#   page_text(...) / write_page / write_flow / GOOD_FLOW    authored files as writers write them
#   seed_cache(repo, pack)     PACK stored where `pages` looks first, so no real build runs
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from book_gen_fakes import commit_all

from jarvis.buildbook.facts_model import (
    FactIndex,
    FactPack,
    FactValue,
    IndexedPage,
    Setting,
    canonical_facts,
)
from jarvis.buildbook.model import ReleaseRef

BOOK = "src/jarvis/buildbook/book"
ROUTER, STORE = "src/jarvis/demo/router.py", "src/jarvis/demo/store.py"
ANDROID_RAW = "android/app/src/main/java/io/github/someone/jarvis/Main.kt"
ANDROID = "android/app/src/main/java/io/github/[removed]/jarvis/Main.kt"
FILES: dict[str, str] = {
    "src/jarvis/__init__.py": '__version__ = "6.3.2"\n',
    "src/jarvis/demo/__init__.py": '"""The demo."""\n',
    ROUTER: (
        '"""The demo router: one tier a request."""\n\nMAX_TRIES = 3\n\n\n'
        'def pick(asked: str) -> str:\n    """The tier for `asked`."""\n    return "balanced"\n'
    ),
    STORE: '"""The demo store."""\n\nKEEP_DAYS = 30\n',
    "src/jarvis/config.py": (
        "from pydantic import Field\n\n\nclass Settings:\n"
        "    demo_limit: int = Field(default=5, ge=1, le=10)\n"
    ),
    ANDROID_RAW: "class Main\n",
    "README.md": "# Demo\n",
}
SHA = "31" * 20
RELEASE = ReleaseRef(
    id=SHA[:7], sha=SHA, label="R6.3", committed_at="2026-11-24T09:00:00+05:30", version="v6.3.2"
)


def _v(value: Any, source: str, *, verified: bool = True) -> FactValue:
    return FactValue(value=value, source=source, verified=verified)


def _page(pid: str, kind: str, title: str, part: str, refs: tuple[str, ...], **kw: Any) -> Any:
    return IndexedPage.model_validate(
        {"id": pid, "kind": kind, "title": title, "part": part, "refs": refs, **kw}
    )


PAGES = (
    _page("pg_chapter_example", "chapter", "The running example", "plain", (ROUTER, STORE)),
    _page("pg_module_demo", "module", "The demo", "modules", (ROUTER, STORE), sources=("C01",)),
    _page("pg_card_c01", "card", "Demo router", "parts", (ROUTER,), chapter="demo",
          sources=("C01",)),
    _page("pg_card_c02", "card", "Demo store", "parts", (STORE,), chapter="demo",
          sources=("C02",)),
    _page("pg_screen_phone", "screen", "The phone", "screens", (ANDROID,)),
    _page("pg_service_anthropic", "service", "Anthropic", "services", (ROUTER,),
          sources=("C01",)),
)  # fmt: skip
PACK = FactPack(
    release=RELEASE,
    values={
        "cards.count": _v(2, "docs/architecture/JARVIS-Architecture.md"),
        f"{ROUTER}:MAX_TRIES": _v(3, f"{ROUTER}:MAX_TRIES"),
        f"{STORE}:KEEP_DAYS": _v(30, f"{STORE}:KEEP_DAYS"),
        "settings.demo_limit": _v(5, "src/jarvis/config.py:demo_limit"),
        "hosting.region": _v("asia-south1", "deploy/cloudrun.sh", verified=False),
        "release.label": _v("R6.3", "src/jarvis/__init__.py"),
    },
    index=FactIndex(
        paths=tuple(sorted({*FILES, ANDROID} - {ANDROID_RAW})),
        symbols=(f"{ROUTER}:pick",),
        constants=(f"{ROUTER}:MAX_TRIES", f"{STORE}:KEEP_DAYS"),
        settings=("demo_limit",),
        collections=("demo_notes",),
        routes=("GET /v1/demo",),
    ),
    settings=(Setting(name="demo_limit", kind="int", default=5, ge=1, le=10),),
    pages=PAGES,
)


def draft(plain: str, example: str, how: str, costs: str, fails: str) -> str:
    return (
        f"## In plain words\n{plain}\n\n## Example (made up)\n{example}\n\n"
        f"## How it works\n{how}\n\n## What it costs\n{costs}\n\n## When it fails\n{fails}\n"
    )


GOOD_BODY = draft(
    "The demo router picks one model for each request.",
    "Asha asks for the weather twice; the router picks the same tier both times.",
    f"The router (`{ROUTER}`) asks `pick` for a tier and tries at most "
    f"{{{{fact:{ROUTER}:MAX_TRIES}}}} times. The limit is the setting "
    "`demo_limit` ({{fact:settings.demo_limit}} by default).",
    "Nothing: it runs inside the server.",
    "When every try fails it says so plainly and calls nothing else.",
)
GOOD_FLOW: dict[str, Any] = {
    "title": "The demo router",
    "dir": "down",
    "nodes": [
        {"id": "ask", "label": "A request", "kind": "person", "rank": 0, "col": 0},
        {"id": "pick", "label": "Pick a tier", "kind": "step", "rank": 1, "col": 0, "ref": ROUTER},
        {"id": "notes", "label": "The notes", "kind": "store", "rank": 2, "col": 0, "ref": STORE},
    ],
    "edges": [
        {"from": "ask", "to": "pick"},
        {"from": "pick", "to": "notes", "label": "keeps", "style": "side"},
    ],
}


def short(data: bytes | str) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()[:16]


def hashes_of(root: Path, refs: tuple[str, ...]) -> dict[str, str]:
    real = {ANDROID: ANDROID_RAW}
    return {r: short((root / real.get(r, r)).read_bytes()) for r in refs}


def page_text(
    pid: str,
    sources: dict[str, str] | None = None,
    body: str = GOOD_BODY,
    *,
    extra: str = "",
    written_by: str = "Workshop · Mark XXIV",
    written_on: str = "2026-11-24",
) -> str:
    lines = ["---", f"page: {pid}", f"written_by: {written_by}", f"written_on: {written_on}"]
    if sources is not None:
        lines.append("sources:" + ("" if sources else " {}"))
        lines += [f"  {json.dumps(k)}: {json.dumps(v)}" for k, v in sources.items()]
    if extra:
        lines.append(extra)
    return "\n".join([*lines, "---", ""]) + body


def write_page(root: Path, pid: str, text: str) -> Path:
    path = root / BOOK / "pages" / f"{pid}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_flow(root: Path, pid: str, spec: dict[str, Any] | str = GOOD_FLOW) -> Path:
    path = root / BOOK / "flows" / f"{pid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(spec if isinstance(spec, str) else json.dumps(spec), encoding="utf-8")
    return path


def make_repo(tmp: Path, name: str = "repo") -> Path:
    root = tmp / name
    for rel, text in FILES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    for folder in ("pages", "flows"):
        (root / BOOK / folder).mkdir(parents=True, exist_ok=True)
        (root / BOOK / folder / ".gitkeep").write_text("", encoding="utf-8")
    commit_all(root)
    return root


def seed_cache(root: Path, pack: FactPack = PACK) -> Path:
    """PACK where `pages` looks before building (the key of the checkout as it is now)."""
    from jarvis.buildbook.gen import facts_cache
    from jarvis.buildbook.gen.repo import Repo

    path = facts_cache.path_for(Repo.from_git(root))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_facts(pack))
    return path


__all__ = [
    "ANDROID",
    "ANDROID_RAW",
    "BOOK",
    "FILES",
    "GOOD_BODY",
    "GOOD_FLOW",
    "PACK",
    "PAGES",
    "RELEASE",
    "ROUTER",
    "STORE",
    "draft",
    "hashes_of",
    "make_repo",
    "page_text",
    "seed_cache",
    "short",
    "write_flow",
    "write_page",
]

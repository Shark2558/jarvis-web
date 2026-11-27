#!/usr/bin/env python3
# docs/plans/r8-mockups/tools/kit.py -- make each R8 mockup page self-contained: put the console's OWN stylesheets
# (copied verbatim, comments stripped, whitespace folded), its self-hosted OFL fonts (as data: URLs), tools/r8-common.css
# and tools/deck.js between the <!-- KIT:BEGIN --> and <!-- KIT:END --> lines of every page given (default: all five).
# A page with its own new pieces gets one more stylesheet after r8-common.css (PAGE_CSS: bar-edit.html -> r8-bar.css).
# Standard library only; reads the repo, writes only the pages. Usage: python3 -I tools/kit.py [page.html ...]
from __future__ import annotations

import base64
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MOCKS = HERE.parent
REPO = MOCKS.parents[2]
STATIC = REPO / "src" / "jarvis" / "api" / "static"
SHEETS = ("console.css", "console-deck.css", "console-memory.css", "console-helpers.css", "console-vitals.css", "console-camera.css")
# the faces the console draws with (Orbitron 700, Rajdhani 600/700, Share Tech Mono 400); the two it declares but
# never uses on these screens (Orbitron 600, Rajdhani 500) are left out to keep each page small
FONTS = {
    "orbitron-latin-700-normal.woff2", "rajdhani-latin-600-normal.woff2", "rajdhani-latin-700-normal.woff2",
    "share-tech-mono-latin-400-normal.woff2",
}
PAGES = ("camera-setup.html", "desk-coach.html", "workout-phone.html", "activity-timeline.html", "bar-edit.html")
PAGE_CSS = {"bar-edit.html": "r8-bar.css"}  # the R8 part I "your bar, your way" pieces, in the console's tokens only
BEGIN, END = "<!-- KIT:BEGIN", "<!-- KIT:END -->"
FACE = re.compile(r"@font-face\{[^}]*?url\(/static/fonts/([\w.-]+)\?v=\d+\)[^}]*\}")


def fold(css: str) -> str:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return re.sub(r"\s+", " ", css).strip()


def inline_fonts(css: str) -> str:
    def face(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in FONTS:
            return ""
        data = base64.b64encode((STATIC / "fonts" / name).read_bytes()).decode("ascii")
        return m.group(0).replace(f"/static/fonts/{name}?v=1", f"data:font/woff2;base64,{data}")
    return FACE.sub(face, css)


def kit(page: str) -> str:
    sha = subprocess.run(["git", "-C", str(REPO), "log", "-1", "--format=%h", "--", "src/jarvis/api/static"],
                         capture_output=True, text=True, check=False).stdout.strip() or "unknown"
    console = inline_fonts(" ".join(fold((STATIC / s).read_text(encoding="utf-8")) for s in SHEETS))
    common = (HERE / "r8-common.css").read_text(encoding="utf-8").strip()
    extra = (HERE / PAGE_CSS[page]).read_text(encoding="utf-8").strip() if page in PAGE_CSS else ""
    deck = (HERE / "deck.js").read_text(encoding="utf-8").strip()
    if "</style" in common or "</style" in extra or "</script" in deck:
        raise SystemExit("kit.py: a closing tag inside the kit sources")
    own = f", then tools/{PAGE_CSS[page]}" if page in PAGE_CSS else ""
    head = (f"{BEGIN} made by tools/kit.py: the console's own CSS ({', '.join(SHEETS)} from src/jarvis/api/static at {sha}, "
            f"comments stripped) with its OFL fonts inlined, then tools/r8-common.css{own} and tools/deck.js. "
            "Edit those files, never this block. -->")
    styles = f'<style id="kit-r8">\n{common}\n</style>\n' + (f'<style id="kit-page">\n{extra}\n</style>\n' if extra else "")
    return f'{head}\n<style id="kit-console">{console}</style>\n{styles}<script id="kit-deck">\n{deck}\n</script>\n{END}'


def main(argv: list[str]) -> int:
    for name in argv or PAGES:
        page = (MOCKS / name).resolve()
        block = kit(page.name)
        text = page.read_text(encoding="utf-8")
        a, b = text.find(BEGIN), text.find(END)
        if a < 0 or b < a:
            print(f"kit.py: no KIT markers in {page.name}", file=sys.stderr)
            return 1
        page.write_text(text[:a] + block + text[b + len(END):], encoding="utf-8")
        print(f"{page.name}: {page.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

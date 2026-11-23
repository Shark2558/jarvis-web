# scripts/arch_files.py
"""R6.1 D6, the file checks for `arch_coverage.py`: what the guide cites exists, and the folder
holds no secret or personal data.

- Every path a card's "Where in the code" names as a code span (`src/...`, `deploy/...`, a file
  name with an extension, `Dockerfile`, `Makefile`; a `*` is a glob that must match). A bare name
  is looked up next to the path cited before it, then in the console's static folder, `api/`,
  `src/jarvis/` and the repository root, so `src/jarvis/voice/` (`service.py`) and `console.js`
  both resolve. R6.3 seam 17: that rule is `jarvis.buildbook.gen.refs.resolve` (the build book's
  pages index uses the same one).
- Every `diagrams/...` file the guide links, and an `.svg` and a `.png` for every fixed diagram
  name, in the `diagrams/` folder next to the guide.
- The secret scan: the R6 build book scrubber (`jarvis.buildbook.gen.scrub`) on the `.md`,
  `.markdy`, `.svg`, `.txt` and `.json` files of a folder (file, line and kind, never the text).
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

NO_DIAGRAMS = "diagram files: no `diagrams/` folder next to the guide (Part C exports them)"
_LINK = re.compile(r"\]\((diagrams/[^)\s]+)\)")
REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:  # R6.3 seam 17: the resolver lives in the package
    sys.path.insert(0, str(REPO / "src"))
from jarvis.buildbook.gen.refs import resolve  # noqa: E402

SCAN_SUFFIXES = (".md", ".markdy", ".svg", ".txt", ".json")
_SHA256 = re.compile(r"\b[0-9a-f]{64}\b")


def cited(repo: Path, card: str, where: str) -> list[str]:
    """The paths in one card's "Where in the code" that do not exist (`gen/refs.resolve`'s rule:
    a bare name next to the path cited before it, then the static folder, `api/`, `src/jarvis/`
    and the repository root)."""
    return [
        f"card `{card}`: cited path `{span}` does not exist"
        for span, hit in resolve(repo, where)
        if hit is None
    ]


def check_cited(repo: Path, cards: Iterable[tuple[str, Mapping[str, str]]]) -> list[str]:
    return [
        p for name, fields in cards for p in cited(repo, name, fields.get("Where in the code", ""))
    ]


def check_diagram_files(text: str, folder: Path, names: Sequence[str]) -> list[str]:
    if not folder.is_dir():
        return [NO_DIAGRAMS]
    wanted = {link.removeprefix("diagrams/") for link in _LINK.findall(text)}
    wanted |= {f"{n}.{ext}" for n in names for ext in ("svg", "png")}
    return [
        f"diagram file `diagrams/{f}` is missing"
        for f in sorted(wanted)
        if not (folder / f).is_file()
    ]


def _words(path: Path, raw: str) -> str:
    """What the personal-data rules read: an SVG's drawn words only (its geometry is runs of
    digits, never personal), and no SHA-256 hashes; line breaks are kept for line numbers."""
    text = _SHA256.sub(" ", raw)
    if path.suffix != ".svg":
        return text
    return re.sub(r"<[^>]*>", lambda m: "\n" * m.group(0).count("\n") + " ", text)


def scan(folder: Path) -> list[str]:
    """Secret shapes on every line; the scrubber's personal-data rules on the readable words."""
    from jarvis.buildbook.gen.scrub import SECRET_SHAPES, default_scrubber

    scrubber, out = default_scrubber(), []
    for path in sorted(p for p in folder.rglob("*") if p.suffix in SCAN_SUFFIXES and p.is_file()):
        raw = path.read_text(encoding="utf-8")
        pairs = zip(raw.splitlines(), _words(path, raw).splitlines(), strict=False)
        for n, (line, words) in enumerate(pairs, start=1):
            kinds = set(scrubber.findings(words))
            kinds |= {"secret"} if any(p.search(line) for _, p in SECRET_SHAPES) else set()
            if kinds:
                out.append(f"secret scan: {path.name}:{n} ({', '.join(sorted(kinds))})")
    return out

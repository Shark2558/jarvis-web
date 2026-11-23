# scripts/redact_add.py
"""R6.3 M8 (docs/plans/r6-3-book-content.md D4, seam 17): add words to the build book's redact list
as SHA-256 hashes ONLY.

    python scripts/redact_add.py WORDS_FILE [--redact src/jarvis/buildbook/gen/redact.json]

WORDS_FILE (kept outside the repository, e.g. under /tmp) holds one word or name a line: the owner's
locality, workplace and employer words the Workshop relays. Each word of a line (as the scrubber
splits words) is hashed the way `gen/scrub.py` looks names up (NFKD, accents and format characters
dropped, look-alikes folded, case folded) and the hash joins `redact.json`'s `sha256` list, sorted
and unique. A word shorter than 3 letters is skipped (it would remove too much). The script prints
COUNTS only and never a word, and never writes a word anywhere: the words stay in WORDS_FILE.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))
from jarvis.buildbook.gen import scrub  # noqa: E402

REDACT = REPO / "src" / "jarvis" / "buildbook" / "gen" / "redact.json"
MIN_LETTERS = 3


def hashes_of(text: str) -> tuple[set[str], int]:
    """The hashes of every word in `text` (one name a line), and how many short words it skipped."""
    found: set[str] = set()
    skipped = 0
    for line in text.splitlines():
        for word in scrub._WORD.findall(line):
            key = scrub._plain(word).casefold()
            if sum(c.isalpha() for c in key) < MIN_LETTERS:
                skipped += 1
                continue
            found.add(scrub._hash(key))
    return found, skipped


def add(words_file: Path, redact_file: Path = REDACT) -> dict[str, int]:
    """Merge the words' hashes into `redact_file`; the counts (never a word)."""
    new, skipped = hashes_of(words_file.read_text(encoding="utf-8"))
    data = json.loads(redact_file.read_text(encoding="utf-8"))
    before = set(data.get("sha256", []))
    data["sha256"] = sorted(before | new)
    redact_file.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    scrub.load_redact(redact_file)  # the result is still a valid list (raises GenError if not)
    return {
        "words": len(new),
        "added": len(new - before),
        "skipped": skipped,
        "total": len(data["sha256"]),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("words", type=Path)
    ap.add_argument("--redact", type=Path, default=REDACT)
    args = ap.parse_args(argv)
    if not args.words.is_file():
        sys.stderr.write("redact_add: no words file there\n")
        return 2
    got = add(args.words, args.redact)
    sys.stdout.write(
        f"redact_add: {got['words']} word hashes, {got['added']} new, {got['skipped']} short words "
        f"skipped, {got['total']} in the list\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

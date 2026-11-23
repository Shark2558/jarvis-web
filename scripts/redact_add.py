# scripts/redact_add.py
"""R6.3 M8 (docs/plans/r6-3-book-content.md D4, seam 17): add the owner's private words to the build
book's redact list as SHA-256 hashes ONLY.

    python scripts/redact_add.py WORDS_FILE [--redact src/jarvis/buildbook/gen/redact.json]

WORDS_FILE (kept outside the repository, e.g. under /tmp) holds one name a line: the owner's
locality, workplace and employer words the Workshop relays. A line of ONE word is a name: its hash
joins `sha256` (the way `gen/scrub.py` looks names up: NFKD, accents and format characters dropped,
look-alikes folded, case folded), and a name under 3 letters is skipped (it would remove too much).
A line of SEVERAL words is a phrase: the hash of its words so folded and joined by one space joins
`phrases` (part A's scrubber matches it as consecutive words), and its words are NOT hashed one by
one, since a phrase is often made of ordinary words that must stay in the book. Both lists stay
sorted and unique. The script prints COUNTS only and never writes or says a word.
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


def key_of(word: str) -> str:
    return scrub._plain(word).casefold()


def hashes_of(text: str) -> tuple[set[str], set[str], int]:
    """(name hashes, phrase hashes, short names skipped) of `text`, one name a line."""
    names: set[str] = set()
    phrases: set[str] = set()
    skipped = 0
    for line in text.splitlines():
        words = [key_of(w) for w in scrub._WORD.findall(line)]
        if len(words) > 1:
            phrases.add(scrub._hash(" ".join(words)))
        elif words and sum(c.isalpha() for c in words[0]) >= MIN_LETTERS:
            names.add(scrub._hash(words[0]))
        elif words:
            skipped += 1
    return names, phrases, skipped


def add(words_file: Path, redact_file: Path = REDACT) -> dict[str, int]:
    """Merge the hashes into `redact_file`; the counts (never a word)."""
    names, phrases, skipped = hashes_of(words_file.read_text(encoding="utf-8"))
    data = json.loads(redact_file.read_text(encoding="utf-8"))
    had_n, had_p = set(data.get("sha256", [])), set(data.get("phrases", []))
    data["sha256"], data["phrases"] = sorted(had_n | names), sorted(had_p | phrases)
    redact_file.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    scrub.load_redact(redact_file)  # the result is still a valid list (raises GenError if not)
    return {
        "names": len(names),
        "phrases": len(phrases),
        "added": len(names - had_n) + len(phrases - had_p),
        "skipped": skipped,
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
        f"redact_add: {got['names']} name and {got['phrases']} phrase hashes, {got['added']} new, "
        f"{got['skipped']} short names skipped\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

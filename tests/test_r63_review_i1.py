# tests/test_r63_review_i1.py -- R6.3's combined review of I1 (docs/plans/r6-3-integration/
# REVIEW-I1.md): one test (or a few) a finding, each written red before its fix. No model is called.
# R6.3.1 D8: the findings on the runtime writer (M-1 to M-3, L-2 to L-4, L-7 and M-4's estimate)
# went with it; L-1 (a bearer script never reads the full book) is in tests/test_r631_e_serve.py.
from __future__ import annotations

import re

from r63_fakes import FIXTURE_FACTS, FIXTURE_FILES

from jarvis.buildbook.gen.scrub import default_scrubber
from jarvis.buildbook.gen.snapshot import _zip
from jarvis.buildbook.writer import carry, packs

C01 = FIXTURE_FACTS.page("pg_card_c01")
assert C01 is not None
GUIDE_TEXT = "# Guide\n\n#### C01 · The demo\nThe demo's card, as the guide words it.\n"


def _snapshot(rid: str, files: dict[str, str]) -> bytes:
    """A source.zip exactly as R6's snapshot zips it: every file under `JARVIS-source-<id>/`."""
    return _zip(f"JARVIS-source-{rid}", {k: v.encode("utf-8") for k, v in files.items()})


# ---- H-1, H-2: R6's snapshot keeps every file under one root folder ------------------------------
def test_h1_the_packs_read_the_code_under_the_snapshots_root_folder() -> None:
    never = {
        ".claude/agents/reviewer.md": "the agents' own rules",
        "tests/test_demo.py": "def test_x():\n    pass\n",
        "evals/demo.py": "CASES = []\n",
        "docs/.claude/notes.md": "a nested agents folder",
        ".env.local": "TOKEN=x\n",
    }
    tree = packs.read_source(_snapshot("abc1234", {**FIXTURE_FILES, **never}))
    assert set(FIXTURE_FILES) <= set(tree)  # the repository's own paths, as the pages cite them
    assert not set(never) & set(tree)  # the never-read rule holds under the root too
    assert not any(name.startswith("JARVIS-source-") for name in tree)
    pack = packs.build(C01, FIXTURE_FACTS, tree, default_scrubber())
    assert "code:src/jarvis/demo/router.py" in pack.body  # the cited file's signatures are read


def test_h2_the_free_carry_sees_a_changed_file_and_the_cards_across_two_releases() -> None:
    router = "src/jarvis/demo/router.py"
    base = {**FIXTURE_FILES, packs.GUIDE: GUIDE_TEXT}
    old = carry.tree_of(_snapshot("aaaaaaa", base))
    new = carry.tree_of(_snapshot("bbbbbbb", {**base, router: base[router] + "\n# changed\n"}))
    assert old.cards and old.cards == new.cards  # the guide is found in both
    assert old.files[router] != new.files[router]
    assert carry.is_changed(C01, old, new)
    same = carry.tree_of(_snapshot("ccccccc", base))
    assert not carry.is_changed(C01, old, same)  # only the root differs: nothing changed


# ---- M-4: building the packs never stops the event loop, and is not done twice -----------------
def _mentioned_by_regex(names: list[str], texts: list[str]) -> list[str]:
    """The rule as B wrote it: one regex a name (the reference for the faster form)."""
    joined = "\n".join(texts)
    return [n for n in names if re.search(rf"(?<![\w]){re.escape(n)}(?![\w])", joined)]


def test_m4_mentioned_finds_exactly_what_one_regex_a_name_finds() -> None:
    texts = ["demo_limit = Field(1)", "x.demo_notes, 1demo_x, café_ok", "book-pages and jarvis.x"]
    names = ["demo_limit", "demo_notes", "demo_x", "café_ok", "café", "book-pages", "jarvis.x",
             "missing", "demo", "x"]  # fmt: skip
    assert packs._mentioned(names, texts) == _mentioned_by_regex(names, texts)


def test_m4_a_block_is_scrubbed_once_a_release_however_many_pages_quote_it() -> None:
    calls: list[str] = []
    scrub = default_scrubber()

    class Counting:
        def clean(self, text: str) -> str:
            calls.append(text)
            return scrub.clean(text)

    cache: dict[str, str] = {}
    tree = {**FIXTURE_FILES}
    first = packs.build(C01, FIXTURE_FACTS, tree, Counting(), cache=cache)  # type: ignore[arg-type]
    n = len(calls)
    again = packs.build(C01, FIXTURE_FACTS, tree, Counting(), cache=cache)  # type: ignore[arg-type]
    assert again == first and len(calls) == n  # the second page's blocks came from the cache

# tests/test_r631_i0_authoring.py -- R6.3.1 I0 (docs/plans/r6-3-1-book-at-build.md D1-D5): the
# writers' guide, src/jarvis/buildbook/book/AUTHORING.md, keeps the repository's document format
# (version line, change log), and its complete example page and flowchart load as written.
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

from book_gen_fakes import ROOT

from jarvis.buildbook.book import authored
from jarvis.buildbook.book.flow import FlowSpec
from jarvis.buildbook.writer.model import SECTION_CAPS

GUIDE = ROOT / authored.BOOK_DIR / "AUTHORING.md"


def _doc_problems(text: str) -> list[str]:
    spec = importlib.util.spec_from_file_location(
        "check_doc_versions_i0", ROOT / "scripts" / "check_doc_versions.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    found: list[str] = module.problems(text)
    return found


def test_the_guide_has_the_version_line_and_the_change_log() -> None:
    assert _doc_problems(GUIDE.read_text(encoding="utf-8")) == []


def test_the_guide_names_the_tools_the_rules_and_the_caps() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    for tool in (
        "pages --list",
        "pages --pack",
        "pages --check",
        "pages --stamp",
        "--allow-missing",
    ):
        assert tool in text, tool
    for word in ("Unverified", "Planned:", "British spelling", "{{fact:<key>}}", "made-up"):
        assert word in text, word
    caps = [SECTION_CAPS[s] for s in ("plain", "example", "how", "costs", "fails")]
    assert caps == [900, 900, 2_400, 900, 900] and "2,400" in text


def test_the_example_page_and_flowchart_load(tmp_path: Path) -> None:
    text = GUIDE.read_text(encoding="utf-8")
    page = re.search(r"```markdown\n(.*?)```", text, re.S)
    flow = re.search(r"```json\n(.*?)```", text, re.S)
    assert page is not None and flow is not None
    path = tmp_path / "pg_card_c50.md"
    path.write_text(page.group(1), encoding="utf-8")
    loaded = authored.load_page(path)
    assert loaded.page == "pg_card_c50" and len(loaded.sections) == 5
    spec = FlowSpec.model_validate(json.loads(flow.group(1)))
    assert {n.ref for n in spec.nodes if n.ref} == set(loaded.sources)


def test_no_example_page_file_sits_in_the_folder() -> None:
    assert not (ROOT / authored.BOOK_DIR / "pages" / "pg_card_c50.md").exists() or (
        "3f1c0a9b2d4e5f60" not in authored.page_path(ROOT, "pg_card_c50").read_text("utf-8")
    )

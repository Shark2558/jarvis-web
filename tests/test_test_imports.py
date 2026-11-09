# tests/test_test_imports.py
"""Test modules never import through the `tests` package.

CI runs plain `pytest`, which does not put the repo root on sys.path, so `from tests.x import y`
works locally under `python -m pytest` but fails collection on GitHub (R4 PR #23, 9 Nov).
Shared fakes are imported bare (`from billing_fakes import ...`), as pytest's rootdir-relative
`tests/` entry on sys.path allows."""

from __future__ import annotations

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
PACKAGE_IMPORT = re.compile(r"^\s*(from\s+tests(\.|\s)|import\s+tests(\.|\s|$))", re.MULTILINE)


def test_no_test_module_imports_through_the_tests_package() -> None:
    offenders = [
        str(path.relative_to(TESTS))
        for path in sorted(TESTS.rglob("*.py"))
        if path.name != "test_test_imports.py" and PACKAGE_IMPORT.search(path.read_text("utf-8"))
    ]
    assert offenders == []


def test_the_pattern_catches_the_forms_that_broke_ci() -> None:
    for line in (
        "from tests.conftest import TIERS",
        "from tests.billing_fakes import UID",
        "import tests.fakes",
        "    from tests import fakes",
    ):
        assert PACKAGE_IMPORT.search(line), line
    for line in ("from billing_fakes import UID", "from testsuite import x", "# from tests.x"):
        assert not PACKAGE_IMPORT.search(line), line

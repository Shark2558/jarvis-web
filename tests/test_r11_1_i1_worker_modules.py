# tests/test_r11_1_i1_worker_modules.py
"""R11.1 I1 (CI run 107): the extraction child never imports numpy or pandas.

openpyxl imports numpy when it is installed (`openpyxl.compat.numbers`). The homebridge extra
installs numpy on the CI's Python 3.12 leg, and numpy's OpenBLAS reserves address space for each
CPU, so on GitHub's 4-CPU runners a workbook child passed its 200 MiB RLIMIT_AS cap while
importing and ended with code 1 ("too complex") before it read a byte. The child needs neither
module, so it keeps them out before any import: same answer on every machine, smaller memory.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from dataclasses import asdict

import pytest

from jarvis.documents import isolation
from jarvis.documents.extract import Limits
from jarvis.documents.isolation import Sandbox, extract_isolated

# Above what the child needs without numpy (about 40 MiB measured), below what importing
# openpyxl with numpy needs even on a 2-CPU machine (about 150 MiB measured).
TIGHT_CAP = 100 * 1024 * 1024


def _workbook() -> bytes:
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    for r in range(20):
        sheet.append([f"row {r}", r])
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def test_the_child_keeps_numpy_and_pandas_out_before_it_imports_anything() -> None:
    probe = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from jarvis.documents import worker; worker._keep_out_unneeded(); "
        "import openpyxl, openpyxl.compat.numbers as n; "
        "print(n.NUMPY, sys.modules.get('numpy'), sys.modules.get('pandas'))"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", probe, isolation.PKG_ROOT],
        capture_output=True,
        env=isolation.child_env(),
        check=True,
    )
    assert done.stdout.decode().split() == ["False", "None", "None"]


async def test_a_workbook_reads_under_a_cap_numpy_alone_would_break() -> None:
    out = await extract_isolated(_workbook(), "xlsx", Limits(), Sandbox(memory_bytes=TIGHT_CAP))
    assert "row 19" in out.text
    assert out.sheets == 1


def test_the_real_child_command_reads_a_workbook_under_the_tight_cap() -> None:
    cmd = [
        sys.executable,
        "-I",
        "-c",
        isolation._BOOT,
        isolation.PKG_ROOT,
        "xlsx",
        json.dumps(asdict(Limits())),
        str(isolation.CPU_LIMIT_S),
        str(TIGHT_CAP),
    ]
    done = subprocess.run(cmd, input=_workbook(), capture_output=True, env=isolation.child_env())
    assert done.returncode == 0, done.stderr.decode()[-400:]
    assert json.loads(done.stdout)["ok"] is True

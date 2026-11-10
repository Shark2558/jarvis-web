# evals/r6_book/run.py
"""R6 eval -- the build book (plan docs/plans/r6-build-book.md "Evals and tests"), one suite file
per part so each builder fills only its own:

    python evals/r6_book/run.py --mock [--part gen --part seal ...]

    gen.py     A  the generator: byte-equal double build, every section, scrub, secret scan, caps
    seal.py    B  sealing, retention 3, tamper fails closed, one notice, racing sealers
    access.py  C  passkey AND fresh sign-in, console only, tokens, what a guest can't read
    guest.py   C  a worst-case mock brain: owner-data asks refused with no call, canary, limits
    wipe.py    C  after close: no needle anywhere, one content-free notice, the sweep
    lock.py    C  the guest lock over every cookie session; only a book_resume passkey lifts it

Every part file exposes:

    PART: str        its name (the file's stem)
    BUILT: bool      False while it is the I0 stub
    async def cases() -> list[dict]       each {"id": "<part>:<case>", "passed", "failures"}
    async def control() -> dict           {"name", "suite_failed", "failed_cases"}: the part's
                                          cases re-run with its negative control applied

An unbuilt part reports one passing case "<part>:not_built_yet" and is not asked for a control.
The suite passes when every case passes AND every BUILT part's control made that part fail (a
suite that cannot fail proves nothing). Gated in `make eval-mock` from I1 (evals/run_all_mock.py).
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import logging
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))
from r1d_common import finish  # noqa: E402

PARTS = ("gen", "seal", "access", "guest", "wipe", "lock")


def load(part: str) -> ModuleType | None:
    """The part's module, by path under a unique name (no clash with any other `gen` or `lock`)."""
    path = HERE / f"{part}.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"r6_book_{part}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _missing(part: str) -> dict[str, Any]:
    return {"id": f"{part}:missing", "passed": False, "failures": [f"evals/r6_book/{part}.py"]}


async def run_parts(parts: tuple[str, ...]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    results: list[dict[str, Any]] = []
    controls: dict[str, Any] = {}
    for part in parts:
        module = load(part)
        if module is None:
            results.append(_missing(part))
            continue
        results.extend(await module.cases())
        if module.BUILT:
            controls[part] = await module.control()
    return results, controls


def combined(controls: dict[str, Any], parts: tuple[str, ...]) -> dict[str, Any]:
    built = sorted(controls)
    return {
        "name": " + ".join(c["name"] for c in controls.values()) or "none: no part is built yet",
        "suite_failed": all(bool(c["suite_failed"]) for c in controls.values()),
        "failed_cases": {p: controls[p]["failed_cases"] for p in built},
        "parts_not_built": [p for p in parts if p not in controls],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="the only mode (CI)")
    ap.add_argument("--part", action="append", choices=PARTS, help="run only these parts")
    args = ap.parse_args()
    logging.getLogger().setLevel(logging.INFO)
    parts = tuple(args.part or PARTS)
    results, controls = asyncio.run(run_parts(parts))
    return finish(HERE, "r6_book", results, combined(controls, parts))


if __name__ == "__main__":
    sys.exit(main())

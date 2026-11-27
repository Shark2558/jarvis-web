# tests/r8_fakes.py -- R8 I0 seam S23 (docs/plans/r8-vision.md v8.0.3 section 8): the R8 and R8.1
# tests' shared fakes. `run_node(module, call, *args)` imports one console ES module (or a fixture
# in tests/fixtures/r8/) in Node and returns what `call(...args)` gives, as JSON; the synthetic
# bodies and hands are tests/fixtures/r8/poses.mjs and hands.mjs. A clock, a made-up key and a
# session id. Nothing here is a real person's data.
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "jarvis" / "api" / "static"
FIXTURES = ROOT / "tests" / "fixtures" / "r8"
KEY = bytes(range(31, 63))  # a made-up token key: never a real one
SESSION = "cs_0123456789ab"
NOON_IST = datetime(2026, 11, 28, 6, 30, tzinfo=UTC)
_RUN = """
const [path, call, args] = JSON.parse(process.argv[1]);
const mod = await import(path);
const fixtures = {
  poses: await import(%(poses)s),
  hands: await import(%(hands)s),
};
const fn = call.split('.').reduce((o, k) => o[k], { mod, ...fixtures });
const made = (a) => a.$fixture.split('.').reduce((o, k) => o[k], fixtures)(...(a.args || []));
const out = await fn(...args.map((a) => (a && a.$fixture ? made(a) : a)));
process.stdout.write(JSON.stringify(out === undefined ? null : out));
"""


def _url(path: Path) -> str:
    return json.dumps(path.resolve().as_uri())


def run_node(module: str | Path, call: str, *args: Any) -> Any:
    """`call` is `mod.<export>` (the module) or `poses.<fn>` / `hands.<fn>` (the fixtures); an
    argument `{"$fixture": "poses.body", "args": [...]}` is that fixture's result."""
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is not installed")
    path = module if isinstance(module, Path) else STATIC / module
    script = _RUN % {"poses": _url(FIXTURES / "poses.mjs"), "hands": _url(FIXTURES / "hands.mjs")}
    done = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            script,
            json.dumps([path.resolve().as_uri(), call, list(args)]),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return json.loads(done.stdout)


__all__ = ["FIXTURES", "KEY", "NOON_IST", "SESSION", "STATIC", "run_node"]

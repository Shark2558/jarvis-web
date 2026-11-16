# tests/r13_record.py -- R13 I1: the recorder for D's tool calls (imported bare; not a test module).
#
# D's panel (Playwright, against D's fake server), D's scan module (the Node harness) and D's
# No-AI sentences each make gateway calls. `record(...)` appends one JSON line per call to the file
# named by R13_RECORD_CALLS (and does nothing when it is not set), and
#
#     python tests/r13_record.py build <raw.jsonl> tests/fixtures/r13/d_calls.json
#
# folds them into the corpus `tests/test_r13_i1_replay.py` replays through each part's REAL tool
# schema and the gateway. The corpus holds fixture ids only (the drawn pilot set): no personal data.
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def record(source: str, tool: str, arguments: dict[str, Any]) -> None:
    path = os.environ.get("R13_RECORD_CALLS")
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as f:
        f.write(json.dumps({"source": source, "tool": tool, "arguments": arguments}) + "\n")


def _plain(value: Any) -> Any:
    """Random client ids (the page makes a new one each press) folded to one, so the corpus is
    stable between recordings."""
    if isinstance(value, dict):
        return {k: "wd" + "0" * 14 if k == "client_id" else _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def build(raw: Path, out: Path) -> int:
    seen: dict[str, dict[str, Any]] = {}
    for line in raw.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        row["arguments"] = _plain(row["arguments"])
        key = json.dumps([row["source"], row["tool"], row["arguments"]], sort_keys=True)
        seen.setdefault(key, row)
    rows = sorted(seen.values(), key=lambda r: (r["tool"], r["source"], json.dumps(r["arguments"])))
    out.write_text(json.dumps(rows, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return len(rows)


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "build":
        raise SystemExit("usage: r13_record.py build <raw.jsonl> <out.json>")
    print(build(Path(sys.argv[2]), Path(sys.argv[3])), "calls")

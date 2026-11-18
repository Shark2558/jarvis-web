# tests/r131_console_query.py -- R13.1 I1 (integrated code review H1): row 388's card asked for
# EXACTLY as the console asks for it. `card_query(card)` runs `console-tryon-list.js`'s own
# `cardQuery` in Node (the function `console-tryon.js` calls when a card lands), so A's tests, the
# joins test and the e2e eval build no query of their own: had they done so (as before), the
# console could drop the card's day and code and every test would still pass. Imported bare
# (`from r131_console_query import card_query`); not a test module.
from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

LIST_JS = Path(__file__).resolve().parents[1] / "src/jarvis/api/static/console-tryon-list.js"


def _plain(card: Any) -> Mapping[str, Any]:
    """A `TryOnCard` (the model) or the card as the reply carries it (JSON)."""
    if hasattr(card, "model_dump"):
        return dict(card.model_dump(mode="json"))
    return dict(card)


def _run(fn: str, *args: Any) -> str:
    """`console-tryon-list.js`'s `fn(...args)`, run in Node: the console's own query string."""
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is not installed")
    called = f"L.{fn}(...{json.dumps(list(args))})"
    src = (
        f"const L = await import({json.dumps(LIST_JS.as_uri())});"
        f"process.stdout.write(JSON.stringify({called}));"
    )
    got = subprocess.run(
        [node, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=60,
        check=False,
    )  # fmt: skip
    if got.returncode != 0:
        raise RuntimeError(f"{fn} failed: {got.stderr[-400:]}")
    return str(json.loads(got.stdout))


def card_query(card: Any) -> str:
    """The query string the console sends to `GET /v1/tryon/look?` when this card lands."""
    return _run("cardQuery", _plain(card))


def look_query(picks: list[dict[str, str]], plan: str | None, look: Any) -> str:
    """The query string of a swap, an undo or a refresh: `picks` ({slot, piece}) of `look` (the
    TryonLook as JSON: its day, dress code and covered slots), in `plan`'s context when given."""
    return _run("query", picks, plan, _plain(look))


__all__ = ["card_query", "look_query"]

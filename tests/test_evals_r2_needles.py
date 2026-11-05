# tests/test_evals_r2_needles.py -- R2 I1: the cross-cutting needle scan runs in the unit suite too
# (mock): 22 conversations + 5 scans pass, and ignoring `Tool.activity_words` makes it fail. R2
# review S4: the world stores approval cards the way the app does (DocApprovalStore), a spoken
# note becomes a waiting card, and only those card documents may hold a note's words (D13).
from __future__ import annotations

import importlib.util
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from jarvis.storage.approvals import DocApprovalStore
from jarvis.storage.docs import Set

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evals" / "r2_needles" / "run.py"


def test_r2_needles_pass_and_the_activity_words_control_fails_the_suite() -> None:
    r = subprocess.run([sys.executable, str(RUN), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    report = json.loads((ROOT / "evals" / "r2_needles" / "report.json").read_text())
    ids = [x["id"] for x in report["results"]]
    assert report["pass_rate"] == 1.0 and len(ids) == 27
    assert len([i for i in ids if not i.startswith("scan_")]) == 22
    assert {"typed_where_positive_control", "training_brain_same_session"} <= set(ids)
    assert {"voice_kb_add_note_card", "brief_day_inbox_copy"} <= set(ids)  # review S4
    control = report["negative_control"]
    assert control["suite_failed"] is True and "scan_activity_rows" in control["failed_cases"]


def _needles() -> Any:
    spec = importlib.util.spec_from_file_location("r2_needles_run", RUN)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["r2_needles_run"] = mod
    spec.loader.exec_module(mod)
    return mod


async def test_the_world_keeps_cards_like_the_app_and_only_cards_may_hold_a_note() -> None:
    """Review S4: the eval's gateway stores waiting cards in Firestore documents (as the app's
    DocApprovalStore does), so the scan can see them; the allowlist is exactly those documents."""
    m = _needles()
    w = await m.build_world()
    try:
        assert isinstance(w.gateway.gate.store, DocApprovalStore)
        assert await m.voice_note_card(w) == []
        cards = m.approval_cards(w)
        assert cards and all(k.startswith(m.APPROVALS) for k in cards)
        assert await m.scan_documents(w) == []
        # the allowlist is exact: the same words in any other document fail the scan
        await w.docs.write([Set("jarvis_somewhere/x", {"text": m.VOICE_NOTE})])
        assert any("Firestore document" in f for f in await m.scan_documents(w))
    finally:
        logging.getLogger().removeHandler(w.logs)

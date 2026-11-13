# tests/test_r7_a_push.py -- R7 Part A, alerts that open the panel they are about (docs/plans/
# r7-mobile.md D8, D9, D10; acceptance check 2): every alert kind's push payload carries a real
# target, `/?open=<panel>` with a panel the launch reader allows (or `/` for a test alert); the push
# worker keeps that target (its address check learns the `?`), puts the kind in the tag (`tag:
# kind`, phone-contract.md section 6) and offers "Talk"; a click hands the target to the JARVIS
# window already open over a BroadcastChannel and never calls navigate() (static half; the browser
# half is tests/browser/test_r7_a_push.py).
from __future__ import annotations

import json
import re
from typing import get_args

import pytest
from r7_fakes_a import STATIC, dock_panels, links_panels, links_words, text

from jarvis.alerts import AlertKind
from jarvis.webpush.service import MAX_PAYLOAD_BYTES, TARGETS, payload_for

KINDS: tuple[str, ...] = get_args(AlertKind)
SW = STATIC / "console-sw.js"
# the worker's own address rule, copied from console-sw.js (checked to be there, below)
SW_RULE = r"^\/(?:\?(?:open=[a-z]{2,20}|do=(?:talk|look|sos|shared)))?$"


@pytest.mark.parametrize("kind", KINDS)
def test_every_alert_kind_opens_a_panel_the_launch_reader_allows(kind: str) -> None:
    url = json.loads(payload_for(kind, "A made-up alert."))["url"]
    if kind == "test":
        assert url == "/"
        return
    assert re.fullmatch(r"/\?open=[a-z]+", url), url
    assert url.removeprefix("/?open=") in links_panels()
    assert re.fullmatch(SW_RULE, url)  # the worker keeps it


def test_the_targets_cover_every_kind_and_name_only_real_panels() -> None:
    assert set(TARGETS) == set(KINDS) - {"test"}
    assert set(TARGETS.values()) <= set(dock_panels())
    assert {k: v for k, v in TARGETS.items() if k.startswith("home_")} == {
        k: "home" for k in KINDS if k.startswith("home_")
    }
    assert TARGETS["approval_waiting"] == "approvals" and TARGETS["brief_ready"] == "brief"
    assert TARGETS["sos_sent"] == TARGETS["phone_linked"] == "integrations"
    assert TARGETS["watch_stale"] == "helpers" and TARGETS["faces_to_name"] == "faces"


def test_an_unknown_kind_opens_the_console_and_the_payload_stays_small() -> None:
    assert json.loads(payload_for("not_a_kind", "x"))["url"] == "/"
    raw = payload_for("home_intruder", "ക" * 5000)
    assert len(raw) <= MAX_PAYLOAD_BYTES
    assert set(json.loads(raw)) == {"kind", "text", "url"}


def test_the_launch_reader_allows_the_four_words_and_every_dock_panel() -> None:
    assert links_words() == ["talk", "look", "sos", "shared"]
    assert links_panels() == dock_panels()


# ---- the push worker (console-sw.js), statically ---------------------------------------------
def test_the_worker_keeps_a_target_with_its_question_mark_and_nothing_else() -> None:
    src = text(SW)
    assert "/^\\/(?:\\?(?:open=[a-z]{2,20}|do=(?:talk|look|sos|shared)))?$/" in src
    good = ["/", "/?open=home", "/?do=talk", "/?open=approvals"]
    bad = ["/#home", "//evil.example/", "/?open=Home", "/?do=call", "/?open=home&x=1"]
    bad += ["https://evil.example/", "/?open=home#x", "/x?open=home", "/?reauth=1"]
    assert all(re.fullmatch(SW_RULE, u) for u in good)
    assert not [u for u in bad if re.fullmatch(SW_RULE, u)]


def test_the_click_hands_over_and_never_navigates_or_opens_a_second_window() -> None:
    src = text(SW)
    assert "navigate(" not in src  # it fails on a window this worker does not control
    assert "new BroadcastChannel('jarvis-launch')" in src
    assert "addEventListener('fetch'" not in src  # still no fetch handler (R3 D11)
    assert "tag: kind" in src  # phone-contract.md section 6: the app's channels read it
    assert "action: 'talk'" in src and "'/?do=talk'" in src
    assert src.isascii() and len(src.splitlines()) <= 80

# tests/test_r131_i1_console.py -- R13.1 I1: the console lines D proposed for I0's files, applied
# (INTEGRATION-D section 9, "Needs I1" 1 and 2). Written red first, on the files as I0 left them.
#   - the door (`console-r7-send.js`) carries See it on me's paid press (PictureIn's five checked
#     fields), Keep, the deletes and the garment list, inside its 165-line guard;
#   - I0's hook (`console-helpers-wardrobe.js`) draws a plan's "Show in 3D" only while Try-on's
#     state is "on", and draws again on `jarvis:tryon-state`: with Try-on off, R13's plan rows
#     look as R13's.
from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "api" / "static"


def test_the_door_carries_see_it_on_mes_press_keep_deletes_and_list() -> None:
    door = (STATIC / "console-r7-send.js").read_text(encoding="utf-8")
    assert len(door.splitlines()) <= 165
    last = door.rstrip("\n").splitlines()[-1]
    assert "myPhoto, make, keep, forget, garments, sentToday" in last
    assert "confirm_cost === true" in door and "/^tq_[0-9a-f]{16}$/" in door  # five fields


def test_show_in_3d_is_drawn_only_while_try_on_is_on() -> None:
    hook = (STATIC / "console-helpers-wardrobe.js").read_text(encoding="utf-8")
    assert len(hook.splitlines()) <= 306
    assert "UI.tryon.state() === 'on') box.append(acts(btn('Show in 3D'" in hook
    assert "document.addEventListener('jarvis:tryon-state'" in hook
    assert "if (!p.cancelled) box.append(acts(btn('Show in 3D'" not in hook

# tests/test_r7_a_icons.py -- R7 Part A (docs/plans/r7-mobile.md D0, D3; owner question 14): the
# app's icons are drawn by scripts/app_icons.py from the console's own core ring (and its mic and
# camera strokes) on the Night background, byte for byte: what is committed is what the script
# draws, every icon is opaque on #04070D, and the maskable one keeps inside Android's safe circle.
from __future__ import annotations

import importlib.util
import sys
import zlib
from pathlib import Path
from types import ModuleType

import pytest
from r7_fakes_a import ICONS, ROOT, png_size

import jarvis.api.app_shell as shell


def _script() -> ModuleType:
    path = ROOT / "scripts" / "app_icons.py"
    spec = importlib.util.spec_from_file_location("r7a_app_icons", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["r7a_app_icons"] = module
    spec.loader.exec_module(module)
    return module


ICON_SCRIPT = _script()


def _rows(raw: bytes) -> list[bytes]:
    w, h = png_size(raw)
    data = raw[raw.index(b"IDAT") + 4 :]
    pixels = zlib.decompressobj().decompress(data)
    stride = 1 + 3 * w
    return [pixels[i * stride + 1 : (i + 1) * stride] for i in range(h)]


def test_the_committed_icons_are_exactly_what_the_script_draws(tmp_path: Path) -> None:
    assert [i.name for i in ICON_SCRIPT.ICONS] == list(shell.ICONS)
    assert ICON_SCRIPT.main(["--out", str(tmp_path)]) == 0
    for name in shell.ICONS:
        assert (tmp_path / name).read_bytes() == (ICONS / name).read_bytes(), name


def test_a_changed_icon_is_caught_by_the_check(tmp_path: Path) -> None:
    for name in shell.ICONS:
        (tmp_path / name).write_bytes((ICONS / name).read_bytes())
    path = tmp_path / "talk-96.png"
    path.write_bytes(path.read_bytes()[:-20] + b"\x00" * 20)
    assert ICON_SCRIPT.main(["--check", "--out", str(tmp_path)]) == 1


@pytest.mark.parametrize("name", list(shell.ICONS))
def test_each_icon_is_an_opaque_square_on_the_night_background(name: str) -> None:
    raw = (ICONS / name).read_bytes()
    w, h = png_size(raw)
    assert w == h == shell.ICONS[name]
    assert raw[24:26] == b"\x08\x02"  # 8-bit RGB: no transparency for a launcher to fill white
    rows = _rows(raw)
    assert rows[0][:3] == rows[-1][-3:] == bytes((4, 7, 13))  # the corners are #04070D


def test_the_maskable_icon_draws_nothing_outside_the_safe_circle() -> None:
    raw = (ICONS / "jarvis-maskable-512.png").read_bytes()
    rows, n = _rows(raw), 512
    background = bytes((4, 7, 13))
    for y in range(0, n, 4):
        for x in range(0, n, 4):
            dx, dy = x + 0.5 - n / 2, y + 0.5 - n / 2
            if dx * dx + dy * dy > (0.4 * n) ** 2:
                assert rows[y][3 * x : 3 * x + 3] == background, (x, y)


def test_the_script_draws_from_its_own_shapes_only() -> None:
    src = (ROOT / "scripts" / "app_icons.py").read_text(encoding="utf-8")
    assert "import PIL" not in src and "urllib" not in src and "open(" not in src
    assert src.isascii()


def test_the_scripts_help_starts_with_its_one_line_description(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        ICON_SCRIPT.main(["--help"])
    assert "the app's icons, drawn here" in " ".join(capsys.readouterr().out.split())

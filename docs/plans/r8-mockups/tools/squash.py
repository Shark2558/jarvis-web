#!/usr/bin/env python3
# docs/plans/r8-mockups/tools/squash.py -- shrink mockup PNGs in place: Pillow's quantize to a 256-colour palette (fast
# octree), then the picture mapped onto it with Floyd-Steinberg dithering (without it the Core's glow and the sheet's
# scrim band into blotches), saved with optimize: about 60 % smaller, text unchanged. A file is replaced only when the
# result is smaller. The branch already carries the first 50 shots (31 MB), so new shots go in squashed.
# Usage: python3 -I tools/squash.py <png> [<png> ...]   (needs Pillow; the console's own Python has it, the Playwright venv may not)
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


def squash(path: Path) -> tuple[int, int]:
    before = path.stat().st_size
    with Image.open(path) as im:
        rgb = im.convert("RGB")
        palette = rgb.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
        small = rgb.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG)
    tmp = path.with_suffix(".squash.png")
    small.save(tmp, optimize=True)
    after = tmp.stat().st_size
    if after < before:
        tmp.replace(path)
    else:
        tmp.unlink()
        after = before
    return before, after


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: squash.py <png> [<png> ...]", file=sys.stderr)
        return 2
    total_before = total_after = 0
    for name in argv:
        before, after = squash(Path(name))
        total_before += before
        total_after += after
        print(f"{Path(name).name}: {before // 1024} KB -> {after // 1024} KB")
    print(f"total: {total_before // 1024} KB -> {total_after // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

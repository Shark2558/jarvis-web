# scripts/app_icons.py
"""R7 Part A (docs/plans/r7-mobile.md D0, D3; owner question 14): the app's icons, drawn here.

    python scripts/app_icons.py            write src/jarvis/api/static/icons/*.png
    python scripts/app_icons.py --check    exit 1 when a committed icon differs from this drawing

The app icon is the console's own core ring (console-fx.js `coreSVG`, the large size: the faint
outer circle, 72 ticks with every sixth long, three arcs, three marks, the dotted inner circle, two
inner arcs, the glow, the nucleus and its dot) in the Workshop theme's two accents, on the Night
surface's background `#04070D`. The three shortcut icons (Talk, Camera, SOS) are the console's own
mic and camera strokes and a plain warning mark, on the same background. Every shape is drawn here
from its distance field (one pixel of anti-aliasing), so no third-party artwork or brand logo is
used and the output is byte-for-byte the same on every machine (PNG without a time chunk, fixed
zlib level). Standard library only.
"""

from __future__ import annotations

import argparse
import math
import struct
import sys
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "api" / "static" / "icons"
RGB = tuple[float, float, float]

BG: RGB = (4, 7, 13)  # #04070D: the Night surface and the manifest's colours
ACCENT: RGB = (0, 113, 227)  # #0071E3: Workshop --accent
ACCENT_2: RGB = (0, 194, 224)  # #00C2E0: Workshop --accent-2
WELL: RGB = (11, 19, 30)  # #0B131E: Night --well (the nucleus)
WHITE: RGB = (255, 255, 255)
BAD: RGB = (242, 85, 90)  # #F2555A: Night --bad (the SOS mark)

# A layer answers, for one point (in the drawing's own units), its signed distance (< 0 inside)
# or None when the point is far from it; plus its colour and opacity there.
Paint = tuple[RGB, float]
Layer = Callable[[float, float, float, float], tuple[float, RGB, float] | None]


@dataclass(frozen=True)
class Icon:
    name: str
    size: int
    draw: Callable[[], Sequence[Layer]]
    units: float  # the drawing's half-width in its own units
    fill: float  # the share of the half-width the drawing fills


# ---- distance helpers ---------------------------------------------------------------------------
def _segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    vx, vy, wx, wy = bx - ax, by - ay, px - ax, py - ay
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / (vx * vx + vy * vy or 1.0)))
    return math.hypot(wx - vx * t, wy - vy * t)


def _deg(x: float, y: float) -> float:
    """Clockwise from 3 o'clock (the y axis points down, as in SVG), 0 to 360."""
    return math.degrees(math.atan2(y, x)) % 360.0


def _in(angle: float, start: float, end: float) -> bool:
    return (angle - start) % 360.0 <= (end - start) % 360.0


def _polar(r: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return r * math.cos(a), r * math.sin(a)


# ---- the core ring (console-fx.js coreSVG, size lg, centred on 0,0 in its 120-unit box) ---------
def _ring(radius: float, width: float, colour: RGB, alpha: float) -> Layer:
    def layer(x: float, y: float, r: float, a: float) -> tuple[float, RGB, float] | None:
        d = abs(r - radius) - width / 2
        return (d, colour, alpha) if d < 2 else None

    return layer


def _dashes(radius: float, width: float, spans: Sequence[tuple[float, float]], c: RGB) -> Layer:
    """Arcs with round caps (stroke-dasharray on a circle, which starts at 3 o'clock)."""
    ends = [_polar(radius, deg) for span in spans for deg in span]

    def layer(x: float, y: float, r: float, a: float) -> tuple[float, RGB, float] | None:
        if abs(r - radius) > width + 2:
            return None
        if any(_in(a, s, e) for s, e in spans):
            return abs(r - radius) - width / 2, c, 1.0
        return min(math.hypot(x - ex, y - ey) for ex, ey in ends) - width / 2, c, 1.0

    return layer


def _ticks(count: int, every: int, colour: RGB, alpha: float) -> Layer:
    step = 360.0 / count

    def layer(x: float, y: float, r: float, a: float) -> tuple[float, RGB, float] | None:
        if not 46.0 < r < 58.0:
            return None
        # ticks start at 12 o'clock (console-fx.js `tick`: deg - 90)
        k = round(((a + 90.0) % 360.0) / step) % count
        major = k % every == 0
        r0, w = (48.5, 1.7) if major else (52.5, 0.9)
        off = math.radians((a + 90.0) % 360.0 - k * step)
        across = abs(r * math.sin(off)) - w / 2
        along = abs(r * math.cos(off) - (r0 + 56.0) / 2) - (56.0 - r0) / 2
        outside = math.hypot(max(across, 0.0), max(along, 0.0))
        return outside + min(max(across, along), 0.0), colour, alpha

    return layer


def _marks(at: Sequence[float], radius: float, size: float, colour: RGB) -> Layer:
    """Three small squares turned 45 degrees (console-fx.js `diamond`)."""
    centres = [_polar(radius, deg - 90.0) for deg in at]

    def layer(x: float, y: float, r: float, a: float) -> tuple[float, RGB, float] | None:
        if abs(r - radius) > size + 2:
            return None
        best = 9e9
        for cx, cy in centres:
            dx, dy = x - cx, y - cy
            best = min(best, (abs(dx) + abs(dy)) / math.sqrt(2) - size / 2)
        return best, colour, 1.0

    return layer


def _dotted(radius: float, width: float, dot: float, gap: float, c: RGB, alpha: float) -> Layer:
    period = dot + gap

    def layer(x: float, y: float, r: float, a: float) -> tuple[float, RGB, float] | None:
        if abs(r - radius) > width + 2:
            return None
        along = (math.radians(a) * radius) % period
        across = abs(r - radius) - width / 2
        lengthwise = abs(along - dot / 2) - dot / 2
        outside = math.hypot(max(across, 0.0), max(lengthwise, 0.0))
        return outside + min(max(across, lengthwise), 0.0), c, alpha

    return layer


def _glow(radius: float) -> Layer:
    """The radial gradient: white, accent-2 at half (opacity .55), accent at the edge (0)."""

    def layer(x: float, y: float, r: float, a: float) -> tuple[float, RGB, float] | None:
        if r >= radius:
            return None
        t = r / radius
        if t < 0.5:
            k = t / 0.5
            colour = tuple(w + (c - w) * k for w, c in zip(WHITE, ACCENT_2, strict=True))
            alpha = 1.0 + (0.55 - 1.0) * k
        else:
            k = (t - 0.5) / 0.5
            colour = tuple(c + (e - c) * k for c, e in zip(ACCENT_2, ACCENT, strict=True))
            alpha = 0.55 * (1.0 - k)
        return -1.0, (colour[0], colour[1], colour[2]), alpha

    return layer


def _disc(radius: float, colour: RGB) -> Layer:
    def layer(x: float, y: float, r: float, a: float) -> tuple[float, RGB, float] | None:
        d = r - radius
        return (d, colour, 1.0) if d < 2 else None

    return layer


def core() -> Sequence[Layer]:
    return (
        _ring(57.5, 0.8, ACCENT_2, 0.4),
        _ticks(72, 6, ACCENT_2, 0.6),
        _dashes(43.0, 3.0, ((0, 70), (120, 190), (240, 310)), ACCENT),
        _marks((95.0, 215.0, 335.0), 36.5, 4.0, ACCENT),
        _dotted(31.0, 1.0, 1.0, 3.0, ACCENT_2, 0.4),
        _dashes(31.0, 2.2, ((0, 40), (180, 220)), ACCENT_2),
        _glow(22.0),
        _disc(8.75, ACCENT),  # the nucleus's ring (r 8, stroke 1.5)...
        _disc(8.0 - 0.75, WELL),  # ...and its fill
        _disc(3.2, ACCENT),
    )


# ---- the shortcut glyphs (the console's 20-unit strokes, centred on 0,0) -----------------------
def _strokes(
    parts: Sequence[tuple[float, float, float, float]], width: float, colour: RGB
) -> Layer:
    def layer(x: float, y: float, r: float, a: float) -> tuple[float, RGB, float] | None:
        d = min(_segment(x, y, ax, ay, bx, by) for ax, ay, bx, by in parts)
        return d - width / 2, colour, 1.0

    return layer


Segment = tuple[float, float, float, float]


def _arc(cx: float, cy: float, radius: float, start: float, end: float) -> list[Segment]:
    steps = 24
    pts = [_polar(radius, start + (end - start) * i / steps) for i in range(steps + 1)]
    return [
        (cx + x0, cy + y0, cx + x1, cy + y1)
        for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False)
    ]


def _outline(cx: float, cy: float, radius: float, width: float, colour: RGB) -> Layer:
    def layer(x: float, y: float, r: float, a: float) -> tuple[float, RGB, float] | None:
        return abs(math.hypot(x - cx, y - cy) - radius) - width / 2, colour, 1.0

    return layer


def talk() -> Sequence[Layer]:
    # console.html #micBtn: M10 2.6a2.6 2.6 0 0 0-2.6 2.6v4.6a2.6 2.6 0 0 0 5.2 0V5.2...
    # (moved so 10,10 is 0,0): the capsule, the cradle, the stem and the foot
    capsule = [(0.0, -4.8, 0.0, -0.2)]
    cradle = _arc(0.0, -0.4, 5.0, 0.0, 180.0)
    stem = [(0.0, 4.6, 0.0, 7.4), (-2.8, 7.4, 2.8, 7.4)]
    return (
        _ring(9.4, 0.25, ACCENT_2, 0.4),
        _strokes(capsule, 5.2, ACCENT_2),
        _strokes(cradle + stem, 1.8, ACCENT_2),
    )


def look() -> Sequence[Layer]:
    # a camera: the body (a rounded box), the lens and the top
    body = [(-5.0, -4.0, 5.0, -4.0), (7.0, -2.0, 7.0, 4.0), (5.0, 6.0, -5.0, 6.0)]
    body += [(-7.0, 4.0, -7.0, -2.0)]
    body += _arc(5.0, -2.0, 2.0, 270.0, 360.0) + _arc(5.0, 4.0, 2.0, 0.0, 90.0)
    body += _arc(-5.0, 4.0, 2.0, 90.0, 180.0) + _arc(-5.0, -2.0, 2.0, 180.0, 270.0)
    top = [(-3.0, -4.0, -2.0, -6.0), (-2.0, -6.0, 2.0, -6.0), (2.0, -6.0, 3.0, -4.0)]
    return (
        _ring(9.4, 0.25, ACCENT_2, 0.4),
        _strokes(body + top, 1.6, ACCENT_2),
        _outline(0.0, 1.0, 3.0, 1.6, ACCENT_2),
    )


def sos() -> Sequence[Layer]:
    # a plain warning mark: a ring, a bar and a dot
    return (
        _ring(9.4, 0.25, BAD, 0.5),
        _outline(0.0, 0.0, 7.0, 1.7, BAD),
        _strokes([(0.0, -3.8, 0.0, 1.0)], 1.9, BAD),
        _disc_at(0.0, 3.9, 1.15, BAD),
    )


def _disc_at(cx: float, cy: float, radius: float, colour: RGB) -> Layer:
    def layer(x: float, y: float, r: float, a: float) -> tuple[float, RGB, float] | None:
        return math.hypot(x - cx, y - cy) - radius, colour, 1.0

    return layer


# The "any" icons fill 84% of the square; the maskable one keeps inside Android's safe circle
# (radius 40%: 72% here); a shortcut glyph fills 80%.
ICONS: tuple[Icon, ...] = (
    Icon("jarvis-192.png", 192, core, 57.9, 0.84),
    Icon("jarvis-512.png", 512, core, 57.9, 0.84),
    Icon("jarvis-maskable-512.png", 512, core, 57.9, 0.72),
    Icon("talk-96.png", 96, talk, 9.6, 0.8),
    Icon("look-96.png", 96, look, 9.6, 0.8),
    Icon("sos-96.png", 96, sos, 9.6, 0.8),
)


# ---- drawing and the PNG -----------------------------------------------------------------------
def pixels(icon: Icon) -> bytearray:
    """RGB rows, each led by PNG's filter byte 0. Every layer is laid over the ones before it."""
    layers = icon.draw()
    n = icon.size
    scale = icon.units / (icon.fill * n / 2)  # drawing units per pixel
    out = bytearray()
    for row in range(n):
        out.append(0)
        y = (row + 0.5 - n / 2) * scale
        for col in range(n):
            x = (col + 0.5 - n / 2) * scale
            r, a = math.hypot(x, y), _deg(x, y)
            cr, cg, cb = BG
            for layer in layers:
                hit = layer(x, y, r, a)
                if hit is None:
                    continue
                dist, colour, alpha = hit
                cover = max(0.0, min(1.0, 0.5 - dist / scale)) * alpha
                if cover <= 0.0:
                    continue
                cr += (colour[0] - cr) * cover
                cg += (colour[1] - cg) * cover
                cb += (colour[2] - cb) * cover
            out += bytes((round(cr), round(cg), round(cb)))
    return out


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(icon: Icon) -> bytes:
    header = struct.pack(">IIBBBBB", icon.size, icon.size, 8, 2, 0, 0, 0)  # 8-bit RGB
    body = zlib.compress(bytes(pixels(icon)), 9)
    chunks = _chunk(b"IHDR", header) + _chunk(b"IDAT", body) + _chunk(b"IEND", b"")
    return b"\x89PNG\r\n\x1a\n" + chunks


def icon_named(name: str) -> Icon:
    for icon in ICONS:
        if icon.name == name:
            return icon
    raise KeyError(name)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--check", action="store_true", help="compare, write nothing")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    stale = []
    for icon in ICONS:
        raw, path = png(icon), args.out / icon.name
        if args.check:
            if not path.is_file() or path.read_bytes() != raw:
                stale.append(icon.name)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        print(f"wrote {path.name} ({len(raw):,} bytes)")
    if stale:
        print("icons differ from scripts/app_icons.py: " + ", ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

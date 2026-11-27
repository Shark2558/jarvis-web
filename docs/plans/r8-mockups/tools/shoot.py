#!/usr/bin/env python3
# docs/plans/r8-mockups/tools/shoot.py -- screenshots of every mockup state (Playwright + Chromium), a check pass on each
# (console errors, cut text, sideways overflow, WCAG contrast of every text line inside the new panels, computed from
# the rendered colours) and the contact sheet. Opens the pages as file:// URLs: no server.
# Usage: python -I tools/shoot.py [--only <page>] [--sheet-only] [--chrome <path to chrome>]
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
MOCKS = HERE.parent
PNG = MOCKS / "png"
THEMES = ("night", "day")
# (number, page, view, states) -- the order of the contact sheet
MATRIX = (
    (1, "camera-setup", "laptop", ("first", "active", "off", "warn", "error", "check")),
    (1, "camera-setup", "phone", ("active",)),
    (2, "desk-coach", "laptop", ("first", "active", "off", "warn", "error", "bp", "game")),
    (3, "workout-phone", "phone", ("first", "active", "off", "warn", "error")),
    (4, "activity-timeline", "laptop", ("first", "active", "off", "warn", "error")),
    (4, "activity-timeline", "phone", ("active",)),
)
TITLES = {"camera-setup": "Camera setup", "desk-coach": "Desk coach", "workout-phone": "Workout session (phone)",
          "activity-timeline": "Activity timeline and screen time"}
STATE_WORDS = {"first": "First use", "active": "Active", "off": "Camera off", "warn": "Warning", "error": "Error: camera blocked",
               "check": "No-cloud check", "bp": "BP posture checklist", "game": "Reaction game"}
SIZE = {"laptop": (1920, 1080, 1), "phone": (390, 844, 2)}

# runs in the page: every text line inside the new panels, its colour against the background it really sits on
CHECK_JS = r"""
() => {
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const rgba = (c) => { cx.clearRect(0, 0, 1, 1); cx.fillStyle = 'rgba(0,0,0,0)'; cx.fillStyle = c; cx.fillRect(0, 0, 1, 1);
    const d = cx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
  const over = (top, bot) => { const a = top[3]; return [0, 1, 2].map((i) => top[i] * a + bot[i] * (1 - a)).concat(1); };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  function bgOf(el) {
    const layers = []; let n = el;
    while (n && n.nodeType === 1) { const c = rgba(getComputedStyle(n).backgroundColor); if (c[3] > 0) { layers.push(c); if (c[3] >= 0.999) break; } n = n.parentElement; }
    let base = layers.length && layers[layers.length - 1][3] >= 0.999 ? layers.pop() : rgba(getComputedStyle(document.body).backgroundColor);
    if (base[3] < 0.999) base = [4, 7, 13, 1];
    while (layers.length) base = over(layers.pop(), base);
    return base;
  }
  function opacityOf(el) { let o = 1, n = el; while (n && n.nodeType === 1) { o *= parseFloat(getComputedStyle(n).opacity) || 1; n = n.parentElement; } return o; }
  const out = { contrast: [], cut: [], wide: [], min: 99 };
  const scope = [...document.querySelectorAll('.panel:not(#p-chat), .cam-chip')];
  const seen = new Set();
  scope.forEach((root) => root.querySelectorAll('*').forEach((el) => {
    if (seen.has(el)) return; seen.add(el);
    const own = [...el.childNodes].some((t) => t.nodeType === 3 && t.textContent.trim());
    const r = el.getBoundingClientRect();
    if (!own || r.width === 0 || r.height === 0) return;
    if (el.closest('[aria-hidden="true"]') || el.closest('svg') || el.closest('.sr-only') || el.disabled || el.closest('[disabled]') || el.closest('[aria-disabled="true"]')) return; // WCAG 1.4.3: inactive controls are exempt
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden') return;
    const bg = bgOf(el), fg0 = rgba(cs.color), op = opacityOf(el);
    const fg = over([fg0[0], fg0[1], fg0[2], fg0[3] * op], bg);
    const k = ratio(fg, bg), size = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight, 10) >= 700;
    const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
    const text = [...el.childNodes].filter((t) => t.nodeType === 3).map((t) => t.textContent.trim()).join(' ').slice(0, 48);
    out.min = Math.min(out.min, k);
    if (k < need) out.contrast.push(`${k.toFixed(2)} < ${need} "${text}"`);
    if ((cs.overflowX === 'hidden' || cs.overflowX === 'clip' || cs.textOverflow === 'ellipsis') && el.scrollWidth > el.clientWidth + 1) out.cut.push(`"${text}" ${el.scrollWidth}>${el.clientWidth}`);
  }));
  document.querySelectorAll('.panel:not(#p-chat) .pbody').forEach((b) => { if (b.scrollWidth > b.clientWidth + 1) out.wide.push(`${b.closest('.panel').id} ${b.scrollWidth}>${b.clientWidth}`); });
  out.min = Math.round(out.min * 100) / 100;
  return out;
}
"""


def shots(only: str | None) -> list[tuple[int, str, str, str, str]]:
    rows = []
    for num, page, view, states in MATRIX:
        if only and page != only:
            continue
        for theme in THEMES:
            for s in states:
                rows.append((num, page, view, s, theme))
    return rows


def name(num: int, page: str, view: str, state: str, theme: str) -> str:
    return f"{num}-{page}-{view}-{state}-{theme}.png"


def shoot(browser, only: str | None) -> int:
    PNG.mkdir(exist_ok=True)
    problems = 0
    report = {}
    for num, page, view, state, theme in shots(only):
        w, h, dsf = SIZE[view]
        ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=dsf, is_mobile=view == "phone",
                                  has_touch=view == "phone", reduced_motion="reduce")
        pg = ctx.new_page()
        errs: list[str] = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto((MOCKS / f"{page}.html").as_uri() + f"?v={view}&s={theme}&st={state}")
        pg.wait_for_selector("html[data-ready='1']", timeout=10000)
        pg.evaluate("document.fonts.ready")
        pg.wait_for_timeout(250)
        out = name(num, page, view, state, theme)
        pg.screenshot(path=str(PNG / out))
        res = pg.evaluate(CHECK_JS)
        res["errors"] = errs
        report[out] = res
        bad = res["contrast"] or res["cut"] or res["wide"] or errs
        problems += 1 if bad else 0
        print(f"{'!!' if bad else 'ok'} {out}  min contrast {res['min']}" + (f"  {json.dumps({k: v for k, v in res.items() if v and k != 'min'})}" if bad else ""))
        ctx.close()
    (HERE / "check-report.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    return problems


def sheet(browser) -> None:
    sections = []
    for num, page in ((1, "camera-setup"), (2, "desk-coach"), (3, "workout-phone"), (4, "activity-timeline")):
        cells = []
        for n, p, view, states in MATRIX:
            if p != page:
                continue
            for theme in THEMES:
                for s in states:
                    f = name(n, p, view, s, theme)
                    cells.append(f'<figure class="{view}"><img src="png/{f}" alt=""><figcaption><b>{STATE_WORDS[s]}</b>'
                                 f'<span>{view} · {theme}</span></figcaption></figure>')
        sections.append(f'<section><h2><span>{num}</span>{TITLES[page]}</h2><div class="grid">{"".join(cells)}</div></section>')
    html = ("<!doctype html><html><head><meta charset='utf-8'><style>"
            "body{margin:0;padding:36px 40px 40px;background:#04070D;color:#E6EDF6;font:15px/1.4 system-ui,sans-serif;width:2480px}"
            "h1{margin:0 0 4px;font:600 26px/1.2 ui-monospace,monospace;letter-spacing:.2em;text-transform:uppercase}"
            "p.v{margin:0 0 24px;color:#AEBACB;font:13px/1.4 ui-monospace,monospace;letter-spacing:.06em}"
            "section{margin:0 0 30px;padding:18px 18px 8px;border:1px solid #1d3550;border-radius:10px;background:#0A111B}"
            "h2{display:flex;align-items:center;gap:12px;margin:0 0 14px;font:600 18px/1 ui-monospace,monospace;letter-spacing:.16em;text-transform:uppercase;color:#2190FF}"
            "h2 span{display:grid;place-items:center;width:30px;height:30px;border-radius:50%;border:1px solid #2190FF}"
            ".grid{display:flex;flex-wrap:wrap;gap:14px 14px;align-items:flex-start}"
            "figure{margin:0 0 10px;display:flex;flex-direction:column;gap:6px}"
            "figure.laptop img{width:392px;height:220.5px}figure.phone img{width:150px;height:324.6px}"
            "img{display:block;border:1px solid #1d3550;border-radius:6px}"
            "figcaption{display:flex;flex-direction:column;gap:1px;max-width:392px}figcaption b{font-weight:600;font-size:14px}"
            "figcaption span{color:#97A4B8;font:12px/1.3 ui-monospace,monospace;letter-spacing:.08em;text-transform:uppercase}"
            "</style></head><body><h1>JARVIS R8 / R8.1 · new screens · mockups</h1>"
            "<p class='v'>Draft for the owner's approval · 28 Nov 2026 · the console's own look (Workshop theme), Night and Day · laptop 1920 × 1080, phone 390 × 844</p>"
            + "".join(sections) + "</body></html>")
    tmp = MOCKS / "contact-sheet.src.html"
    tmp.write_text(html, encoding="utf-8")
    try:
        ctx = browser.new_context(viewport={"width": 2560, "height": 1200}, device_scale_factor=1)
        pg = ctx.new_page()
        pg.goto(tmp.as_uri())
        pg.wait_for_load_state("load")
        pg.screenshot(path=str(MOCKS / "contact-sheet.png"), full_page=True)
        ctx.close()
    finally:
        tmp.unlink()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--sheet-only", action="store_true")
    ap.add_argument("--chrome", default="/opt/pw-browsers/chromium-1243/chrome-linux64/chrome")
    a = ap.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=a.chrome) if a.chrome and Path(a.chrome).exists() else p.chromium.launch()
        problems = 0 if a.sheet_only else shoot(browser, a.only)
        if not a.only:
            sheet(browser)
        browser.close()
    print(f"{problems} shot(s) with findings")
    return 0


if __name__ == "__main__":
    sys.exit(main())

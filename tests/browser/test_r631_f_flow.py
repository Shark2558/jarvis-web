# tests/browser/test_r631_f_flow.py -- R6.3.1 Part F (docs/plans/r6-3-1-book-at-build.md D3, D10):
# the Full book's flowcharts (console-book-flow.js) in a real Chromium, against the real app (mock
# brain) with the book routes stubbed (book_mocks.FakeBook) and the full book's two routes answered
# here: an index of three pages, a chapter with an 8-node "one conversation turn" flow, a module
# with a small "right" flow, and a card with no flow. R6.4 D1: the full book reads on its own page,
# /book/read (console-book-read-*.js), so these open it there, the owner's token in this tab.
#   - a page with a flow: a framed figure at the top of "How it works", the title as its caption, an SVG
#     (role="img", <title>, aria-describedby -> the steps list) with one card per node and one
#     connector and arrowhead per edge, each kind by its shape, pills off the cards
#   - the steps list: visually hidden, in order; "Show steps as a list" opens and closes it from
#     the keyboard (Tab, Enter, Space) with a visible focus ring
#   - a page without a flow reads exactly as before (no figure, the six sections)
#   - the phone: laid out "down", drawn 1:1 (text never under 12 px), no sideways scroll
#   - Night and Day: the console's own tokens, the console's visual gate (tests/test_ui_audit.py);
#     with R631F_SHOTS=<folder> each look is also saved as a picture for the owner
#   - a hostile or broken flow: text stays text, a flow with nothing to draw draws nothing
# ruff: noqa: E501 -- JavaScript evaluated in the page
from __future__ import annotations

import copy
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from book_mocks import RELEASE, TOKEN, FakeBook, j
from test_console import Console
from test_ui_audit import NAMELESS_JS, WRAP_JS, _assert_clean
from ui_checks import DOM_CHECKS_JS, FINISH_ANIMATIONS_JS

_pw = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser
SHOTS = os.environ.get("R631F_SHOTS", "")  # pictures only when asked for
SIZES = {"desktop": {"width": 1280, "height": 900}, "phone": {"width": 390, "height": 844}}
PAGES, FIG = "#brPage", "#brPage .bk-flow"  # R6.4 D1: the full book's own page
SEED = (
    "if (!sessionStorage.getItem('__seeded')) { sessionStorage.setItem('__seeded', '1');"
    f" sessionStorage.setItem('jarvis_book_token', '{TOKEN}'); }}"
)
CHAPTER, MODULE, CARD = "pg_chapter_turn", "pg_module_router", "pg_card_c01"
HEADINGS = [
    ("plain", "In plain words"), ("example", "Example (made up)"), ("how", "How it works"),
    ("costs", "What it costs"), ("fails", "When it fails"), ("code", "Where in the code"),
]  # fmt: skip
TURN: dict[str, Any] = {
    "title": "One conversation turn",
    "dir": "down",
    "nodes": [
        {"id": "owner", "label": "You", "kind": "person", "rank": 0, "col": 1},
        {"id": "console", "label": "Console", "kind": "step", "rank": 1, "col": 1,
         "ref": "src/jarvis/api/static/console.js"},
        {"id": "gateway", "label": "Tool gateway checks it", "kind": "guard", "rank": 2, "col": 1,
         "ref": "src/jarvis/tools/gateway.py"},
        {"id": "brain", "label": "Brain answers by tier", "kind": "service", "rank": 3, "col": 1,
         "ref": "src/jarvis/llm/router.py"},
        {"id": "memory", "label": "Session memory", "kind": "store", "rank": 3, "col": 2,
         "ref": "src/jarvis/memory/session.py"},
        {"id": "tools", "label": "Tools run", "kind": "step", "rank": 4, "col": 1,
         "ref": "src/jarvis/tools/registry.py"},
        {"id": "confirm", "label": "Your OK for R3 actions", "kind": "person", "rank": 4, "col": 0},
        {"id": "audit", "label": "Audit log", "kind": "store", "rank": 5, "col": 1,
         "ref": "src/jarvis/tools/audit.py"},
    ],
    "edges": [
        {"from": "owner", "to": "console", "label": "types"},
        {"from": "console", "to": "gateway", "label": "a request"},
        {"from": "gateway", "to": "brain", "label": "allowed"},
        {"from": "brain", "to": "memory", "label": "reads", "style": "side"},
        {"from": "brain", "to": "tools", "label": "a tool call", "style": "main"},
        {"from": "tools", "to": "confirm", "label": "R3 asks you", "style": "side"},
        {"from": "tools", "to": "audit", "label": "recorded"},
        {"from": "brain", "to": "console", "label": "the reply", "style": "side"},
    ],
}  # fmt: skip
ROUTER: dict[str, Any] = {
    "title": "The demo router",
    "dir": "right",
    "nodes": [
        {"id": "ask", "label": "A request", "kind": "person", "rank": 0, "col": 0},
        {"id": "router", "label": "Router picks a tier", "kind": "service", "rank": 1, "col": 0,
         "ref": "src/jarvis/demo/router.py"},
        {"id": "store", "label": "Note kept 30 days", "kind": "store", "rank": 2, "col": 0,
         "ref": "src/jarvis/demo/store.py"},
        {"id": "limit", "label": "demo_limit", "kind": "guard", "rank": 1, "col": 1},
    ],
    "edges": [
        {"from": "ask", "to": "router"},
        {"from": "router", "to": "store", "label": "keeps"},
        {"from": "router", "to": "limit", "label": "reads", "style": "side"},
    ],
}  # fmt: skip
STEPS = [
    "You \u2192 Console (types)",
    "Console \u2192 Tool gateway checks it (a request)",
    "Tool gateway checks it \u2192 Brain answers by tier (allowed)",
    "Brain answers by tier \u2192 Console (the reply; side path)",
    "Brain answers by tier \u2192 Session memory (reads; side path)",
    "Brain answers by tier \u2192 Tools run (a tool call)",
    "Tools run \u2192 Your OK for R3 actions (R3 asks you; side path)",
    "Tools run \u2192 Audit log (recorded)",
]


def page_json(pid: str, kind: str, title: str, flow: Any = None) -> dict[str, Any]:
    """GET /v1/book/pages/{id}: the six sections (made-up demo words), the optional `flow`."""
    words = {
        "plain": "The demo picks one tier for each request.",
        "example": "A made-up household asks for a reminder; 3 tries at most.",
        "how": "- The request arrives.\n- The router reads the setting.\n- One tier answers.",
        "costs": "Nothing by itself.",
        "fails": "When no brain answers, it says so plainly.",
        "code": "The router and its store.",
    }
    body = {
        "id": pid,
        "kind": kind,
        "title": title,
        "part": "parts",
        "chapter": "demo",
        "sections": [
            {
                "id": s,
                "heading": h,
                "text": words[s],
                "refs": ["src/jarvis/demo/router.py"] if s == "code" else [],
            }
            for s, h in HEADINGS
        ],  # fmt: skip
        "meta": None,
        "changed": False,
    }
    if flow is not None:
        body["flow"] = flow
    return body


def book(**flows: Any) -> dict[str, dict[str, Any]]:
    pages = {
        CHAPTER: page_json(CHAPTER, "chapter", "One conversation turn", TURN),
        MODULE: page_json(MODULE, "module", "The router module", ROUTER),
        CARD: page_json(CARD, "card", "Demo router"),
    }
    for pid, flow in flows.items():
        pages[pid] = page_json(pages[pid]["id"], pages[pid]["kind"], pages[pid]["title"], flow)
    return pages


def index(pages: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = [
        {"id": p["id"], "kind": p["kind"], "title": p["title"], "written": None, "changed": False}
        for p in pages.values()
    ]
    chapter = {"id": "demo", "title": "The demo", "pages": rows}
    return {
        "release": RELEASE["id"],
        "parts": [{"id": "parts", "title": "Parts", "chapters": [chapter]}],
        "limitations": {"shown": 0, "total": 0},
    }


def route_pages(page: Any, pages: dict[str, dict[str, Any]]) -> None:
    """After FakeBook: the full book's index and pages (Playwright tries the last routes first)."""

    def one(route: Any) -> None:
        pid = route.request.url.split("/v1/book/pages/", 1)[1].split("?", 1)[0]
        if pid in pages:
            return j(route, 200, pages[pid])
        return j(route, 404, {"error": "no_page", "detail": "That page isn't in this release."})

    for pattern in ("**/v1/book/pages", "**/v1/book/pages?*"):
        page.route(pattern, lambda route: j(route, 200, index(pages)))
    page.route("**/v1/book/pages/**", one)


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with _pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def reader(
    browser: Any, url: str, token: str, size: str = "desktop", surface: str = "night", **flows: Any
) -> Console:
    """The full book's page (/book/read) with an owner's book token in this tab."""
    c = Console(browser, url, token, SIZES[size])
    c.page.add_init_script(SEED)
    c.page.add_init_script(f"localStorage.setItem('jarvis_surface', '{surface}');")
    FakeBook(c.page)
    route_pages(c.page, book(**flows))
    c.page.goto(url + "/book/read")
    c.page.locator("#brTitle").wait_for()
    return c


IDS = {"One conversation turn": CHAPTER, "The router module": MODULE, "Demo router": CARD}


def read(c: Console, title: str) -> None:
    c.page.evaluate(f"location.hash = '{IDS[title]}'")
    c.page.locator("#brTitle", has_text=title).wait_for()


STABLE_JS = """(sel) => new Promise((ok) => {
  const was = document.querySelector(sel);
  requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(() => ok(!!was && document.querySelector(sel) === was), 150)));
})"""


def chart(c: Console) -> Any:
    """The chart once it has settled: the same SVG over two frames (a re-layout draws a new one)."""
    svg = c.page.locator(f"{FIG} svg.fl-svg")
    svg.wait_for()
    for _ in range(20):
        if c.page.evaluate(STABLE_JS, f"{FIG} svg.fl-svg"):
            break
    c.page.evaluate(FINISH_ANIMATIONS_JS)
    return svg


def clean(c: Console) -> None:
    assert c.errors == [] and c.csp_violations() == []


GEOMETRY_JS = """(fig) => {
  const svg = fig.querySelector('svg.fl-svg'), r = (e) => e.getBoundingClientRect();
  const cards = [...svg.querySelectorAll('.fl-node')].map((g) => r(g.querySelector('.fl-card')));
  const pills = [...svg.querySelectorAll('.fl-pill rect')].map(r);
  const hit = (a, b) => a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1;
  const pairs = (xs, ys) => xs.flatMap((a, i) => ys.filter((b, k) => (xs !== ys || k > i) && hit(a, b)));
  const vb = svg.viewBox.baseVal, box = r(svg), host = r(fig.querySelector('.bk-flowbox'));
  const texts = [...svg.querySelectorAll('text')].map((t) => {
    const b = r(t), g = t.closest('.fl-node, .fl-pill'), o = g ? r(g.querySelector('.fl-card, rect')) : null;
    return o ? (b.left >= o.left - 0.5 && b.right <= o.right + 0.5 && b.top >= o.top - 0.5 && b.bottom <= o.bottom + 0.5) : true;
  });
  return { cardOverlaps: pairs(cards, cards).length, pillOnCard: pairs(pills, cards).length, pillOverlaps: pairs(pills, pills).length,
    scale: box.width / vb.width, inHost: box.left >= host.left - 0.5 && box.right <= host.right + 0.5, textsInside: texts.every(Boolean) };
}"""


def test_r631_f_a_chapter_with_a_flow_shows_its_chart_above_how_it_works(
    browser: Any, server_url: str, token: str
) -> None:
    c = reader(browser, server_url, token)
    try:
        read(c, "One conversation turn")
        svg = chart(c)
        fig = c.page.locator(FIG)
        assert fig.locator("figcaption").inner_text().lower() == "one conversation turn"
        where = fig.evaluate(
            "(f) => [f.closest('.bk-sec').id, f.parentElement.previousElementSibling.textContent,"
            " f.parentElement.nextElementSibling.tagName]"
        )
        assert where == ["brSec-how", "How it works", "UL"]  # under its heading, above its words
        assert svg.get_attribute("role") == "img" and svg.get_attribute("data-dir") == "down"
        named = svg.evaluate(
            "(s) => document.getElementById(s.getAttribute('aria-labelledby')).textContent"
        )
        assert named == "One conversation turn" and svg.locator("> title").count() == 1
        assert c.page.get_by_role("img", name="One conversation turn").count() == 1
        motion = "(s) => getComputedStyle(s).animationName"
        assert svg.evaluate(motion) == "fadeIn"  # one fade, once
        c.page.emulate_media(reduced_motion="reduce")
        assert svg.evaluate(motion) == "none"
        steps = c.page.locator("#" + str(svg.get_attribute("aria-describedby")))
        assert steps.locator("li").all_text_contents() == STEPS
        assert svg.locator(".fl-node").count() == 8
        assert svg.locator(".fl-edge").count() == 8 and svg.locator(".fl-head").count() == 8
        assert (
            svg.locator(".fl-mains .fl-link").count() == 5
            and svg.locator(".fl-sides .fl-link").count() == 3
        )
        assert svg.locator(".fl-pill").count() == 8
        kinds = {
            k: svg.locator(f".fl-node.fl-k-{k}").count()
            for k in ("person", "step", "guard", "service", "store")
        }
        assert kinds == {"person": 2, "step": 2, "guard": 1, "service": 1, "store": 2}
        # the shape tells the kind: a lid on a store, a double border on a service, a pill person
        assert svg.locator(".fl-k-store .fl-lid").count() == 2
        assert svg.locator(".fl-k-service .fl-inner").count() == 1
        assert svg.locator(".fl-k-guard path.fl-card").count() == 1
        pill = svg.locator(".fl-k-person rect.fl-card").first
        assert float(pill.get_attribute("rx") or 0) * 2 == float(pill.get_attribute("height") or 0)
        assert svg.locator(".fl-glyph").count() == 8
        assert svg.locator('.fl-node[data-id="gateway"] .fl-ref').text_content() == "gateway.py"
        geo = fig.evaluate(GEOMETRY_JS)
        assert geo["cardOverlaps"] == 0 and geo["pillOnCard"] == 0 and geo["pillOverlaps"] == 0, geo
        assert geo["inHost"] and geo["textsInside"] and geo["scale"] >= 0.999, geo
        key = fig.locator(".bk-flowkey li").all_inner_texts()
        assert key == ["Step", "Store", "Service", "Guard", "Person", "Main path", "Side path"]
        clean(c)
    finally:
        c.close()


def test_r631_f_the_steps_list_opens_and_closes_from_the_keyboard(
    browser: Any, server_url: str, token: str
) -> None:
    c = reader(browser, server_url, token)
    try:
        read(c, "One conversation turn")
        svg = chart(c)
        steps = c.page.locator("#" + str(svg.get_attribute("aria-describedby")))
        assert (
            steps.evaluate("(e) => e.getBoundingClientRect().width") <= 1
        )  # hidden, still read out
        assert steps.locator(".bk-flowsteps-h").text_content() == "Steps in order"
        btn = c.page.locator(FIG).get_by_role("button", name="Show steps as a list")
        assert btn.get_attribute("aria-controls") == steps.get_attribute("id")
        c.page.locator("#brSec-how h2").evaluate("(h) => { h.tabIndex = -1; h.focus(); }")
        c.page.keyboard.press("Tab")  # the chart draws no stop of its own: the next is the toggle
        assert btn.evaluate("(b) => b === document.activeElement && b.matches(':focus-visible')")
        ring = btn.evaluate(
            "(b) => [getComputedStyle(b).outlineStyle, getComputedStyle(b).outlineWidth]"
        )
        assert ring[0] != "none" and ring[1] != "0px"
        c.page.keyboard.press("Enter")
        hide = c.page.locator(FIG).get_by_role("button", name="Hide the list")
        assert hide.get_attribute("aria-expanded") == "true"
        assert steps.evaluate("(e) => e.getBoundingClientRect().height") > 100
        assert steps.locator("li").first.is_visible()
        c.page.keyboard.press("Space")
        assert btn.get_attribute("aria-expanded") == "false"
        assert steps.evaluate("(e) => e.getBoundingClientRect().width") <= 1
        clean(c)
    finally:
        c.close()


def test_r631_f_a_page_without_a_flow_reads_as_before(
    browser: Any, server_url: str, token: str
) -> None:
    c = reader(browser, server_url, token)
    try:
        read(c, "Demo router")
        c.page.locator(f"{PAGES} details.bk-more", has_text="Where in the code").wait_for()
        c.page.wait_for_timeout(300)  # the module would have answered by now
        labels = c.page.locator(f"{PAGES} .bk-sec > .bk-h2").all_text_contents()
        assert labels == ["In plain words", "Example", "How it works", "What it costs", "When it fails"]
        assert c.page.locator(f"{PAGES} .bk-flow, {PAGES} .bk-fig, {PAGES} svg.fl-svg").count() == 0
        clean(c)
    finally:
        c.close()


def test_r631_f_right_in_a_wide_page_down_in_a_narrow_one(
    browser: Any, server_url: str, token: str
) -> None:
    """R6.4: the full book's page column (about 650 px of chart at 1280 px) lays this flow out
    "down"; given the whole window (rail and "On this page" put away), the chart lays itself out
    again in the flow's own direction, "right" (ResizeObserver), and back "down" when narrow."""
    wide = (
        "() => { for (const id of ['brRail', 'brToc']) document.getElementById(id).style.display = 'none';"
        " document.getElementById('brBody').style.gridTemplateColumns = '1fr';"
        " document.getElementById('brPage').style.maxWidth = 'none'; }"
    )
    c = reader(browser, server_url, token)
    try:
        read(c, "The router module")
        assert chart(c).get_attribute("data-dir") == "down"
        c.page.evaluate(wide)
        c.page.wait_for_function(
            "() => document.querySelector('#brPage .bk-flow svg.fl-svg').dataset.dir === 'right'"
        )
        geo = c.page.locator(FIG).evaluate(GEOMETRY_JS)
        assert geo["inHost"] and geo["scale"] >= 0.999 and geo["cardOverlaps"] == 0, geo
        assert c.page.locator(f"{FIG} .fl-node").count() == 4
        if SHOTS:
            Path(SHOTS).mkdir(parents=True, exist_ok=True)
            c.page.locator(FIG).screenshot(path=str(Path(SHOTS) / "flow-wide-panel-right.png"))
        c.page.evaluate("() => { document.getElementById('brPage').style.maxWidth = '420px'; }")
        c.page.wait_for_function(
            "() => document.querySelector('#brPage .bk-flow svg.fl-svg').dataset.dir === 'down'"
        )
        assert c.page.locator(f"{FIG} svg.fl-svg").count() == 1  # drawn again, not added to
        clean(c)
    finally:
        c.close()


@pytest.mark.parametrize("title", ["The router module", "One conversation turn"])
def test_r631_f_the_phone_lays_it_down_1_to_1_with_no_sideways_scroll(
    browser: Any, server_url: str, token: str, title: str
) -> None:
    c = reader(browser, server_url, token, "phone")
    try:
        read(c, title)
        svg = chart(c)
        assert svg.get_attribute("data-dir") == "down"
        geo = c.page.locator(FIG).evaluate(GEOMETRY_JS)
        assert geo["inHost"] and geo["scale"] >= 0.999 and geo["textsInside"], geo
        assert geo["cardOverlaps"] == 0 and geo["pillOnCard"] == 0 and geo["pillOverlaps"] == 0, geo
        sizes = svg.evaluate(
            "(s) => [...s.querySelectorAll('text')].map((t) => parseFloat(getComputedStyle(t).fontSize))"
        )
        assert min(sizes) >= 12  # drawn 1:1, so 12 px is 12 px on the screen
        wide = c.page.evaluate(
            """() => { const b = document.getElementById('brMain');
              return [document.documentElement.scrollWidth - innerWidth, b.scrollWidth - b.clientWidth]; }"""
        )
        assert wide[0] <= 0 and wide[1] <= 1, wide
        clean(c)
    finally:
        c.close()


SCREENS = [(s, f) for s in SIZES for f in ("night", "day")]


@pytest.mark.parametrize(("size", "surface"), SCREENS)
def test_r631_f_night_and_day_on_the_consoles_tokens_and_its_visual_gate(
    browser: Any, server_url: str, token: str, size: str, surface: str
) -> None:
    c = reader(browser, server_url, token, size, surface)
    try:
        read(c, "One conversation turn")
        chart(c)
        assert c.page.locator("html").get_attribute("data-surface") == surface
        paint = c.page.evaluate(
            """(sel) => { const s = document.querySelector(sel), v = (name) => { const d = document.createElement('i'); d.style.color = 'var(' + name + ')';
                document.body.append(d); const c = getComputedStyle(d).color; d.remove(); return c; };
              const cs = (sel, p) => getComputedStyle(s.querySelector(sel))[p];
              return { card: [cs('.fl-card', 'fill'), v('--well')], line: [cs('.fl-card', 'stroke'), v('--line')],
                main: [cs('.fl-mains .fl-edge', 'stroke'), v('--accent')], side: [cs('.fl-sides .fl-edge', 'stroke'), v('--ink-3')],
                ink: [cs('.fl-t', 'fill'), v('--ink')], ref: [cs('.fl-ref', 'fill'), v('--ink-3')],
                dash: cs('.fl-sides .fl-edge', 'strokeDasharray'), solid: cs('.fl-mains .fl-edge', 'strokeDasharray') }; }""",
            f"{FIG} svg.fl-svg",
        )
        for part in ("card", "line", "main", "side", "ink", "ref"):
            assert paint[part][0] == paint[part][1], (part, paint)
        assert paint["dash"] not in ("none", "") and paint["solid"] == "none"
        fig = c.page.locator(FIG)
        fig.scroll_into_view_if_needed()
        c.page.evaluate("() => document.fonts.ready.then(() => true)")
        c.page.evaluate(FINISH_ANIMATIONS_JS)
        vp = "phone" if size == "phone" else "desktop"
        res = c.page.evaluate(DOM_CHECKS_JS, FIG)
        assert not res.get("missing")
        what = f"flowchart {size} {surface}"
        _assert_clean(
            res, c.page.evaluate(NAMELESS_JS, FIG), c.page.evaluate(WRAP_JS, FIG), vp, what
        )
        if SHOTS:  # the page, then the whole figure (a taller window, the same width)
            folder = Path(SHOTS)
            folder.mkdir(parents=True, exist_ok=True)
            c.page.screenshot(path=str(folder / f"flow-{size}-{surface}.png"))
            c.page.set_viewport_size({"width": SIZES[size]["width"], "height": 1900})
            chart(c)
            fig.scroll_into_view_if_needed()
            fig.screenshot(path=str(folder / f"flow-{size}-{surface}-figure.png"))
            fig.get_by_role("button", name="Show steps as a list").click()
            fig.screenshot(path=str(folder / f"flow-{size}-{surface}-steps.png"))
        clean(c)
    finally:
        c.close()


def test_r631_f_text_stays_text_and_a_flow_with_nothing_to_draw_draws_nothing(
    browser: Any, server_url: str, token: str
) -> None:
    hostile = copy.deepcopy(TURN)
    hostile["title"] = "<img src=x onerror=alert(1)>"
    hostile["nodes"][0]["label"] = "<script>alert(1)</script>"
    hostile["nodes"].append({"id": "bad", "label": "x", "kind": "robot", "rank": 1, "col": 0})
    hostile["edges"].append({"from": "owner", "to": "nowhere"})
    empty = {"title": "Nothing", "dir": "down", "nodes": [TURN["nodes"][0]], "edges": []}
    c = reader(browser, server_url, token, **{CHAPTER: hostile, MODULE: empty})
    try:
        c.page.on("dialog", lambda d: d.dismiss())
        read(c, "One conversation turn")
        svg = chart(c)
        assert c.page.locator(f"{FIG} figcaption").text_content() == "<img src=x onerror=alert(1)>"
        assert svg.locator(".fl-node").count() == 8 and svg.locator(".fl-edge").count() == 8
        assert "<script>" in (svg.locator('.fl-node[data-id="owner"]').text_content() or "")
        assert c.page.locator(f"{PAGES} img, {PAGES} script").count() == 0
        read(c, "The router module")
        c.page.wait_for_timeout(300)
        assert c.page.locator(f"{PAGES} .bk-flow, {PAGES} .bk-fig").count() == 0
        clean(c)
    finally:
        c.close()


SWEEP_JS = """async ([flows]) => {
  const m = await import('/static/console-book-flow-layout.js');
  const big = { title: 'Fourteen nodes', dir: 'right', nodes: [], edges: [] };
  for (let i = 0; i < 14; i += 1) big.nodes.push({ id: 'n' + i, label: 'Step number ' + i + ' of the long flow', kind: m.KINDS ? Object.keys(m.KINDS)[i % 5] : 'step', rank: Math.floor(i / 2) % 10, col: (i * 7) % 6, ref: 'src/jarvis/x/' + i + '.py' });
  for (let i = 0; i < 24; i += 1) big.edges.push({ from: 'n' + (i % 14), to: 'n' + ((i * 5 + 3) % 14), label: i % 3 ? 'edge ' + i : '', style: i % 4 ? 'main' : 'side' });
  const out = [];
  for (const raw of [...flows, big]) {
    const spec = m.normalFlow(raw);
    for (let w = 240; w <= 1240; w += 37) {
      const a = m.layout(spec, w), b = m.layout(spec, w);
      out.push({ title: spec.title, w, dir: a.dir, vbw: a.vb[2], same: JSON.stringify(a) === JSON.stringify(b),
        nodes: a.cards.length, edges: a.edges.filter((e) => e.pts.length > 1).length, pills: a.pills.length,
        labels: spec.edges.filter((e) => e.label).length, edgesIn: spec.edges.length, nodesIn: spec.nodes.length });
    }
  }
  return out;
}"""


def test_r631_f_the_layout_is_the_same_every_time_and_fits_its_room(
    browser: Any, server_url: str, token: str
) -> None:
    """Every width from 240 to 1240 px, for both sample flows and a 14-node, 24-edge one: the same
    spec and room give the same chart; under 560 px it is "down" and never wider than its room;
    every node, edge and label is drawn."""
    c = reader(browser, server_url, token)
    try:
        rows = c.page.evaluate(SWEEP_JS, [[TURN, ROUTER]])
        assert len(rows) == 3 * 28
        for r in rows:
            assert r["same"], r
            assert r["nodes"] == r["nodesIn"] and r["edges"] == r["edgesIn"], r
            assert r["pills"] == r["labels"], r
            if r["w"] < 560:
                assert r["dir"] == "down" and r["vbw"] <= r["w"] + 0.5, r
            if r["dir"] == "right":
                assert r["vbw"] <= r["w"] + 0.5, r
        clean(c)
    finally:
        c.close()

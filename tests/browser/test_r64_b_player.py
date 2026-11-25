# tests/browser/test_r64_b_player.py -- R6.4 builder B (docs/plans/r6-4-book-look.md D7, D11; workbook rows 390, 394):
# the narrated chapter player on /book/read and its effects engine, played with the REAL Vault chapter and pages
# (r64_chapter_fakes.serve_vault) and a browser voice under the test's control (no real audio). Open and play line by
# line; pause, skip lines and pages, Stop back to the page being told; the tour's keys; the caption's words lit as they
# are said (boundaries, else the timed estimate); the lit box follows node cues and survives the chart's redraw; a count
# counts up to its number; Pause leaves no running animation (WCAG 2.2.2); reduced motion runs no Web Animation and Off
# none at all; nothing repeats faster than 3 times a second; the picker never repeats a variant back to back and spreads
# every family; continue where I left off keeps the tour's and the reader's fields; a failed load says so plainly; the
# cloud-voice note; a hidden tab pauses; the phone's 44 px controls; the new colour pairs reach AA on Night and Day.
# ruff: noqa: E501 -- JavaScript strings
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from book_mocks import RELEASE, TOKEN, FakeBook
from r64_chapter_fakes import HOLD, LINES, PAGES, SPEECH, ChapterBook, first_line, serve_vault
from test_console import DESKTOP, PHONE, Console

_pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

SEED = """
if (!sessionStorage.getItem('__seeded')) {
  sessionStorage.setItem('__seeded', '1');
  sessionStorage.setItem('jarvis_book_token', '%s');
  sessionStorage.setItem('jarvis_book_session', JSON.stringify({ audience: 'owner', session_id: 'bk_0123456789abcdef' }));
}
"""
IN_PLAYER = "(a) => a.effect && a.effect.target && document.getElementById('brPlayer').contains(a.effect.target)"
FAMILY_SEQ = """async ({ lines, flows, seed }) => {
  const P = await import('/static/console-book-fx-plan.js');
  const out = {};
  P.plan(seed, lines, flows).forEach((x) => Object.entries(x.fx).forEach(([k, v]) => { if (typeof v === 'string' && v) (out[k] = out[k] || []).push(v); }));
  const fams = {};
  Object.entries(P.FAMILIES).forEach(([k, vs]) => { fams[k] = vs.slice(); });
  const dealt = {};
  Object.keys(P.FAMILIES).forEach((k) => { const d = P.dealer(seed); dealt[k] = Array.from({ length: 40 }, (_, n) => d(k, n + 1)); });
  return { out, fams, dealt };
}"""


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with _pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _player(browser: Any, url: str, token: str, *, viewport: dict[str, int] = DESKTOP, speech: str = HOLD,
            motion: str = "full", surface: str = "night", reduced: bool = False, init: str = "") -> tuple[Console, FakeBook, ChapterBook]:  # fmt: skip
    c = Console(browser, url, token, viewport)
    c.page.add_init_script(SEED % TOKEN)
    c.page.add_init_script(
        f"try {{ localStorage.setItem('jarvis_motion', '{motion}'); localStorage.setItem('jarvis_surface', '{surface}'); }} catch (_) {{}}"
    )
    c.page.add_init_script(speech)
    if init:
        c.page.add_init_script(init)
    if reduced:
        c.page.emulate_media(reduced_motion="reduce")
    fake = FakeBook(c.page)
    book = serve_vault(c.page, fake)
    c.page.goto(url + "/book/read")
    c.page.locator("#bookRead[data-state=ready]").wait_for()
    return c, fake, book


def _open(c: Console, line: int | None = None) -> bool:
    arg = "" if line is None else f", {{ line: {line} }}"
    return bool(c.page.evaluate(f"window.JarvisBookChapter.open('module_vault'{arg})"))


def _state(c: Console) -> dict[str, Any]:
    return dict(c.page.evaluate("window.JarvisBookChapter.state()"))


def _at(c: Console, n: int) -> None:
    c.page.wait_for_function(f"() => window.JarvisBookChapter.state().line === {n}")


def _clean(c: Console, *expected: int) -> None:
    said = [f"status of {code} " for code in expected]
    errors = [e for e in c.errors if not any(s in e for s in said)]
    assert errors == [] and c.csp_violations() == []


def test_play_tells_the_vault_chapter_line_by_line_with_its_pages(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake, _ = _player(browser, server_url, token)
    try:
        assert _open(c) is True
        p = c.page
        assert p.locator("#bookRead").get_attribute("data-mode") == "player"
        assert p.locator("#brPlayer").is_visible() and p.locator(".bk-body").is_hidden()
        (got,) = fake.to("GET", "/v1/book/chapters/module_vault")
        assert got["headers"]["x-jarvis-book"] == TOKEN
        assert sorted(
            x["path"].rsplit("/", 1)[-1]
            for x in fake.calls
            if x["path"].startswith("/v1/book/pages/")
        ) == sorted(PAGES)
        assert p.locator("#brPTitle").inner_text() == "Vault and documents"
        assert p.locator("#brPSteps .step").count() == 5
        assert p.locator("#brPCapText").inner_text() == LINES[0]["text"]
        assert p.locator("#brPPageOf").inner_text() == "Page 1 of 5"
        st = _state(c)
        assert (
            st["open"]
            and st["playing"]
            and st["chapter"] == "module_vault"
            and st["line"] == 1
            and st["page"] == "pg_module_vault"
        )
        p.wait_for_function("() => window.__said.length === 1")
        p.evaluate("window.__endLine()")
        _at(c, 2)
        assert p.locator("#brPCapText").inner_text() == LINES[1]["text"]
        said = p.evaluate("window.__said")
        assert [s["text"] for s in said[:2]] == [LINES[0]["text"], LINES[1]["text"]] and said[0][
            "rate"
        ] == 1
        assert fake.to("POST", "/v1/book/show/speak") == []  # always the browser's voice
        _clean(c)
    finally:
        c.close()


def test_controls_pause_skip_lines_and_pages_and_stop_back_to_the_page_told(
    browser: Any, server_url: str, token: str
) -> None:
    c, _, _ = _player(browser, server_url, token)
    try:
        p = c.page
        _open(c)
        p.evaluate(
            "window.__stopped = []; document.addEventListener('jarvis:book-chapter', (e) => window.__stopped.push(e.detail))"
        )
        p.locator("#brPPlay").click()
        assert (
            _state(c)["playing"] is False
            and p.locator("#brPPlay").get_attribute("aria-label") == "Play (Space)"
        )
        p.locator("#brPNextLine").click()
        _at(c, 2)
        p.locator("#brPPrevLine").click()
        _at(c, 1)
        p.locator("#brPNextPage").click()
        _at(c, 25)
        assert (
            p.locator("#brPPageOf").inner_text() == "Page 2 of 5"
            and _state(c)["page"] == "pg_card_c07"
        )
        assert p.locator("#brPSteps li.now b").inner_text() == "Attached documents"
        assert p.locator("#brPSteps li.done").count() == 1
        p.locator("#brPNextPage").click()
        _at(c, 40)
        p.locator("#brPPrevPage").click()
        _at(c, 25)
        assert _state(c)["playing"] is False  # skipping while paused stays paused
        p.locator("#brPPlay").click()
        assert _state(c)["playing"] is True
        p.locator("#brPStop").click()
        assert (
            p.locator("#brPlayer").is_hidden()
            and p.locator("#bookRead").get_attribute("data-mode") is None
        )
        (detail,) = p.evaluate("window.__stopped")
        assert detail == {
            "action": "stop",
            "chapter": "module_vault",
            "page": "pg_card_c07",
            "line": 25,
            "release": RELEASE["id"],
        }
        assert _state(c)["open"] is False
        _clean(c)
    finally:
        c.close()


def test_the_tours_keys_drive_the_player(browser: Any, server_url: str, token: str) -> None:
    c, _, _ = _player(browser, server_url, token)
    try:
        p, k = c.page, c.page.keyboard
        _open(c)
        k.press("Space")
        assert _state(c)["playing"] is False
        k.press("ArrowRight")
        _at(c, 2)
        k.press("ArrowLeft")
        _at(c, 1)
        k.press("PageDown")
        _at(c, 25)
        k.press("PageUp")
        _at(c, 1)
        k.press("c")
        assert (
            p.locator("#brPCap").is_hidden()
            and p.locator("#brPCC").get_attribute("aria-pressed") == "false"
        )
        k.press("C")
        assert p.locator("#brPCap").is_visible()
        k.press("m")
        assert (
            p.locator("#brPSound").get_attribute("aria-pressed") == "false"
            and p.locator("#brPSound").text_content() == "Muted"
        )
        k.press("Space")
        assert _state(c)["playing"] is True
        k.press("Escape")
        assert _state(c)["open"] is False and p.locator("#brPlayer").is_hidden()
        _clean(c)
    finally:
        c.close()


def test_the_caption_lights_the_words_as_they_are_said(
    browser: Any, server_url: str, token: str
) -> None:
    c, _, _ = _player(browser, server_url, token, init="window.__speech.ms = 250;")
    try:
        p = c.page
        _open(c)
        p.wait_for_function("() => document.querySelectorAll('#brPCapText .w.on').length >= 2")
        lit = p.evaluate("""(() => { const all = [...document.querySelectorAll('#brPCapText .w')], on = all.filter((w) => w.classList.contains('on'));
          const css = getComputedStyle(document.documentElement);
          return { on: on.length, all: all.length, first: getComputedStyle(all[0]).color, last: getComputedStyle(all[all.length - 1]).color,
            ink: getComputedStyle(document.body).color }; })()""")
        assert 2 <= lit["on"] < lit["all"]
        assert (
            lit["first"] == lit["ink"] and lit["last"] != lit["ink"]
        )  # said in --ink, the rest in --ink-2
        p.wait_for_function(
            "() => document.querySelectorAll('#brPCapText .w.on').length === document.querySelectorAll('#brPCapText .w').length"
        )
        # no boundaries from the voice: the timed estimate lights the words
        p.locator("#brPPlay").click()
        p.evaluate("window.__speech.boundaries = false")
        p.locator("#brPNextLine").click()
        _at(c, 2)
        assert p.locator("#brPCapText .w.on").count() == 0
        p.locator("#brPPlay").click()
        p.wait_for_function(
            "() => document.querySelectorAll('#brPCapText .w.on').length >= 1", timeout=4000
        )
        _clean(c)
    finally:
        c.close()


def test_the_lit_box_follows_node_cues_and_survives_a_redraw(
    browser: Any, server_url: str, token: str
) -> None:
    c, _, _ = _player(browser, server_url, token)
    try:
        p = c.page
        n = LINES[first_line("node", "kind")]["n"]
        _open(c, n)
        _at(c, n)
        lit = """(() => { const s = document.querySelector('#brPStage svg.fl-svg'); if (!s) return null;
          const ids = (cls) => [...s.querySelectorAll('g.fl-node.' + cls)].map((g) => g.getAttribute('data-id'));
          return { told: s.classList.contains('fl-told'), now: ids('fl-now'), done: ids('fl-done'), old: !!s.__old }; })()"""
        p.wait_for_function(f"() => {{ const x = {lit}; return x && x.now.length === 1; }}")
        got = p.evaluate(lit)
        assert got["told"] and got["now"] == ["kind"] and got["done"] == ["file"]
        assert p.locator("#brPStage .fx-layer.fx-chart").get_attribute("data-on") == "1"
        p.evaluate("document.querySelector('#brPStage svg.fl-svg').__old = true")
        p.set_viewport_size(PHONE)  # the chart lays itself out again for the narrow stage
        p.wait_for_function(f"() => {{ const x = {lit}; return x && !x.old; }}")
        got = p.evaluate(lit)
        assert got["told"] and got["now"] == ["kind"] and got["done"] == ["file"]
        p.evaluate("window.__endLine()")  # [edge:kind>refused]
        _at(c, n + 1)
        p.wait_for_function(f"() => {{ const x = {lit}; return x && x.now[0] === 'refused'; }}")
        assert sorted(p.evaluate(lit)["done"]) == ["file", "kind"]
        _clean(c)
    finally:
        c.close()


def test_a_count_counts_up_to_the_filled_number(browser: Any, server_url: str, token: str) -> None:
    c, _, _ = _player(browser, server_url, token)
    try:
        p = c.page
        i = first_line("count", "10")
        seen = p.evaluate(
            """async (n) => {
          const seen = []; const t = setInterval(() => { const n = document.querySelector('#brPStage .fx-num'); if (n && seen[seen.length - 1] !== n.textContent) seen.push(n.textContent); }, 16);
          await window.JarvisBookChapter.open('module_vault', { line: n });
          await new Promise((r) => setTimeout(r, 2200)); clearInterval(t); return seen; }""",
            LINES[i]["n"],
        )
        assert seen[-1] == "10" and len(seen) >= 3, seen
        assert [int(v) for v in seen] == sorted(int(v) for v in seen)  # it only counts up
        assert p.locator("#brPStage .fx-unit").inner_text() == "files"
        _clean(c)
    finally:
        c.close()


def test_pause_leaves_no_running_animation(browser: Any, server_url: str, token: str) -> None:
    c, _, _ = _player(browser, server_url, token)
    try:
        p = c.page
        _open(c, LINES[first_line("node", "kind")]["n"])
        p.wait_for_function(
            f"() => document.getAnimations().filter({IN_PLAYER}).some((a) => a.playState === 'running')"
        )
        p.locator("#brPPlay").click()
        running = f"document.getAnimations().filter({IN_PLAYER}).filter((a) => a.playState === 'running').length"
        assert p.evaluate(running) == 0
        assert p.locator("#brPlayer").get_attribute("data-fx") == "paused"
        p.wait_for_timeout(400)
        assert (
            p.evaluate("document.getAnimations().filter((a) => a.playState === 'running').length")
            == 0
        )
        p.locator("#brPPlay").click()
        assert p.locator("#brPlayer").get_attribute("data-fx") is None
        _clean(c)
    finally:
        c.close()


@pytest.mark.parametrize("how", ["reduced", "off"])
def test_reduced_motion_runs_no_web_animation_and_off_none_at_all(
    browser: Any, server_url: str, token: str, how: str
) -> None:
    c, _, _ = _player(
        browser,
        server_url,
        token,
        speech=SPEECH,
        motion="off" if how == "off" else "full",
        reduced=how == "reduced",
    )
    try:
        p = c.page
        seen = p.evaluate(
            """async (n) => {
          const inP = """
            + IN_PLAYER
            + """, kinds = new Set();
          const t = setInterval(() => document.getAnimations().filter(inP).forEach((a) => kinds.add(a.constructor.name)), 10);
          await window.JarvisBookChapter.open('module_vault', { line: n });
          await new Promise((r) => setTimeout(r, 2500)); clearInterval(t);
          return { kinds: [...kinds], st: window.JarvisBookChapter.state() }; }""",
            LINES[first_line("show", "overview")]["n"],
        )
        assert (
            seen["st"]["line"] > LINES[first_line("show", "overview")]["n"]
        )  # several lines went by
        assert (
            seen["st"]["fx"]["motion"] == ("calm" if how == "reduced" else "off")
            and seen["st"]["fx"]["ambient"] is False
        )
        assert (
            "Animation" not in seen["kinds"]
        )  # no Web Animation: no camera move, no packet, no entrance
        if how == "off":
            assert seen["kinds"] == []  # no animation of any kind: instant states
        else:
            assert set(seen["kinds"]) <= {"CSSTransition"}  # cross-fades only
        _clean(c)
    finally:
        c.close()


def test_nothing_repeats_faster_than_three_times_a_second(
    browser: Any, server_url: str, token: str
) -> None:
    c, _, _ = _player(browser, server_url, token, speech=SPEECH)
    try:
        got = c.page.evaluate(
            """async () => {
          const inP = """
            + IN_PLAYER
            + """, fast = [], cls = new Set(); let count = 0;
          const t = setInterval(() => document.getAnimations().filter(inP).forEach((a) => {
            count += 1; const tm = a.effect.getComputedTiming();
            if ((tm.iterations > 1 || tm.iterations === Infinity) && tm.duration < 334) fast.push([a.effect.target.getAttribute('class'), tm.duration]);
            cls.add(String(a.effect.target.getAttribute('class') || a.effect.target.tagName).split(' ')[0]); }), 25);
          await window.JarvisBookChapter.open('module_vault');
          await new Promise((r) => setTimeout(r, 7000)); clearInterval(t);
          return { fast, cls: [...cls], count, line: window.JarvisBookChapter.state().line }; }"""
        )
        assert got["fast"] == [] and got["count"] > 20, got
        assert got["line"] > 20  # the chart's and the cards' effects all went by
        _clean(c)
    finally:
        c.close()


def test_the_picker_never_repeats_and_spreads_every_family(
    browser: Any, server_url: str, token: str
) -> None:
    c, _, _ = _player(browser, server_url, token)
    try:
        flows = {pid: pg["flow"] for pid, pg in PAGES.items() if pg.get("flow")}
        a = c.page.evaluate(FAMILY_SEQ, {"lines": LINES, "flows": flows, "seed": "module_vault"})
        again = c.page.evaluate(
            FAMILY_SEQ, {"lines": LINES, "flows": flows, "seed": "module_vault"}
        )
        other = c.page.evaluate(
            FAMILY_SEQ, {"lines": LINES, "flows": flows, "seed": "module_brain"}
        )
        assert a == again  # deterministic: the chapter id and the line numbers
        assert a["out"] != other["out"]  # another chapter, another choreography
        for fam, seq in a["out"].items():
            if fam == "accent":  # by kind, not dealt
                continue
            assert all(x != y for x, y in zip(seq, seq[1:], strict=False)), (fam, seq)
            assert set(seq) == set(a["fams"][fam]), (
                fam,
                seq,
            )  # every variant appears in the chapter
        assert set(a["out"]["accent"]) == {"lock", "fill", "turn", "wave", "nudge"}
        for fam, seq in a["dealt"].items():  # 40 deals: no repeat, every variant in each round
            size = len(a["fams"][fam])
            assert all(x != y for x, y in zip(seq, seq[1:], strict=False)), fam
            for r in range(0, 40 - size + 1, size):
                assert sorted(seq[r : r + size]) == sorted(a["fams"][fam]), (fam, r, seq)
        _clean(c)
    finally:
        c.close()


def test_continue_where_i_left_off_keeps_the_other_parts_fields(
    browser: Any, server_url: str, token: str
) -> None:
    rid = RELEASE["id"]
    mine = f"if (!localStorage.getItem('jarvis_book_place_v1')) localStorage.setItem('jarvis_book_place_v1', JSON.stringify({{ release: '{rid}', scene: 3, page: 'pg_card_c42' }}));"
    c, _, _ = _player(browser, server_url, token, init=mine)
    try:
        p = c.page
        place = "JSON.parse(localStorage.getItem('jarvis_book_place_v1'))"
        _open(c)
        p.wait_for_function(f"() => {place}.line === 1")
        p.evaluate("window.__endLine()")
        p.wait_for_function(f"() => {place}.line === 2")
        assert p.evaluate(place) == {
            "release": rid,
            "scene": 3,
            "page": "pg_card_c42",
            "chapter": "module_vault",
            "line": 2,
        }
        p.locator("#brPStop").click()
        assert p.evaluate(f"window.JarvisBookChapter.place('{rid}')") == {
            "chapter": "module_vault",
            "line": 2,
        }
        _open(c, 25)
        _at(c, 25)
        assert p.locator("#brPPageOf").inner_text() == "Page 2 of 5"
        _clean(c)
    finally:
        c.close()
    theirs = "localStorage.setItem('jarvis_book_place_v1', JSON.stringify({ release: 'abcdef1', scene: 4 }));"
    c, _, _ = _player(browser, server_url, token, init=theirs)
    try:
        _open(c)
        c.page.evaluate("window.__endLine()")
        _at(c, 2)
        assert json.loads(c.page.evaluate("localStorage.getItem('jarvis_book_place_v1')")) == {
            "release": "abcdef1",
            "scene": 4,
        }
        _clean(c)
    finally:
        c.close()


def test_a_failed_load_says_so_plainly_and_goes_back_to_reading(
    browser: Any, server_url: str, token: str
) -> None:
    c, _, book = _player(browser, server_url, token)
    book.chapter_status = 503
    try:
        p = c.page
        assert _open(c) is False
        assert (
            p.locator("#brPMsgText").inner_text()
            == "This chapter can\u2019t be loaded right now. Try again in a moment."
        )
        assert p.locator("#brPAgain").is_hidden()
        p.locator("#brPBack").click()
        assert (
            p.locator("#brPlayer").is_hidden()
            and p.locator("#bookRead").get_attribute("data-mode") is None
        )
        _clean(c, 503)
    finally:
        c.close()


def test_with_the_cloud_voice_chosen_the_player_says_chapters_use_the_browsers_voice(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake, _ = _player(browser, server_url, token)
    fake.settings["show_voice"] = "cloud"
    try:
        p = c.page
        _open(c)
        p.locator("#brPNote").wait_for()
        assert "browser\u2019s voice" in p.locator("#brPNote").inner_text()
        p.wait_for_function("() => window.__said.length >= 1")
        assert fake.to("POST", "/v1/book/show/speak") == []
        _clean(c)
    finally:
        c.close()


def test_a_hidden_tab_pauses_and_a_return_plays_on_only_if_it_was_playing(
    browser: Any, server_url: str, token: str
) -> None:
    c, _, _ = _player(browser, server_url, token)
    hide = "(h) => { Object.defineProperty(document, 'hidden', { value: h, configurable: true }); document.dispatchEvent(new Event('visibilitychange')); }"
    try:
        p = c.page
        _open(c)
        p.evaluate(hide, True)
        assert _state(c)["playing"] is False
        p.evaluate(hide, False)
        assert _state(c)["playing"] is True
        p.locator("#brPPlay").click()
        p.evaluate(hide, True)
        p.evaluate(hide, False)
        assert _state(c)["playing"] is False  # paused by the owner: it stays paused
        _clean(c)
    finally:
        c.close()


def test_the_phone_player_keeps_44px_controls_and_no_sideways_scroll(
    browser: Any, server_url: str, token: str
) -> None:
    c, _, _ = _player(browser, server_url, token, viewport=PHONE)
    try:
        p = c.page
        _open(c)
        boxes = p.evaluate(
            "[...document.querySelectorAll('#brPlayer .bk-ctl button')].filter((b) => b.offsetParent).map((b) => { const r = b.getBoundingClientRect(); return [b.id, r.width, r.height, r.right]; })"
        )
        assert {b[0] for b in boxes} >= {
            "brPPrevLine",
            "brPPlay",
            "brPNextLine",
            "brPCC",
            "brPSound",
            "brPStop",
        }
        assert all(w >= 44 and h >= 44 and right <= 390 for _, w, h, right in boxes), boxes
        assert p.evaluate("document.documentElement.scrollWidth") <= 390
        assert p.locator("#brPCapText").is_visible() and p.locator("#brPSteps").is_hidden()
        assert "page 1 of 5" in str(p.locator("#brPlayer .bk-side").text_content()).lower()
        _clean(c)
    finally:
        c.close()


CONTRAST = """(sel) => {
  const parse = (s) => { const m = /rgba?\\(([^)]+)\\)/.exec(s) || /color\\(srgb ([^)]+)\\)/.exec(s); if (!m) return null;
    const v = m[1].replace('/', ' ').split(/[\\s,]+/).filter(Boolean).map(Number); const isSrgb = s.startsWith('color(');
    return { r: isSrgb ? v[0] * 255 : v[0], g: isSrgb ? v[1] * 255 : v[1], b: isSrgb ? v[2] * 255 : v[2], a: v.length > 3 ? v[3] : 1 }; };
  const over = (top, bot) => ({ r: top.r * top.a + bot.r * (1 - top.a), g: top.g * top.a + bot.g * (1 - top.a), b: top.b * top.a + bot.b * (1 - top.a), a: 1 });
  const lum = (c) => { const f = (x) => { x /= 255; return x <= 0.04045 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const bgOf = (el) => { const layers = []; for (let n = el; n && n.nodeType === 1; n = n.parentElement) { const c = parse(getComputedStyle(n).backgroundColor); if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; } }
    let acc = parse(getComputedStyle(document.documentElement).backgroundColor) || { r: 0, g: 0, b: 0, a: 1 }; for (let i = layers.length - 1; i >= 0; i -= 1) acc = over(layers[i], acc); return acc; };
  const el = document.querySelector(sel.fg); if (!el) return null;
  const st = getComputedStyle(el); let fg = parse(sel.svg ? st.fill : st.color);
  let bg = sel.bgFill ? parse(getComputedStyle(document.querySelector(sel.bgFill)).fill) : null;
  const base = bgOf(sel.svg ? document.querySelector('#brPStage .bk-flow') : el);
  bg = bg ? over(bg, base) : base; fg = over(fg, bg);
  const a = lum(fg), b = lum(bg); return Math.round(((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)) * 100) / 100; }"""


@pytest.mark.parametrize("surface", ["night", "day"])
def test_the_new_colour_pairs_reach_aa(
    browser: Any, server_url: str, token: str, surface: str
) -> None:
    c, _, _ = _player(browser, server_url, token, surface=surface, motion="off")
    try:
        p = c.page
        found: dict[str, float] = {}

        def pair(name: str, **sel: Any) -> None:
            p.wait_for_selector(sel["fg"], state="attached")
            found[name] = p.evaluate(CONTRAST, sel)

        node = LINES[first_line("node", "kind")]["n"]
        _open(c, node)
        _at(c, node)
        p.wait_for_function("() => document.querySelectorAll('#brPCapText .w.on').length >= 1")
        pair("caption, said", fg="#brPCapText .w.on")
        pair("caption, still to say", fg="#brPCapText .w:not(.on)")
        pair(
            "spoken box label",
            fg="#brPStage .fl-node.fl-now .fl-t",
            bgFill="#brPStage .fl-node.fl-now .fl-card",
            svg=True,
        )
        pair(
            "box not yet told",
            fg="#brPStage .fl-node:not(.fl-now):not(.fl-done) .fl-t",
            bgFill="#brPStage .fl-node:not(.fl-now):not(.fl-done) .fl-card",
            svg=True,
        )
        p.locator("#brPPlay").click()
        for target, names in ((first_line("count", "10"), ("readout number", "readout unit")),
                              (first_line("show", "plain"), ("card label", "card point")),
                              (first_line("show", "fails"), ("failure label", "failure point"))):  # fmt: skip
            while _state(c)["line"] != LINES[target]["n"]:
                p.keyboard.press(
                    "ArrowRight" if _state(c)["line"] < LINES[target]["n"] else "ArrowLeft"
                )
            if names[0].startswith("readout"):
                pair(names[0], fg="#brPStage .fx-num")
                pair(names[1], fg="#brPStage .fx-unit")
            else:
                pair(names[0], fg="#brPStage .fx-layer[data-on='1'] .fx-k")
                pair(names[1], fg="#brPStage .fx-layer[data-on='1'] .fx-pt.cur")
        p.keyboard.press("PageDown")
        pair("step done number", fg="#brPSteps li.done .no")
        pair("step now number", fg="#brPSteps li.now .no")
        print(surface, found)
        assert all(v >= 4.5 for v in found.values()), (surface, found)
        _clean(c)
    finally:
        c.close()

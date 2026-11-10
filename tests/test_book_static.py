# tests/test_book_static.py -- R6 D (docs/plans/r6-build-book.md D13, D15, D16, "Rules and gate"):
# the Book panel and the show's static assets. Sizes (R6 modules <= 400 lines, CSS <= 300), ASCII,
# no HTML sinks, three.js only from the vendored ES module, the scene modules split as the plan
# says, the show's lines never hard-coded in JS (they come from the server script), the token only
# in this tab's sessionStorage and sent as X-Jarvis-Book, and the owner's standing rule: no new
# colours, fonts, radii or shadows (the console's own tokens only).
from __future__ import annotations

import re
from pathlib import Path

import pytest

from jarvis.buildbook.lines import LINES

STATIC = Path(__file__).resolve().parents[1] / "src/jarvis/api/static"
JS = [
    "console-book.js",
    "console-book-reader.js",
    "console-book-show.js",
    "console-book-voice.js",
    "console-book-3d.js",
    "console-book-scenes.js",
    "console-book-scenes-flow.js",
    "console-book-scenes-data.js",
    "console-book-2d.js",
    "console-book-talk.js",
]
CSS = ["console-book.css", "book.css"]
SCENE_SPLIT = {
    "console-book-scenes.js": {1, 2, 12, 13},
    "console-book-scenes-flow.js": {3, 5, 6, 8},
    "console-book-scenes-data.js": {4, 7, 9, 10, 11},
}
SINKS = (
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "document.write",
    "createContextualFragment",
    "DOMParser",
    "setHTMLUnsafe",
    "srcdoc",
    "eval(",
    "new Function",
)
OLDER_CSS = ["console.css", "console-deck.css", "console-systems.css", "console-vitals.css"]


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", JS + CSS)
def test_each_file_is_ascii_and_within_its_size(name: str) -> None:
    text = _read(name)
    assert text.isascii(), name
    assert len(text.splitlines()) <= (300 if name.endswith(".css") else 400), name


@pytest.mark.parametrize("name", JS)
def test_no_html_sink_and_server_text_by_textcontent(name: str) -> None:
    text = _read(name)
    assert [s for s in SINKS if s in text] == [], name
    assert not re.search(r"set(?:Timeout|Interval)\(\s*['\"`]", text), name
    assert not re.search(r"setAttribute\(\s*['\"`]on", text), name


@pytest.mark.parametrize("name", JS)
def test_the_show_lines_are_never_hard_coded(name: str) -> None:
    """D13/D15: every line JARVIS says comes from the server's script (none is typed into JS)."""
    text = _read(name)
    for key, line in LINES.items():
        for part in re.split(r"\{[a-z]+\}", line):
            frag = part.strip(" .,")
            if len(frag) >= 18:  # a distinctive piece of the line, not a word like "Thank you"
                assert frag not in text, (name, key, frag)


def test_three_is_only_the_vendored_es_module() -> None:
    engine = _read("console-book-3d.js")
    assert "/static/vendor/three-0.187.0/three.module.min.js" in engine
    for name in JS:
        text = _read(name)
        imports = re.findall(r"import\(\s*['\"]([^'\"]+)['\"]", text) + re.findall(
            r"^import [^;]*?from ['\"]([^'\"]+)['\"]", text, re.M
        )
        for target in imports:
            assert target.startswith(("/static/vendor/three-0.187.0/", "./console-")), (
                name,
                target,
            )
        text = text.replace("'http://www.w3.org/2000/svg'", "")  # the SVG namespace, not an address
        assert "http://" not in text and "https://" not in text, name  # no CDN, no off-site call


def test_the_engine_imports_createcore_and_never_edits_the_console_3d() -> None:
    engine = _read("console-book-3d.js")
    assert "import('./console-3d-scenes.js')" in engine
    for name in JS:  # the deck's engine is never imported by the show (only createCore's module)
        assert not re.search(r"import\(?\s*['\"][^'\"]*console-3d\.js", _read(name)), name


@pytest.mark.parametrize("name", sorted(SCENE_SPLIT))
def test_each_scene_module_exports_its_scenes(name: str) -> None:
    text = _read(name)
    m = re.search(r"export const SCENES = Object\.freeze\(\{([^}]*)\}\)", text)
    assert m, name
    keys = {int(k) for k in re.findall(r"(\d+)\s*:", m.group(1))}
    assert keys == SCENE_SPLIT[name], name


def test_the_engine_keeps_the_plan_budgets() -> None:
    engine = _read("console-book-3d.js")
    assert re.search(r"fps:\s*30,\s*dpr:\s*1\.5", engine)  # <= 30 fps, DPR <= 1.5 (tier 0)
    assert re.search(r"MAX_DRAW_CALLS\s*=\s*150\b", engine)
    assert re.search(r"MAX_LABELS\s*=\s*24\b", engine)
    assert "forceContextLoss" in engine and "setAnimationLoop(null)" in engine  # full teardown
    assert "MIN_WIDTH = 900" in engine  # phones get the 2D show, no GL context


def test_the_token_lives_in_this_tab_and_travels_as_x_jarvis_book() -> None:
    show, panel = _read("console-book-show.js"), _read("console-book.js")
    assert "'X-Jarvis-Book'" in show and "'X-Jarvis-Book'" in panel
    for name in JS:
        text = _read(name)
        assert not re.search(r"localStorage[^;\n]*jarvis_book", text), name
    assert "sessionStorage" in show and "'jarvis_book_token'" in show
    assert "'jarvis_book_pending'" in panel  # D8: the re-sign-in hop resumes from here
    assert "'/auth/login?reauth=1'" in panel


def test_the_passkey_purposes_and_targets() -> None:
    panel, talk = _read("console-book.js"), _read("console-book-talk.js")
    assert re.search(r"prove\('book_open',\s*audience\)", panel)
    assert re.search(r"prove\('book_resume',\s*\w+\)", talk)


def test_the_show_page_links_its_parts_in_order() -> None:
    html = _read("book.html")
    links = re.findall(r'<link rel="stylesheet" href="/static/([^"]+)">', html)
    assert links == ["console.css", "console-deck.css", "book.css"]
    scripts = re.findall(r'<script ([^>]*)src="/static/([^"]+)"', html)
    names = [s for _, s in scripts]
    assert names.index("console-fx.js") < names.index("console-permissions.js")
    assert names.index("console-book-show.js") < names.index("console-book-talk.js")
    assert ('type="module" ', "console-book-3d.js") in scripts
    assert "<script>" not in html  # no inline script (CSP script-src 'self')
    assert not re.search(r"\son[a-z]+=", html)  # no inline handlers (CSP script-src 'self')
    assert 'aria-live="polite"' in html and 'id="shCap"' in html


def _older_css() -> str:
    return "\n".join(_read(n) for n in OLDER_CSS)


@pytest.mark.parametrize("name", CSS)
def test_no_new_colours_fonts_radii_or_shadows(name: str) -> None:
    """The owner's standing rule: the console's aesthetics never change."""
    css = re.sub(r"/\*.*?\*/", "", _read(name), flags=re.S)
    older = _older_css().lower()
    for hexcol in re.findall(r"#[0-9a-fA-F]{3,8}\b", css):
        assert hexcol.lower() in older, (name, hexcol)
    assert not re.search(r"\b(?:rgb|rgba|hsl|hsla|hwb|lab|lch|oklch)\(", css), name
    for fam in re.findall(r"font-family\s*:\s*([^;}]+)", css):
        assert re.fullmatch(r"var\(--(?:font|tech|hud|disp|mono)\)", fam.strip()), (name, fam)
    for font in re.findall(r"(?<![-\w])font\s*:\s*([^;}]+)", css):
        assert re.search(r"var\(--(?:font|tech|hud|disp|mono)\)|inherit", font), (name, font)
    radii = set(re.findall(r"border-radius\s*:\s*([^;}]+)", older))
    for rad in re.findall(r"border-radius\s*:\s*([^;}]+)", css):
        assert rad.strip().lower() in radii, (name, rad)
    for sh in re.findall(r"box-shadow\s*:\s*([^;}]+)", css):
        assert "rgba(" not in sh and "#" not in sh, (name, sh)
        assert re.fullmatch(
            r"(?:none|var\(--[\w-]+\)|inset [0-9px ]+var\(--[\w-]+\))(?:,.*)?", sh.strip()
        ), (
            name,
            sh,
        )


def test_the_3d_colours_are_the_console_palette() -> None:
    """Colours in the show's JS: JarvisFX.tokens() roles, plus the console-3d amber pair only."""
    allowed = {"#f59e0b", "#b45309"}  # console-3d-scenes.js AMBER_NIGHT / AMBER_DAY
    for name in JS:
        for hexcol in re.findall(r"['\"](#[0-9a-fA-F]{6})['\"]", _read(name)):
            assert hexcol.lower() in allowed, (name, hexcol)


def test_the_reader_names_the_layers_as_the_book_does() -> None:
    """The panel and scene 2 name each layer one way: buildbook.sections.LAYERS."""
    from jarvis.buildbook.sections import LAYERS

    m = re.search(r"LAYER_NAMES = \{(.*?)\};", _read("console-book-reader.js"), re.S)
    assert m
    assert dict(re.findall(r"(\w+): '([^']*)'", m.group(1))) == dict(LAYERS)


def test_the_3d_labels_are_text_for_screen_readers() -> None:
    """WCAG 1.1.1: on a desktop a scene's facts are only in the labels over the canvas."""
    tag = re.search(r"<div[^>]*id=\"shLabels\"[^>]*>", _read("book.html"))
    assert tag and "aria-hidden" not in tag.group(0)


def test_rupees_only() -> None:
    for name in JS:
        for lit in re.findall(r"'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`", _read(name)):
            assert "$" not in re.sub(r"\$\{", "", lit), (name, lit[:60])

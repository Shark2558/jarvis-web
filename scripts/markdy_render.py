# scripts/markdy_render.py — the headless browser behind scripts/markdy_export.py (R6.1 D2).
"""Renders the final frame of a Markdy diagram to SVG + PNG with the pinned `@markdy/renderer-dom`
(from `tools/markdy/node_modules`, MIT) in headless Chromium driven by Python Playwright. Nothing
is fetched from the network: the page and the pinned modules are served from disk by a route, and
any other request is blocked and reported as a problem for that diagram.

Loaded by `markdy_export.main` only when a diagram is exported (`--check` and `--lint-only` never
start a browser). It imports nothing from the export script: the two error classes to raise come
in through the constructor.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

BASE_URL = "http://markdy-export.localhost/"
PAGE_NAME = "export.html"
RENDER_TIMEOUT_MS = 30_000
VIEW_WIDTH = 1440
PIXEL_RATIO = 2.0
IMPORTS = {
    "@markdy/core": "node_modules/@markdy/core/dist/index.js",
    "@markdy/renderer-dom": "node_modules/@markdy/renderer-dom/dist/index.js",
    "html2canvas": "node_modules/html2canvas/dist/html2canvas.esm.js",
}
_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<style>body{margin:0;background:#fff}#app{width:%(w)dpx}</style>
<script type="importmap">%(imports)s</script></head><body><div id="app"></div>
<script type="module">
import { createDiagram } from "@markdy/renderer-dom";
window.__markdyRender = (code) => {
  const warnings = [];
  const d = createDiagram({ container: document.getElementById("app"), code, autoplay: false,
    onWarning: (w) => warnings.push(`line ${w.line}: ${w.message}`) });
  window.__markdy = { d, warnings };
  return true;
};
</script></body></html>"""
_PNG_JS = """async (ratio) => {
  const blob = await window.__markdy.d.exportPng({ pixelRatio: ratio });
  const buf = new Uint8Array(await blob.arrayBuffer()); let s = "";
  for (let i = 0; i < buf.length; i += 0x8000) {
    s += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  }
  return btoa(s);
}"""


class ChromiumRenderer:
    """Headless Chromium (Python Playwright) rendering the final frame of a diagram with the pinned
    `@markdy/renderer-dom`, served from `tools/markdy/node_modules`. One browser for a whole run;
    a fresh page per diagram. Every request that is not the page or a pinned module is blocked."""

    def __init__(
        self,
        tool_dir: Path,
        *,
        setup_error: type[Exception] = RuntimeError,
        export_error: type[Exception] = RuntimeError,
    ) -> None:
        self._setup_error, self._export_error = setup_error, export_error
        self._modules = (tool_dir / "node_modules").resolve()
        imports = {k: BASE_URL + v for k, v in IMPORTS.items()}
        self._page = _PAGE % {"w": VIEW_WIDTH, "imports": json.dumps({"imports": imports})}
        self._pw: Any = None
        self._browser: Any = None

    def __enter__(self) -> ChromiumRenderer:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise self._setup_error(
                "exporting needs Python Playwright (pip install playwright)"
            ) from None
        try:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch()
        except PlaywrightError as exc:
            self.__exit__(None, None, None)
            raise self._setup_error(f"Chromium can't start: {str(exc).splitlines()[0]}") from None
        return self

    def __exit__(self, *exc: object) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._pw is not None:
            self._pw.stop()
        self._browser = self._pw = None

    def _module(self, rel: str) -> bytes | None:
        if not rel.startswith("node_modules/") or not rel.endswith(".js"):
            return None
        path = (self._modules.parent / rel).resolve()
        if not path.is_relative_to(self._modules) or not path.is_file():
            return None
        return path.read_bytes()

    def _serve(self, route: Any, blocked: list[str]) -> None:
        url = str(route.request.url)
        if not url.startswith(BASE_URL):
            blocked.append(url)
            route.abort()
            return
        rel = url[len(BASE_URL) :].split("?", 1)[0]
        if rel == PAGE_NAME:
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=self._page)
            return
        body = self._module(rel)
        if body is None:
            route.fulfill(status=404, body="")
            return
        route.fulfill(status=200, content_type="text/javascript; charset=utf-8", body=body)

    def __call__(self, source: str) -> tuple[str, bytes]:
        if self._browser is None:
            raise self._setup_error("the renderer was used outside `with`")
        errors: list[str] = []
        blocked: list[str] = []
        page = self._browser.new_page(viewport={"width": VIEW_WIDTH + 40, "height": 1000})
        try:
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.route("**/*", lambda route: self._serve(route, blocked))
            page.goto(BASE_URL + PAGE_NAME)
            page.wait_for_function(
                "typeof window.__markdyRender === 'function'", timeout=RENDER_TIMEOUT_MS
            )
            page.evaluate("(code) => window.__markdyRender(code)", source)
            page.evaluate("() => document.fonts.ready.then(() => true)")
            svg = str(
                page.evaluate("() => window.__markdy.d.exportSvg({ includeThemeStyles: true })")
            )
            png = base64.b64decode(page.evaluate(_PNG_JS, PIXEL_RATIO))
            warnings = [str(w) for w in page.evaluate("() => window.__markdy.warnings")]
        except Exception as exc:  # noqa: BLE001 - any browser failure is this diagram's problem
            raise self._export_error(f"the browser failed: {str(exc).splitlines()[0]}") from None
        finally:
            page.close()
        trouble = [f"page error: {e}" for e in errors] + [f"blocked request: {u}" for u in blocked]
        trouble += [f"renderer warning: {w}" for w in warnings]
        if trouble:
            raise self._export_error("; ".join(trouble))
        return svg, png


__all__ = ["BASE_URL", "IMPORTS", "ChromiumRenderer"]

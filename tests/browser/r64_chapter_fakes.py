# tests/browser/r64_chapter_fakes.py -- R6.4 builder B (docs/plans/r6-4-book-look.md D7, D11): the chapter player's
# browser fakes, on top of book_mocks.FakeBook. `serve_vault` answers GET /v1/book/chapters/module_vault and
# GET /v1/book/pages/{id} with the REAL Vault chapter and its five pages, as this tree's compiled book serves them
# (r64_vault_chapter.json, checked against the script by tests/test_r64_b_static.py); every call is recorded in
# FakeBook.calls. `SPEECH` is a browser voice under the test's control: each line "speaks" its words as boundary events
# (15 ms apart), then ends by itself (`window.__speech.auto = true`, the default) or only when the test calls
# `window.__endLine()`; no real audio ever plays.
# ruff: noqa: E501 -- JavaScript strings
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from book_mocks import RELEASE, FakeBook, j

VAULT: dict[str, Any] = json.loads(
    Path(__file__).with_name("r64_vault_chapter.json").read_text(encoding="utf-8")
)
CHAPTER: dict[str, Any] = {**VAULT["chapter"], "release": RELEASE["id"]}
PAGES: dict[str, dict[str, Any]] = VAULT["pages"]
LINES: list[dict[str, Any]] = CHAPTER["lines"]


def first_line(cue_kind: str, target: str | None = None, page: str | None = None) -> int:
    """The 0-based index of the first line with that cue (and target, and page)."""
    for i, line in enumerate(LINES):
        if page and line["page"] != page:
            continue
        if any(
            c["kind"] == cue_kind and (target is None or c["target"] == target)
            for c in line["cues"]
        ):
            return i
    raise LookupError((cue_kind, target, page))


class ChapterBook:
    """The chapter and page routes for one page; `chapter_status` / `page_status` make them fail."""

    def __init__(self, page: Any, fake: FakeBook) -> None:
        self.fake = fake
        self.chapter_status = 200
        self.page_status = 200
        page.route("**/v1/book/chapters/*", self._chapter)
        page.route("**/v1/book/pages/*", self._page)

    def _chapter(self, route: Any) -> None:
        c = self.fake._record(route)
        cid = c["path"].rsplit("/", 1)[-1]
        if self.chapter_status != 200:
            return j(
                route,
                self.chapter_status,
                {"error": "unavailable", "detail": "Try again in a moment."},
            )
        if cid != "module_vault":
            return j(route, 404, {"error": "no_chapter", "detail": "No such chapter."})
        return j(route, 200, CHAPTER)

    def _page(self, route: Any) -> None:
        c = self.fake._record(route)
        pid = c["path"].rsplit("/", 1)[-1]
        if pid == "search" or pid not in PAGES:
            return j(route, 404, {"error": "no_page", "detail": "No such page."})
        if self.page_status != 200:
            return j(
                route,
                self.page_status,
                {"error": "unavailable", "detail": "Try again in a moment."},
            )
        return j(route, 200, PAGES[pid])


def serve_vault(page: Any, fake: FakeBook) -> ChapterBook:
    return ChapterBook(page, fake)


SPEECH = """
window.__said = []; window.__live = null;
(() => {
  const S = { auto: true, ms: 15, boundaries: true };
  window.__speech = S;
  const synth = { speaking: false, pending: false, paused: false,
    speak(u) {
      window.__said.push({ text: u.text, rate: u.rate });
      const me = { u, ended: false, t: 0, hold: null }, at = [], re = /\\S+/g;
      let m, k = 0;
      while ((m = re.exec(u.text)) !== null) at.push(m.index);
      window.__live = me;
      const end = () => { if (me.ended) return; me.ended = true; u.onend && u.onend(); };
      const step = () => {
        if (me.ended) return;
        if (synth.paused) { me.t = setTimeout(step, 20); return; }
        if (k < at.length) { if (S.boundaries && u.onboundary) u.onboundary({ name: 'word', charIndex: at[k], charLength: 1 }); k += 1; me.t = setTimeout(step, S.ms); return; }
        if (S.auto || me.go) end(); else me.hold = end;
      };
      setTimeout(() => { if (me.ended) return; u.onstart && u.onstart(); step(); }, 5);
    },
    cancel() { const me = window.__live; if (me) { me.ended = true; clearTimeout(me.t); } },
    pause() { synth.paused = true; }, resume() { synth.paused = false; }, getVoices() { return []; } };
  window.__endLine = () => { const me = window.__live; if (!me) return; if (me.hold) me.hold(); else me.go = true; };
  try { Object.defineProperty(window, 'speechSynthesis', { value: synth, configurable: true }); } catch (_) {}
})();
"""
HOLD = SPEECH + "\nwindow.__speech.auto = false;\n"

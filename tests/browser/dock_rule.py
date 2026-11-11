# tests/browser/dock_rule.py -- shared by test_dock_fit.py, test_brief.py and test_memory.py (R6.1).
# The dock's folding rule worked out from the test's own measurement of the page, so the browser
# tests check console-dock.js against the text this renderer draws, not one machine's numbers.
# Why: GitHub's Chromium 153 draws the dock labels a little wider than this machine's. There
# CONNECTORS no longer fits its 78 px tab and a 390 px phone holds one tab fewer, and the dock folds
# them behind More, as it should; tests that had this machine's counts written in failed.
# The rule (console-dock.js, R6.1 D7 and review A):
#   desktop: a tab whose label is wider than the tab (inside its borders) folds wherever it sits;
#            of the others the dock shows as many as fit the room, in order, last ones folding first
#            (More, and the separator when a tab after it shows, take room too).
#   phone:   every tab shares the bar equally; a tab needs its label rounded up to a whole px, its
#            borders and LABEL_CLEAR of air, and 44 px at the least; at most eight items, More
#            included.
#   both:    Chat, Brief and Approvals never fold for lack of room.
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

PINNED_COUNT = 3  # Chat, Brief, Approvals: the first three tabs
PHONE_MAX_TABS = 8  # More included
MIN_TOUCH = 44
LABEL_CLEAR = 8  # px of air a phone tab keeps beside its label
EPS = 0.01  # px of sub-pixel slack when comparing lengths
TIE = 0.05  # px: text this close to a limit may land on either side of it, so both readings count

# Every item drawn for the read (folded ones too), then folded back before the frame is painted.
# The room is what the window gives the dock: its max-width on a desktop (the window less its
# gutters), the whole window on a phone, inside the dock's padding and border.
MEASURE_JS = """() => {
  const dock = document.getElementById('dock'), more = document.getElementById('dockMore');
  const sep = dock.querySelector('.sep');
  const tabs = [...dock.querySelectorAll('.dk[data-open]')];
  const all = [...tabs, more, ...(sep ? [sep] : [])];
  const was = all.map((e) => e.hidden);
  all.forEach((e) => { e.hidden = false; });
  const px = (v) => parseFloat(v) || 0;
  const shown = (e) => e.getClientRects().length > 0;
  function item(t) {  // the tab's width and borders, and its visible label's text as painted
    const c = getComputedStyle(t);
    const span = [...t.querySelectorAll('span')]
      .find((x) => shown(x) && getComputedStyle(x).position !== 'absolute');
    let label = null;
    if (span) {
      const rg = document.createRange(); rg.selectNodeContents(span);
      label = rg.getBoundingClientRect().width;
    }
    return {id: t.dataset.open || t.id, width: t.getBoundingClientRect().width,
            borders: px(c.borderLeftWidth) + px(c.borderRightWidth), label};
  }
  const s = getComputedStyle(dock), cap = parseFloat(s.maxWidth);
  const vw = document.documentElement.clientWidth;
  const room = (Number.isFinite(cap) ? Math.min(vw, cap) : vw) - px(s.paddingLeft)
    - px(s.paddingRight) - px(s.borderLeftWidth) - px(s.borderRightWidth);
  let sepW = 0;
  if (sep && shown(sep)) {
    const ss = getComputedStyle(sep);
    sepW = sep.getBoundingClientRect().width + px(ss.marginLeft) + px(ss.marginRight);
  }
  const out = {
    phone: matchMedia('(max-width: 899px)').matches, room, gap: px(s.columnGap), sep: sepW,
    afterSep: sep ? tabs.findIndex(
      (t) => sep.compareDocumentPosition(t) & Node.DOCUMENT_POSITION_FOLLOWING) : -1,
    tabs: tabs.map(item), more: item(more),
  };
  all.forEach((e, i) => { e.hidden = was[i]; });
  return out;
}"""
# The entries the open More sheet shows, in order.
SHEET_JS = """() => [...document.querySelectorAll('#moreSheet [data-sheet-open]')]
  .filter((b) => b.getClientRects().length > 0).map((b) => b.dataset.sheetOpen)"""


@dataclass(frozen=True)
class Item:
    """One dock button as measured: its border box, its borders, its visible label's width."""

    id: str
    width: float
    borders: float
    label: float | None  # None: only an icon shows (phones under 360 px)


@dataclass(frozen=True)
class Dock:
    phone: bool
    room: float
    gap: float
    sep: float  # the separator with its margins; 0 where it is not drawn (phones)
    after_sep: int  # index of the first tab after the separator, -1 without one
    tabs: tuple[Item, ...]
    more: Item


def measure_dock(page: Any) -> Dock:
    raw = page.evaluate(MEASURE_JS)

    def item(r: dict[str, Any]) -> Item:
        return Item(r["id"], r["width"], r["borders"], r["label"])

    return Dock(
        phone=raw["phone"],
        room=raw["room"],
        gap=raw["gap"],
        sep=raw["sep"],
        after_sep=raw["afterSep"],
        tabs=tuple(item(t) for t in raw["tabs"]),
        more=item(raw["more"]),
    )


def holds_label(tab: Item, phone: bool, wider: float = 0.0) -> bool:
    """Desktop: the label is no wider than the tab inside its borders. Phone tabs share the bar
    instead, so they always hold theirs. `wider` reads the text that many px wider."""
    return phone or tab.label is None or tab.label + wider <= tab.width - tab.borders + EPS


def overflowing(d: Dock) -> list[str]:
    """The desktop tabs whose label is wider than the tab, in dock order (none on a phone)."""
    return [t.id for t in d.tabs if not holds_label(t, d.phone)]


def _need(tab: Item, phone: bool, wider: float) -> float:
    if not phone:
        return tab.width  # desktop tabs keep their own size
    label = math.ceil(tab.label + wider) if tab.label is not None else 0
    return max(MIN_TOUCH, label + tab.borders + LABEL_CLEAR)


def _fits(d: Dock, show: list[int], wider: float) -> bool:
    """Do these tabs (indexes, in dock order) fit the room, beside More when some are left out?"""
    folded = len(show) < len(d.tabs)
    items = len(show) + int(folded)
    needs = [_need(d.tabs[i], d.phone, wider) for i in show]
    if folded:
        needs.append(_need(d.more, d.phone, wider))
    if d.phone:
        share = (d.room - d.gap * (items - 1)) / items
        return items <= PHONE_MAX_TABS and share >= max(needs) - EPS
    with_sep = d.sep > 0 and d.after_sep >= 0 and any(i >= d.after_sep for i in show)
    total = sum(needs) + (d.sep if with_sep else 0) + d.gap * (items + int(with_sep) - 1)
    return total <= d.room + EPS


def expected_shown(d: Dock, wider: float = 0.0) -> list[str]:
    """The tabs the dock should show: those holding their label, in order, as many as fit, never
    fewer than the pinned ones among them."""
    able = [i for i, t in enumerate(d.tabs) if holds_label(t, d.phone, wider)]
    pinned = sum(1 for i in able if i < PINNED_COUNT)
    k = next((k for k in range(len(able), pinned, -1) if _fits(d, able[:k], wider)), pinned)
    return [d.tabs[i].id for i in able[:k]]


def shown_choices(d: Dock) -> list[list[str]]:
    """The expected tabs; where a measured length sits within TIE px of its limit, the reading a
    hair either side counts too (sub-pixel layout may round it either way)."""
    choices: list[list[str]] = []
    for wider in (0.0, -TIE, TIE):
        shown = expected_shown(d, wider)
        if shown not in choices:
            choices.append(shown)
    return choices


def assert_follows_rule(d: Dock, visible: list[str]) -> None:
    """The dock shows exactly the tabs the measured rule expects, in dock order."""
    choices = shown_choices(d)
    assert visible in choices, {"shown": visible, "expected": choices, "dock": d}

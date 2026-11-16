# src/jarvis/wardrobe/catalog/views.py
"""His panel's views of the catalog (docs/plans/r13-wardrobe.md "The HTTP contract", D10, D3;
INV-13, LND-15): exactly `jarvis.wardrobe.http`'s models. Pure over the index and a clock.

- A place is "Drawer 2" while it was confirmed there within `stale_days` and the piece is Ready;
  otherwise "Drawer 2 (last known)": an unobserved move or a piece in the laundry is never said
  to be where it was last seen (INV-13).
- A private piece is in the list only when he tapped "Show private basics"; otherwise it is
  counted in `private_hidden` (D10: everything, but behind a tap, in his own panel).
- A piece's detail: its last 50 events with their marks, and the current step in words with the
  time in HIS zone ("Drying since 14:05", LND-15).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from jarvis.wardrobe import http
from jarvis.wardrobe.catalog.counts import Tally
from jarvis.wardrobe.catalog.links import pair_of
from jarvis.wardrobe.model import Piece, WardrobeView
from jarvis.wardrobe.ports import HistoryItem
from jarvis.wardrobe.states import STATE_WORDS

PAGE_MAX = http.PAGE_MAX
HISTORY_MAX = 50


class Views:
    def __init__(self, now: Callable[[], datetime], *, stale_days: int, cap_inr: int) -> None:
        self._now, self._stale = now, timedelta(days=stale_days)
        self._cap = cap_inr
        self.tally = Tally()

    def place_words(self, view: WardrobeView, p: Piece) -> str:
        place = view.places.get(p.place or "")
        if place is None:
            return ""
        fresh = p.place_at is not None and self._now() - p.place_at <= self._stale
        return place.label if fresh and p.state == "ready" else f"{place.label} (last known)"

    def piece_view(self, view: WardrobeView, p: Piece) -> http.PieceView:
        pair = pair_of(view, p.id)
        sets = tuple(s.id for s in view.sets.values() if any(x.piece == p.id for x in s.parts))
        return http.PieceView(
            id=p.id, category=p.category, type=p.type, label=p.label, colour=p.colour,
            second=p.second, pattern=p.pattern, locked=p.locked, features=dict(p.features),
            size=(p.size.v, p.size.ok) if p.size else None,
            brand=(p.brand.v, p.brand.ok) if p.brand else None,
            fabric=tuple((f.v, f.ok) for f in p.fabric), care=tuple((c.v, c.ok) for c in p.care),
            formality=p.formality, occasions=p.occasions, weather=p.weather, mess_ok=p.mess_ok,
            delicate=p.delicate, private=p.private, state=p.state,
            state_words=STATE_WORDS[p.state], eligible=p.eligible, place=p.place,
            place_words=self.place_words(view, p), place_at=p.place_at,
            expected_back=p.expected_back, hold=p.hold, wears=p.wears, last_worn=p.last_worn,
            label_code=p.label_code, photos=p.photos, pair=pair.id if pair else None, sets=sets,
        )  # fmt: skip

    def _settings(self, view: WardrobeView) -> http.SettingsView:
        st = view.settings
        return http.SettingsView(
            calendar_chosen=st.calendar is not None, fields=st.fields, lead_h=st.lead_h,
            plan_alerts=st.plan_alerts, ai_tagging=st.ai_tagging, auto_swap=st.auto_swap,
            show_private=st.show_private, tag_month_inr=round(view.tag_inr, 2),
            tag_cap_inr=self._cap, custom_types=st.custom_types,
        )  # fmt: skip

    def wardrobe_view(
        self, view: WardrobeView, *, ready: str, show_private: bool, after: str | None = None
    ) -> http.WardrobeView:
        active = sorted(view.active(), key=lambda p: (p.category, p.type, p.id))
        rest = active
        if after:  # from the cursor's place in the same order (ids are random: never `id >`)
            at = next((i for i, p in enumerate(active) if p.id == after), None)
            rest = active[at + 1 :] if at is not None else []
        shown = [p for p in rest if show_private or not p.private]
        page, more = shown[:PAGE_MAX], len(shown) > PAGE_MAX
        return http.WardrobeView(
            ready=ready, rev=view.rev, pieces=tuple(self.piece_view(view, p) for p in page),
            next=page[-1].id if more else None,
            private_hidden=sum(p.private for p in active) if not show_private else 0,
            counts=self.tally.of(view), pairs=self.tally.pair_views(view),
            sets=self.tally.set_views(view),
            places=tuple(
                http.PlaceView(id=pl.id, label=pl.label, kind=pl.kind, baseline_at=pl.baseline_at)
                for pl in view.places.values()
            ),
            labels=tuple(
                http.LabelView(code=lb.code, number=lb.number, piece=lb.piece)
                for lb in view.labels.values()
            ),
            settings=self._settings(view),
        )  # fmt: skip

    def event_view(self, view: WardrobeView, h: HistoryItem) -> http.EventView:
        e = h.event
        place = view.places.get(e.place or "")
        return http.EventView(
            id=e.id, kind=e.kind, at=e.at, source=e.source, verified=e.verified, mark=h.mark,
            to=e.to, place_words=place.label if place else "", note=e.note,
        )  # fmt: skip

    def detail(
        self, view: WardrobeView, p: Piece, history: Sequence[HistoryItem], zone: ZoneInfo
    ) -> http.PieceDetail:
        rows = tuple(self.event_view(view, h) for h in history[-HISTORY_MAX:])
        setting = [h.event for h in history if h.mark == "applied" and h.event.kind != "seen"]
        step = STATE_WORDS[p.state]
        if setting and p.state != "ready":
            since = setting[-1].at.astimezone(zone).strftime("%H:%M")
            step = f"{step} since {since}"
        return http.PieceDetail(piece=self.piece_view(view, p), history=rows, step=step)


__all__ = ["HISTORY_MAX", "Views"]

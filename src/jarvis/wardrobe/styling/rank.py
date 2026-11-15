# src/jarvis/wardrobe/styling/rank.py
"""R13 D12: how the engine ranks what is left after the hard exclusions, and its words (pure).

Ranking: closeness to the dress code's formality, his festive pieces for a festive code, rain-ok
shoes and outer layer when rain is likely, light fabrics (verified) in the heat, the colours he
likes or avoids, a piece worn in the last days, the colour-pairing table (bottom and outer with
the top, socks with the bottom), a belt that matches the shoes, a set worn whole; ties by piece
id (`best`). Words: each pick's reason with its ids (STY-11), the header, and a gap naming the
step that left a required slot empty with its next action (STY-08, STY-16).
"""

from __future__ import annotations

from datetime import timedelta

from jarvis.wardrobe.model import Piece
from jarvis.wardrobe.styling import texts
from jarvis.wardrobe.styling.look import FORMAL_SLOTS, PARTNER, Run, Unit, never_hit, sets_of, whole

WHY = {"formality": "none is formal enough", "mess": "none is marked okay to stain"}


def recent(r: Run, p: Piece) -> bool:
    if p.last_worn is None:
        return False
    return r.ask.day - p.last_worn.date() <= timedelta(days=r.rules.recent_days)


def piece_score(r: Run, slot: str, p: Piece) -> float:
    s = 0.0
    if slot in FORMAL_SLOTS:
        s -= abs(r.code.target - r.rules.formality_of(p))
    if r.code.occasion and r.code.occasion in p.occasions:
        s += 2
    if r.ask.rain and slot in ("shoes", "outer") and "rain_ok" in p.weather:
        s += 3
    light = any(f.ok and f.v in r.rules.light_fabrics for f in p.fabric)
    s += 1 if r.ask.hot and slot in ("top", "bottom") and light else 0
    s += 1 if p.colour in r.ask.likes else 0
    s -= 2 if p.colour in r.ask.avoids else 0
    s -= 1 if recent(r, p) else 0
    return s


def colour(r: Run, slot: str) -> str | None:
    got = r.picks.get(slot)
    return r.p(got.pieces[0]).colour if got is not None else None


def match_score(r: Run, slot: str, p: Piece) -> float:
    partner = colour(r, PARTNER[slot]) if slot in PARTNER else None
    s = 0.0
    if slot in ("bottom", "outer", "socks"):
        s += r.rules.pairs_with(p.colour, partner)
    if slot == "socks" and r.rules.same_family(p.colour, partner):
        s += 1
    if slot == "belt" and partner is not None:
        s += 3 if r.rules.same_family(p.colour, partner) else -1
    if r.code.sets_whole and any(whole(r.view, parts) for _, parts in sets_of(r.view, p.id)):
        s += 2
    return s


def score(r: Run, slot: str, unit: Unit) -> float:
    ps = [r.p(i) for i in unit]
    return sum(piece_score(r, slot, p) + match_score(r, slot, p) for p in ps) / len(ps)


def best(r: Run, slot: str, units: list[Unit]) -> Unit:
    return min(units, key=lambda u: (-score(r, slot, u), u))


# ---- the words -----------------------------------------------------------------------------------
def gap(r: Run, slot: str, step: str | None, removed: list[Unit]) -> str:
    words, code = r.rules.slot_words_of(slot), r.rules.code_words(r.ask.code)
    ids = [i for u in removed for i in u]
    if step == "available":
        qual = "formal " if r.code.target >= 4 and slot in FORMAL_SLOTS else ""
        return f"No ready {qual}{words}: {texts.states_line([r.p(i) for i in ids])}."
    head = f"No {words} for {code}: "
    if step is None:
        return f"{head}you have none yet (add one {texts.WHERE})."
    if step == "reserved":
        held = " and ".join(dict.fromkeys(r.ask.reserved.get(i, "") for i in ids))
        verb = "are" if len(ids) > 1 else "is"
        return f"{head}{texts.ids_words(ids)} {verb} reserved for {held}."
    if step == "prefs":
        hits = [h for i in ids if (h := never_hit(r, r.p(i))) is not None]
        if hits:
            rule = texts.never_words(*hits[0])
            return f'{head}your rule "never {rule}" leaves none ({texts.ids_words(ids)}).'
        return f"{head}you excluded {texts.ids_words(ids)} for this."
    return f"{head}{WHY.get(step, 'none is rain-ok')} ({texts.ids_words(ids)})."


def why(r: Run, slot: str, unit: Unit) -> str:
    ps = [r.p(i) for i in unit]
    head = f"{r.rules.slot_words_of(slot).capitalize()} {texts.ids_words(unit)}: {r.words(unit)}"
    if any(p.private for p in ps):
        return f"{head}."
    bits = []
    if slot in FORMAL_SLOTS:
        bits.append(f"formality {r.rules.formality_of(ps[0])}")
    other = r.picks.get(PARTNER.get(slot, ""))
    if other is not None and match_score(r, slot, ps[0]) > 0:
        bits.append(f"goes with {texts.ids_words(other.pieces)}")
    if r.ask.rain and all("rain_ok" in p.weather for p in ps):
        bits.append("rain-ok")
    if r.code.mess_ok and all(p.mess_ok for p in ps):
        bits.append("okay to stain")
    if any(p.state == "in_use" for p in ps):
        bits.append("handed on from the plan it is worn for (declared)")
    return f"{head}; {', '.join(bits)}." if bits else f"{head}."


def header(r: Run) -> str:
    words = r.rules.code_words(r.ask.code)
    tail = f" for {r.ask.for_words}" if r.ask.for_words else ""
    return f"{words[0].upper()}{words[1:]}{tail}."


def stale(r: Run, p: Piece) -> str | None:
    seen = p.place_at
    if r.ask.stale_before is None or seen is None or seen >= r.ask.stale_before:
        return None
    return (
        f"Check that {texts.piece_words(p)} ({p.id}) is still in its place: not seen since "
        f"{texts.date_words(seen.date())}."
    )


__all__ = ["best", "gap", "header", "match_score", "piece_score", "score", "stale", "why"]

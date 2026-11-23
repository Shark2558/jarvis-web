# src/jarvis/buildbook/gen/tour.py
"""R6.3 D9 (docs/plans/r6-3-book-content.md "The short tour's first script"): the short tour,
filled and timed at CI. No model writes a word of it (Rs 0).

`build(repo, facts, *, show=None, script=None) -> Tour | None` (`jarvis.buildbook.tour_model`):
`gen/tour.json`, the Workshop's script the owner approved on 23 Nov 2026, 14:53 IST, copied
verbatim, with every `{{key}}` filled from the fact pack, once per audience:

- the keys: `facts_model.FACT_TOUR_KEYS` (part A computes them), `tour.minutes` (this module: whole
  minutes of that audience's timer, rounded up) and, in a picture only, `modules.others` (T14's
  list of the modules that aren't his seven highlights, from the module map). An unknown key, a
  key the pack lacks, a line over 400 characters once filled, a digit typed outside a placeholder
  (except in the running example's quoted words, T03-T05, and "3D"), a brace the show can't fill
  (only `{h}`, `{his}`, `{by}`, filled when served) or a doubled word ("about about", L1) is a
  GenError. A pack with none of the tour's keys (I0's stub, a fixture repository) is no tour.
- the pictures (M6): a scene's `{"from_show": n}` copies that show scene's facts (so `show` is
  needed), T12-T14 carry their own, filled; `picture_problems` checks per `visual` that the data
  its 3D and 2D modules read is there.
- the audiences (D9, H1): a guest's tour leaves out T16 and every owner-only line and has no Rs
  anywhere: a guest's line naming Rs is a GenError, a borrowed picture fact naming Rs is dropped
  from a guest's copy; the owner's leaves out the guest's own line (t13b04).
- the timer: `tour_model.seconds(words, lines, scenes)`; outside `HARD_BAND_S` (600-900 s) the
  generator refuses.
None: no script (an empty one), or no tour facts.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from pydantic import ValidationError

from jarvis.buildbook import tour_model
from jarvis.buildbook.facts_model import FACT_TOUR_KEYS, TOUR_TIMER_KEYS, FactPack, Scalar
from jarvis.buildbook.gen import modules
from jarvis.buildbook.gen.repo import GenError, Repo
from jarvis.buildbook.model import Show
from jarvis.buildbook.tour_model import (
    AudienceTour,
    FromShow,
    ScriptScene,
    Tour,
    TourBeat,
    TourFact,
    TourPicture,
    TourScene,
    TourScript,
)

# package data (pyproject.toml), read through importlib.resources (the deploy installs it)
SCRIPT_FILE: Traversable | Path = files("jarvis.buildbook.gen") / "tour.json"
PICTURE_KEYS: tuple[str, ...] = ("modules.others",)  # T14's picture: one fact a module
KNOWN_KEYS = frozenset((*FACT_TOUR_KEYS, *TOUR_TIMER_KEYS, *PICTURE_KEYS))
KIN = ("{h}", "{his}", "{by}")  # filled when served (tour_serve, lines.render's words)
BEAT_CAP = 400
EXAMPLE_SCENES = frozenset({3, 4, 5})  # the running example: its quoted words may hold digits
ALLOWED_DIGITS = ("3D",)
LABELLED = frozenset({1, 2, 3, 5, 6, 8, 11})  # pictures that write every fact's label
_KEY = re.compile(r"\{\{([^{}]*)\}\}")
_BRACE = re.compile(r"[{}]")
_DIGIT = re.compile(r"[0-9]")
_QUOTED = re.compile(r'"[^"]*"')
_DOUBLED = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)
RUPEE = re.compile("₹|\\bRs\\b|rupee", re.IGNORECASE)

Pictures = Mapping[int, tuple[TourFact, ...]]


def load_script(path: Traversable | Path | None = None) -> TourScript:
    return TourScript.model_validate_json((path or SCRIPT_FILE).read_bytes())


def build(
    repo: Repo,
    facts: FactPack,
    *,
    show: Show | None = None,
    script: TourScript | None = None,
) -> Tour | None:
    """The filled tour for both audiences, or None (no script, no tour facts). GenError: a typing
    mistake in the script, a pack without a tour key, a picture its visual can't draw, a time
    outside 10-15 minutes."""
    del repo  # the join's shape: everything the tour states comes from the pack and the show
    script = load_script() if script is None else script
    if not script.scenes or not any(k in facts.values for k in FACT_TOUR_KEYS):
        return None
    check_script(script)
    values = tour_values(facts)
    pictures = _pictures(script, values, show)
    try:
        return Tour(
            owner=_audience(script, values, pictures, "owner"),
            guest=_audience(script, values, pictures, "guest"),
        )
    except ValidationError as exc:
        raise GenError(f"the tour doesn't fit its shape ({exc.error_count()} problems)") from None


# ---- the script: what may be typed ---------------------------------------------------------------
def check_script(script: TourScript) -> None:
    """GenError for an unknown key, a stray brace or a typed digit anywhere in the script."""
    for scene in script.scenes:
        for beat in scene.beats:
            _check_text(beat.text, beat.id, quoted_ok=scene.n in EXAMPLE_SCENES)
        if isinstance(scene.picture.facts, tuple):
            for f in scene.picture.facts:
                for text in (f.label, f.value, f.group):
                    _check_text(text, f"T{scene.n:02d}'s picture", quoted_ok=False)


def _check_text(text: str, where: str, *, quoted_ok: bool) -> None:
    unknown = [k for k in _KEY.findall(text) if k not in KNOWN_KEYS]
    if unknown:
        raise GenError(f"{where}: unknown placeholder {{{{{unknown[0]}}}}} (D9's facts table)")
    bare = _KEY.sub(" ", text)
    for kin in KIN:
        bare = bare.replace(kin, " ")
    if _BRACE.search(bare):
        raise GenError(f"{where}: a placeholder the show can't fill (only {{{{key}}}} and {{h}})")
    if quoted_ok:
        bare = _QUOTED.sub(" ", bare)
    for allowed in ALLOWED_DIGITS:
        bare = bare.replace(allowed, " ")
    if _DIGIT.search(bare):
        raise GenError(f"{where}: a digit typed outside a placeholder (D9: numbers come from code)")


# ---- the facts -----------------------------------------------------------------------------------
def tour_values(facts: FactPack) -> dict[str, str]:
    """Every tour key's value as the words the tour says. GenError: a key the pack lacks."""
    missing = [k for k in FACT_TOUR_KEYS if k not in facts.values]
    if missing:
        raise GenError(f"the fact pack lacks tour keys: {', '.join(missing)}")
    return {k: _words(k, facts.values[k].value) for k in FACT_TOUR_KEYS}


def _words(key: str, value: Scalar) -> str:
    if isinstance(value, bool):
        raise GenError(f"tour fact {key} is a yes/no, not words")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = " ".join(str(value).split())
    if not text:
        raise GenError(f"tour fact {key} is empty")
    return text


def _fill(text: str, values: Mapping[str, str]) -> str:
    return _KEY.sub(lambda m: values[m.group(1)], text)


def _line(text: str, values: Mapping[str, str], where: str) -> str:
    out = _fill(text, values)
    if len(out) > BEAT_CAP:
        raise GenError(f"{where} is {len(out)} characters once filled, over {BEAT_CAP}")
    doubled = _DOUBLED.search(out)
    if doubled:
        raise GenError(f"{where} says {doubled.group(0)!r} once filled (a doubled word, L1)")
    return out


# ---- the pictures (M6) ---------------------------------------------------------------------------
def picture_problems(visual: int, facts: Iterable[TourFact]) -> list[str]:
    """What today's picture `visual` reads and this data lacks (empty: it can draw it)."""
    got = tuple(facts)
    if not got:
        return ["nothing to draw"]
    groups = {f.group.lower() for f in got}
    out = []
    if visual == 4 and "purpose" not in groups:
        out.append("no purpose group (the keyring)")
    if visual == 7 and not {"home", "edge"} <= groups:
        out.append("needs a home and an edge group")
    if visual == 9 and not any(f.group for f in got):
        out.append("no group (one orbit a group)")
    if visual == 10 and any(f.n is None for f in got):
        out.append("a fact without a number (a bar)")
    if visual in LABELLED and any(not f.label for f in got):
        out.append("a fact without a label")
    return out


def _pictures(script: TourScript, values: Mapping[str, str], show: Show | None) -> Pictures:
    out: dict[int, tuple[TourFact, ...]] = {}
    for scene in script.scenes:
        facts = _picture(scene, values, show)
        problems = picture_problems(scene.picture.visual, facts)
        if problems:
            raise GenError(
                f"T{scene.n:02d}'s picture {scene.picture.visual}: {'; '.join(problems)}"
            )
        out[scene.n] = facts
    return out


def _picture(
    scene: ScriptScene, values: Mapping[str, str], show: Show | None
) -> tuple[TourFact, ...]:
    data = scene.picture.facts
    if isinstance(data, FromShow):
        if show is None:
            raise GenError(f"T{scene.n:02d} borrows show scene {data.from_show}: build needs show=")
        return tuple(TourFact(**f.model_dump()) for f in show.scenes[data.from_show - 1].facts)
    out: list[TourFact] = []
    for f in data:
        if f.label == "{{modules.others}}":
            out.extend(_others(f.group, values))
            continue
        out.append(
            f.model_copy(
                update={k: _fill(getattr(f, k), values) for k in ("label", "value", "group")}
            )
        )
    return tuple(out)


def _others(group: str, values: Mapping[str, str]) -> list[TourFact]:
    """T14: one fact a module that isn't his seven highlights, in the map's order (D9: a new
    module grows the screen, not the time); its count is the one the tour says."""
    table = {m.id: m for m in modules.MODULES}
    ids = modules.others()
    if str(len(ids)) != values["modules.else_count"]:
        raise GenError(f"T14 shows {len(ids)} modules but modules.else_count says otherwise")
    return [
        TourFact(label=table[i].title, value=_parts(len(table[i].cards)), group=group) for i in ids
    ]


def _parts(count: int) -> str:
    return f"{count} part" if count == 1 else f"{count} parts"


# ---- one audience: its scenes, its lines, its timer ----------------------------------------------
def _audience(
    script: TourScript, values: Mapping[str, str], pictures: Pictures, who: str
) -> AudienceTour:
    scenes = [s for s in script.scenes if who == "owner" or s.audience != "owner"]
    draft = _scenes(scenes, {**values, "tour.minutes": "0"}, pictures, who)
    minutes = math.ceil(_timed(draft, who)[0] / 60)
    final = _scenes(scenes, {**values, "tour.minutes": str(minutes)}, pictures, who)
    secs, words, texts = _timed(final, who)
    return AudienceTour(
        scenes=final, seconds=secs, words=words, chars=sum(map(len, texts)), lines=len(texts)
    )


def _timed(scenes: tuple[TourScene, ...], who: str) -> tuple[float, int, list[str]]:
    texts = [b.text for s in scenes for b in s.beats]
    words = sum(len(t.split()) for t in texts)
    secs = tour_model.seconds(words, len(texts), len(scenes))
    low, high = tour_model.HARD_BAND_S
    if not low <= secs <= high:
        raise GenError(f"the {who}'s tour times {secs} s, outside {low:.0f}-{high:.0f} s (D9)")
    return secs, words, texts


def _scenes(
    scenes: Iterable[ScriptScene], values: Mapping[str, str], pictures: Pictures, who: str
) -> tuple[TourScene, ...]:
    out = []
    for s in scenes:
        beats = tuple(
            TourBeat(id=b.id, text=_line(b.text, values, b.id), audience=b.audience, focus=b.focus)
            for b in s.beats
            if b.audience in ("both", who)
        )
        facts = pictures[s.n]
        if who != "owner":
            facts = _guest_safe(s, beats, facts)
        picture = TourPicture(visual=s.picture.visual, facts=facts)
        out.append(
            TourScene(
                n=s.n,
                id=s.id,
                title=s.title,
                picture=picture,
                chapter=s.chapter,
                audience=s.audience,
                beats=beats,
            )
        )
    return tuple(out)


def _guest_safe(
    scene: ScriptScene, beats: tuple[TourBeat, ...], facts: tuple[TourFact, ...]
) -> tuple[TourFact, ...]:
    """A guest hears and sees no Rs (D9): a line naming it is the script's mistake; a borrowed
    fact naming it is dropped from the guest's copy."""
    said = next((b.id for b in beats if RUPEE.search(b.text)), None)
    if said:
        raise GenError(f"{said} would name rupees to a guest (D9: a guest's tour has no Rs)")
    kept = tuple(f for f in facts if not RUPEE.search(f.model_dump_json()))
    problems = picture_problems(scene.picture.visual, kept)
    if problems:
        raise GenError(f"T{scene.n:02d}'s guest picture: {'; '.join(problems)}")
    return kept


__all__ = [
    "KNOWN_KEYS",
    "PICTURE_KEYS",
    "RUPEE",
    "SCRIPT_FILE",
    "build",
    "check_script",
    "load_script",
    "picture_problems",
    "tour_values",
]

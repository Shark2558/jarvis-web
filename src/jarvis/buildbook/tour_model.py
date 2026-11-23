# src/jarvis/buildbook/tour_model.py
"""R6.3 D9 (docs/plans/r6-3-book-content.md "The short tour's first script", approval stop 2): the
short tour's two shapes. Pure data, frozen, extra fields refused, no I/O.

- `TourScript` = `gen/tour.json`: the Workshop's script the owner approved on 23 Nov 2026, 14:53 IST
  (part D copies its spoken words VERBATIM): 17 scenes, beats with `{{key}}` placeholders, each
  scene's picture (`visual`, one of today's 11, and its data: `{"from_show": n}` or its own list,
  M6). An empty script is I0's stub (no tour is built).
- `Tour` = `book.json`'s `tour`, filled at CI (D's `gen/tour.py`) once per audience (`owner`,
  `guest`: each its own lines and minutes), timed (`seconds`: 145 words a minute, 0.8 s a line,
  1.4 s a scene; hard band 600-900 s).
`TOUR_SCENES` pins each scene as approved; `HIGHLIGHTS` are his seven, in his order.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from jarvis.buildbook.sections import NAME, Frozen

TOUR_LINE_ID = r"^t[0-9]{2}b[0-9]{2}$"
TOUR_PAGE = r"^(?:pg_(?:chapter|module|card|screen|service)_[a-z0-9_]{1,40})?$"
SceneAudience = Literal["both", "owner"]
LineAudience = Literal["both", "owner", "guest"]
# (n, id, title, the picture it borrows (today's scene number), who sees it), as approved
TOUR_SCENES: tuple[tuple[int, str, str, int, SceneAudience], ...] = (
    (1, "what", "What JARVIS is", 1, "both"),
    (2, "layers", "The eight layers", 2, "both"),
    (3, "asking", "One request: asking", 3, "both"),
    (4, "approval", "One request: the approval", 5, "both"),
    (5, "cancel", 'One request: "Cancel it"', 3, "both"),
    (6, "privacy", "Privacy and security", 4, "both"),
    (7, "voice", "Highlight 1 of 7: Voice", 6, "both"),
    (8, "approvals", "Highlight 2 of 7: Approvals and passkeys", 5, "both"),
    (9, "memory", "Highlight 3 of 7: Memory", 4, "both"),
    (10, "vault", "Highlight 4 of 7: Vault and documents", 4, "both"),
    (11, "home", "Highlight 5 of 7: Home bridge and cameras", 7, "both"),
    (12, "phone", "Highlight 6 of 7: The phone app and SOS", 9, "both"),
    (13, "wardrobe", "Highlight 7 of 7: Wardrobe & Try-on", 9, "both"),
    (14, "else", "What else I can do", 9, "both"),
    (15, "built", "How I'm built", 9, "both"),
    (16, "costs", "What I cost", 10, "owner"),
    (17, "planned", "What's planned next", 11, "both"),
)
TOUR_SCENE_COUNT = len(TOUR_SCENES)
HIGHLIGHTS: tuple[str, ...] = ("voice", "approvals", "memory", "vault", "home", "phone", "wardrobe")
OWN_PICTURE_DATA = frozenset({12, 13, 14})  # M6: no show scene of the same subject
PACE_WPM, LINE_PAUSE_S, SCENE_PAUSE_S = 145, 0.8, 1.4
HARD_BAND_S = (600.0, 900.0)
AIMED_S: dict[str, tuple[float, float]] = {"owner": (780.0, 870.0), "guest": (760.0, 850.0)}


def seconds(words: int, lines: int, scenes: int) -> float:
    """The timer (D9); the plan's 796 s for the owner: 1,762 words, 54 lines, 17 scenes."""
    return round(words * 60 / PACE_WPM + lines * LINE_PAUSE_S + scenes * SCENE_PAUSE_S, 1)


class TourFact(Frozen):
    """What a picture draws: the same fields as `model.Fact` (a seam test keeps them equal)."""

    label: str = Field(max_length=80)
    value: str = Field(default="", max_length=120)
    n: float | None = None
    group: str = Field(default="", max_length=40)
    flag: str = Field(default="", max_length=20)


class FromShow(Frozen):  # the show scene of the same subject, copied at CI
    from_show: int = Field(ge=1, le=11)


def _scene_checks(n: int, sid: str, title: str, visual: int, audience: str) -> None:
    if (n, sid, title, visual, audience) != TOUR_SCENES[n - 1]:
        raise ValueError("a tour scene must match TOUR_SCENES (the approved script)")


# ---- gen/tour.json (the script, with placeholders) -----------------------------------------------
class ScriptPicture(Frozen):
    visual: int = Field(ge=1, le=11)
    facts: FromShow | tuple[TourFact, ...]


class ScriptBeat(Frozen):
    id: str = Field(pattern=TOUR_LINE_ID)
    text: str = Field(min_length=1, max_length=600)  # <= 400 once filled (D9)
    audience: LineAudience = "both"
    focus: str = Field(default="", max_length=60)


class ScriptScene(Frozen):
    n: int = Field(ge=1, le=TOUR_SCENE_COUNT)
    id: str = Field(pattern=NAME)
    title: str = Field(max_length=60)
    picture: ScriptPicture
    chapter: str = Field(default="", pattern=TOUR_PAGE)  # the full book's page for this scene
    audience: SceneAudience = "both"
    beats: tuple[ScriptBeat, ...] = Field(min_length=1, max_length=12)
    facts: tuple[str, ...] = ()  # the fact keys its lines and picture use

    @model_validator(mode="after")
    def _approved(self) -> ScriptScene:
        _scene_checks(self.n, self.id, self.title, self.picture.visual, self.audience)
        if any(not b.id.startswith(f"t{self.n:02d}b") for b in self.beats):
            raise ValueError("a tour beat's id names its scene")
        return self


class TourScript(Frozen):
    v: Literal[1] = 1
    scenes: tuple[ScriptScene, ...] = ()

    @model_validator(mode="after")
    def _all_or_none(self) -> TourScript:
        if self.scenes and [s.n for s in self.scenes] != list(range(1, TOUR_SCENE_COUNT + 1)):
            raise ValueError("the tour script is all 17 scenes in order (or empty: no tour)")
        return self


# ---- book.json's `tour` (filled) ----------------------------------------------------------------
class TourPicture(Frozen):
    visual: int = Field(ge=1, le=11)
    facts: tuple[TourFact, ...] = Field(default=(), max_length=60)


class TourBeat(Frozen):
    id: str = Field(pattern=TOUR_LINE_ID)  # the line id POST /v1/book/show/speak takes
    text: str = Field(min_length=1, max_length=400)
    audience: LineAudience = "both"
    focus: str = Field(default="", max_length=60)


class TourScene(Frozen):
    n: int = Field(ge=1, le=TOUR_SCENE_COUNT)
    id: str = Field(pattern=NAME)
    title: str = Field(max_length=60)
    picture: TourPicture
    chapter: str = Field(default="", pattern=TOUR_PAGE)
    audience: SceneAudience = "both"
    beats: tuple[TourBeat, ...] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def _approved(self) -> TourScene:
        _scene_checks(self.n, self.id, self.title, self.picture.visual, self.audience)
        if any(not b.id.startswith(f"t{self.n:02d}b") for b in self.beats):
            raise ValueError("a tour beat's id names its scene")
        return self


class AudienceTour(Frozen):
    """One audience's filled tour (each fills its own `{{tour.minutes}}`): its scenes in order (a
    guest's without owner-only scenes and lines) and what the timer counted."""

    scenes: tuple[TourScene, ...]
    seconds: float = Field(ge=HARD_BAND_S[0], le=HARD_BAND_S[1])  # the generator refuses outside
    words: int = Field(ge=0)
    chars: int = Field(ge=0)
    lines: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> AudienceTour:
        ns = [s.n for s in self.scenes]
        ids = [b.id for s in self.scenes for b in s.beats]
        if ns != sorted(set(ns)) or len(ids) != len(set(ids)):
            raise ValueError("a tour's scenes are in order and its line ids used once")
        return self


class Tour(Frozen):
    v: Literal[1] = 1
    owner: AudienceTour
    guest: AudienceTour

    @model_validator(mode="after")
    def _whole(self) -> Tour:
        if [s.n for s in self.owner.scenes] != list(range(1, TOUR_SCENE_COUNT + 1)):
            raise ValueError("the owner's tour is all 17 scenes, in order")
        mine = {s[0] for s in TOUR_SCENES if s[4] == "owner"}
        guest = self.guest.scenes
        if [s.n for s in guest] != [n for n in range(1, TOUR_SCENE_COUNT + 1) if n not in mine]:
            raise ValueError("a guest's tour is every scene but the owner's, in order")
        if any(b.audience == "owner" for s in guest for b in s.beats):
            raise ValueError("a guest's tour has no owner-only line")
        return self

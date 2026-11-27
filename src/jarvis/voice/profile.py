# src/jarvis/voice/profile.py
"""The owner's voice profile (R5.2; docs/plans/r5-2-voice.md 3.3-3.5, D4, D7; Layers 2 and 7).

What the 20-minute voice session learns, kept in the cloud as settings
(`jarvis.voice.profile_store`, `{prefix}voice_profile/{uid}`): which listening engine understands
him best (row 81), measured by word error on held-out prompts; the mishearings that repeat, as a
correction list applied after listening; the session's progress. Never audio, a voice print or
a wake-word file: recordings stay on the laptop kit (encrypted), the speaker check's print in each
browser. New words he uses join R5's "words to recognise" (`VoiceSettings.phrases`, at most
`WORDS_MAX`).

- `ListenEngine`: the console's listening engines (browser, Google, the laptop's two Whispers)
- `listening_order`: D7 — the session's best, then Google, then the browser (each once); before a
  session, the laptop's Whisper small first when the kit is healthy (plan 7a), as today without it
- `Correction`, `apply_corrections`: whole words only; a correction can never touch numbers,
  money or codes (no digits, currency signs, number, money or code words on either side)
- `BARS`: the plan's eval bars (section 5), shared by V1, V3, V4 and V5's suites

"Spoken by the owner" (row 84) is a label the console may send (`SPOKEN_BY_HEADER`) for display
only: it is never consulted by the gateway, a confirmation, a passkey or an unlock, and never
approves anything (slice 9 D11 stands). Pure Pydantic and the standard library (no I/O).
"""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum
from typing import Final, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from jarvis.localspeech.protocol import PROMPT_ID, SESSION_ID, EngineSlot, PromptKind

# ---- the session (plan 1, 3.3) -----------------------------------------------------------------
SESSION_MINUTES: Final = 20
BLOCKS: Final = 4
BLOCK_MINUTES: Final = 5
PROMPTS_TARGET: Final = 120
WAKE_PROMPTS: Final = 30  # "Hey Jarvis" said 30 ways
CORRECTIONS_MAX: Final = 100
WORDS_MAX: Final = 50  # = jarvis.voice.settings.PHRASE_ITEMS (R5 D16)
RANKING_MAX: Final = 8
SPOKEN_BY_HEADER: Final = "x-jarvis-spoken-by"
SPOKEN_BY_OWNER: Final = "owner"


class ListenEngine(StrEnum):
    BROWSER = "browser"  # the browser's own listening (in the console, never on the server)
    GOOGLE = "google"  # Google with his words, inside the free allowance
    WHISPER_SMALL = "laptop-whisper-small"
    WHISPER_MEDIUM = "laptop-whisper-medium"

    @property
    def slot(self) -> EngineSlot | None:
        return _SLOTS.get(self)

    @property
    def on_laptop(self) -> bool:
        return self in _SLOTS


_SLOTS: Final[dict[ListenEngine, EngineSlot]] = {
    ListenEngine.WHISPER_SMALL: EngineSlot.WHISPER_SMALL,
    ListenEngine.WHISPER_MEDIUM: EngineSlot.WHISPER_MEDIUM,
}
LAPTOP_ENGINES: Final = tuple(_SLOTS)
DEFAULT_LAPTOP: Final = ListenEngine.WHISPER_SMALL  # D2


def engine_of_slot(slot: EngineSlot) -> ListenEngine:
    for engine, s in _SLOTS.items():
        if s is slot:
            return engine
    raise ValueError("that engine does not listen to the console")


class SessionState(StrEnum):
    NONE = "none"
    RECORDING = "recording"
    SCORING = "scoring"
    DONE = "done"
    FAILED = "failed"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Prompt(_Frozen):
    id: str = Field(pattern=PROMPT_ID)
    block: int = Field(ge=1, le=BLOCKS)
    kind: PromptKind
    text: str = Field(min_length=1, max_length=120)
    held_out: bool = False  # scored, never trained on
    how: str = Field(default="", max_length=40)  # "far", "tired", "over music" (wake prompts)


class EngineScore(_Frozen):
    engine: ListenEngine
    wer: float = Field(ge=0)  # word error rate on the held-out prompts (0.07 = 7 %)
    commands: float = Field(ge=0, le=1)  # commands understood right
    prompts: int = Field(ge=0)
    median_ms: int | None = Field(default=None, ge=0)


# ---- corrections ---------------------------------------------------------------------------------
_NUMBER_WORDS = (
    "zero oh nil one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty "
    "ninety hundred thousand lakh lakhs lac lacs crore crores million billion double triple point "
    "half quarter first second third"
)
# R5.2 review: ordinals, plurals and counting words too (a correction once could write "fifth")
_ORDINAL_WORDS = (
    "fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth "
    "fifteenth sixteenth seventeenth eighteenth nineteenth twentieth thirtieth fortieth fiftieth "
    "sixtieth seventieth eightieth ninetieth hundredth thousandth millionth billionth"
)
_COUNT_WORDS = (
    "zeros zeroes ones twos threes fours fives sixes sevens eights nines tens elevens twelves "
    "dozen dozens hundreds thousands millions billions twenties thirties forties fifties sixties "
    "seventies eighties nineties nought naught once twice thrice"
)
_MONEY_WORDS = "rupee rupees rs inr paise paisa dollar dollars usd euro euros pound pounds"
_CODE_WORDS = "otp pin code cvv cvc upi ifsc pan aadhaar password passcode passkey pincode"
PROTECTED_WORDS: Final = frozenset(
    f"{_NUMBER_WORDS} {_ORDINAL_WORDS} {_COUNT_WORDS} {_MONEY_WORDS} {_CODE_WORDS}".split()
)
_WORD = re.compile(r"^[^\W\d_]+(?:['-][^\W\d_]+)*$")  # letters, inner ' or -
HEARD_WORDS_MAX = 3
MEANT_WORDS_MAX = 5
WORD_CHARS_MAX = 40


def _words(raw: str, *, most: int, fold: bool) -> str:
    text = " ".join(unicodedata.normalize("NFC", raw).replace("’", "'").split())
    words = text.split(" ")
    if not text or len(text) > WORD_CHARS_MAX or len(words) > most:
        raise ValueError(f"1 to {most} words, at most {WORD_CHARS_MAX} characters")
    for w in words:
        bare = w.rstrip(".")
        if not _WORD.fullmatch(bare) or bare.casefold() in PROTECTED_WORDS:
            raise ValueError("letters only, and never a number, money or code word")
    if sum(c.isalpha() for c in text) < 2:
        raise ValueError("too short to correct safely")
    return text.casefold() if fold else text


class Correction(_Frozen):
    heard: str  # what the engine wrote, folded ("java's")
    meant: str  # what he said ("JARVIS")
    seen: int = Field(default=1, ge=1)

    @field_validator("heard")
    @classmethod
    def _heard(cls, v: str) -> str:
        return _words(v, most=HEARD_WORDS_MAX, fold=True)

    @field_validator("meant")
    @classmethod
    def _meant(cls, v: str) -> str:
        return _words(v, most=MEANT_WORDS_MAX, fold=False)


def apply_corrections(text: str, corrections: tuple[Correction, ...]) -> str:
    """`text` with each correction's `heard` (whole words, any case, any spacing) replaced by its
    `meant`, in one pass (a replacement is never corrected again)."""
    if not corrections:
        return text
    by_heard = {c.heard: c.meant for c in corrections}
    alts = sorted(by_heard, key=len, reverse=True)
    pattern = r"(?<!\w)(?:" + "|".join(r"\s+".join(map(_escaped, h.split())) for h in alts)
    found = re.compile(pattern + r")(?!\w)", re.IGNORECASE)
    return found.sub(lambda m: by_heard[_key(m.group(0))], text)


def _escaped(word: str) -> str:
    return re.escape(word).replace("'", "['\u2019]")  # a typed or a curly apostrophe


def _key(said: str) -> str:
    return " ".join(said.replace("\u2019", "'").split()).casefold()


# ---- the profile ---------------------------------------------------------------------------------
class VoiceProfile(_Frozen):
    state: SessionState = SessionState.NONE
    session_id: str | None = Field(default=None, pattern=SESSION_ID)
    chosen: ListenEngine | None = None  # None: no session yet (the default order)
    ranking: tuple[EngineScore, ...] = Field(default=(), max_length=RANKING_MAX)  # best first
    corrections: tuple[Correction, ...] = Field(default=(), max_length=CORRECTIONS_MAX)
    corrections_on: bool = True
    clips: int = Field(default=0, ge=0)  # recorded on the laptop this session
    compare_seconds: float = Field(default=0.0, ge=0)  # Google seconds the comparison used
    measured_at: AwareDatetime | None = None  # when the session's scores were taken

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        scored = {s.engine for s in self.ranking}
        if len(scored) != len(self.ranking):
            raise ValueError("an engine is ranked once")
        if self.chosen is not None and self.ranking and self.chosen not in scored:
            raise ValueError("the chosen engine is one that was scored")
        if len({c.heard for c in self.corrections}) != len(self.corrections):
            raise ValueError("one correction per mishearing")
        return self

    def best(self) -> EngineScore | None:
        return next((s for s in self.ranking if s.engine is self.chosen), None)


def listening_order(profile: VoiceProfile, *, laptop_ready: bool) -> tuple[ListenEngine, ...]:
    """D7: the session's best -> Google -> the browser, each once; a laptop engine only while the
    kit is healthy. Before a session: the laptop's Whisper small first (plan 7a), then as today."""
    first = profile.chosen if profile.chosen is not None else DEFAULT_LAPTOP
    if first.on_laptop and not laptop_ready:
        first = ListenEngine.GOOGLE
    order = (first, ListenEngine.GOOGLE, ListenEngine.BROWSER)
    return tuple(dict.fromkeys(order))


# ---- the plan's eval bars (section 5) ------------------------------------------------------------
class ProfileBars(_Frozen):
    wer_margin_points: float = 2.0  # the chosen engine's WER <= the best cloud engine's + 2 points
    commands_min: float = 0.95
    false_wakes_per_hour_max: float = 0.5
    tv_audio_hours: float = 2.0  # of openly licensed TV / podcast audio
    wake_miss_max: float = 0.05
    other_speaker_reject_min: float = 0.90  # with the verifier
    speaker_eer_max: float = 0.05
    first_audio_gpu_s: float = 0.7
    first_audio_cpu_s: float = 1.5
    stt_realtime_factor_min: float = 3.0

    def recognition_ok(self, *, chosen_wer: float, best_cloud_wer: float, commands: float) -> bool:
        margin = self.wer_margin_points / 100
        return chosen_wer <= best_cloud_wer + margin + 1e-9 and commands >= self.commands_min


BARS: Final = ProfileBars()

__all__ = [
    "BARS",
    "BLOCKS",
    "BLOCK_MINUTES",
    "CORRECTIONS_MAX",
    "DEFAULT_LAPTOP",
    "LAPTOP_ENGINES",
    "PROMPTS_TARGET",
    "PROTECTED_WORDS",
    "SESSION_MINUTES",
    "SPOKEN_BY_HEADER",
    "SPOKEN_BY_OWNER",
    "WAKE_PROMPTS",
    "WORDS_MAX",
    "Correction",
    "EngineScore",
    "ListenEngine",
    "ProfileBars",
    "Prompt",
    "SessionState",
    "VoiceProfile",
    "apply_corrections",
    "engine_of_slot",
    "listening_order",
]

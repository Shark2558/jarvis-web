# src/jarvis/voice/session_api.py
"""`ProfileApi` (R5.2 V3; I0 seams): the handlers behind `/v1/voice/profile` for the voice session
and the profile, on `app.state.voice_profile_api` (I1 wires `build_profile_api`). Each checks its
body (strict: unknown fields refused, 422 `input_rejected` in fixed words that never echo it),
calls `jarvis.voice.session.VoiceSessions` and answers a plain JSON view; refusals are
`ProfileRefused` (the route turns them into {error, detail}).

    view / update            the profile: engines ranked for his voice, the chosen one, the
                             listening order (D7), corrections (on / off, forget one)
    session / start          the prompts, blocks and progress; start (402 needs_yes: the ₹)
    put_clip                 {audio: base64 WAV, browser_heard?}
    score / results          the laptop hears the comparison lines; the results when ready
    recheck                  "Check again"
    delete_recordings        "Delete my recordings" (the route checks {"confirm": "DELETE"})

The production parts are here too: Google through `VoiceService.transcribe` (with his words, free-
only inside the free minutes), his words through R5's settings store (the one list), and R18's
transcript normaliser.
"""

from __future__ import annotations

import importlib
import time
from typing import Any, Final, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jarvis.config import Settings
from jarvis.localspeech.protocol import KitClient, PromptKind
from jarvis.storage.docs import Docs
from jarvis.voice.profile import (
    BLOCK_MINUTES,
    SESSION_MINUTES,
    EngineScore,
    ListenEngine,
    VoiceProfile,
    listening_order,
)
from jarvis.voice.profile_ports import Answer, ProfileRefused, ProfileStore
from jarvis.voice.service import VoiceService
from jarvis.voice.session import ClipDone, SessionParts, StartIn, VoiceSessions, decode_wav
from jarvis.voice.session_compare import YES_WORD, GoogleHeard, needs_yes
from jarvis.voice.session_prompts import BLOCK_TITLES, TYPED_WORDS_MAX, scored
from jarvis.voice.session_score import Normalise, meets_bar
from jarvis.voice.session_store import Compare, CompareMode, DocSessionStore, SessionDoc
from jarvis.voice.settings import PHRASE_ITEMS, VoiceSettingsPatch, clean_phrase

LABELS: Final[dict[ListenEngine, str]] = {
    ListenEngine.BROWSER: "This browser",
    ListenEngine.GOOGLE: "Google (with your words)",
    ListenEngine.WHISPER_SMALL: "Laptop: Whisper small",
    ListenEngine.WHISPER_MEDIUM: "Laptop: Whisper medium",
}
REJECTED = "That request isn't one the voice session understands."
TYPE_YES = f"To include Google beyond the free minutes, type {YES_WORD} exactly."
WORDS_ONLY_HERE = (
    "Deleted the comparison's words kept here. The laptop speech kit isn't set up, so any "
    "recordings on your laptop stay until it is."
)
BAD_WORD = (
    f"Give at most {TYPED_WORDS_MAX} names or places, each 1 to 40 characters with at least one "
    "letter (letters, numbers, spaces and - ' . & only)."
)
COMPARE_WORDS: Final[dict[CompareMode, str]] = {
    CompareMode.FREE: "Google hears the comparison lines inside this month's free minutes: ₹0.",
    CompareMode.OFF: "The comparison runs without Google.",
    CompareMode.UNAVAILABLE: (
        "Google's listening isn't set up here, so the comparison is this browser against the "
        "laptop."
    ),
    CompareMode.LIMIT: (
        "Your monthly limit was reached, so Google stopped hearing the comparison lines."
    ),
}


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfilePatch(_Body):
    chosen: ListenEngine | None = None
    corrections_on: bool | None = None
    forget: str | None = Field(default=None, min_length=1, max_length=80)  # a correction's heard


class StartBody(_Body):
    yes: str | None = Field(default=None, max_length=10)
    compare: bool | None = None  # False: go on without Google
    restart: bool = False
    words: list[str] = Field(default_factory=list, max_length=TYPED_WORDS_MAX)


class ClipBody(_Body):
    audio: str = Field(max_length=1_000_000)
    browser_heard: str | None = Field(default=None, max_length=2_000)


class EmptyBody(_Body):
    pass


_BodyT = TypeVar("_BodyT", bound=_Body)


def _parse(model: type[_BodyT], body: dict[str, Any]) -> _BodyT:
    try:
        return model.model_validate(body)
    except ValidationError:
        raise ProfileRefused(422, "input_rejected", REJECTED) from None


# ---- views ---------------------------------------------------------------------------------------
def _score(s: EngineScore, chosen: ListenEngine | None) -> dict[str, Any]:
    return {
        "engine": s.engine.value,
        "label": LABELS[s.engine],
        "wer_pct": round(s.wer * 100, 1),
        "commands_pct": round(s.commands * 100, 1),
        "prompts": s.prompts,
        "median_ms": s.median_ms,
        "on_laptop": s.engine.on_laptop,
        "chosen": s.engine is chosen,
    }


def profile_view(p: VoiceProfile, *, laptop_ready: bool) -> dict[str, Any]:
    order = listening_order(p, laptop_ready=laptop_ready)
    return {
        "state": p.state.value,
        "session_id": p.session_id,
        "chosen": p.chosen.value if p.chosen else None,
        "chosen_label": LABELS[p.chosen] if p.chosen else "",
        "ranking": [_score(s, p.chosen) for s in p.ranking],
        "meets_bar": meets_bar(p.ranking, p.chosen),
        "corrections": [
            {"heard": c.heard, "meant": c.meant, "seen": c.seen} for c in p.corrections
        ],
        "corrections_on": p.corrections_on,
        "clips": p.clips,
        "compare_seconds": round(p.compare_seconds, 1),
        "measured_at": p.measured_at.isoformat() if p.measured_at else None,
        "order": [e.value for e in order],
        "order_labels": [LABELS[e] for e in order],
        "laptop_ready": laptop_ready,
    }


def compare_view(c: Compare) -> dict[str, Any]:
    if c.mode is CompareMode.NEEDS_YES:
        words = needs_yes(c).words
    elif c.mode is CompareMode.YES:
        words = (
            f"You said {YES_WORD}: Google hears the comparison lines at about "
            f"₹{c.inr_per_minute:.2f} a minute, at most about ₹{round(c.inr_max)}."
        )
    else:
        words = COMPARE_WORDS[c.mode]
    return {
        "mode": c.mode.value,
        "minutes": c.minutes,
        "inr_per_minute": c.inr_per_minute,
        "inr_max": c.inr_max,
        "clips": c.clips,
        "cap_clips": c.cap_clips,
        "seconds": c.seconds,
        "words": words,
        "yes_word": YES_WORD,
    }


def session_view(doc: SessionDoc | None, preview: Compare | None = None) -> dict[str, Any]:
    if doc is None:
        return {
            "state": "none",
            "minutes": SESSION_MINUTES,
            "blocks": [_block(b, 0, 0) for b in BLOCK_TITLES],
            "prompts": [],
            "done": [],
            "next": None,
            "total": 0,
            "compare": compare_view(preview) if preview else None,
            "reason": "",
            "words_added": [],
        }
    done = set(doc.done)
    return {
        "state": doc.state.value,
        "session_id": doc.session_id,
        "minutes": SESSION_MINUTES,
        "blocks": [
            _block(
                b,
                sum(p.block == b for p in doc.prompts),
                sum(p.block == b and p.id in done for p in doc.prompts),
            )
            for b in BLOCK_TITLES
        ],
        "prompts": [
            {
                "id": p.id,
                "block": p.block,
                "kind": p.kind.value,
                "text": p.text,
                "how": p.how,
                "compare": scored(p),
                "wake": p.kind is PromptKind.WAKE,
            }
            for p in doc.prompts
        ],
        "done": list(doc.done),
        "next": doc.next_prompt(),
        "total": len(doc.prompts),
        "compare": compare_view(doc.compare),
        "reason": doc.reason,
        "words_added": list(doc.words_added),
    }


def _block(block: int, prompts: int, done: int) -> dict[str, Any]:
    title = BLOCK_TITLES[block]
    return {
        "block": block,
        "title": title,
        "minutes": BLOCK_MINUTES,
        "prompts": prompts,
        "done": done,
    }


def _clip(c: ClipDone) -> dict[str, Any]:
    return {
        "prompt_id": c.prompt_id,
        "seconds": c.seconds,
        "clips": c.clips,
        "done": c.done,
        "total": c.total,
        "next": c.next,
        "compare": c.compare.value,
    }


# ---- the handlers --------------------------------------------------------------------------------
class SessionApi:
    """`jarvis.voice.profile_ports.ProfileApi` (app.state.voice_profile_api)."""

    def __init__(self, sessions: VoiceSessions) -> None:
        self.s = sessions

    async def _profile(self, uid: str) -> dict[str, Any]:
        return profile_view(await self.s.profile(uid), laptop_ready=await self.s.laptop_ready())

    async def view(self, uid: str) -> Answer:
        return await self._profile(uid)

    async def update(self, uid: str, body: dict[str, Any]) -> Answer:
        patch = _parse(ProfilePatch, body)
        await self.s.change_profile(
            uid, chosen=patch.chosen, corrections_on=patch.corrections_on, forget=patch.forget
        )
        return await self._profile(uid)

    async def session(self, uid: str) -> Answer:
        doc = await self.s.current(uid)
        return session_view(doc, None if doc else await self.s.preview(uid))

    async def start(self, uid: str, body: dict[str, Any]) -> Answer:
        b = _parse(StartBody, body)
        if b.yes is not None and b.yes.strip() != YES_WORD:
            raise ProfileRefused(422, "type_yes", TYPE_YES)
        words = [clean_phrase(w) for w in b.words]
        if any(w is None for w in words):
            raise ProfileRefused(422, "input_rejected", BAD_WORD)
        req = StartIn(
            yes=b.yes is not None,
            skip_google=b.compare is False,
            restart=b.restart,
            words=tuple(w for w in words if w is not None),
        )
        return session_view(await self.s.start(uid, req))

    async def put_clip(self, uid: str, prompt_id: str, body: dict[str, Any]) -> Answer:
        b = _parse(ClipBody, body)
        return _clip(await self.s.put_clip(uid, prompt_id, decode_wav(b.audio), b.browser_heard))

    async def score(self, uid: str, body: dict[str, Any]) -> Answer:
        _parse(EmptyBody, body)
        await self.s.score(uid)
        return await self.results(uid)

    async def results(self, uid: str) -> Answer:
        doc, job = await self.s.poll(uid)
        view = session_view(doc)
        return {
            "state": view["state"],
            "reason": view["reason"],
            "words_added": view["words_added"],
            "job": None if job is None else {"state": job.state.value, "progress": job.progress},
            "profile": await self._profile(uid),
        }

    async def recheck(self, uid: str, body: dict[str, Any]) -> Answer:
        _parse(EmptyBody, body)
        await self.s.recheck(uid)
        return await self.results(uid)

    async def delete_recordings(self, uid: str, *, wakeword: bool = False) -> Answer:
        gone = await self.s.delete_recordings(uid, wakeword=wakeword)
        n = gone.clips
        words = f"Deleted {n} recording{'s' if n != 1 else ''} from your laptop."
        if not self.s.kit_set_up:
            words = WORDS_ONLY_HERE
        elif gone.wakeword_files:
            words += " The wake-word files made from them are deleted too."
        return {"clips": n, "wakeword_files": gone.wakeword_files, "words": words}


# ---- the production parts ------------------------------------------------------------------------
class ServiceGoogle:
    """Google's listening with his words, through the voice service's own gate and meter."""

    def __init__(self, voice: VoiceService) -> None:
        self.v = voice

    def ready(self) -> bool:
        return self.v.state("stt")[0] == "ready"

    async def free_seconds_left(self) -> float:
        price = self.v.prices.stt
        used = (await self.v.billing.allowance([price.key])).used(price.key)
        return max(0.0, price.free_units - used)

    async def inr_per_minute(self) -> float:
        return await self.v.billing.inr(self.v.prices.stt.usd_per_unit * 60)

    async def hear(self, uid: str, wav: bytes, *, free_only: bool) -> GoogleHeard:
        start = time.monotonic()
        # I1: Google alone (V2's routing would send it to the laptop and apply his corrections)
        got = await self.v.transcribe(uid, wav, free_only=free_only, google_only=True)
        return GoogleHeard(text=got.text, ms=int((time.monotonic() - start) * 1000))


class SettingsWords:
    """His words to recognise: R5's `VoiceSettings.phrases`, the one list (at most 50)."""

    def __init__(self, voice: VoiceService) -> None:
        self.v = voice

    async def read(self, uid: str) -> tuple[str, ...]:
        return (await self.v.store.get(uid)).phrases  # raises when it can't be read

    async def add(self, uid: str, words: tuple[str, ...]) -> tuple[str, ...]:
        have = list(await self.read(uid))
        known = {w.casefold() for w in have}
        added: list[str] = []
        for raw in words:
            w = clean_phrase(raw)
            if w is None or w.casefold() in known or len(have) + len(added) >= PHRASE_ITEMS:
                continue
            known.add(w.casefold())
            added.append(w)
        if added:
            await self.v.update_settings(uid, VoiceSettingsPatch(phrases=[*have, *added]))
        return tuple(added)


def r18_normalise() -> Normalise:
    """R18's transcript normaliser (`jarvis.calls.langcheck.scoring.normalise`, R18 B), found when
    the app is built: R5.2 reuses it, never copies it (brief rule 10)."""
    try:
        module = importlib.import_module("jarvis.calls.langcheck.scoring")
    except ImportError as exc:
        raise RuntimeError("R18's language check (jarvis.calls.langcheck) is not merged") from exc
    return cast(Normalise, module.normalise)


def build_profile_api(
    s: Settings,
    *,
    docs: Docs,
    voice: VoiceService,
    profiles: ProfileStore,
    kit: KitClient | None,
    normalise: Normalise | None = None,
) -> SessionApi:
    """I1: `app.state.voice_profile_api` (`profiles`: the one `DocProfileStore` V2 reads too)."""
    parts = SessionParts(
        kit=kit if s.local_speech_configured else None,
        profiles=profiles,
        sessions=DocSessionStore(docs, prefix=s.firestore_prefix),
        google=ServiceGoogle(voice),
        words=SettingsWords(voice),
        normalise=normalise or r18_normalise(),
        compare_minutes=s.voice_session_compare_minutes,
        health_s=float(s.local_speech_health_s),
    )
    return SessionApi(VoiceSessions(parts))


__all__ = [
    "LABELS",
    "ServiceGoogle",
    "SessionApi",
    "SettingsWords",
    "build_profile_api",
    "compare_view",
    "profile_view",
    "r18_normalise",
    "session_view",
]

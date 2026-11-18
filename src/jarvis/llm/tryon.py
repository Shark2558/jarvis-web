# src/jarvis/llm/tryon.py
"""R13.1 I0 seam 5 (docs/plans/r13-1-try-on.md D10, D13, D15, D18, D19; plan review H1, L4, L12):
the try-on provider PORT. "See it on me" asks this port, never a model id (the model-agnostic
rule): the wardrobe reads `WardrobeContext.tryon()`, which the wiring fills from `build_tryon`.

- `TryOnProvider.make(ask) -> TryOnResult`: ONE picture of the person in the garments. A provider
  whose model takes one garment a call (`max_garments = 1`) chains inside its own adapter, so the
  wardrobe never sees steps (H1). `describe()` is what the consent names; `estimate(n)` is
  `(typical_usd, worst_usd)` for `n` garments.
- Billed or not (Google: "You're charged only for requests that return a 200 response code"):
  `TryOnNotBilled` (any non-200, or never sent: the hold is released) and `TryOnMaybeBilled` (a
  timeout after sending, a cut 200: kept at the hold). A 200 without a picture is a result with
  `blocked` set, and it IS billed.
- `TRYON_PRICES` per (model, location): Google's token prices (G4, read 17 Nov 2026); `price_of`,
  `typical_usd`, `worst_usd` (the hold: `MAX_OUTPUT_TOKENS` out, the image at its price and the
  rest at the text price) and `cost_usd` (the settle, from the answer's usage). Dollars only: the
  ₹, the day's rate and GST are the wardrobe's (`billing.spend.with_tax`).
- `build_tryon(s, tokens=, project=)`: None while pictures are off (`tryon_pictures`) or the
  (model, location) is unpriced, or while the family's adapter is not built yet; else the
  adapter module's `build(s, tokens=, project=)` (Part C writes `jarvis.llm.tryon_gemini`).
  `tokens` is a bearer-token source (the wiring passes `voice.adc.AdcTokens`); `project()` is
  the Google Cloud project (`firestore_project`, else ADC's), looked up late.

Nothing here makes a call, reads a clock, logs a body or keeps a picture.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass
from importlib import import_module
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from jarvis.logging import get_logger

if TYPE_CHECKING:
    from jarvis.config import Settings

log = get_logger(__name__)

PROVIDER_WORDS = "Google Cloud's Agent Platform"
MODEL_WORDS: Mapping[str, str] = {
    "gemini-3.1-flash-image": "Gemini 3.1 Flash Image",
    "gemini-nano-banana-2.1": "Gemini Nano Banana 2.1",
}
LOCATION_WORDS: Mapping[str, str] = {
    "us": "processed in the United States",
    "eu": "processed in the European Union",
    "global": "processed in any country Google chooses",
}
RETIRES_ON: Mapping[str, str] = {"gemini-3.1-flash-image": "2027-05-28"}  # "or later" (G9)
ADAPTERS: dict[str, str] = {"gemini": "jarvis.llm.tryon_gemini"}  # a model family -> its adapter
MAX_GARMENTS = 3  # the top, the bottom and the outer layer, in one request (D13.1)
MAX_OUTPUT_TOKENS = 8192  # `generationConfig.maxOutputTokens` (D10): the hold's worst case
THINKING_TYPICAL = 1000  # about 1,000 thinking tokens a picture (the plan's ≈ ₹8.9)
PROMPT_TOKENS = 150  # the fixed English text part
# The only words a garment is sent in: lower-case letters and spaces ("a new navy shirt"). One
# rule for the wardrobe (before the reserve) and every adapter (before anything leaves) (I1).
FIXED_WORDS = re.compile(r"^[a-z][a-z ]{0,59}$")


@dataclass(frozen=True)
class TryOnPrice:
    """Dollars per million tokens: input, text (and thinking) output, image output; the tokens
    one image counts for (in or out, a 1K picture)."""

    input_per_m: float
    text_per_m: float
    image_per_m: float
    tokens_per_image: int = 1120


_FLASH = TryOnPrice(input_per_m=0.55, text_per_m=3.30, image_per_m=66.0)  # non-global (G4)
TRYON_PRICES: Mapping[tuple[str, str], TryOnPrice] = {
    ("gemini-3.1-flash-image", "us"): _FLASH,
    ("gemini-3.1-flash-image", "eu"): _FLASH,
    # `global` only; its text price is not on the page read: the image price bounds it (G4, G10)
    ("gemini-nano-banana-2.1", "global"): TryOnPrice(1.50, 30.0, 30.0),
}


def price_of(model: str, location: str) -> TryOnPrice:
    """The price of (model, location); KeyError when it is not priced (then nothing is sent)."""
    return TRYON_PRICES[(model, location)]


def _usd(tokens: float, per_m: float) -> float:
    return tokens * per_m / 1_000_000


def _input_usd(price: TryOnPrice, garments: int) -> float:
    return _usd((1 + garments) * price.tokens_per_image + PROMPT_TOKENS, price.input_per_m)


def typical_usd(price: TryOnPrice, *, garments: int, thinking: int = THINKING_TYPICAL) -> float:
    """His photo and `garments` crops in, one 1K picture out, `thinking` text tokens."""
    out = _usd(price.tokens_per_image, price.image_per_m) + _usd(thinking, price.text_per_m)
    return _input_usd(price, garments) + out


def worst_usd(price: TryOnPrice, *, garments: int) -> float:
    """The most one request may cost: the picture and the rest of `MAX_OUTPUT_TOKENS` as text."""
    rest = MAX_OUTPUT_TOKENS - price.tokens_per_image
    out = _usd(price.tokens_per_image, price.image_per_m) + _usd(rest, price.text_per_m)
    return _input_usd(price, garments) + out


@dataclass(frozen=True)
class TryOnUsage:
    """What the answer says it used (`usageMetadata`): the settle reads these."""

    input_tokens: int
    image_tokens: int
    text_tokens: int = 0  # text and thinking output


def cost_usd(price: TryOnPrice, usage: TryOnUsage) -> float:
    return (
        _usd(usage.input_tokens, price.input_per_m)
        + _usd(usage.image_tokens, price.image_per_m)
        + _usd(usage.text_tokens, price.text_per_m)
    )


@dataclass(frozen=True)
class Garment:
    image: bytes  # the piece's saved crop (JPEG), never a private piece's
    words: str  # fixed words only ("a navy shirt"): never his label


@dataclass(frozen=True)
class TryOnAsk:
    person: bytes  # his one photo (a cleaned JPEG)
    garments: tuple[Garment, ...]
    timeout_s: float


@dataclass(frozen=True)
class TryOnResult:
    picture: bytes | None  # as the provider returned it (never decoded or re-encoded, L5)
    mime: str | None  # from its magic bytes: image/jpeg or image/png
    usage: TryOnUsage | None
    blocked: str | None  # a 200 without a picture (a safety block, a finish without one): billed

    @property
    def made(self) -> bool:
        return self.picture is not None and self.blocked is None


@dataclass(frozen=True)
class TryOnDescription:
    """What the consent names (D11) and the section shows."""

    provider: str
    model: str
    model_words: str
    location: str
    location_words: str
    max_garments: int
    retires_on: str  # YYYY-MM-DD, or "" when the provider names no end

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class TryOnError(RuntimeError):
    """No picture. `billed` says whether Google may have charged for it."""

    billed: bool = True


class TryOnNotBilled(TryOnError):
    """Any non-200 answer, or never sent: nothing was charged (release the hold)."""

    billed = False


class TryOnMaybeBilled(TryOnError):
    """A timeout after sending, or a 200 cut short: it may be charged (keep the hold)."""

    billed = True


@runtime_checkable
class TryOnProvider(Protocol):
    def describe(self) -> TryOnDescription: ...

    def estimate(self, n: int) -> tuple[float, float]: ...

    async def make(self, ask: TryOnAsk) -> TryOnResult: ...


class BearerTokens(Protocol):
    """Request headers proving who JARVIS is to Google (`voice.adc.AdcTokens` has this shape)."""

    async def headers(self) -> dict[str, str]: ...

    def invalidate(self) -> None: ...


ProjectFn = Callable[[], Awaitable[str | None]]


def family_of(model: str) -> str:
    return model.split("-", 1)[0]


def build_tryon(s: Settings, *, tokens: BearerTokens, project: ProjectFn) -> TryOnProvider | None:
    """The deployment's try-on provider, or None (pictures off, unpriced, adapter not built)."""
    if not s.tryon_pictures:
        return None
    if (s.tryon_model, s.tryon_location) not in TRYON_PRICES:
        log.warning("try-on: no price for this model and location", extra={"model": s.tryon_model})
        return None
    name = ADAPTERS.get(family_of(s.tryon_model))
    if name is None:
        return None
    try:
        module = import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise  # the adapter is there but something it needs is missing: never hidden
        log.info("try-on: the adapter is not built yet", extra={"model": s.tryon_model})
        return None
    provider: TryOnProvider = module.build(s, tokens=tokens, project=project)
    return provider


__all__ = [
    "ADAPTERS",
    "FIXED_WORDS",
    "LOCATION_WORDS",
    "MAX_GARMENTS",
    "MAX_OUTPUT_TOKENS",
    "MODEL_WORDS",
    "PROMPT_TOKENS",
    "PROVIDER_WORDS",
    "RETIRES_ON",
    "THINKING_TYPICAL",
    "TRYON_PRICES",
    "BearerTokens",
    "Garment",
    "ProjectFn",
    "TryOnAsk",
    "TryOnDescription",
    "TryOnError",
    "TryOnMaybeBilled",
    "TryOnNotBilled",
    "TryOnPrice",
    "TryOnProvider",
    "TryOnResult",
    "TryOnUsage",
    "build_tryon",
    "cost_usd",
    "family_of",
    "price_of",
    "typical_usd",
    "worst_usd",
]

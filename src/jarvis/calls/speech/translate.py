# src/jarvis/calls/speech/translate.py
"""Call sentences translated by the brain, once (R18 B; Layer 4 through `jarvis.llm` tiers).

The pre-made lines (the opening disclosure, hold, goodbye, ...) and the language check's call
sentences are written in English and translated ONCE per language by the FAST tier, then cached
(`jarvis.calls.speech.lines`, `jarvis.calls.langcheck`): never per call.

Containment: only a brain that does not train on content (`BrainSpec.tools_allowed`; never the
Gemini free tier, brief "Brain") is asked; no tools; the owner's monthly limit is checked first
(`Billing.ensure_allowed`) and the reply's cost metered (`Billing.record`). The input is JARVIS's
own fixed English sentences (no one else's words). The output is checked before it is kept:

- exactly the keys asked, each a non-empty string of at most MAX_LINE characters, one line
- every `{placeholder}` of the English kept exactly once, and no other brace
- the same numbers (digit for digit, any script's digits) as the English
- every marked fact (`facts`) a part of its own translation; facts that are not are dropped

A reply that fails any of these is refused whole (`TranslationRefused`): a wrong opening
disclosure is worse than English.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from jarvis.billing import Billing, BudgetError
from jarvis.calls.langcheck.scoring import normalise, number_facts
from jarvis.calls.models import LANGUAGE_NAMES
from jarvis.llm.base import ChatMessage, LLMError, Role
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.pricing import cost_usd
from jarvis.llm.router import ModelTier
from jarvis.logging import get_logger

log = get_logger(__name__)

MAX_LINE = 400
MAX_LINES = 20
MAX_TOKENS = 3_000
_PLACEHOLDER = re.compile(r"\{[a-z_]+\}")
_BRACE = re.compile(r"[{}]")

SYSTEM = """You translate short phone-call sentences for JARVIS, an AI assistant that makes \
phone calls for its owner.

Rules
- Translate every value into {language} as a polite native speaker says it on the phone: \
natural spoken words, short, the same meaning. Use the language's own script.
- Keep every placeholder in curly braces, such as {{first_name}}, exactly as written, once.
- Write every number and time with digits exactly as in the English (10:30 stays 10:30).
- Answer with JSON only, no other text: an object with exactly the same keys; each value an \
object {{"text": "<the translation>", "facts": ["<word>", ...]}}. "facts" lists the words of \
YOUR translation that carry a key fact: each number or time as written, the word for yes or no, \
day names and names. An empty list when there are none."""


class TranslationRefused(RuntimeError):
    """No translation: no private brain, the limit, the brain failed, or its reply was not kept."""


@dataclass(frozen=True)
class Translation:
    text: str
    facts: tuple[str, ...] = ()


class Translator(Protocol):
    async def translate(self, english: Mapping[str, str], lang: str) -> dict[str, Translation]: ...


def private_brain(registry: BrainRegistry) -> BrainSpec | None:
    """The default brain if it keeps content private, else the first that does, else None."""
    if registry.default.tools_allowed:
        return registry.default
    return next((b for b in registry.list() if b.tools_allowed), None)


def _json_object(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise TranslationRefused("the brain's reply was not JSON")
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        raise TranslationRefused("the brain's reply was not JSON") from None
    if not isinstance(data, dict):
        raise TranslationRefused("the brain's reply was not a JSON object")
    return data


def _one(key: str, english: str, raw: object) -> Translation:
    if not isinstance(raw, dict) or not isinstance(raw.get("text"), str):
        raise TranslationRefused(f"no translation for {key}")
    text = " ".join(str(raw["text"]).split())
    if not text or len(text) > MAX_LINE:
        raise TranslationRefused(f"the translation of {key} is empty or too long")
    wanted = sorted(_PLACEHOLDER.findall(english))
    if sorted(_PLACEHOLDER.findall(text)) != wanted or len(_BRACE.findall(text)) != 2 * len(wanted):
        raise TranslationRefused(f"the translation of {key} changed a placeholder")
    if number_facts(text) != number_facts(english):
        raise TranslationRefused(f"the translation of {key} changed a number")
    facts_raw = raw.get("facts", [])
    facts = facts_raw if isinstance(facts_raw, list) else []
    norm = f" {normalise(text)} "
    kept = tuple(
        f.strip() for f in facts if isinstance(f, str) and f.strip() and f" {normalise(f)} " in norm
    )
    return Translation(text, kept[:10])


def check_reply(english: Mapping[str, str], reply: str) -> dict[str, Translation]:
    """The brain's reply, checked (see the module docstring)."""
    data = _json_object(reply)
    if set(data) != set(english):
        raise TranslationRefused("the brain's reply did not have exactly the keys asked")
    return {k: _one(k, english[k], data[k]) for k in english}


class BrainTranslator:
    """`Translator` on the FAST tier of a private brain, gated and metered for `uid`."""

    def __init__(self, brains: BrainRegistry, billing: Billing, uid: str) -> None:
        self.brains = brains
        self.billing = billing
        self.uid = uid

    async def translate(self, english: Mapping[str, str], lang: str) -> dict[str, Translation]:
        if not english or len(english) > MAX_LINES:
            raise ValueError(f"1 to {MAX_LINES} sentences at a time")
        name = LANGUAGE_NAMES.get(lang)
        if name is None:
            raise ValueError("unknown call language")
        spec = private_brain(self.brains)
        if spec is None:
            raise TranslationRefused("no brain that keeps content private is configured")
        router = self.brains.router_for(spec.id)
        if await router.blocked_now():
            raise TranslationRefused("the AI is switched off just now")
        try:
            await self.billing.ensure_allowed(self.uid, spec)
            reply = await router.complete(
                tier=ModelTier.FAST,
                system=SYSTEM.format(language=name),
                messages=[ChatMessage(role=Role.USER, content=json.dumps(dict(english)))],
                max_tokens=MAX_TOKENS,
                tools=None,
                allow_degrade=False,
            )
        except (BudgetError, LLMError) as exc:
            log.warning("call lines not translated", extra={"why": type(exc).__name__})
            raise TranslationRefused("the brain could not translate just now") from None
        await self.billing.record(
            self.uid, spec.id, reply.cost_usd or cost_usd(reply.model, reply.usage)
        )
        out = check_reply(english, reply.text)
        log.info("call lines translated", extra={"lang": lang, "lines": len(out)})
        return out


__all__ = [
    "MAX_LINE",
    "SYSTEM",
    "BrainTranslator",
    "Translation",
    "TranslationRefused",
    "Translator",
    "check_reply",
    "private_brain",
]

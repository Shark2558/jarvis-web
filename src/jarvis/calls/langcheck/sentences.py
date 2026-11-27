# src/jarvis/calls/langcheck/sentences.py
"""The language check's call sentences (R18 B; plan 5.3 step 2): 10 per language, made once.

Ten short sentences of the kind a call carries (a time, a day, an amount, a yes or a no), written
in English with their key facts. For another language the brain translates them once (FAST tier,
`jarvis.calls.speech.translate`: numbers kept as digits, the fact words marked in its own
translation and checked to be there) and the result is kept:

    {prefix}call_check_sentences/{lang}   items {key: {text, facts}}, english (hash), made_at

A sentence's key facts are its numbers (digit groups, as the scorer reads them) and the words the
brain marked (yes / no, day and month names; never a digit, so no fact counts twice).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Protocol

from jarvis.calls.langcheck.scoring import number_facts
from jarvis.calls.models import ENGLISH, LANGUAGE_NAMES
from jarvis.calls.speech.translate import Translator
from jarvis.storage.docs import Docs, DocTx

COLL = "call_check_sentences"
# key: (English sentence, its word facts; its numbers are facts too)
ENGLISH_SENTENCES: MappingProxyType[str, tuple[str, tuple[str, ...]]] = MappingProxyType(
    {
        "pickup": ("Yes, the pickup is tomorrow at 10:30.", ("yes",)),
        "closed": ("No, we are closed on Sunday.", ("no", "Sunday")),
        "total": ("The total is 450 rupees.", ()),
        "later": ("Please call back after 4 in the evening.", ()),
        "booking": ("Your booking number is 7291.", ()),
        "saturday": ("We can come on Saturday between 11 and 1.", ("Saturday",)),
        "items": ("Yes, 3 shirts and 2 trousers.", ("yes",)),
        "appointment": ("The appointment is on 28 November at 9:15.", ("November",)),
        "address": ("No, the shop is at 12 Station Road.", ("no",)),
        "delivery": ("Thank you, we will deliver in 2 days.", ()),
    }
)
ENGLISH_HASH = hashlib.sha256(
    json.dumps({k: v[0] for k, v in ENGLISH_SENTENCES.items()}, sort_keys=True).encode()
).hexdigest()[:32]


@dataclass(frozen=True)
class Sentence:
    key: str
    text: str
    facts: tuple[str, ...]  # numbers (digit strings) and words


class SentenceSource(Protocol):
    async def sentences(self, lang: str) -> list[Sentence]: ...


def _facts(text: str, words: tuple[str, ...]) -> tuple[str, ...]:
    kept = tuple(w for w in words if not any(c.isdecimal() for c in w))
    return (*number_facts(text), *kept)


def english() -> list[Sentence]:
    return [
        Sentence(k, text, _facts(text, words)) for k, (text, words) in ENGLISH_SENTENCES.items()
    ]


class CheckSentences:
    def __init__(self, docs: Docs, *, prefix: str, translator: Translator) -> None:
        self.docs = docs
        self.prefix = prefix
        self.translator = translator

    def _path(self, lang: str) -> str:
        return f"{self.prefix}{COLL}/{lang}"

    async def sentences(self, lang: str) -> list[Sentence]:
        if lang not in LANGUAGE_NAMES:
            raise ValueError("unknown call language")
        if lang == ENGLISH:
            return english()
        stored = await self.docs.get(self._path(lang))
        items = stored.get("items") if stored and stored.get("english") == ENGLISH_HASH else None
        if isinstance(items, dict) and set(items) == set(ENGLISH_SENTENCES):
            return [
                Sentence(k, str(items[k]["text"]), tuple(str(f) for f in items[k]["facts"]))
                for k in ENGLISH_SENTENCES
            ]
        made = await self.translator.translate(
            {k: v[0] for k, v in ENGLISH_SENTENCES.items()}, lang
        )
        out = [Sentence(k, made[k].text, _facts(made[k].text, made[k].facts)) for k in made]
        doc = {
            "items": {s.key: {"text": s.text, "facts": list(s.facts)} for s in out},
            "english": ENGLISH_HASH,
            "made_at": datetime.now(UTC).isoformat(),
        }

        async def save(tx: DocTx) -> None:
            tx.set(self._path(lang), doc)

        await self.docs.transaction(save)
        return out


__all__ = [
    "COLL",
    "ENGLISH_SENTENCES",
    "CheckSentences",
    "Sentence",
    "SentenceSource",
    "english",
]

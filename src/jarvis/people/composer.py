# src/jarvis/people/composer.py
"""The one brain call behind a dossier (R4 D10). It asks the router for a TIER (never a model id),
with no tools at all, so the untrusted findings in the prompt cannot trigger any action. In
no-AI mode the router itself refuses (`BrainOff`), and `PeopleService` degrades to links.
"""

from __future__ import annotations

from jarvis.llm.base import ChatMessage, Role
from jarvis.llm.router import ModelRouter, ModelTier
from jarvis.people.research import Composer

MAX_TOKENS = 400


def router_composer(router: ModelRouter, tier: ModelTier = ModelTier.FAST) -> Composer:
    async def compose(system: str, prompt: str) -> str:
        done = await router.complete(
            tier=tier,
            system=system,
            messages=[ChatMessage(role=Role.USER, content=prompt)],
            max_tokens=MAX_TOKENS,
            tools=None,
        )
        return done.text

    return compose


__all__ = ["router_composer"]

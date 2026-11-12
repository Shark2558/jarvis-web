# src/jarvis/llm/brains.py
"""BrainRegistry: every configured LLM backend ("brain"), selectable per session.

A brain = provider + tier→model map + privacy flags. `tools_allowed` is DERIVED from
`trains_on_content` and cannot be configured independently: a vendor that may train on prompts
must never receive tool specs or tool output (email, calendar, files). `Brain` enforces it.
"""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.config import LLMBackend, Settings
from jarvis.llm.anthropic_provider import AnthropicProvider
from jarvis.llm.base import LLMProvider
from jarvis.llm.fallback import FallbackBrain
from jarvis.llm.gemini_provider import GeminiProvider
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.openai_compat_provider import OpenAICompatProvider
from jarvis.llm.router import ModelRouter, ModelTier, tiers_for

TRAINING_WARNING = (
    "{label} brain: the provider may use what you type here to improve its products. "
    "Do not share private or confidential information. Tools are disabled on this brain."
)


@dataclass(frozen=True)
class BrainSpec:
    id: str
    label: str
    provider: LLMProvider
    tiers: dict[ModelTier, str]
    trains_on_content: bool = False

    @property
    def tools_allowed(self) -> bool:
        return not self.trains_on_content

    @property
    def sees_pictures(self) -> bool:
        """R11.1 D10: this brain may be sent an attached picture: its provider can read one AND
        it never trains on content (a private picture never reaches a training brain)."""
        return bool(getattr(self.provider, "vision", False)) and not self.trains_on_content

    @property
    def warning(self) -> str:
        return TRAINING_WARNING.format(label=self.label) if self.trains_on_content else ""

    def router(self, fallback: FallbackBrain | None = None) -> ModelRouter:
        return ModelRouter(self.provider, self.tiers, fallback=fallback)


class BrainRegistry:
    def __init__(
        self,
        brains: list[BrainSpec],
        *,
        default_id: str,
        fallback: FallbackBrain | None = None,
    ) -> None:
        self._brains = {b.id: b for b in brains}
        if default_id not in self._brains:
            raise ValueError(f"default brain {default_id!r} is not configured")
        self._default_id = default_id
        # R1 D10: every brain falls back to the owner's laptop when ITS cloud is unreachable
        self._routers = {b.id: b.router(fallback) for b in brains}

    def list(self) -> list[BrainSpec]:
        return list(self._brains.values())

    @property
    def default(self) -> BrainSpec:
        return self._brains[self._default_id]

    def get(self, brain_id: str) -> BrainSpec:
        try:
            return self._brains[brain_id]
        except KeyError:
            raise LookupError(f"unknown brain {brain_id!r}") from None

    def router_for(self, brain_id: str) -> ModelRouter:
        self.get(brain_id)
        return self._routers[brain_id]

    # ---- construction --------------------------------------------------------------------

    @classmethod
    def from_settings(
        cls,
        s: Settings,
        provider: LLMProvider | None = None,
        *,
        local: FallbackBrain | None = None,
    ) -> BrainRegistry:
        """Build every brain that has credentials. `provider` (tests) replaces the default
        brain's provider and skips the credential check for it. `local` (R1): the fallback brain
        on the owner's laptop, shared by every router."""
        brains: list[BrainSpec] = []
        default = s.llm_backend.value

        def add(spec: BrainSpec) -> None:
            brains.append(spec)

        if provider is not None or (s.llm_backend is LLMBackend.MOCK):
            # single injected provider under the default id (tests / offline dev)
            tiers = tiers_for(s, s.llm_backend)
            add(
                BrainSpec(
                    id=default,
                    label=_LABELS.get(s.llm_backend, default),
                    provider=provider or MockProvider(),
                    tiers=tiers,
                    trains_on_content=s.llm_trains_on_content,
                )
            )
            return cls(brains, default_id=default, fallback=local)

        if s.anthropic_api_key is not None:
            add(
                BrainSpec(
                    id=LLMBackend.ANTHROPIC.value,
                    label="Claude",
                    provider=AnthropicProvider(
                        s.anthropic_api_key.get_secret_value(),
                        timeout_s=s.llm_timeout_s,
                        max_retries=s.llm_max_retries,
                    ),
                    tiers=tiers_for(s, LLMBackend.ANTHROPIC),
                )
            )
        if s.gemini_api_key is not None:
            add(
                BrainSpec(
                    id=LLMBackend.GEMINI.value,
                    label="Gemini" + ("" if s.gemini_paid_tier else " (free)"),
                    provider=GeminiProvider(
                        s.gemini_api_key.get_secret_value(), timeout_s=s.llm_timeout_s
                    ),
                    tiers=tiers_for(s, LLMBackend.GEMINI),
                    trains_on_content=not s.gemini_paid_tier,
                )
            )
        if s.openai_compat_configured:
            assert s.openai_compat_base_url is not None
            add(
                BrainSpec(
                    id=LLMBackend.OPENAI_COMPAT.value,
                    label=s.openai_compat_label,
                    provider=OpenAICompatProvider(
                        s.openai_compat_base_url,
                        api_key=(
                            s.openai_compat_api_key.get_secret_value()
                            if s.openai_compat_api_key
                            else None
                        ),
                        timeout_s=s.llm_timeout_s,
                    ),
                    tiers=tiers_for(s, LLMBackend.OPENAI_COMPAT),
                    trains_on_content=s.openai_compat_trains_on_content,
                )
            )
        if default not in {b.id for b in brains}:
            raise RuntimeError(_MISSING[s.llm_backend])
        return cls(brains, default_id=default, fallback=local)


_LABELS = {
    LLMBackend.ANTHROPIC: "Claude",
    LLMBackend.GEMINI: "Gemini",
    LLMBackend.OPENAI_COMPAT: "Custom",
    LLMBackend.MOCK: "Mock",
}

_MISSING = {
    LLMBackend.ANTHROPIC: "JARVIS_ANTHROPIC_API_KEY is required for the anthropic backend",
    LLMBackend.GEMINI: "JARVIS_GEMINI_API_KEY is required for the gemini backend",
    LLMBackend.OPENAI_COMPAT: "JARVIS_OPENAI_COMPAT_BASE_URL and _MODEL_BALANCED are required",
    LLMBackend.MOCK: "mock backend misconfigured",
}

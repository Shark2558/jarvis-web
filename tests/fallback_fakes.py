# tests/fallback_fakes.py -- scripted cloud provider and fallback brain for the R1 C router tests.
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from jarvis.llm.base import ChatMessage, Completion, LLMError, Role, Usage
from jarvis.llm.router import ModelTier

TIERS = {ModelTier.FAST: "f", ModelTier.BALANCED: "b", ModelTier.STRONG: "s"}
MSGS = [ChatMessage(role=Role.USER, content="hi")]
KW: dict[str, Any] = {"system": "sys", "messages": MSGS, "max_tokens": 50}


def _completion(model: str, text: str = "ok", offline: bool = False) -> Completion:
    return Completion(
        text=text, model=model, provider="p", usage=Usage(), latency_ms=1, offline=offline
    )


class CloudProvider:
    name = "cloud"

    def __init__(self, *errors: Exception, deltas: list[str] | None = None) -> None:
        self.errors = list(errors)
        self.models: list[str] = []
        self.deltas = deltas or ["a ", "b "]
        self.stream_fail_after: int | None = None

    async def complete(self, **kw: Any) -> Completion:
        self.models.append(kw["model"])
        if self.errors:
            raise self.errors.pop(0)
        return _completion(kw["model"], "from cloud")

    async def stream(self, **kw: Any) -> AsyncIterator[str]:
        self.models.append(kw["model"])
        if self.errors and self.stream_fail_after is None:
            raise self.errors.pop(0)
        for i, d in enumerate(self.deltas):
            if self.stream_fail_after is not None and i == self.stream_fail_after:
                raise self.errors.pop(0)
            yield d


class FakeFallback:
    def __init__(
        self, *, ready: bool = True, fail: bool = False, error: Exception | None = None
    ) -> None:
        self._ready = ready
        self.fail = fail
        self.error = error
        self.calls: list[dict[str, Any]] = []
        self.streams: list[dict[str, Any]] = []
        self.cloud_oks = 0

    async def ready(self) -> bool:
        return self._ready

    async def complete(self, **kw: Any) -> Completion:
        self.calls.append(kw)
        if self.error:
            raise self.error
        if self.fail:
            raise LLMError("laptop down")
        return _completion("laptop", "from laptop", offline=True)

    async def stream(self, **kw: Any) -> AsyncIterator[str]:
        self.streams.append(kw)
        if self.fail:
            raise LLMError("laptop down")
        yield "lap "
        yield "top "

    async def cloud_ok(self) -> None:
        self.cloud_oks += 1

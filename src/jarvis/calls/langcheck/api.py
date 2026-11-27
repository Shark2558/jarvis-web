# src/jarvis/calls/langcheck/api.py
"""What the Calls panel's language routes call (R18 B; I1 wires them into `CallsApi`).

    POST /api/calls/languages/check  `handle_check(check, body)`
        {languages?, options?, estimate_only = true, accept_inr = 0, accept_unknown = false}
        estimate_only (the default): the plan and its ₹, nothing sent to any vendor; else the run
        (minutes: run it as a background task), refused with 409 when its ₹ is above
        `accept_inr` or a check is already running
    POST /api/calls/languages/score  `handle_score(check, body)` {lang, option, scores: [1-5]}
    GET  /api/calls/languages        `languages_view(results, settings)`: the table

Bodies are validated strictly (unknown fields, a language JARVIS does not list, a score outside
1-5: 422 with plain words, never the value echoed). Answers carry no audio and no transcript.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from jarvis.calls.langcheck.runner import CheckPlan, CheckRefused, LanguageCheck
from jarvis.calls.langcheck.select import table
from jarvis.calls.models import LANGUAGE_NAMES, CallSettings, LanguageResult, SpeechOption
from jarvis.calls.ports import CallsRefused
from jarvis.calls.speech.catalogue import DEFAULT_CHECK

MAX_ACCEPT_INR = 500


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    languages: tuple[str, ...] = Field(default=DEFAULT_CHECK, min_length=1, max_length=23)
    options: tuple[SpeechOption, ...] | None = None
    estimate_only: bool = True
    accept_inr: float = Field(default=0.0, ge=0, le=MAX_ACCEPT_INR)
    accept_unknown: bool = False

    @field_validator("languages")
    @classmethod
    def _known(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if any(x not in LANGUAGE_NAMES for x in v):
            raise ValueError("a language JARVIS does not list")
        return tuple(dict.fromkeys(v))


class ScoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lang: str
    option: SpeechOption
    scores: tuple[int, ...] = Field(min_length=1, max_length=10)

    @field_validator("lang")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in LANGUAGE_NAMES:
            raise ValueError("a language JARVIS does not list")
        return v

    @field_validator("scores")
    @classmethod
    def _range(cls, v: tuple[int, ...]) -> tuple[int, ...]:
        if any(s < 1 or s > 5 for s in v):
            raise ValueError("each score is 1 to 5")
        return v


def _parse(model: type[BaseModel], body: Mapping[str, Any]) -> Any:
    try:
        return model.model_validate(dict(body))
    except ValidationError as exc:
        fields = sorted({".".join(str(x) for x in e["loc"][:1]) for e in exc.errors()})
        raise CallsRefused(
            422, "bad_request", f"Check these fields: {', '.join(fields)}."
        ) from None


def plan_view(plan: CheckPlan) -> dict[str, Any]:
    return {
        "total_inr": plan.total_inr,
        "unknown_price": [f"{p.lang} {p.option}" for p in plan.unknown],
        "pairs": [
            {
                "lang": p.lang,
                "option": p.option,
                "hear": p.hear,
                "speak": p.speak,
                "runs": p.runs,
                "inr": p.inr,
                "why": p.why,
            }
            for p in plan.pairs
        ],
    }


async def handle_check(check: LanguageCheck, body: Mapping[str, Any]) -> dict[str, Any]:
    req: CheckRequest = _parse(CheckRequest, body)
    options = [o.value for o in req.options] if req.options is not None else None
    plan = await check.plan(req.languages, options)
    if req.estimate_only:
        return {"plan": plan_view(plan)}
    try:
        report = await check.run(plan, accept_inr=req.accept_inr, accept_unknown=req.accept_unknown)
    except CheckRefused as exc:
        raise CallsRefused(409, "check_refused", str(exc)) from None
    return {
        "plan": plan_view(plan),
        "results": [r.model_dump(mode="json") for r in report.results],
        "skipped": report.skipped,
    }


async def handle_score(check: LanguageCheck, body: Mapping[str, Any]) -> dict[str, Any]:
    req: ScoreRequest = _parse(ScoreRequest, body)
    try:
        r = await check.score(req.lang, req.option.value, req.scores)
    except LookupError as exc:
        raise CallsRefused(404, "not_checked", str(exc)) from None
    return {"result": r.model_dump(mode="json")}


def languages_view(
    results: Sequence[LanguageResult], settings: CallSettings, langs: Sequence[str] = ()
) -> dict[str, Any]:
    rows = table(
        results,
        list(langs) or list(LANGUAGE_NAMES),
        sarvam_on=settings.sarvam_on,
        allow_balanced=settings.allow_balanced,
    )
    return {
        "languages": [
            {
                "lang": r.lang,
                "name": r.name,
                "offered": r.option is not None,
                "option": r.option,
                "inr_per_minute": r.inr_per_minute,
                "native_heard": r.native_heard,
                "needs_balanced": r.needs_balanced,
                "why": list(r.why),
            }
            for r in rows
        ]
    }


__all__ = [
    "MAX_ACCEPT_INR",
    "CheckRequest",
    "ScoreRequest",
    "handle_check",
    "handle_score",
    "languages_view",
    "plan_view",
]

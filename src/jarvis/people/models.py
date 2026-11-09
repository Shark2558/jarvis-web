# src/jarvis/people/models.py
"""The value types of people research: a profile link, a finding, a dossier."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Profile:
    platform: str
    url: str
    title: str


@dataclass(frozen=True)
class Finding:
    title: str
    domain: str
    snippet: str


@dataclass(frozen=True)
class Dossier:
    name: str
    context: str
    profiles: list[Profile] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    summary: str | None = None
    spoken: str = ""
    ambiguous: bool = False
    no_ai: bool = False
    note: str = ""
    subject: str = ""  # the verified class: public_figure | due_diligence
    cost_usd: float = 0.0  # what the model calls for this dossier cost (0 when none)


def dossier_from_dict(raw: dict[str, Any]) -> Dossier:
    """Rebuild a stored dossier; raises on anything that is not the shape we wrote."""
    return Dossier(
        name=str(raw["name"]),
        context=str(raw["context"]),
        profiles=[Profile(str(p["platform"]), str(p["url"]), str(p["title"]))
                  for p in raw["profiles"]],
        findings=[Finding(str(f["title"]), str(f["domain"]), str(f["snippet"]))
                  for f in raw["findings"]],
        summary=None if raw.get("summary") is None else str(raw["summary"]),
        spoken=str(raw.get("spoken", "")),
        ambiguous=bool(raw.get("ambiguous", False)),
        no_ai=bool(raw.get("no_ai", False)),
        note=str(raw.get("note", "")),
        subject=str(raw.get("subject", "")),
        cost_usd=float(raw.get("cost_usd", 0.0)),
    )  # fmt: skip


__all__ = ["Dossier", "Finding", "Profile", "dossier_from_dict"]

# src/jarvis/photos/tools.py
"""R4 C tools (permission row `connectors`): connect_github, connect_youtube, photos_import,
github_profile, github_repos, github_activity. Registered by the integrator (INTEGRATION.md);
a connector that is not built gets no tools.

- No tool ever takes a token: GitHub's is pasted in the Connectors panel (HTTP), never in chat.
- GitHub and YouTube words are other people's: fenced with `wrap_external`, never vouched.
- `photos_import` is two-step with no arguments: the first call opens Google's Picker (the owner
  chooses photos there); the next sends the chosen ones to the home laptop. It reports ids and
  counts, and names only consented, enrolled adults; a child is always "a child from your family".
  Enrolling an unnamed face is a panel action with consent, never a tool (as for Faces, D19).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.faces.models import NAME_MAX
from jarvis.faces.ports import FAMILY_CHILD
from jarvis.integrations.github import DEFAULT_ITEMS, MAX_ITEMS, GithubClient, GithubError
from jarvis.integrations.google import GoogleAPIError, GoogleNotConnected
from jarvis.integrations.youtube import YouTubeNotGranted, YouTubeOwn
from jarvis.photos.edge import EdgeOffline
from jarvis.photos.picker import PhotosNotGranted, PickerError
from jarvis.photos.service import NoSession, PhotosService
from jarvis.tools.base import Tool
from jarvis.tools.context import require_tool_context
from jarvis.tools.external import wrap_external

GITHUB_SOURCE = "your GitHub account"
PHOTOS_SOURCE = "your Faces list"
TEXT_LIMIT = 200
EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}
LIMIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "limit": {"type": "integer", "description": f"How many to list (1-{MAX_ITEMS})."}
    },
}
GITHUB_HOW = (
    "GitHub is not connected yet. Open the Connectors panel and paste a GitHub token there "
    "(JARVIS never takes it in chat)."
)
YOUTUBE_HOW = (
    "Open Integrations and press Grant next to 'YouTube' (sign in with Google first if asked)."
)
IMPORT_NOTE = (
    "Faces JARVIS didn't recognise stay unnamed. To add someone, use the Faces panel: they (or "
    "a parent for a child) must agree first."
)
PICK_NOTE = "Open the link, choose the photos, then ask me to import them again."
_PROBLEMS = (
    GithubError,
    GoogleAPIError,
    GoogleNotConnected,
    YouTubeNotGranted,
    PhotosNotGranted,
    PickerError,
    NoSession,
)


@dataclass(frozen=True)
class ConnectorDeps:
    github: GithubClient | None
    youtube: YouTubeOwn | None
    photos: PhotosService | None


def _fence(text: str, source: str = GITHUB_SOURCE) -> str:
    return wrap_external(text, source=source, limit=TEXT_LIMIT)


def _limit_check(args: dict[str, Any]) -> None:
    value = args.get("limit", DEFAULT_ITEMS)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("limit must be a whole number")


def _guarded(
    fn: Callable[[dict[str, Any]], Awaitable[Any]],
) -> Callable[[dict[str, Any]], Awaitable[Any]]:
    """Known trouble becomes a plain `unavailable` answer, never a stack trace or vendor text."""

    async def run(args: dict[str, Any]) -> Any:
        try:
            return await fn(args)
        except _PROBLEMS as exc:
            return {"status": "unavailable", "message": str(exc)}

    return run


def _uid() -> str:
    return require_tool_context().user_id


def _github_tools(gh: GithubClient) -> list[Tool]:
    async def connect(_a: dict[str, Any]) -> Any:
        st = await gh.status(_uid())
        if not st["connected"]:
            return {"connected": False, "message": GITHUB_HOW}
        return {
            "connected": True,
            "login": _fence(str(st["login"])),
            "message": "GitHub is connected.",
        }

    async def profile(_a: dict[str, Any]) -> Any:
        p = await gh.profile(_uid())
        return {
            "login": _fence(p.login),
            "name": _fence(p.name),
            "public_repos": p.public_repos,
            "followers": p.followers,
            "url": p.url,
        }

    async def repos(a: dict[str, Any]) -> Any:
        found = await gh.repos(_uid(), a.get("limit", DEFAULT_ITEMS))
        return {
            "count": len(found),
            "repos": [
                {
                    "name": _fence(r.name),
                    "description": _fence(r.description),
                    "private": r.private,
                    "language": r.language,
                    "stars": r.stars,
                    "pushed_at": r.pushed_at,
                    "url": r.url,
                }
                for r in found
            ],
        }

    async def activity(a: dict[str, Any]) -> Any:
        found = await gh.activity(_uid(), a.get("limit", DEFAULT_ITEMS))
        return {
            "count": len(found),
            "events": [{"kind": e.kind, "repo": _fence(e.repo), "at": e.at} for e in found],
        }

    def read(name: str, text: str, fn: Any, words: str, schema: dict[str, Any]) -> Tool:
        return Tool(
            name,
            text,
            schema,
            ActionRisk.READ_ONLY,
            _guarded(fn),
            agent="connectors",
            check=_limit_check if schema is LIMIT_SCHEMA else None,
            activity_words=words,
        )

    return [
        read(
            "connect_github",
            "Say whether your own GitHub is connected and how to connect it. "
            "It never takes a token.",
            connect,
            "Checked your GitHub connection",
            EMPTY_SCHEMA,
        ),
        read(
            "github_profile",
            "Your own GitHub profile (read only).",
            profile,
            "Read your GitHub profile",
            EMPTY_SCHEMA,
        ),
        read(
            "github_repos",
            "Your most recently pushed GitHub repositories (read only).",
            repos,
            "Listed your GitHub repositories",
            LIMIT_SCHEMA,
        ),
        read(
            "github_activity",
            "Your recent GitHub activity (read only).",
            activity,
            "Read your recent GitHub activity",
            LIMIT_SCHEMA,
        ),
    ]


def _youtube_tool(yt: YouTubeOwn) -> Tool:
    async def connect(_a: dict[str, Any]) -> Any:
        st = await yt.status(_uid())
        if st["connected"]:
            return {"connected": True, "message": "Your YouTube account is connected."}
        return {"connected": False, "message": YOUTUBE_HOW}

    return Tool(
        "connect_youtube",
        "Say whether your own YouTube account is connected and how to grant it.",
        EMPTY_SCHEMA,
        ActionRisk.READ_ONLY,
        _guarded(connect),
        agent="connectors",
        activity_words="Checked your YouTube connection",
    )


def _person(name: str, child: bool) -> str:
    return FAMILY_CHILD if child else wrap_external(name, source=PHOTOS_SOURCE, limit=NAME_MAX)


def _photos_tool(svc: PhotosService) -> Tool:
    async def run(_a: dict[str, Any]) -> Any:
        uid = _uid()
        res = await svc.collect(uid)
        if res.status == "no_session":
            s = await svc.begin(uid)
            return {"status": "pick_photos", "picker_uri": s.picker_uri, "note": PICK_NOTE}
        if res.status in ("waiting", "laptop_offline"):
            return {"status": res.status, "message": _WAIT[res.status]}
        return {
            "status": "done",
            "photos": res.photos,
            "skipped": res.skipped,
            "faces_found": res.faces_found,
            "recognised": [{"name": _person(p.name, p.child)} for p in res.recognised],
            "unknown_faces": len(res.unknown_clusters),
            "note": IMPORT_NOTE,
        }

    return Tool(
        "photos_import",
        "Pick-only Google Photos import: the first call opens Google's picker, "
        "the next sends the photos you chose to your home laptop to find faces. Never reads the "
        "whole library.",
        EMPTY_SCHEMA,
        ActionRisk.REVERSIBLE,
        _guarded(_edge_safe(run)),
        agent="connectors",
        activity_words="Looked at the photos you picked",
    )


_WAIT = {
    "waiting": "Still waiting for you to choose photos in Google Photos.",
    "laptop_offline": "Your home laptop isn't reachable; try again when it's on.",
}


def _edge_safe(
    fn: Callable[[dict[str, Any]], Awaitable[Any]],
) -> Callable[[dict[str, Any]], Awaitable[Any]]:
    async def run(args: dict[str, Any]) -> Any:
        try:
            return await fn(args)
        except EdgeOffline as exc:
            return {"status": "laptop_offline", "message": str(exc)}

    return run


def tools(deps: ConnectorDeps) -> list[Tool]:
    out: list[Tool] = []
    if deps.github is not None:
        out.extend(_github_tools(deps.github))
    if deps.youtube is not None:
        out.append(_youtube_tool(deps.youtube))
    if deps.photos is not None:
        out.append(_photos_tool(deps.photos))
    return out


__all__ = ["ConnectorDeps", "tools"]

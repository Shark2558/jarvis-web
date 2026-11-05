# src/jarvis/people/sources.py
"""Which URLs may be offered as a person's profile (R4 D10/D11). A search hit is other people's
words, so a URL is accepted only when it is https, has no credentials, sits on a known profile
host (exact host or a subdomain of it, never a look-alike) and has that platform's profile shape.
The URL is rebuilt in canonical form (no query, no fragment), so the client opens exactly it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

_HANDLE = re.compile(r"^[A-Za-z0-9._-]{1,60}$")
_YT_HANDLE = re.compile(r"^@[A-Za-z0-9._-]{1,60}$")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_WIKI_TITLE = re.compile(r"^[^\s/:?#<>\\]{1,120}$")
_GITHUB_RESERVED = frozenset(
    {"orgs", "topics", "search", "settings", "login", "about", "pricing", "features", "sponsors",
     "marketplace", "explore", "notifications", "pulls", "issues", "enterprise", "collections"}
)  # fmt: skip
_X_RESERVED = frozenset({"i", "home", "search", "explore", "intent", "share", "hashtag", "login"})
_SOCIAL_RESERVED = frozenset(
    {"p", "reel", "reels", "explore", "stories", "accounts", "login", "sharer", "share", "groups",
     "watch", "marketplace", "events", "pages", "public"}
)  # fmt: skip


@dataclass(frozen=True)
class ProfileLink:
    platform: str
    url: str


def _host_is(host: str, base: str) -> bool:
    return host == base or host.endswith("." + base)


def _segments(path: str) -> list[str]:
    return [p for p in path.split("/") if p]


def _linkedin(seg: list[str]) -> str | None:
    if len(seg) >= 2 and seg[0] == "in" and _ID.match(seg[1]):
        return f"https://www.linkedin.com/in/{seg[1]}"
    return None


def _github(seg: list[str]) -> str | None:
    if len(seg) == 1 and _HANDLE.match(seg[0]) and seg[0].lower() not in _GITHUB_RESERVED:
        return f"https://github.com/{seg[0]}"
    return None


def _youtube(seg: list[str]) -> str | None:
    if len(seg) == 1 and _YT_HANDLE.match(seg[0]):
        return f"https://www.youtube.com/{seg[0]}"
    if len(seg) == 2 and seg[0] in ("channel", "c", "user") and _ID.match(seg[1]):
        return f"https://www.youtube.com/{seg[0]}/{seg[1]}"
    return None


def _x(seg: list[str]) -> str | None:
    if len(seg) == 1 and _HANDLE.match(seg[0]) and seg[0].lower() not in _X_RESERVED:
        return f"https://x.com/{seg[0]}"
    return None


def _wikipedia(host: str, seg: list[str]) -> str | None:
    if len(seg) == 2 and seg[0] == "wiki" and ":" not in seg[1] and _WIKI_TITLE.match(seg[1]):
        return f"https://{host}/wiki/{seg[1]}"
    return None


def _social(base: str, seg: list[str]) -> str | None:
    if len(seg) == 1 and _HANDLE.match(seg[0]) and seg[0].lower() not in _SOCIAL_RESERVED:
        return f"https://www.{base}/{seg[0]}"
    return None


def classify_profile(url: str) -> ProfileLink | None:
    """The canonical profile link for `url`, or None when it is not a public profile page."""
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    if parts.scheme != "https" or "@" in parts.netloc or not host:
        return None
    seg = _segments(parts.path)
    if _host_is(host, "linkedin.com"):
        found, platform = _linkedin(seg), "linkedin"
    elif host == "github.com" or host == "www.github.com":
        found, platform = _github(seg), "github"
    elif _host_is(host, "youtube.com"):
        found, platform = _youtube(seg), "youtube"
    elif host in ("x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"):
        found, platform = _x(seg), "x"
    elif host.endswith(".wikipedia.org") and host.count(".") == 2:
        found, platform = _wikipedia(host, seg), "wikipedia"
    elif _host_is(host, "instagram.com"):
        found, platform = _social("instagram.com", seg), "instagram"
    elif _host_is(host, "facebook.com"):
        found, platform = _social("facebook.com", seg), "facebook"
    else:
        return None
    return ProfileLink(platform, found) if found else None


__all__ = ["ProfileLink", "classify_profile"]

# src/jarvis/integrations/github.py
"""The owner's own GitHub, read-only (R4 D9; Layer 6).

The token (an OAuth-app token or a PAT the owner pastes in the Connectors panel, never in chat)
is stored sealed under the keyring purpose `connectors` on the Docs port: no Secret Manager
secret, never in a Firestore field in clear, never logged, never returned. Only `api.github.com`
is called, over https, with GET only, redirects off, a deadline and a size cap. Errors are our
own plain words (GitHub's text and the token never appear in them). Whatever GitHub holds about
a repo (names, descriptions) is other people's words: fields are one clean line each and the
tools fence them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import SecretStr

from jarvis.integrations.vault import VaultError
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, Set
from jarvis.tools.card import one_line
from jarvis.undo.store import owner_ok

log = get_logger(__name__)

API = "https://api.github.com"
HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
MAX_RESPONSE_BYTES = 1_000_000
MAX_TOKEN_CHARS = 255
MAX_ITEMS = 30
DEFAULT_ITEMS = 10
FIELD_LIMIT = 200
HTTP_OK = 200
STATUS_FORBIDDEN = 403
STATUS_UNAUTHORIZED = 401
STATUS_TOO_MANY = 429
STATUS_SERVER_ERROR = 500
_TOKEN = re.compile(r"[A-Za-z0-9_\-]{1,255}")
_LOGIN = re.compile(r"[A-Za-z0-9-]{1,39}")
_OWN_URL = re.compile(r"https://github\.com/[A-Za-z0-9._/-]{1,200}")

NOT_CONNECTED = "GitHub is not connected yet: add your token in the Connectors panel."
BAD_TOKEN = "That doesn't look like a GitHub token."
REFUSED = "GitHub refused the token: make a new one and connect again."
LIMIT = "GitHub's rate limit is reached; try again later."
NO_ACCESS = "GitHub says that token lacks access to this; make a new one with read access."
RECONNECT = (
    "JARVIS can't read the saved GitHub token any more: reconnect GitHub with a new token "
    "in the Connectors panel."
)
DOWN = "GitHub is unavailable right now; try again shortly."
UNREACHABLE = "Could not reach GitHub; try again shortly."
UNREADABLE = "GitHub returned an unreadable response."
UNSAVED = "JARVIS couldn't save that just now. Try again in a minute."


class GithubError(RuntimeError):
    """A GitHub call failed (plain words, no vendor text, never the token)."""


class GithubNeedsReconnect(GithubError):
    """The saved token can't be read (wrong key, tampered or malformed record)."""

    def __init__(self) -> None:
        super().__init__(RECONNECT)


def token_ok(value: str) -> bool:
    return bool(_TOKEN.fullmatch(value)) and len(value) <= MAX_TOKEN_CHARS


@dataclass(frozen=True)
class Profile:
    login: str
    name: str
    public_repos: int
    followers: int
    url: str


@dataclass(frozen=True)
class Repo:
    name: str
    private: bool
    description: str
    language: str
    stars: int
    pushed_at: str
    url: str


@dataclass(frozen=True)
class Activity:
    kind: str
    repo: str
    at: str


class GithubStore:
    """`{prefix}connectors_github/{uid}` = {v, kid, blob}; blob = AES-GCM({token, login})."""

    def __init__(self, docs: Docs, keyring: Keyring, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._ring = keyring
        self._col = f"{prefix}connectors_github"

    def _path(self, uid: str) -> str:
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        return f"{self._col}/{uid}"

    @staticmethod
    def _aad(uid: str) -> str:
        return f"github/{uid}/v1"

    async def save(self, uid: str, token: SecretStr, login: str) -> None:
        try:
            plain = json.dumps({"token": token.get_secret_value(), "login": login})
            blob = self._ring.cipher("connectors").encrypt(plain.encode(), aad=self._aad(uid))
            await self._d.write(
                [Set(self._path(uid), {"v": 1, "kid": self._ring.kid, "blob": blob})]
            )
        except Exception as exc:  # noqa: BLE001 - never leak the cause (it may hold the token)
            log.warning("github save failed", extra={"reason": type(exc).__name__})
            raise GithubError(UNSAVED) from None

    async def load(self, uid: str) -> tuple[SecretStr, str] | None:
        """(token, login), None when nothing is saved; `GithubNeedsReconnect` when a record
        exists but can't be read, so the owner is told to reconnect rather than "not connected"."""
        doc = await self._d.get(self._path(uid))
        if doc is None:
            return None
        try:
            blob = doc["blob"]
            if not isinstance(blob, str):
                raise TypeError("blob is not a string")
            raw = json.loads(self._ring.cipher("connectors").decrypt(blob, aad=self._aad(uid)))
            token, login = str(raw["token"]), str(raw["login"])
            if not token_ok(token) or not _LOGIN.fullmatch(login):
                raise ValueError("stored values have a bad shape")
            return SecretStr(token), login
        except (VaultError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            log.warning("github record unreadable", extra={"reason": type(exc).__name__})
            raise GithubNeedsReconnect from None

    async def delete(self, uid: str) -> None:
        await self._d.write([Delete(self._path(uid))])


def _text(value: Any, limit: int = FIELD_LIMIT) -> str:
    return one_line(value, limit) if isinstance(value, str) else ""


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _own_url(value: Any) -> str:
    return value if isinstance(value, str) and _OWN_URL.fullmatch(value) else ""


def _status_error(status: int, headers: httpx.Headers) -> GithubError:
    if status == STATUS_UNAUTHORIZED:
        return GithubError(REFUSED)
    if status == STATUS_TOO_MANY:
        return GithubError(LIMIT)
    if status == STATUS_FORBIDDEN:  # 403 is a limit only when the allowance is spent
        return GithubError(LIMIT if headers.get("x-ratelimit-remaining") == "0" else NO_ACCESS)
    if status >= STATUS_SERVER_ERROR:
        return GithubError(DOWN)
    return GithubError(f"GitHub returned an unexpected status ({status}).")


class GithubClient:
    def __init__(self, store: GithubStore, *, http: httpx.AsyncClient | None = None) -> None:
        self._store = store
        self._http = http or httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=False)

    def __repr__(self) -> str:
        return "GithubClient(<hidden>)"

    async def aclose(self) -> None:
        """Close the HTTP client (call from the app's lifespan shutdown)."""
        await self._http.aclose()

    async def status(self, uid: str) -> dict[str, Any]:
        try:
            found = await self._store.load(uid)
        except GithubNeedsReconnect:
            return {"connected": False, "login": None, "needs_reconnect": True}
        login = None if found is None else found[1]
        return {"connected": found is not None, "login": login, "needs_reconnect": False}

    async def connect(self, uid: str, token: SecretStr) -> str:
        raw = token.get_secret_value()
        if not token_ok(raw):
            raise GithubError(BAD_TOKEN)
        who = await self._get(raw, "/user", {})
        login = who.get("login") if isinstance(who, dict) else None
        if not isinstance(login, str) or not _LOGIN.fullmatch(login):
            raise GithubError(UNREADABLE)
        await self._store.save(uid, token, login)
        log.info("github connected")
        return login

    async def disconnect(self, uid: str) -> None:
        await self._store.delete(uid)

    async def _token(self, uid: str) -> tuple[str, str]:
        found = await self._store.load(uid)
        if found is None:
            raise GithubError(NOT_CONNECTED)
        return found[0].get_secret_value(), found[1]

    async def profile(self, uid: str) -> Profile:
        token, _ = await self._token(uid)
        d = await self._get(token, "/user", {})
        if not isinstance(d, dict):
            raise GithubError(UNREADABLE)
        return Profile(
            _text(d.get("login"), 39),
            _text(d.get("name")),
            _count(d.get("public_repos")),
            _count(d.get("followers")),
            _own_url(d.get("html_url")),
        )

    async def repos(self, uid: str, limit: int = DEFAULT_ITEMS) -> tuple[Repo, ...]:
        token, _ = await self._token(uid)
        n = max(1, min(limit, MAX_ITEMS))
        d = await self._get(token, "/user/repos", {"sort": "pushed", "per_page": n})
        rows = [r for r in d if isinstance(r, dict)] if isinstance(d, list) else []
        return tuple(
            Repo(
                _text(r.get("name"), 100),
                r.get("private") is True,
                _text(r.get("description")),
                _text(r.get("language"), 40),
                _count(r.get("stargazers_count")),
                _text(r.get("pushed_at"), 40),
                _own_url(r.get("html_url")),
            )
            for r in rows[:n]
        )

    async def activity(self, uid: str, limit: int = DEFAULT_ITEMS) -> tuple[Activity, ...]:
        token, login = await self._token(uid)
        n = max(1, min(limit, MAX_ITEMS))
        d = await self._get(token, f"/users/{login}/events", {"per_page": n})
        rows = [r for r in d if isinstance(r, dict)] if isinstance(d, list) else []
        out = []
        for r in rows[:n]:
            repo = r.get("repo")
            name = repo.get("name") if isinstance(repo, dict) else ""
            out.append(
                Activity(_text(r.get("type"), 40), _text(name, 100), _text(r.get("created_at"), 40))
            )
        return tuple(out)

    async def _get(self, token: str, path: str, params: dict[str, Any]) -> Any:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            async with self._http.stream(
                "GET",
                f"{API}{path}",
                params=params,
                headers=headers,
                timeout=HTTP_TIMEOUT,
                follow_redirects=False,
            ) as r:
                if r.status_code != HTTP_OK:
                    log.warning(
                        "github error", extra={"status": r.status_code, "path": path.split("/")[1]}
                    )
                    raise _status_error(r.status_code, r.headers)
                body = await _capped(r)
        except httpx.HTTPError as exc:
            log.warning("github unreachable", extra={"reason": type(exc).__name__})
            raise GithubError(UNREACHABLE) from None
        try:
            return json.loads(body)
        except ValueError:
            raise GithubError(UNREADABLE) from None


async def _capped(r: httpx.Response) -> bytes:
    """The body, refused by its declared length first and aborted at the cap while streaming."""
    declared = r.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_RESPONSE_BYTES:
        raise GithubError(UNREADABLE)
    buf = bytearray()
    async for chunk in r.aiter_bytes():
        buf += chunk
        if len(buf) > MAX_RESPONSE_BYTES:
            raise GithubError(UNREADABLE)
    return bytes(buf)


__all__ = [
    "Activity",
    "GithubClient",
    "GithubError",
    "GithubNeedsReconnect",
    "GithubStore",
    "Profile",
    "Repo",
    "token_ok",
]

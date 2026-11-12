# src/jarvis/integrations/github.py
"""The owner's own GitHub, read-only (R4 D9; Layer 6).

The token (an OAuth-app token or a PAT the owner pastes in the Connectors panel, never in chat)
is stored sealed under the keyring purpose `connectors` on the Docs port: no Secret Manager
secret, never in a Firestore field in clear, never logged, never returned. Only `api.github.com`
is called, over https, with GET only, redirects off, a deadline and a size cap. Errors are our
own plain words (GitHub's text and the token never appear in them). Whatever GitHub holds about
a repo (names, descriptions) is other people's words: fields are one clean line each and the
tools fence them.

R11.1 D19: a connected token whose facts were never stored (connected before R5.1, or the record
could not be saved) is asked about by `learn_token_facts`: one `GET /rate_limit`, at most every
`FACTS_EVERY_S` per owner. The mark that counts the period is written to the stored record in a
transaction BEFORE the read, so neither a restart nor a second instance reads again. A mark ahead
of the clock (it was set back) still counts, up to `FACTS_AHEAD_S` ahead. The claim and the start
of the read are shielded from the caller's own deadline (a mark is never left with no read), and
a read that is cancelled (a shutdown) takes its mark back, so the period is not lost.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from pydantic import SecretStr

from jarvis.integrations.github_meta import MetaBook, TokenMeta
from jarvis.integrations.vault import VaultError
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, DocTx, Set
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
FACTS_EVERY_S = 6 * 3600.0  # R11.1 D19: a token with no stored facts is read at most this often
FACTS_AHEAD_S = 6 * 3600.0  # a mark ahead of the clock (set back) still counts, this far at most
# how long a caller waits for that read before it is told "checking": well inside the Vitals
# source's own deadline (vitals.own.SOURCE_TIMEOUT_S, 3 s), which also covers the claim before it
FACTS_WAIT_S = 1.0
FACTS_PATH = "/rate_limit"  # GitHub does not count this call against the hourly limit
FACTS_MARK = "facts_checked_at"  # the stored record's clear field: when the period's read began
# what `learn_token_facts` answers: the facts are there now / a read is in flight / a read was
# made this period and learned nothing (nothing more is tried until the period ends)
FactsState = Literal["known", "checking", "waiting"]
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


def facts_recent(now: float, mark: float, every_s: float) -> bool:
    """Is `mark` (when a read of missing facts began) inside the period? A mark ahead of the
    clock (the clock was set back) counts too, up to `FACTS_AHEAD_S` ahead."""
    return 0 <= now - mark < every_s or 0 < mark - now <= FACTS_AHEAD_S


@dataclass(frozen=True)
class FactsClaim:
    """The answer to "may this caller read the token's facts from GitHub now?" (R11.1 D19).
    `state`: "take" (yes: the period's one read is now this caller's), "recent" (a read was
    claimed at `since`, inside the period), "known" (the facts are stored) or "gone" (no record)."""

    state: Literal["take", "recent", "known", "gone"]
    since: float | None = None


class GithubStore:
    """`{prefix}connectors_github/{uid}` = {v, kid, blob, meta, facts_checked_at}; blob =
    AES-GCM({token, login}); `meta` = clear `TokenMeta` fields (expiry and hourly limit from
    GitHub's headers; no secret); `facts_checked_at` = when a read of missing facts last began."""

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

    async def save(
        self, uid: str, token: SecretStr, login: str, meta: TokenMeta | None = None
    ) -> None:
        try:
            plain = json.dumps({"token": token.get_secret_value(), "login": login})
            blob = self._ring.cipher("connectors").encrypt(plain.encode(), aad=self._aad(uid))
            doc: dict[str, Any] = {"v": 1, "kid": self._ring.kid, "blob": blob}
            if meta is not None:
                doc["meta"] = meta.fields()
            await self._d.write([Set(self._path(uid), doc)])
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

    async def meta(self, uid: str) -> TokenMeta | None:
        """The clear `meta` fields, read without opening the sealed token."""
        doc = await self._d.get(self._path(uid))
        return TokenMeta.read(doc.get("meta")) if doc is not None else None

    async def claim_facts_read(self, uid: str, now: float, every_s: float) -> FactsClaim:
        """Take the one read of a token's missing facts for this period (R11.1 D19). The mark is
        written in the same transaction that grants it, so two instances never both read, and a
        restart finds it. A record with readable facts, or none at all, grants nothing."""
        path = self._path(uid)

        async def take(tx: DocTx) -> FactsClaim:
            doc = await tx.get(path)
            if doc is None:
                return FactsClaim("gone")
            if TokenMeta.read(doc.get("meta")) is not None:
                return FactsClaim("known")
            last = doc.get(FACTS_MARK)
            if isinstance(last, int | float) and not isinstance(last, bool):
                if facts_recent(now, float(last), every_s):
                    return FactsClaim("recent", float(last))
            tx.set(path, {**doc, FACTS_MARK: now})
            return FactsClaim("take", now)

        return await self._d.transaction(take)

    async def release_facts_read(self, uid: str, since: float) -> bool:
        """Take back the mark of a read that never finished (it was cancelled), so the period is
        not lost. Only that very mark: a newer one, or another record, is left as it is."""
        path = self._path(uid)

        async def drop(tx: DocTx) -> bool:
            doc = await tx.get(path)
            if doc is None or doc.get(FACTS_MARK) != since:
                return False
            tx.set(path, {k: v for k, v in doc.items() if k != FACTS_MARK})
            return True

        return await self._d.transaction(drop)

    async def note_meta(self, uid: str, meta: TokenMeta) -> bool:
        """Put `meta` on the existing record (in a transaction: a record deleted or replaced
        meanwhile is never brought back). False when there is no record."""
        path = self._path(uid)

        async def put(tx: DocTx) -> bool:
            doc = await tx.get(path)
            if doc is None:
                return False
            tx.set(path, {**doc, "meta": meta.fields()})
            return True

        return await self._d.transaction(put)


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


Seen = Callable[[int, httpx.Headers], None]


class GithubClient:
    def __init__(
        self,
        store: GithubStore,
        *,
        http: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._http = http or httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=False)
        self._clock = clock
        self._book = MetaBook()  # R5.1: the token's facts from GitHub's headers, per owner
        # R11.1 D19: a read of missing facts in flight, and when this period's read was claimed
        self._facts: dict[str, asyncio.Task[None]] = {}
        self._facts_since: dict[str, float] = {}
        self._facts_lock = asyncio.Lock()

    def __repr__(self) -> str:
        return "GithubClient(<hidden>)"

    async def aclose(self) -> None:
        """Close the HTTP client (call from the app's lifespan shutdown)."""
        for task in self._facts.values():
            task.cancel()
        await self.settled()
        await self._http.aclose()

    async def settled(self) -> None:
        """Wait until no read of missing facts is in flight (shutdown, tests)."""
        running = [t for t in self._facts.values() if not t.done()]
        if running:
            await asyncio.gather(*running, return_exceptions=True)

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
        probe = MetaBook()  # this token's facts, kept only if the connect succeeds
        who = await self._get(raw, "/user", {}, seen=self._seen(probe, uid))
        login = who.get("login") if isinstance(who, dict) else None
        if not isinstance(login, str) or not _LOGIN.fullmatch(login):
            raise GithubError(UNREADABLE)
        await self._store.save(uid, token, login, probe.get(uid))
        self._book.saved(uid, probe.get(uid))
        self._facts_since.pop(uid, None)  # a new record: its own six hours
        log.info("github connected")
        return login

    async def disconnect(self, uid: str) -> None:
        await self._store.delete(uid)
        self._book.forget(uid)
        self._facts_since.pop(uid, None)

    async def token_meta(self, uid: str) -> TokenMeta | None:
        """R5.1 (Vitals): what GitHub's headers last said about the token: this process's latest
        or the stored copy, whichever is newer. None when nothing is known (or not connected)."""
        stored, mine = await self._store.meta(uid), self._book.get(uid)
        if mine is None or (stored is not None and stored.seen_at > mine.seen_at):
            return stored
        return mine

    async def learn_token_facts(self, uid: str) -> FactsState:
        """R11.1 D19 (Vitals): for a connected token whose facts are missing, read them from
        GitHub: ONE `GET /rate_limit`, at most every `FACTS_EVERY_S` per owner (counted in the
        stored record, so also across restarts and instances). Waits up to `FACTS_WAIT_S` for the
        answer; a slower GitHub is "checking" and the read goes on by itself. Never raises: a
        store that can't take the mark means no read (a read JARVIS can't count is not made)."""
        if self._book.get(uid) is not None:
            return "known"
        async with self._facts_lock:  # one starter at a time: a second caller joins the read
            task = self._facts.get(uid)
            started: asyncio.Task[None] | FactsState = (
                task
                if task is not None and not task.done()
                # shielded: a caller whose deadline fires mid-claim still leaves the read started
                else await asyncio.shield(self._begin_facts_read(uid))
            )
        if not isinstance(started, asyncio.Task):
            return started
        try:
            await asyncio.wait_for(asyncio.shield(started), FACTS_WAIT_S)
        except TimeoutError:
            return "checking"
        return "known" if self._book.get(uid) is not None else "waiting"

    async def _begin_facts_read(self, uid: str) -> asyncio.Task[None] | FactsState:
        """The period's read, started; or why there is none: the facts are stored ("known"), or
        this period's read was already made ("waiting")."""
        if self._book.get(uid) is not None:
            return "known"  # a read that finished while this caller waited for the lock
        now = self._clock()
        since = self._facts_since.get(uid)
        if since is not None and facts_recent(now, since, FACTS_EVERY_S):
            return "waiting"  # this process already knows of a read in this period
        try:
            found = await self._store.load(uid)
            if found is None:
                return "waiting"
            claim = await self._store.claim_facts_read(uid, now, FACTS_EVERY_S)
        except Exception as exc:  # noqa: BLE001 - never the cause: it may hold the token
            log.warning("github facts read not started", extra={"reason": type(exc).__name__})
            return "waiting"
        if claim.since is not None:
            self._facts_since[uid] = claim.since
        if claim.state == "known":
            return "known"
        if claim.state != "take":
            return "waiting"
        task = asyncio.create_task(self._read_facts(uid, found[0].get_secret_value(), now))
        self._facts[uid] = task
        return task

    async def _read_facts(self, uid: str, token: str, since: float) -> None:
        """The one `GET /rate_limit`. Its headers go through the same book as every other answer
        (`_call`) and are stored at once; a 401 is a fact too ("refused"). Nothing is raised but a
        cancel, after the read's mark has been taken back."""
        try:
            await self._call(uid, token, FACTS_PATH, {})
        except GithubError:
            pass  # `_get` logged the status; the row says the facts could not be read
        except asyncio.CancelledError:
            await self._give_back(uid, since)
            raise
        except Exception as exc:  # noqa: BLE001 - a background read never raises
            log.warning("github facts read failed", extra={"reason": type(exc).__name__})

    async def _give_back(self, uid: str, since: float) -> None:
        """A cancelled read never counted: its mark goes, here and in the stored record."""
        if self._facts_since.get(uid) == since:
            self._facts_since.pop(uid, None)
        try:
            await self._store.release_facts_read(uid, since)
        except Exception as exc:  # noqa: BLE001 - the mark then simply runs out after the period
            log.warning("github facts mark kept", extra={"reason": type(exc).__name__})

    def _seen(self, book: MetaBook, uid: str) -> Seen:
        gen = book.generation(uid)  # a reconnect / disconnect meanwhile drops this read's facts
        return lambda status, headers: book.observe(uid, status, headers, self._clock(), gen)

    async def _call(self, uid: str, token: str, path: str, params: dict[str, Any]) -> Any:
        """A read for the owner; afterwards the token's facts are stored when due (a failure is
        logged by class name only and never raised: the read itself already answered)."""
        seen = self._seen(self._book, uid)
        gen = self._book.generation(uid)
        try:
            return await self._get(token, path, params, seen=seen)
        finally:
            await self._store_meta(uid, gen)

    async def _store_meta(self, uid: str, gen: int) -> None:
        now = self._clock()
        meta = self._book.due(uid, now)
        if meta is None or gen != self._book.generation(uid):
            return  # nothing due, or the token changed while the read was in flight
        try:
            if await self._store.note_meta(uid, meta):
                self._book.stored(uid, meta)
                return
        except Exception as exc:  # noqa: BLE001 - never leak the cause
            log.warning("github meta not saved", extra={"reason": type(exc).__name__})
        self._book.failed(uid, now)  # no record or a failed write: wait before trying again

    async def _token(self, uid: str) -> tuple[str, str]:
        found = await self._store.load(uid)
        if found is None:
            raise GithubError(NOT_CONNECTED)
        return found[0].get_secret_value(), found[1]

    async def profile(self, uid: str) -> Profile:
        token, _ = await self._token(uid)
        d = await self._call(uid, token, "/user", {})
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
        d = await self._call(uid, token, "/user/repos", {"sort": "pushed", "per_page": n})
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
        d = await self._call(uid, token, f"/users/{login}/events", {"per_page": n})
        rows = [r for r in d if isinstance(r, dict)] if isinstance(d, list) else []
        out = []
        for r in rows[:n]:
            repo = r.get("repo")
            name = repo.get("name") if isinstance(repo, dict) else ""
            out.append(
                Activity(_text(r.get("type"), 40), _text(name, 100), _text(r.get("created_at"), 40))
            )
        return tuple(out)

    async def _get(
        self, token: str, path: str, params: dict[str, Any], *, seen: Seen | None = None
    ) -> Any:
        """GET `path`; `seen` gets every answer's status and headers (R5.1: token facts)."""
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
                if seen is not None:
                    seen(r.status_code, r.headers)
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
    "FACTS_AHEAD_S",
    "FACTS_EVERY_S",
    "FACTS_MARK",
    "FACTS_WAIT_S",
    "Activity",
    "FactsClaim",
    "FactsState",
    "GithubClient",
    "GithubError",
    "GithubNeedsReconnect",
    "GithubStore",
    "Profile",
    "Repo",
    "facts_recent",
    "token_ok",
]

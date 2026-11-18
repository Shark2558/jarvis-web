# evals/r13_1/wired.py
"""R13.1 I1: Try-on through the REAL app, for the `e2e` and `needles` suites (not a suite itself:
the runner loads only the names in `run.PARTS`).

`running()` builds `create_app` as R13's I1 did (`evals/r13/wired.py`: the owner's token and a
token key, so every wardrobe part is on; a FIXED clock, `app.state.wardrobe_now`; a recording
notifier and log handler) with See it on me's pictures on and Google's cache proved off, as the
deploy sets them. C's REAL Gemini adapter answers from `r131_fake_gemini.FakeGoogle` (recorded
answers through `httpx.MockTransport`, with a text part that must be read nowhere): nothing
reaches Google and nothing is charged. `World.console` stands for his signed-in console (the
`session_email` the console-only routes check); it is off unless a case turns it on, so a script
holding the token is refused there as in production.

Everything is in memory: no Firestore, no Google, no network.
"""

from __future__ import annotations

import base64
import importlib.util
import logging
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import mock

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
for _p in (ROOT / "src", ROOT / "tests"):  # appended: never ahead of what is already imported
    if str(_p) not in sys.path:
        sys.path.append(str(_p))


def _r13_wired() -> ModuleType:
    """R13's `wired.py` by path under its own unique name (shared with R13's suites)."""
    found = sys.modules.get("r13_wired")
    if found is not None:
        return found
    spec = importlib.util.spec_from_file_location("r13_wired", ROOT / "evals" / "r13" / "wired.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["r13_wired"] = module
    spec.loader.exec_module(module)
    return module


_W13 = _r13_wired()
from httpx import ASGITransport, AsyncClient  # noqa: E402
from r13_fakes import FixedClock, ist  # noqa: E402
from r131_fake_gemini import (  # noqa: E402
    INSTRUCTION,
    PNG_OUT,
    FakeGoogle,
    FakeTokens,
    picture_answer,
    project_of,
)

from jarvis.api import create_app  # noqa: E402
from jarvis.api.identity import primary_user_id  # noqa: E402
from jarvis.config import Settings  # noqa: E402
from jarvis.llm.mock_provider import MockProvider  # noqa: E402
from jarvis.memory.inmemory import InMemorySessionStore  # noqa: E402

AUTH, Alerts, Recorder, want = _W13.AUTH, _W13.Alerts, _W13.Recorder, _W13.want
OWNER_EMAIL = "owner@example.com"
ANSWER = picture_answer(PNG_OUT, text=INSTRUCTION)  # an image and a text part never to be read


def settings() -> Settings:
    """R13's owner settings with pictures on and the cache proved off (the deploy's PATCH)."""
    s: Settings = _W13.owner_settings()
    return s.model_copy(update={"tryon_pictures": True, "tryon_cache": False})


@dataclass
class World(_W13.World):  # type: ignore[misc,name-defined]
    """R13's world (tools through the real gateway, routes through the real HTTP stack) and:
    `google` (every request the adapter sent), `brain` (the mock provider, for scripted turns),
    `console` (whether a request comes from his signed-in console)."""

    google: Any = None
    brain: Any = None
    console: list[bool] = field(default_factory=lambda: [False])

    @contextmanager
    def signed_in(self) -> Iterator[None]:
        self.console[0] = True
        try:
            yield
        finally:
            self.console[0] = False

    async def add(self, *pieces: dict[str, Any]) -> list[str]:
        return list((await self.ok("wardrobe_add", pieces=list(pieces)))["ids"])

    async def crop(self, pid: str, view: str, data: bytes) -> Any:
        head = {"Content-Type": "image/jpeg"}
        return await self.send("POST", f"/v1/wardrobe/photos?piece={pid}&view={view}",
                               content=data, headers=head)  # fmt: skip

    async def chat(self, words: str, *, channel: str = "text") -> dict[str, Any]:
        got = await self.send("POST", "/v1/chat", json={"message": words, "channel": channel})
        assert got.status_code == 200, (got.status_code, got.text[:300])
        return dict(got.json())


PILOT: dict[str, dict[str, Any]] = {  # a made-up pilot set for a business-formal meeting
    "shirt": {"type": "shirt", "label": "White formal shirt", "colour": "white"},
    "trousers": {"type": "trousers", "label": "Grey trousers", "colour": "grey"},
    "black_l": {"type": "dress_shoe", "colour": "black"},
    "black_r": {"type": "dress_shoe", "colour": "black"},
    "brown_l": {"type": "dress_shoe", "colour": "brown"},
    "brown_r": {"type": "dress_shoe", "colour": "brown"},
    "belt": {"type": "belt", "label": "Brown belt", "colour": "brown"},
    "sock_l": {"type": "sock", "colour": "black"},
    "sock_r": {"type": "sock", "colour": "black"},
    "blazer": {"type": "blazer", "label": "Navy blazer", "colour": "navy"},
    "watch": {"type": "watch", "colour": "grey"},
    "vest": {"type": "vest", "colour": "white"},  # private below: always "Base layer (covered)"
    "briefs": {"type": "briefs", "colour": "black"},  # private below
}
PAIRS = (("black_l", "black_r"), ("brown_l", "brown_r"), ("sock_l", "sock_r"))
FORMAL = ("shirt", "black_l", "black_r", "brown_l", "brown_r")
PRIVATE = ("vest", "briefs")


async def seed(w: World, **labels: str) -> dict[str, str]:
    """The pilot set through the real tools (`labels` overrides a piece's label): the shoes and
    socks paired, the shirt and shoes formal, the vest and briefs private. Its ids by name."""
    names = list(PILOT)
    sent = [{**PILOT[n], **({"label": labels[n]} if n in labels else {})} for n in names]
    ids = dict(zip(names, await w.add(*sent), strict=True))
    for a, b in PAIRS:
        await w.ok("wardrobe_edit", piece=ids[a], pair_with=ids[b])
    for n in FORMAL:
        await w.ok("wardrobe_edit", piece=ids[n], formality=5)
    for n in PRIVATE:
        await w.ok("wardrobe_edit", piece=ids[n], private=True)
    return ids


def _provider(google: FakeGoogle) -> Any:
    def build(s: Settings, *, tokens: Any, project: Any) -> Any:
        from jarvis.llm.tryon_gemini import GeminiTryOn

        return GeminiTryOn(model=s.tryon_model, location=s.tryon_location, tokens=FakeTokens(),
                           project=project_of(), http=google.client())  # fmt: skip

    return build


@asynccontextmanager
async def running(
    at: datetime | None = None, *, answers: list[Any] | None = None, s: Settings | None = None
) -> AsyncIterator[World]:
    """The real app, started, on a fixed clock (default Tue 17 Nov 2026, 09:00 IST)."""
    s = s or settings()
    google = FakeGoogle(answers or [ANSWER])
    brain = MockProvider()
    console = [False]
    log = Recorder()
    with ExitStack() as stack:
        stack.enter_context(mock.patch("jarvis.api.tryon_wiring.build_tryon", _provider(google)))
        stack.enter_context(mock.patch(
            "jarvis.api.seeme.session_email", lambda r, st: OWNER_EMAIL if console[0] else None
        ))  # fmt: skip
        app = create_app(s, provider=brain, store=InMemorySessionStore())
        clock = FixedClock(at or ist(2026, 11, 17, 9, 0))
        app.state.wardrobe_now = clock
        logging.getLogger().addHandler(log)
        stack.callback(logging.getLogger().removeHandler, log)
        async with app.router.lifespan_context(app):
            alerts = Alerts()
            app.state.notify = alerts
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield World(app, client, clock, alerts, log, primary_user_id(s),
                            google=google, brain=brain, console=console)  # fmt: skip


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


__all__ = [
    "ANSWER",
    "AUTH",
    "OWNER_EMAIL",
    "PILOT",
    "PRIVATE",
    "World",
    "b64",
    "running",
    "seed",
    "settings",
    "want",
]

# tests/test_r11_1_d_people.py -- R11.1 Part D, O8 on the server side (plan D16): the tool that
# gives profile links to the owner no longer claims to be opening anything (nothing ever opened by
# itself: each link opens from its own card, or from the list in the reply), and what it returns is
# unchanged. The gate that decides WHO may be researched is not touched by this release: its file
# is byte-for-byte the one R4 shipped (plan D17).
from __future__ import annotations

import hashlib
from pathlib import Path

from research_fakes import FakeModel, FakeSearcher, fixed_mode, hit

from jarvis.core.guardrails import ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.people.research import PeopleService
from jarvis.people.tools import OPEN_PROFILES, RESEARCH_PERSON, PeopleDeps, people_tools
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]
SCOPE = "u_owner:sess_1"
GATE_SHA256 = "b3ff32f47cbdf9827b5e652d6830b17a9642327ec7b93429122855672c945f2d"  # as on r11-i1
# a made-up public figure: a (fake) encyclopedia page names her, so the unchanged gate lets her pass
HITS = [
    hit(
        "Lekha Examplekar - Wikipedia",
        "https://en.wikipedia.org/wiki/Lekha_Examplekar",
        "Lekha Examplekar is the minister for ports",
    ),
    hit(
        "Lekha Examplekar - LinkedIn",
        "https://www.linkedin.com/in/example-person-0001",
        "Lekha Examplekar, minister for ports",
    ),
]


def _gateway() -> Gateway:
    svc = PeopleService(FakeSearcher(HITS), FakeModel(), mode=fixed_mode("ai"))
    registry = ToolRegistry()
    for tool in people_tools(PeopleDeps(svc)):
        registry.register(tool)
    return Gateway(registry=registry, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())


def _call(tool: str, **args: object) -> ToolCall:
    return ToolCall(id="t1", name=tool, arguments=dict(args))


async def test_the_links_are_handed_over_without_claiming_to_open_anything() -> None:
    gw = _gateway()
    await gw.execute(_call(RESEARCH_PERSON, name="Lekha Examplekar"), scope=SCOPE)

    res = await gw.execute(_call(OPEN_PROFILES), scope=SCOPE)

    assert res.outcome is GatewayOutcome.EXECUTED
    assert sorted(res.result["open"]) == [
        "https://en.wikipedia.org/wiki/Lekha_Examplekar",
        "https://www.linkedin.com/in/example-person-0001",
    ]
    message = res.result["message"]
    assert message == "Here are 2 profile links, Sir. Each one opens in its own tab."
    assert "Opening" not in message


async def test_one_link_is_said_as_one_link() -> None:
    gw = _gateway()
    await gw.execute(_call(RESEARCH_PERSON, name="Lekha Examplekar"), scope=SCOPE)

    res = await gw.execute(_call(OPEN_PROFILES, platforms=["wikipedia"]), scope=SCOPE)

    assert res.result["message"] == "Here is 1 profile link, Sir. It opens in its own tab."


def test_the_public_figure_check_is_the_file_r4_shipped() -> None:
    """plan D17: nobody edits `people/gate.py`. Its content is pinned by its SHA-256, so any edit,
    however small, fails here and has to be explained."""
    text = (ROOT / "src" / "jarvis" / "people" / "gate.py").read_text(encoding="utf-8")
    plain = text.replace("\r\n", "\n").encode("utf-8")  # the same on a Windows checkout
    assert hashlib.sha256(plain).hexdigest() == GATE_SHA256

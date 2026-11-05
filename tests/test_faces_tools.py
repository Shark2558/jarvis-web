# tests/test_faces_tools.py -- R3 D13/D19: faces_list through the gateway: registry only, fenced,
# children never named on a spoken or Telegram turn, deleting people not listed, no picture,
# never "who was seen".
from __future__ import annotations

from faces_fakes import UID, Faces, add_adult, add_child, enrol, faces

from jarvis.core.channel import telegram_turn
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.faces.ports import FAMILY_CHILD
from jarvis.faces.tools import faces_tools
from jarvis.llm.base import ToolCall
from jarvis.tools.audit import AuditLog
from jarvis.tools.external import FENCE_END
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry

SCOPE = "u_owner:sess_1"


def build(f: Faces) -> Gateway:
    reg = ToolRegistry()
    for tool in faces_tools(f.svc):
        reg.register(tool)
    return Gateway(registry=reg, policy=Policy([]), gate=ConfirmationGate(), audit=AuditLog())


async def run(gw: Gateway):  # type: ignore[no-untyped-def]
    return await gw.execute(ToolCall(id="c", name="faces_list", arguments={}), scope=SCOPE)


def test_one_read_tool_with_fixed_activity_words() -> None:
    (tool,) = faces_tools(faces().svc)
    assert tool.name == "faces_list" and tool.risk is ActionRisk.READ_ONLY
    assert tool.activity_words == "Listed the people JARVIS recognises"
    assert tool.input_schema["properties"] == {}


async def test_empty_registry_says_how_to_add_people() -> None:
    res = await run(build(faces()))
    assert res.outcome is GatewayOutcome.EXECUTED
    assert res.result["count"] == 0 and "Faces panel" in res.result["note"]


async def test_lists_fenced_names_and_whether_pictures_exist_without_any_sighting() -> None:
    f = faces()
    p = await add_adult(f)
    await add_adult(f, "Ravi")
    await enrol(f, p)
    res = await run(build(f))
    assert res.trusted is True
    people = res.result["people"]
    assert FENCE_END.search(people[0]["name"]) and "Anjali" in people[0]["name"]
    assert [x["recognised_at_home"] for x in people] == [True, False]
    blob = str(res.result).lower()
    for word in ("seen", "arrived", "last", "camera", "picture_path", "embedding"):
        assert word not in blob


async def test_a_child_is_never_named_on_telegram_and_names_are_masked() -> None:
    f = faces()
    await add_child(f, "Mini")
    await add_adult(f, "Ravi 9876543210")
    with telegram_turn():
        res = await run(build(f))
    people = res.result["people"]
    assert people[0]["name"] == FAMILY_CHILD
    assert "9876543210" not in str(res.result) and "Mini" not in str(res.result)


async def test_a_person_being_deleted_is_not_listed() -> None:
    f = faces(online=False)
    p = await add_adult(f)
    await f.svc.remove(UID, p.id)
    res = await run(build(f))
    assert res.result["count"] == 0 and "Anjali" not in str(res.result)


async def test_an_unreadable_registry_is_plain_words() -> None:
    f = faces()
    await add_adult(f)
    f.docs._data["jarvis_faces/" + UID]["blob"] = "x"  # type: ignore[attr-defined]
    res = await run(build(f))
    assert res.result["status"] == "unavailable" and "Anjali" not in str(res.result)

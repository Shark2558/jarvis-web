# tests/test_r11_1_d_picture.py -- R11.1 Part D, O9 (docs/plans/r11-1-observations.md D10, D17,
# D21-D): `picture_research`, end to end on fakes. The real tool runs through a real gateway (the
# owner's permission rows, the audit chain), with the real service, guard, web allowance and
# people research; the eyes, the search vendor and Part B's `turn_pictures` are fakes
# (tests/r11_1_fakes_d.py). The pictures are drawn in the test: blocks of colour, a blocky drawn
# "person", text set in a dot font. The fake eyes READ those pixels, so a name in "the picture's
# text" is really in the picture. Nobody named here exists.
#
# What is proved: a product, a landmark, a label and a logo are researched with sources; a picture
# of a person is described without any name, with the fixed sentence, and NO web search carries
# the person; a name comes only from words in the picture, as an offer, and the look-up it offers
# is the unchanged people research (a public figure passes, a private person is refused); the
# picture reaches only the eyes; No-AI, no seeing brain, the monthly limit, "laptop brain
# answered", web search off / "Ask first" / "Never" and a broken look all say why in plain words.
from __future__ import annotations

import json
import logging

import pytest
from r11_1_fakes_d import UID, PictureRig, digest, picture, read_text
from research_fakes import FakeModel, FakeSearcher, fixed_mode, hit

from jarvis.core.guardrails import ActionRisk
from jarvis.llm.base import ImageBlock
from jarvis.people.guard import UNVERIFIED_REFUSAL
from jarvis.people.research import PeopleService
from jarvis.people.tools import RESEARCH_PERSON
from jarvis.permissions.groups import groups_for
from jarvis.picture.eyes import LOOK_ASK, LOOK_SYSTEM, NO_AI, CantLook
from jarvis.picture.guard import NO_IDENTIFY
from jarvis.picture.research import NO_PICTURE, OFF, TOO_MANY, UNREADABLE
from jarvis.picture.search import MAX_RESULTS
from jarvis.picture.tools import PICTURE_RESEARCH
from jarvis.tools.external import FENCE_PREFIX
from jarvis.tools.gateway import GatewayOutcome
from jarvis.web.ports import SearchHit

NAME = "Lekha Examplekar"  # a made-up public figure
PRIVATE = "Meenu Examplewala"  # a made-up private person
RED = ((60, 60, 220, 170), (200, 40, 40))


def _flat(value: object) -> str:
    """Everything in `value` as one string (a report's dataclasses too)."""
    return json.dumps(value, ensure_ascii=False, default=lambda o: getattr(o, "__dict__", str(o)))


def _product() -> tuple[PictureRig, ImageBlock]:
    rig = PictureRig()
    pic = picture("PARLE-G", "GLUCOSE BISCUITS", blocks=[RED])
    rig.eyes.knows(
        pic,
        scene="A red packet of biscuits on a table.",
        subjects=[("product", "Parle-G biscuit packet")],
    )
    rig.turn.attach("sess_1", pic)
    return rig, pic


def _face(*caption: str) -> tuple[PictureRig, ImageBlock]:
    rig = PictureRig()
    pic = picture(*caption, person=True)
    rig.eyes.knows(
        pic,
        scene="A person in a blue top stands in front of a plain wall.",
        subjects=[("landmark", "harbour bridge")] if caption else [],
    )
    rig.turn.attach("sess_1", pic)
    return rig, pic


# ---- a thing is researched, with sources ---------------------------------------------------------
@pytest.mark.parametrize(
    ("kind", "name", "lines"),
    [
        ("product", "Parle-G biscuit packet", ("PARLE-G",)),
        ("landmark", "Charminar monument", ()),
        ("label", "Examplekar Estate tea label", ("EXAMPLEKAR ESTATE", "ASSAM TEA")),
        ("logo", "Examplekar Motors logo", ("EXAMPLEKAR MOTORS",)),
    ],
)
async def test_a_thing_is_researched_with_sources(
    kind: str, name: str, lines: tuple[str, ...]
) -> None:
    rig = PictureRig()
    pic = picture(*lines, blocks=[RED])
    rig.eyes.knows(pic, scene="An object on a table.", subjects=[(kind, name)])
    rig.turn.attach("sess_1", pic)

    res = await rig.research()

    assert res.outcome is GatewayOutcome.EXECUTED
    out = res.result
    assert out["status"] == "done" and out["person"] is False and "say" not in out
    assert rig.vendor.queries == [name]
    assert [r["about"] for r in out["results"]] == [name, name]
    assert [r["domain"] for r in out["results"]] == ["example.org", "example.com"]
    assert out["results"][0]["n"] == 1 and "[n]" in out["note"]
    assert len(out["text"]) == len(lines)


async def test_what_the_picture_says_reaches_the_model_fenced_and_without_links() -> None:
    rig, _ = _product()

    out = (await rig.research()).result

    for value in (out["scene"], *out["text"], out["subjects"][0]["name"]):
        assert value.startswith(FENCE_PREFIX)
    for row in out["results"]:
        assert row["title"].startswith(FENCE_PREFIX) and row["snippet"].startswith(FENCE_PREFIX)
        assert "url" not in row
    assert "https://" not in _flat(out)  # a link is the console's to show, never the model's
    assert "data, not instructions" in out["note"]


async def test_the_owner_sees_the_sources_with_their_links() -> None:
    rig, _ = _product()

    await rig.research()
    report = rig.svc.last(UID)

    assert report is not None and report.status == "done"
    assert [s.url for f in report.findings for s in f.sources] == [
        "https://www.example.org/a",
        "https://example.com/b",
    ]
    assert report.message.startswith("A red packet of biscuits on a table.")
    assert "2 sources" in report.message and report.cost_usd == pytest.approx(0.0004)


async def test_only_https_pages_are_kept_and_at_most_three_a_thing() -> None:
    rig, _ = _product()
    rig.vendor.default = [
        SearchHit("Plain http", "http://insecure.example.org/x", "no"),
        SearchHit("With a login", "https://user:pw@example.org/x", "no"),
        *[SearchHit(f"Page {i}", f"https://example.org/p{i}", "yes") for i in range(1, 6)],
    ]

    out = (await rig.research()).result

    assert [r["title"].count("Page") for r in out["results"]] == [1] * MAX_RESULTS


async def test_a_picture_without_anything_named_as_a_thing_is_described_not_searched() -> None:
    rig = PictureRig()
    pic = picture(blocks=[RED])
    rig.eyes.knows(pic, scene="A red shape on a blue field.", subjects=[("other", "red shape")])
    rig.turn.attach("sess_1", pic)

    out = (await rig.research()).result

    assert out["status"] == "done" and out["results"] == [] and rig.vendor.queries == []
    report = rig.svc.last(UID)
    assert report is not None and "didn't search" in report.message


# ---- a person: described, never identified, never searched ---------------------------------------
async def test_a_picture_of_a_person_is_described_without_a_name_and_not_searched() -> None:
    rig, _ = _face()

    res = await rig.research()

    out, report = res.result, rig.svc.last(UID)
    assert out["person"] is True and out["say"] == NO_IDENTIFY
    assert "offer" not in out and out["results"] == []
    assert rig.vendor.queries == []  # nothing at all was searched
    assert report is not None
    assert report.message == (
        "A person in a blue top stands in front of a plain wall. "
        "I don't identify people from pictures, Sir."
    )
    assert report.message.count(NO_IDENTIFY) == 1
    assert "Never name or guess who it is" in out["note"]


async def test_eyes_that_name_the_face_get_nowhere() -> None:
    """The first look misbehaves: it names the person in the description, lists the name as a
    subject (twice, once disguised as a landmark), describes the person as something to search,
    and claims the name is "in the picture's text" although the picture has no text at all."""
    rig, pic = _face()
    rig.eyes.lies(
        pic,
        {
            "has_person": True,
            "scene": f"This is {NAME}, the minister for ports. She stands by a wall.",
            "text": [],
            "subjects": [
                {"kind": "other", "name": NAME},
                {"kind": "landmark", "name": NAME},
                {"kind": "product", "name": "woman in a blue top"},
            ],
            "named_in_text": NAME,
        },
    )

    res = await rig.research()

    said = _flat(res.result) + _flat(rig.svc.last(UID))
    assert NAME not in said and "Examplekar" not in said and "minister" not in said
    assert rig.vendor.queries == []
    assert res.result["say"] == NO_IDENTIFY and "offer" not in res.result


async def test_eyes_that_invent_a_caption_are_caught_by_the_picture_itself() -> None:
    """The fake eyes read the real pixels, so this shows what the rule rests on: a caption the
    look claims but the picture does not carry is not in what was read off the picture."""
    rig, pic = _face()
    assert read_text(pic) == []
    rig.eyes.lies(
        pic,
        {
            "has_person": True,
            "scene": "A person stands by a wall.",
            "text": ["HARBOUR BRIDGE 2026"],
            "subjects": [],
            "named_in_text": NAME,  # not in the text the look itself reports
        },
    )

    out = (await rig.research()).result

    assert "offer" not in out and NAME not in _flat(out)


async def test_a_landmark_behind_a_person_is_still_researched_but_only_the_landmark() -> None:
    rig = PictureRig()
    pic = picture(person=True)
    rig.eyes.knows(
        pic,
        scene="A person stands in front of a stone monument with four towers.",
        subjects=[("landmark", "Charminar monument"), ("product", "man in a white shirt")],
    )
    rig.turn.attach("sess_1", pic)

    out = (await rig.research()).result

    assert rig.vendor.queries == ["Charminar monument"]
    assert out["say"] == NO_IDENTIFY and len(out["results"]) == 2
    assert [s["name"].count("Charminar") for s in out["subjects"]] == [1]


async def test_results_that_are_about_a_person_are_left_out() -> None:
    """The last net: whatever was searched, pages that are a person's profiles or biography are
    never shown by picture research."""
    rig = PictureRig()
    pic = picture(blocks=[RED])
    rig.eyes.knows(pic, scene="A bronze figure.", subjects=[("landmark", f"{NAME} statue")])
    rig.turn.attach("sess_1", pic)
    rig.vendor.default = [
        SearchHit(f"{NAME} - Wikipedia", "https://en.wikipedia.org/wiki/Lekha_Examplekar",
                  f"{NAME} (born 1970) is an Indian politician."),
        SearchHit(f"{NAME} | LinkedIn", "https://www.linkedin.com/in/example-person-0001", "Bio"),
        SearchHit(f"{NAME} (@example)", "https://www.instagram.com/example_person_0001", "Photos"),
    ]  # fmt: skip

    out = (await rig.research()).result

    report = rig.svc.last(UID)
    assert out["results"] == [] and report is not None
    assert "about a person" in report.message and "born 1970" not in _flat(report)


# ---- D21-D: a name only from words in the picture; the unchanged check decides -------------------
def _people(hits: list[SearchHit]) -> tuple[PeopleService, FakeSearcher]:
    searcher = FakeSearcher(hits)
    return PeopleService(searcher, FakeModel(), mode=fixed_mode("ai")), searcher


async def test_a_caption_that_names_someone_is_offered_and_never_searched_here() -> None:
    rig, pic = _face(f"MINISTER {NAME.upper()}", "OPENS THE HARBOUR BRIDGE")
    rig.eyes.lies(
        pic,
        {
            "has_person": True,
            "scene": "A person in a blue top stands under a banner.",
            "text": read_text(pic),  # what is really written in the picture
            "subjects": [{"kind": "landmark", "name": "harbour bridge"}],
            "named_in_text": NAME,
        },
    )

    out = (await rig.research()).result

    assert out["offer"]["tool"] == RESEARCH_PERSON and NAME in out["offer"]["name"]
    assert out["offer"]["name"].startswith(FENCE_PREFIX)
    assert "only if the owner agrees" in out["offer"]["say"]
    assert out["say"] == NO_IDENTIFY
    assert rig.vendor.queries == ["harbour bridge"]  # the thing; never the name
    report = rig.svc.last(UID)
    assert report is not None and report.named == NAME
    assert f"The picture's text names {NAME}." in report.message
    assert report.message.endswith(f"Shall I look {NAME} up from public sources, Sir?")


async def test_the_offered_look_up_is_the_unchanged_check_a_public_figure_passes() -> None:
    rig, _ = _face(f"MINISTER {NAME.upper()}", "OPENS THE HARBOUR BRIDGE")
    people, searcher = _people(
        [
            hit(f"{NAME} - Wikipedia", "https://en.wikipedia.org/wiki/Lekha_Examplekar",
                f"{NAME} is the minister for ports"),
            hit(f"{NAME} - LinkedIn", "https://www.linkedin.com/in/example-person-0001",
                f"{NAME}, minister for ports"),
        ]
    )  # fmt: skip
    rig.add_people(people)

    res = await rig.call(RESEARCH_PERSON, name=NAME)  # what the offer leads to, on his "yes"

    assert res.outcome is GatewayOutcome.EXECUTED and res.result["subject"] == "public_figure"
    assert {p["platform"] for p in res.result["profiles"]} == {"wikipedia", "linkedin"}
    assert searcher.queries[0] == NAME


async def test_the_offered_look_up_refuses_a_private_person_exactly_as_when_typed() -> None:
    rig, pic = _face(f"WELCOME {PRIVATE.upper()}")
    rig.eyes.lies(
        pic,
        {
            "has_person": True,
            "scene": "A person holds a card.",
            "text": read_text(pic),
            "subjects": [],
            "named_in_text": PRIVATE,
        },
    )
    people, searcher = _people(
        [hit(f"{PRIVATE} (@meenu)", "https://www.instagram.com/example_private_0001", "Photos")]
    )
    rig.add_people(people)

    offered = (await rig.research()).result
    typed = await rig.call(RESEARCH_PERSON, name=PRIVATE)

    assert PRIVATE in offered["offer"]["name"]  # the picture's own words may be read out
    assert typed.result == {
        "refused": True,
        "message": UNVERIFIED_REFUSAL,
        "spoken": UNVERIFIED_REFUSAL,
    }
    assert searcher.credits == 1 and rig.vendor.queries == []


# ---- the picture goes to the eyes and nowhere else -----------------------------------------------
async def test_the_look_is_one_call_with_fixed_words_and_only_the_picture(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig, pic = _product()

    with caplog.at_level(logging.DEBUG):
        res = await rig.research()

    assert rig.eyes.looks == [(UID, LOOK_SYSTEM, LOOK_ASK, digest(pic))]
    assert rig.turn.asked == [(UID, "sess_1")]
    everything = _flat(res.result) + _flat(rig.svc.last(UID)) + _flat(rig.docs._data)  # noqa: SLF001
    logged = " ".join(r.getMessage() + _flat(r.__dict__.get("extra", "")) for r in caplog.records)
    for needle in (pic.b64()[:40], "iVBOR", "GLUCOSE"):
        assert needle not in logged
    assert pic.b64()[:40] not in everything and "iVBOR" not in everything
    entries = (await rig.audit.tail(10)).entries
    assert [(e.agent, e.tool, e.outcome) for e in entries] == [
        ("helpers", "web_search", "executed"),  # the governed read: kind only, never the query
        ("picture", PICTURE_RESEARCH, "executed"),
    ]
    assert "GLUCOSE" not in _flat([e.model_dump(mode="json") for e in entries])
    assert "Parle" not in _flat([e.model_dump(mode="json") for e in entries])


async def test_another_conversations_picture_is_never_used() -> None:
    rig, _ = _product()

    out = (await rig.research(session="sess_2")).result

    assert out == {"status": "no_picture", "message": NO_PICTURE, "spoken": NO_PICTURE}
    assert rig.eyes.looks == [] and rig.vendor.queries == []


async def test_the_second_picture_of_the_turn_can_be_asked_for() -> None:
    rig, first = _product()
    second = picture("ASSAM TEA")
    rig.eyes.knows(second, scene="A tin of tea.", subjects=[("product", "Assam tea tin")])
    rig.turn.attach("sess_1", first, second)

    out = (await rig.research(picture=2)).result
    none = (await rig.research(picture=3)).result

    assert rig.vendor.queries == ["Assam tea tin"] and out["pictures"] == 2
    assert none["status"] == "no_picture" and "2 pictures" in none["message"]


@pytest.mark.parametrize("bad", [0, 5, "1", 1.5, True])
async def test_a_bad_picture_number_is_refused_before_anything_runs(bad: object) -> None:
    rig, _ = _product()

    res = await rig.research(picture=bad)

    assert res.outcome is GatewayOutcome.ERROR and rig.eyes.looks == []


# ---- it says why, in plain words -----------------------------------------------------------------
@pytest.mark.parametrize(
    ("why", "words"),
    [
        ("no_ai", NO_AI),
        ("blind", "No brain on this JARVIS can be shown a picture, Sir."),
        ("limit", "I can't look at the picture, Sir: This month's limit of ₹500 is used up."),
        ("unreachable", "The AI couldn't look at the picture just now, Sir."),
    ],
)
async def test_when_no_look_can_be_made_it_says_why_and_searches_nothing(
    why: str, words: str
) -> None:
    rig, _ = _product()
    rig.eyes.cant = CantLook(why, words)  # type: ignore[arg-type]

    out = (await rig.research()).result

    assert out == {"status": why, "message": words, "spoken": words}
    assert rig.vendor.queries == [] and "$" not in words


@pytest.mark.parametrize("answer", ["", "I can't help with that.", '{"has_person": "maybe"}', "{"])
async def test_a_look_that_is_not_the_schema_is_thrown_away(answer: str) -> None:
    rig, pic = _product()
    rig.eyes.lies(pic, answer)

    out = (await rig.research()).result

    assert out == {"status": "unreadable", "message": UNREADABLE, "spoken": UNREADABLE}
    assert rig.vendor.queries == []


async def test_switched_off_in_settings_there_is_no_tool_and_the_service_says_so() -> None:
    rig = PictureRig(enabled=False)

    report = await rig.svc.research(UID, "sess_1")

    assert (report.status, report.message) == ("off", OFF) and rig.eyes.looks == []
    assert rig.gateway is not None and rig.gateway.registry.get(PICTURE_RESEARCH) is None


async def test_without_web_search_the_picture_is_still_described() -> None:
    rig = PictureRig(web=False)
    pic = picture("PARLE-G")
    rig.eyes.knows(pic, scene="A packet.", subjects=[("product", "Parle-G biscuit packet")])
    rig.turn.attach("sess_1", pic)

    out = (await rig.research()).result

    report = rig.svc.last(UID)
    assert out["status"] == "done" and out["results"] == [] and report is not None
    assert "Web search isn't set up here" in report.message


@pytest.mark.parametrize(
    ("row", "words"),
    [
        ("ask", "Web search is set to 'Ask first' in Permissions"),
        ("never", "Web search is set to 'Never' in Permissions"),
    ],
)
async def test_the_owners_web_search_row_is_obeyed(row: str, words: str) -> None:
    rig, _ = _product()
    rig.rows.web = row

    out = (await rig.research()).result

    report = rig.svc.last(UID)
    assert rig.vendor.queries == [] and out["results"] == []
    assert report is not None and words in report.message
    assert out["status"] == "done"  # the look itself is the Pictures row's, and that is "Allow"


async def test_the_pictures_row_decides_the_tool_itself() -> None:
    rig, _ = _product()
    rig.rows.pictures = "never"
    denied = await rig.research()
    rig.rows.pictures = "ask"
    asked = await rig.research()

    assert denied.outcome is GatewayOutcome.DENIED
    assert asked.outcome is GatewayOutcome.AWAITING_CONFIRMATION
    assert rig.eyes.looks == [] and rig.vendor.queries == []


async def test_a_failing_search_vendor_is_said_plainly_without_its_words() -> None:
    rig, _ = _product()
    rig.vendor.fail = True

    out = (await rig.research()).result

    report = rig.svc.last(UID)
    assert out["status"] == "done" and report is not None
    assert "Web search is not available right now" in report.message
    assert "internal error" not in _flat(out) + _flat(report)


async def test_a_private_detail_read_off_a_picture_is_never_sent_to_the_search_vendor() -> None:
    rig = PictureRig()
    pic = picture(blocks=[RED])
    rig.eyes.knows(
        pic, scene="A bill.", subjects=[("product", "account 123456789012 phone bill box")]
    )
    rig.turn.attach("sess_1", pic)

    await rig.research()

    report = rig.svc.last(UID)
    assert rig.vendor.queries == [] and report is not None
    assert "private detail" in report.message


async def test_too_many_looks_in_a_minute_are_refused() -> None:
    rig, _ = _product()

    results = [(await rig.research()).result for _ in range(5)]

    assert [r["status"] for r in results] == ["done"] * 4 + ["busy"]
    assert results[-1]["message"] == TOO_MANY and len(rig.eyes.looks) == 4


# ---- the tool as the gateway sees it -------------------------------------------------------------
def test_the_tool_is_a_read_in_the_pictures_row() -> None:
    rig = PictureRig()
    assert rig.gateway is not None
    tool = rig.gateway.registry.get(PICTURE_RESEARCH)

    assert tool is not None and tool.risk is ActionRisk.READ_ONLY
    assert tool.trusted_output is False  # what a picture says is someone else's words
    assert tool.activity_words == "Researched a picture"
    assert {g.id for g in groups_for(PICTURE_RESEARCH, ActionRisk.READ_ONLY)} == {"pictures"}
    assert "never identifies a person" in tool.description
    assert set(tool.input_schema["properties"]) == {"picture"}


async def test_the_last_report_is_one_owners_and_is_forgotten_after_ten_minutes() -> None:
    rig, _ = _product()
    await rig.research()

    assert rig.svc.last("u_other") is None and rig.svc.last(UID) is not None
    rig.svc.clock = lambda: 10_000.0  # type: ignore[method-assign]
    assert rig.svc.last(UID) is None

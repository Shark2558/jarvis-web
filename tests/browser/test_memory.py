# tests/browser/test_memory.py — the Memory panel, the "Used N memories" reply chip and the phone
# "More" sheet (slice 8) in a real browser. /v1/memory* is faked with page.route, shaped exactly as
# §5 of docs/plans/phase3-slice8-long-term-memory.md says, so these tests pin the console's side of
# the contract on their own and keep working once the real backend lands. They cover: lazy load and
# plain empty states, add / edit / pin / delete (two-step), server refusals (422 sensitive, 409
# memory_full, 409 consent_required), the learning consent dialog, About you saves, filter, export,
# import preview + confirm, Forget everything (typed FORGET), hostile text, the brain note, the
# reply chip, the phone tab bar + More sheet, contrast on Night and Day, 0 JS errors / CSP reports.
from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import unquote, urlsplit

import pytest
from test_brief import CONTRAST_JS, SETTLE_JS  # same directory (pytest prepend import)
from test_console import DESKTOP, PHONE, Console

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright, expect = _pw.sync_playwright, _pw.expect

pytestmark = pytest.mark.browser

COST_NOTE = "About ₹5–15 a month on the Claude brain; never more than ₹30."
SENSITIVE = "JARVIS never keeps card numbers or ID numbers, Sir."
FULL = "Memory is full — delete some facts first."
CONSENT = "Learning needs your go-ahead first, Sir."
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
MEMORY_URL = re.compile(r".*/v1/memory(?:/[^?]*)?(?:\?.*)?$")


def fact(fid: str, text: str, category: str = "other", **over: Any) -> dict[str, Any]:
    """One fact exactly as §3 describes it."""
    f: dict[str, Any] = {
        "id": fid,
        "text": text,
        "category": category,
        "keywords": [],
        "origin": "told",
        "pinned": True,
        "confidence": 0.9,
        "source": None,
        "created_at": "2026-10-30T09:00:00Z",
        "updated_at": "2026-10-30T09:00:00Z",
        "last_used_at": None,
        "use_count": 0,
        "replaced_by": None,
        "replaced_at": None,
    }
    f.update(over)
    return f


def memory_view(**over: Any) -> dict[str, Any]:
    """GET /v1/memory (§5)."""
    view: dict[str, Any] = {
        "settings": {"use": True, "learn": False, "learn_consented_at": None},
        "profile": {"about": "", "preferences": "", "people": "", "work": ""},
        "facts": [],
        "counts": {"active": 0, "replaced": 0, "limit": 500},
        "learn_cost_note_inr": COST_NOTE,
        "runs_today": 0,
    }
    view.update(over)
    view["counts"] = {**view["counts"], "active": len(view["facts"])}
    return view


FACTS = [
    fact("m1", "My name is Akash; call me Sir.", "about_you"),
    fact("m2", "I prefer tea to coffee.", "preferences", origin="learned", pinned=False),
    fact("m3", "Priya is my manager.", "people", origin="added"),
    fact("m4", "I lead the Unified Registry programme.", "work", origin="imported", pinned=False),
]


def _json(route: Any, status: int, body: Any) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


class FakeMemory:
    """Answers /v1/memory* for one page the way §5 says; records every request."""

    def __init__(self, page: Any, view: dict[str, Any] | None = None) -> None:
        self.view = copy.deepcopy(view if view is not None else memory_view())
        self.calls: list[dict[str, Any]] = []
        self.full = False
        self.consent_always = False  # 409 consent_required even with confirm_spend (a stale page)
        self.fail_get: int | None = None
        self.next_id = 100
        self.replaced = [fact("m0", "I live in Kochi.", "places", replaced_by="m9")]
        page.route(MEMORY_URL, self._handle)

    def to(self, method: str, path: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["method"] == method and c["path"] == path]

    def _handle(self, route: Any) -> None:
        req = route.request
        call = {
            "method": req.method,
            "path": urlsplit(req.url).path,
            "body": json.loads(req.post_data) if req.post_data else None,
            "headers": dict(req.headers),
        }
        self.calls.append(call)
        status, body = self._answer(call["method"], call["path"], call["body"] or {})
        if status == 204:
            route.fulfill(status=204, body="")
        else:
            _json(route, status, body)

    def _count(self) -> None:
        self.view["counts"]["active"] = len(self.view["facts"])

    def _answer(self, method: str, path: str, body: dict[str, Any]) -> tuple[int, Any]:
        v, facts = self.view, self.view["facts"]
        if path == "/v1/memory" and method == "GET":
            if self.fail_get:
                return self.fail_get, {
                    "error": "unavailable",
                    "detail": "Memory store is waking up.",
                }
            return 200, v
        if path == "/v1/memory" and method == "DELETE":
            if body.get("confirm") != "FORGET":
                return 422, {"error": "confirm_required", "detail": "Type FORGET to confirm."}
            v["facts"] = []
            v["profile"] = {k: "" for k in v["profile"]}
            self._count()
            return 204, None
        if path == "/v1/memory/settings" and method == "PUT":
            wants_learn = body.get("learn") is True
            if wants_learn and (body.get("confirm_spend") is not True or self.consent_always):
                return 409, {"error": "consent_required", "detail": CONSENT}
            v["settings"] = {**v["settings"], **{k: body[k] for k in ("use", "learn") if k in body}}
            return 200, v["settings"]
        m = re.fullmatch(r"/v1/memory/profile/([a-z]+)", path)
        if m and method == "PUT":
            label, text = m.group(1), str(body.get("text", ""))
            if label not in v["profile"]:
                return 404, {"error": "not_found", "detail": "No such block."}
            if CARD.search(text):
                return 422, {"error": "sensitive", "detail": SENSITIVE}
            v["profile"][label] = text.strip()
            return 200, {"label": label, "text": text.strip()}
        if path == "/v1/memory/facts" and method == "POST":
            if self.full or len(facts) >= v["counts"]["limit"]:
                return 409, {"error": "memory_full", "detail": FULL}
            if CARD.search(str(body.get("text", ""))):
                return 422, {"error": "sensitive", "detail": SENSITIVE}
            made = fact(
                f"m{self.next_id}",
                body["text"],
                body.get("category", "other"),
                origin="added",
                created_at="2026-11-01T09:00:00Z",
                updated_at="2026-11-01T09:00:00Z",
            )
            self.next_id += 1
            facts.insert(0, made)
            self._count()
            return 200, made
        m = re.fullmatch(r"/v1/memory/facts/([^/]+)", path)
        if m and method in ("PATCH", "DELETE"):
            fid = unquote(m.group(1))
            found = next((f for f in facts if f["id"] == fid), None)
            if found is None:
                return 404, {"error": "not_found", "detail": "No such fact."}
            if method == "DELETE":
                facts.remove(found)
                self._count()
                return 204, None
            if CARD.search(str(body.get("text", ""))):
                return 422, {"error": "sensitive", "detail": SENSITIVE}
            for k in ("text", "category", "pinned"):
                if k in body:
                    found[k] = body[k]
            found["updated_at"] = "2026-11-01T10:00:00Z"
            return 200, found
        if path == "/v1/memory/export" and method == "GET":
            return 200, self.export()
        if path == "/v1/memory/import" and method == "POST":
            return 200, self._import(body.get("data") or {})
        return 404, {"error": "not_found", "detail": "Not found."}

    def export(self) -> dict[str, Any]:
        v = self.view
        return {
            "version": 1,
            "exported_at": "2026-11-01T10:00:00Z",
            "settings": v["settings"],
            "profile": v["profile"],
            "facts": v["facts"] + self.replaced,
        }

    def _import(self, data: dict[str, Any]) -> dict[str, int]:
        added = skipped = 0
        have = {f["text"].lower() for f in self.view["facts"]}
        for f in data.get("facts", []):
            if f.get("replaced_by"):
                continue  # history travels with the file; only active facts are merged
            if f["text"].lower() in have or CARD.search(f["text"]):
                skipped += 1
                continue
            self.view["facts"].append(fact(f"m{self.next_id}", f["text"], origin="imported"))
            self.next_id += 1
            added += 1
        self._count()
        return {"added": added, "skipped": skipped}


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def make(browser: Any, server_url: str, token: str) -> Iterator[Callable[..., Console]]:
    made: list[Console] = []

    def factory(viewport: dict[str, int] = DESKTOP, store: dict[str, str] | None = None) -> Console:
        c = Console(browser, server_url, token, viewport)
        if store:  # device preferences set before any script runs
            lines = [
                f"localStorage.setItem({json.dumps(k)}, {json.dumps(v)});" for k, v in store.items()
            ]
            c.page.add_init_script("".join(lines))
        made.append(c)
        return c

    yield factory
    for c in made:
        c.close()


def _main(c: Console) -> Any:
    c.open_panel("memory")
    main = c.page.locator("#memMain")
    main.wait_for(state="visible")
    return main


def _settings(c: Console) -> None:
    btn = c.page.locator("#memSetBtn")
    if btn.get_attribute("aria-expanded") != "true":
        btn.click()
    c.page.locator("#memSetBody").wait_for(state="visible")


def _row(c: Console, text: str) -> Any:
    return c.page.locator("#memList .mfact", has_text=text)


def _focused(c: Console) -> str:
    return str(c.page.evaluate("document.activeElement.id"))


def _quiet_errors(c: Console) -> list[str]:
    """Page errors other than the refused requests a test provokes on purpose."""
    return [e for e in c.errors if "status of" not in e]


def _day(c: Console, iso: str) -> str:
    return str(
        c.page.evaluate(
            "(iso) => new Intl.DateTimeFormat([], {day: 'numeric', month: 'short'})"
            ".format(new Date(iso))",
            iso,
        )
    )


# ---- loading and empty states --------------------------------------------------------------------
def test_memory_loads_only_when_opened_and_explains_an_empty_memory(
    make: Callable[..., Console],
) -> None:
    c = make()
    fake = FakeMemory(c.page)
    c.open()
    c.page.wait_for_timeout(300)
    assert fake.calls == []  # nothing is read until the owner looks (each GET costs reads)
    _main(c)
    page = c.page
    assert len(fake.to("GET", "/v1/memory")) == 1
    expect(page.locator("#memList")).to_have_text(
        "No facts yet. Say “remember that …” in a conversation, or add one below."
    )
    expect(page.locator("#memoryMeta")).to_have_text("0 of 500 facts")
    assert page.locator("#memFilter").is_hidden()  # nothing to filter yet
    # settings: collapsed by default, with their summary
    assert page.locator("#memSetBtn").get_attribute("aria-expanded") == "false"
    assert page.locator("#memSetBody").is_hidden()
    expect(page.locator("#memSetSum")).to_have_text("Memory in replies on · Learning off")
    for label in ("about", "preferences", "people", "work"):
        assert page.locator(f"#memP-{label}").input_value() == ""
        assert page.locator(f"#memS-{label}").get_attribute("aria-disabled") == "true"
        expect(page.locator(f"#memC-{label}")).to_have_text("0 / 1,000")
    assert page.locator("#memBrainNote").is_hidden()  # the mock brain is not a training brain
    # reopening within a minute reuses what was loaded
    page.locator('.dk[data-open="memory"]').click()
    page.locator("#p-memory").wait_for(state="hidden")
    c.open_panel("memory")
    page.wait_for_timeout(200)
    assert len(fake.to("GET", "/v1/memory")) == 1
    assert c.csp_violations() == []
    assert c.errors == []


def test_memory_not_available_and_a_failed_load_retries(make: Callable[..., Console]) -> None:
    c = make()
    c.page.route(MEMORY_URL, lambda r: _json(r, 404, {"detail": "Not Found"}))
    c.open()
    c.open_panel("memory")
    c.page.locator("#memState", has_text="Not available in this setup").wait_for()
    expect(c.page.locator("#memoryMeta")).to_have_text("Not available")
    assert c.page.locator("#memMain").is_hidden() and c.page.locator("#memoryRefresh").is_hidden()
    assert c.errors == []  # a 404 here is by design, not an error
    c2 = make()
    fake = FakeMemory(c2.page, memory_view(facts=copy.deepcopy(FACTS)))
    fake.fail_get = 503
    c2.open()
    c2.open_panel("memory")
    state = c2.page.locator("#memState")
    state.locator("#memRetry").wait_for()
    assert "Couldn't load your memory. Memory store is waking up." in str(state.text_content())
    fake.fail_get = None
    state.locator("#memRetry").click()
    c2.page.locator("#memMain").wait_for(state="visible")
    expect(c2.page.locator("#memoryMeta")).to_have_text("4 of 500 facts")
    assert _quiet_errors(c2) == []


# ---- facts --------------------------------------------------------------------------------------
def test_facts_are_grouped_with_origin_badges_dates_and_pins(make: Callable[..., Console]) -> None:
    c = make()
    odd = fact(
        "m5", "Odd category lands in Other.", "__proto__", origin="constructor", pinned=False
    )
    FakeMemory(c.page, memory_view(facts=copy.deepcopy(FACTS) + [odd]))
    c.open()
    _main(c)
    page = c.page
    heads = page.locator("#memList .mgh").all_text_contents()
    assert heads == ["About you· 1", "Preferences· 1", "People· 1", "Work· 1", "Other· 1"], heads
    expect(page.locator("#memFactsCount")).to_have_text("· 5 facts · 2 pinned")
    words = {
        "My name is Akash": "you told me",
        "I prefer tea": "learned",
        "Priya is my manager": "added by you",
        "Unified Registry": "imported",
    }
    for text, badge in words.items():
        row = _row(c, text)
        expect(row.locator(".mbadge")).to_have_text(badge)
        assert _day(c, "2026-10-30T09:00:00Z") in str(row.locator(".mwhen").text_content())
    assert _row(c, "Odd category").locator(".mbadge").count() == 0  # unknown origin: no badge
    pin = _row(c, "My name is Akash").get_by_role("button", name="Pin")
    assert pin.get_attribute("aria-pressed") == "true"
    assert "Pinned" in str(_row(c, "My name is Akash").text_content())
    assert _row(c, "I prefer tea").get_by_role("button", name="Pin").get_attribute(
        "aria-pressed"
    ) == ("false")
    assert c.errors == []


def test_pin_edit_and_two_step_delete(make: Callable[..., Console]) -> None:
    c = make()
    fake = FakeMemory(c.page, memory_view(facts=copy.deepcopy(FACTS)))
    c.open()
    _main(c)
    page = c.page
    # pin: one PATCH, the switch and the word follow, focus stays on it
    pin = _row(c, "I prefer tea").get_by_role("button", name="Pin")
    pin.click()
    expect(pin).to_have_attribute("aria-pressed", "true")
    patches = [x for x in fake.calls if x["method"] == "PATCH"]
    assert [(x["path"], x["body"]) for x in patches] == [("/v1/memory/facts/m2", {"pinned": True})]
    assert patches[0]["headers"].get("x-requested-with") == "JARVIS"
    assert patches[0]["headers"].get("authorization") == "Bearer " + c.token
    assert _focused(c) == pin.get_attribute("id")
    # edit inline: Esc cancels (the panel stays), Save sends only what changed
    _row(c, "Priya is my manager").get_by_role("button", name="Edit").click()
    box = page.locator("#memList .medit textarea")
    expect(box).to_be_focused()
    assert box.input_value() == "Priya is my manager."
    box.fill("Priya Nair is my manager at Amnex.")
    page.keyboard.press("Escape")
    expect(page.locator("#memList .medit")).to_have_count(0)
    assert page.locator("#p-memory").is_visible()
    assert _focused(c).startswith("mfEdit-")
    assert _row(c, "Priya is my manager.").count() == 1  # nothing was saved
    _row(c, "Priya is my manager").get_by_role("button", name="Edit").click()
    page.locator("#memList .medit textarea").fill("Priya Nair is my manager at Amnex.")
    page.locator("#memList .medit select").select_option("work")
    page.locator("#memList .medit").get_by_role("button", name="Save").click()
    _row(c, "Priya Nair is my manager at Amnex.").wait_for()
    assert fake.to("PATCH", "/v1/memory/facts/m3")[-1]["body"] == {
        "text": "Priya Nair is my manager at Amnex.",
        "category": "work",
    }
    heads = page.locator("#memList .mgh").all_text_contents()
    assert "People· 1" not in heads and "Work· 2" in heads, heads  # it moved to Work
    # a refused edit keeps the draft and says why
    _row(c, "I prefer tea").get_by_role("button", name="Edit").click()
    page.locator("#memList .medit textarea").fill("My card is 4111 1111 1111 1111")
    page.locator("#memList .medit").get_by_role("button", name="Save").click()
    page.locator("#memList .medit .lerr", has_text=SENSITIVE).wait_for()
    assert (
        page.locator("#memList .medit textarea").input_value() == "My card is 4111 1111 1111 1111"
    )
    page.locator("#memList .medit").get_by_role("button", name="Cancel").click()
    # delete: the first press only asks; Esc and Keep keep it
    row = _row(c, "I prefer tea")
    row.get_by_role("button", name="Delete").click()
    expect(row.locator(".confirm")).to_contain_text("Delete this fact for good?")
    assert _focused(c).startswith("mfKeep-")
    page.keyboard.press("Escape")
    expect(row.locator(".confirm")).to_have_count(0)
    assert _focused(c).startswith("mfDel-") and page.locator("#p-memory").is_visible()
    row.get_by_role("button", name="Delete").click()
    row.locator(".confirm").get_by_role("button", name="Keep").click()
    assert fake.to("DELETE", "/v1/memory/facts/m2") == []
    row.get_by_role("button", name="Delete").click()
    row.locator(".confirm").get_by_role("button", name="Delete").click()
    expect(_row(c, "I prefer tea")).to_have_count(0)
    assert len(fake.to("DELETE", "/v1/memory/facts/m2")) == 1
    expect(page.locator("#memoryMeta")).to_have_text("3 of 500 facts")
    assert _focused(c).startswith("mfDel-")  # on to the next fact, never lost to the page
    assert _quiet_errors(c) == []


def test_add_a_fact_and_the_servers_plain_refusals(make: Callable[..., Console]) -> None:
    c = make()
    fake = FakeMemory(c.page)
    c.open()
    _main(c)
    page = c.page
    add, err = page.locator("#memAddText"), page.locator("#memAddErr")
    page.locator("#memAddBtn").click()  # empty: says so, sends nothing
    expect(err).to_have_text("Write the fact first.")
    add.fill("I work from Thiruvananthapuram on Fridays.")
    expect(page.locator("#memAddC")).to_have_text("42 / 300")
    page.locator("#memAddCat").select_option("places")
    page.locator("#memAddBtn").click()
    _row(c, "Thiruvananthapuram on Fridays").wait_for()
    assert [x["body"] for x in fake.to("POST", "/v1/memory/facts")] == [
        {"text": "I work from Thiruvananthapuram on Fridays.", "category": "places"}
    ]
    expect(_row(c, "Thiruvananthapuram").locator(".mbadge")).to_have_text("added by you")
    assert add.input_value() == "" and err.text_content() == ""
    expect(page.locator("#memoryNote")).to_have_text("Fact added.")
    # 422 sensitive: the server's own sentence, and the text stays for fixing
    add.fill("My card is 4111 1111 1111 1111")
    page.locator("#memAddBtn").click()
    expect(err).to_have_text(SENSITIVE)
    assert add.input_value() == "My card is 4111 1111 1111 1111"
    # 409 memory_full: likewise
    fake.full = True
    add.fill("Another fact.")
    page.locator("#memAddBtn").click()
    expect(err).to_have_text(FULL)
    assert len(fake.view["facts"]) == 1
    assert _quiet_errors(c) == []


def test_filter_box_narrows_the_facts(make: Callable[..., Console]) -> None:
    c = make()
    FakeMemory(c.page, memory_view(facts=copy.deepcopy(FACTS)))
    c.open()
    _main(c)
    page = c.page
    page.locator("#memFilter").fill("TEA")
    expect(page.locator("#memList .mfact")).to_have_count(1)
    expect(page.locator("#memFilterInfo")).to_have_text("Showing 1 of 4.")
    page.locator("#memFilter").fill("learned")  # the badge words match too
    expect(page.locator("#memList .mfact")).to_have_count(1)
    page.locator("#memFilter").fill("zzz")
    expect(page.locator("#memList")).to_have_text("No facts match “zzz”.")
    page.locator("#memFilter").fill("")
    expect(page.locator("#memList .mfact")).to_have_count(4)
    assert c.errors == []


# ---- About you ----------------------------------------------------------------------------------
def test_about_you_saves_each_block_and_keeps_unsaved_typing(make: Callable[..., Console]) -> None:
    c = make()
    profile = {"about": "Akash, project lead.", "preferences": "", "people": "", "work": ""}
    fake = FakeMemory(c.page, memory_view(profile=profile))
    c.open()
    _main(c)
    page = c.page
    about = page.locator("#memP-about")
    assert about.input_value() == "Akash, project lead."
    expect(page.locator("#memC-about")).to_have_text("20 / 1,000")
    about.fill("Akash, project lead in Thiruvananthapuram. Call me Sir.")
    assert page.locator("#memS-about").get_attribute("aria-disabled") is None
    page.locator("#memS-about").click()
    expect(page.locator("#memSt-about")).to_have_text("Saved.")
    puts = fake.to("PUT", "/v1/memory/profile/about")
    assert [x["body"] for x in puts] == [
        {"text": "Akash, project lead in Thiruvananthapuram. Call me Sir."}
    ]
    assert puts[0]["headers"].get("x-requested-with") == "JARVIS"
    assert page.locator("#memS-about").get_attribute("aria-disabled") == "true"  # nothing new
    # a refusal says why; unsaved typing in another block survives a reload of the panel
    page.locator("#memP-people").fill("Card 4111 1111 1111 1111")
    page.locator("#memS-people").click()
    expect(page.locator("#memSt-people")).to_have_text(SENSITIVE)
    page.locator("#memP-work").fill("Unified Registry, still typing")
    page.locator("#memoryRefresh").click()
    page.wait_for_timeout(300)
    assert len(fake.to("GET", "/v1/memory")) == 2
    assert page.locator("#memP-work").input_value() == "Unified Registry, still typing"
    assert about.input_value() == "Akash, project lead in Thiruvananthapuram. Call me Sir."
    assert _quiet_errors(c) == []


# ---- settings and the learning consent ----------------------------------------------------------
def test_learning_asks_first_and_sends_confirm_spend(make: Callable[..., Console]) -> None:
    c = make()
    fake = FakeMemory(c.page, memory_view(runs_today=3))
    c.open()
    _main(c)
    _settings(c)
    page = c.page
    learn, dialog = page.locator("#memLearn"), page.locator("#memoryDialog")
    assert learn.get_attribute("aria-pressed") == "false"
    learn.focus()
    page.keyboard.press("Enter")
    dialog.wait_for(state="visible")
    words = str(dialog.text_content())
    assert COST_NOTE in words and "never the free brain" in words
    assert "Your messages in a conversation are sent to Claude" in words
    assert _focused(c) == "memoryDialogNo"
    page.keyboard.press("Tab")
    assert _focused(c) == "memoryDialogYes"
    page.keyboard.press("Tab")
    assert _focused(c) == "memoryDialogNo"  # focus stays inside
    page.keyboard.press("Escape")  # Esc = Not now
    dialog.wait_for(state="hidden")
    assert _focused(c) == "memLearn" and page.locator("#p-memory").is_visible()
    learn.click()
    dialog.wait_for(state="visible")
    page.keyboard.press("Enter")  # Enter lands on Not now
    dialog.wait_for(state="hidden")
    assert fake.to("PUT", "/v1/memory/settings") == []
    learn.click()
    page.locator("#memoryDialogYes").click()
    expect(learn).to_have_attribute("aria-pressed", "true")
    assert [x["body"] for x in fake.to("PUT", "/v1/memory/settings")] == [
        {"learn": True, "confirm_spend": True}
    ]
    expect(page.locator("#memLearnD")).to_contain_text("Ran 3 times today.")
    # switching it off spends nothing, so it asks nothing; "use" never asks either
    learn.click()
    expect(learn).to_have_attribute("aria-pressed", "false")
    page.locator("#memUse").click()
    expect(page.locator("#memUse")).to_have_attribute("aria-pressed", "false")
    assert [x["body"] for x in fake.to("PUT", "/v1/memory/settings")][1:] == [
        {"learn": False},
        {"use": False},
    ]
    assert dialog.is_hidden()
    page.locator("#memSetBtn").click()
    expect(page.locator("#memSetSum")).to_have_text("Memory in replies off · Learning off")
    expect(page.locator("#memoryMeta")).to_have_text("0 of 500 facts · off in replies")
    assert c.errors == []


def test_a_409_consent_required_leaves_learning_off_and_says_why(
    make: Callable[..., Console],
) -> None:
    c = make()
    fake = FakeMemory(c.page)
    fake.consent_always = True
    c.open()
    _main(c)
    _settings(c)
    c.page.locator("#memLearn").click()
    c.page.locator("#memoryDialogYes").click()
    expect(c.page.locator("#memoryNote")).to_have_text(CONSENT)
    assert c.page.locator("#memLearn").get_attribute("aria-pressed") == "false"
    assert len(fake.to("PUT", "/v1/memory/settings")) == 1
    assert _quiet_errors(c) == []


def test_memory_settings_are_remembered_on_this_device(make: Callable[..., Console]) -> None:
    c = make()
    FakeMemory(c.page)
    c.open()
    _main(c)
    c.page.locator("#memSetBtn").click()
    c.page.locator("#memSetBody").wait_for(state="visible")
    assert c.page.evaluate("localStorage.getItem('jarvis_memory_settings_open')") == "1"
    c.page.reload()
    c.page.locator("#welcome").wait_for()
    c.page.locator("#memMain").wait_for(state="visible")  # the panel was left open: it loads itself
    assert c.page.locator("#memSetBtn").get_attribute("aria-expanded") == "true"
    assert c.page.locator("#memUse").is_visible()
    assert c.errors == []


# ---- export, import, forget everything ----------------------------------------------------------
def test_export_downloads_a_dated_file_with_history(make: Callable[..., Console]) -> None:
    c = make()
    fake = FakeMemory(
        c.page, memory_view(facts=copy.deepcopy(FACTS), counts={"replaced": 1, "limit": 500})
    )
    c.open()
    _main(c)
    expect(c.page.locator("#memExportInfo")).to_have_text(
        "Export includes 1 replaced fact, kept 30 days for your history."
    )
    with c.page.expect_download() as info:
        c.page.locator("#memExport").click()
    download = info.value
    today = c.page.evaluate(
        "(() => { const d = new Date(), p = (n) => String(n).padStart(2, '0');"
        " return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`; })()"
    )
    assert download.suggested_filename == f"jarvis-memory-{today}.json"
    with open(download.path(), encoding="utf-8") as fh:
        assert json.load(fh) == fake.export()
    expect(c.page.locator("#memoryNote")).to_have_text("Export saved to your downloads.")
    assert c.csp_violations() == []
    assert c.errors == []


def _file(name: str, payload: Any) -> dict[str, Any]:
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return {"name": name, "mimeType": "application/json", "buffer": raw}


def test_import_previews_counts_then_asks_before_sending(make: Callable[..., Console]) -> None:
    c = make()
    fake = FakeMemory(c.page, memory_view(facts=copy.deepcopy(FACTS[:1])))
    c.open()
    _main(c)
    page = c.page
    picker = page.locator("#memImportFile")
    # not an export: said plainly, nothing sent
    picker.set_input_files(_file("notes.json", b"{not json"))
    expect(page.locator("#memoryNote")).to_contain_text("it isn't valid JSON")
    picker.set_input_files(_file("list.json", [1, 2, 3]))
    expect(page.locator("#memoryNote")).to_have_text(
        "That file doesn't look like a JARVIS memory export."
    )
    assert page.locator("#memImportBox").is_hidden()
    export = {
        "version": 1,
        "profile": {"about": "Akash.", "preferences": "", "people": "", "work": ""},
        "facts": [
            fact("x1", "My name is Akash; call me Sir.", "about_you"),  # a duplicate: skipped
            fact("x2", "I take the 08:10 train.", "plans"),
            fact("x3", "I lived in Kochi.", "places", replaced_by="x4"),
        ],
    }
    picker.set_input_files(_file("jarvis-memory-2026-10-31.json", export))
    box = page.locator("#memImportBox")
    box.wait_for(state="visible")
    expect(page.locator("#memImportText")).to_have_text(
        "jarvis-memory-2026-10-31.json holds 2 facts, 1 replaced fact and 1 About you note."
    )
    assert _focused(c) == "memImportNo"  # the safe choice
    page.keyboard.press("Escape")
    box.wait_for(state="hidden")
    assert fake.to("POST", "/v1/memory/import") == []
    picker.set_input_files(_file("jarvis-memory-2026-10-31.json", export))
    page.locator("#memImportYes").click()
    expect(page.locator("#memoryNote")).to_have_text("Imported: 1 fact added, 1 skipped.")
    sent = fake.to("POST", "/v1/memory/import")
    assert [x["body"] for x in sent] == [{"data": export}]
    assert sent[0]["headers"].get("x-requested-with") == "JARVIS"
    _row(c, "I take the 08:10 train.").wait_for()  # reloaded after the import
    assert box.is_hidden()
    assert c.errors == []


def test_forget_everything_needs_forget_typed(make: Callable[..., Console]) -> None:
    c = make()
    profile = {"about": "Akash.", "preferences": "Short replies.", "people": "", "work": ""}
    fake = FakeMemory(c.page, memory_view(facts=copy.deepcopy(FACTS), profile=profile))
    c.open()
    _main(c)
    page = c.page
    yes, typed = page.locator("#memForgetYes"), page.locator("#memForgetIn")
    page.locator("#memForget").click()
    page.locator("#memForgetBox").wait_for(state="visible")
    expect(typed).to_be_focused()
    assert yes.is_disabled()
    typed.fill("forget")
    assert yes.is_disabled()  # exactly FORGET
    typed.press("Enter")
    page.wait_for_timeout(200)
    assert fake.to("DELETE", "/v1/memory") == []
    page.keyboard.press("Escape")  # Esc = Keep
    page.locator("#memForgetBox").wait_for(state="hidden")
    assert _focused(c) == "memForget" and page.locator("#p-memory").is_visible()
    page.locator("#memForget").click()
    assert typed.input_value() == ""  # never pre-filled
    typed.fill("FORGET")
    assert yes.is_enabled()
    yes.click()
    expect(page.locator("#memList")).to_contain_text("No facts yet.")
    sent = fake.to("DELETE", "/v1/memory")
    assert [x["body"] for x in sent] == [{"confirm": "FORGET"}]
    assert sent[0]["headers"].get("x-requested-with") == "JARVIS"
    assert page.locator("#memP-about").input_value() == ""
    assert page.locator("#memP-preferences").input_value() == ""
    expect(page.locator("#memoryNote")).to_contain_text("Your switches are kept.")
    assert page.locator("#memForgetBox").is_hidden()
    assert c.errors == []


# ---- the brain note and the reply chip ----------------------------------------------------------
BRAINS = [
    {
        "id": "mock",
        "label": "Mock brain",
        "default": True,
        "trains_on_content": False,
        "tools_allowed": True,
        "warning": "",
        "models": {},
    },
    {
        "id": "gemini",
        "label": "Gemini (free)",
        "default": False,
        "trains_on_content": True,
        "tools_allowed": False,
        "warning": "Free Gemini brain: Google may use what you type.",
        "models": {},
    },
]


def test_memory_is_not_used_with_a_training_brain(make: Callable[..., Console]) -> None:
    c = make()
    c.page.route("**/v1/brains", lambda r: _json(r, 200, BRAINS))
    FakeMemory(c.page)
    c.open()
    _main(c)
    note = c.page.locator("#memBrainNote")
    assert note.is_hidden()
    c.page.locator("#brainSel").select_option("gemini")
    note.wait_for(state="visible")
    assert "Memory is not used with this brain." in str(note.text_content())
    c.page.locator("#brainSel").select_option("mock")
    note.wait_for(state="hidden")
    assert c.errors == []


def _with_memories(c: Console, used: list[Any] | None) -> None:
    """The real reply, plus the memories the backend says it sent (§5 `memory_used`)."""

    def handle(route: Any) -> None:
        response = route.fetch()
        body = response.json()
        if used is not None:
            body["memory_used"] = used
        route.fulfill(response=response, json=body)

    c.page.route("**/v1/chat", handle)


def test_reply_shows_used_memories_as_an_expandable_text_list(make: Callable[..., Console]) -> None:
    c = make()
    FakeMemory(c.page, memory_view(facts=copy.deepcopy(FACTS)))
    used = [
        {"id": "m1", "text": "My name is Akash; call me Sir."},
        {"id": "m2", "text": "I prefer tea."},
    ]
    _with_memories(c, used)
    c.open()
    c.send("what do I drink?")
    page = c.page
    chip = page.locator(".row.jarvis .mchip").last
    expect(chip).to_have_text("Used 2 memories")
    assert chip.get_attribute("aria-expanded") == "false"
    listing = page.locator("#" + str(chip.get_attribute("aria-controls")))
    assert listing.is_hidden()
    chip.click()
    listing.wait_for(state="visible")
    assert chip.get_attribute("aria-expanded") == "true"
    assert listing.locator("li").all_text_contents() == [u["text"] for u in used]
    listing.get_by_role("button", name="Open Memory").click()
    page.locator("#memMain").wait_for(state="visible")
    chip.click()
    listing.wait_for(state="hidden")
    # one memory, then none: singular, then no chip at all
    page.unroute("**/v1/chat")
    _with_memories(c, [{"id": "m1", "text": "My name is Akash; call me Sir."}])
    c.send("and my name?")
    expect(page.locator(".row.jarvis .mchip").last).to_have_text("Used 1 memory")
    page.unroute("**/v1/chat")
    _with_memories(c, [])
    c.send("thanks")
    page.unroute("**/v1/chat")
    _with_memories(c, None)
    c.send("bye")
    expect(page.locator(".row.jarvis .mchip")).to_have_count(2)
    assert c.errors == []


# ---- hostile text stays text --------------------------------------------------------------------
HOSTILE = [
    "<img src=x onerror=window.__pwned=1>",
    "<script>window.__pwned=2</script>",
]
INERT_JS = """() => {
  const bad = [];
  for (const el of [document.getElementById('p-memory'), document.getElementById('memoryDialog'),
                    document.getElementById('log')]) {
    el.querySelectorAll('*').forEach(e => {
      for (const a of e.attributes) if (/^on/i.test(a.name)) bad.push(e.tagName + ':' + a.name);
      const tag = e.tagName.toUpperCase();
      if (['IMG', 'A', 'SCRIPT', 'IFRAME', 'OBJECT', 'EMBED', 'STYLE', 'LINK', 'META', 'BASE',
           'TEMPLATE'].includes(tag)) bad.push(tag);
    });
  }
  return { bad, pwned: window.__pwned ?? null, polluted: ({}).polluted ?? null };
}"""


@pytest.mark.parametrize("h", HOSTILE)
def test_markup_in_memory_text_stays_text(make: Callable[..., Console], h: str) -> None:
    c = make()
    hostile_fact = fact("__proto__", h, "__proto__", origin="constructor", created_at=h)
    view = memory_view(
        facts=[hostile_fact, fact("m2", "Second " + h, "people")],
        profile={
            "about": h,
            "preferences": h,
            "people": "",
            "work": "",
            "__proto__": {"polluted": 1},
        },
        learn_cost_note_inr=h,
        runs_today=h,
    )
    view["counts"] = {"active": h, "replaced": h, "limit": h}
    view["__proto__"] = {"polluted": "view"}
    fake = FakeMemory(c.page, view)
    fake.view["counts"] = {"active": h, "replaced": h, "limit": h}
    _with_memories(c, [{"id": h, "text": h}, {"id": 1, "text": {"__proto__": {"polluted": 1}}}])
    c.open()
    c.send("hello")
    chip = c.page.locator(".row.jarvis .mchip").last
    expect(chip).to_have_text("Used 1 memory")  # the malformed entry is dropped
    chip.click()
    _main(c)
    page = c.page
    text = str(page.locator("#memList").text_content())
    assert h in text and "Second " + h in text
    assert page.locator("#memP-about").input_value() == h
    _row(c, "Second").get_by_role("button", name="Edit").click()
    assert page.locator("#memList .medit textarea").input_value() == "Second " + h
    page.locator("#memList .medit").get_by_role("button", name="Cancel").click()
    _settings(c)
    page.locator("#memLearn").click()
    dialog = page.locator("#memoryDialog")
    dialog.wait_for(state="visible")
    assert h in str(dialog.text_content())
    found = page.evaluate(INERT_JS)
    assert found == {"bad": [], "pwned": None, "polluted": None}, found
    page.keyboard.press("Escape")
    page.locator("#memFilter").fill(h)
    expect(page.locator("#memList .mfact")).to_have_count(2)
    found = page.evaluate(INERT_JS)
    assert found == {"bad": [], "pwned": None, "polluted": None}, found
    assert c.csp_violations() == []
    assert c.errors == []


# ---- phone: the tab bar keeps eight tabs, the rest sit behind More -------------------------------
def test_phone_tab_bar_has_memory_and_a_more_sheet(make: Callable[..., Console]) -> None:
    c = make(PHONE)
    FakeMemory(c.page, memory_view(facts=copy.deepcopy(FACTS)))
    c.open()
    page = c.page
    tabs = page.evaluate(
        """[...document.querySelectorAll('#dock .dk')].filter(b => b.getClientRects().length)
           .map(b => { const r = b.getBoundingClientRect();
                       return {name: b.dataset.open || b.id, w: r.width, h: r.height,
                               left: r.left, right: r.right}; })"""
    )
    names = [t["name"] for t in tabs]
    assert len(tabs) == 8 and "memory" in names and names[-1] == "dockMore", names
    assert "vitals" not in names and "construct" not in names
    for t in tabs:
        assert t["w"] >= 44 and t["h"] >= 44 and t["left"] >= 0 and t["right"] <= 390, t
    more, sheet = page.locator("#dockMore"), page.locator("#moreSheet")
    more.click()
    sheet.wait_for(state="visible")
    assert more.get_attribute("aria-expanded") == "true"
    # focus lands on the first item: Vault since R2 (its four panels lead the sheet, as in the dock)
    assert page.evaluate("document.activeElement.dataset.sheetOpen") == "vault"
    page.keyboard.press("Escape")
    sheet.wait_for(state="hidden")
    expect(more).to_have_attribute("aria-expanded", "false")  # the close event comes a tick later
    expect(more).to_be_focused()
    more.click()
    sheet.get_by_role("button", name=re.compile("Vitals")).click()
    page.locator("#p-vitals").wait_for(state="visible")
    assert sheet.is_hidden() and page.locator("#p-chat").is_hidden()
    assert more.get_attribute("aria-label") == "More panels, Vitals shown"
    assert "on" in str(more.get_attribute("class"))
    # Memory has its own tab: one panel at a time, nothing wider than the screen
    page.locator('.dk[data-open="memory"]').click()
    page.locator("#memMain").wait_for(state="visible")
    assert more.get_attribute("aria-label") == "More panels"
    visible = page.evaluate(
        "[...document.querySelectorAll('.panel[data-panel]')].filter(p => !p.hidden).length"
    )
    assert visible == 1
    widths = page.evaluate(
        "[document.documentElement.scrollWidth, document.body.scrollWidth, window.innerWidth,"
        " document.getElementById('p-memory').querySelector('.pbody').scrollWidth,"
        " document.getElementById('p-memory').querySelector('.pbody').clientWidth]"
    )
    assert widths[0] <= widths[2] and widths[1] <= widths[2] and widths[3] <= widths[4], widths
    for b in page.locator("#memList .mib").all()[:3]:  # touch targets
        box = b.bounding_box()
        assert box and box["width"] >= 44 and box["height"] >= 44, box
    assert c.csp_violations() == []
    assert c.errors == []


# ---- contrast and motion ------------------------------------------------------------------------
@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("accent", [None, "#FFFF00"])
def test_memory_text_meets_aa_contrast(
    make: Callable[..., Console], surface: str, accent: str | None
) -> None:
    store = {"jarvis_surface": surface, "jarvis_memory_settings_open": "1"}
    if accent:
        store["jarvis_accent"] = accent
    c = make(store=store)
    c.page.route("**/v1/brains", lambda r: _json(r, 200, list(reversed(BRAINS))))  # Gemini first
    FakeMemory(
        c.page, memory_view(facts=copy.deepcopy(FACTS), counts={"replaced": 1, "limit": 500})
    )
    c.open()
    page = c.page
    page.locator("#brainSel").select_option("gemini")  # the amber note is measured too
    _main(c)
    page.locator("#memBrainNote").wait_for(state="visible")
    # every control enabled (a disabled one is exempt from WCAG 1.4.3, and drawn at half opacity)
    for label in ("about", "preferences", "people", "work"):
        page.locator(f"#memP-{label}").fill("Something unsaved")
    row = _row(c, "I prefer tea")
    row.get_by_role("button", name="Delete").click()  # the red confirm row too
    page.locator("#memForget").click()  # and the red Forget box
    page.locator("#memForgetIn").fill("FORGET")
    page.locator("#memoryNote").evaluate(
        "n => { n.textContent = 'Fact added.'; n.className = 'bnote mlive ok'; }"
    )
    page.evaluate(SETTLE_JS, "#p-memory")
    found = page.evaluate(CONTRAST_JS, "#p-memory")
    assert len(found) > 40, len(found)
    low = [f for f in found if f["ratio"] < 4.5]
    assert low == [], low
    page.locator("#memLearn").click()
    page.locator("#memoryDialog").wait_for(state="visible")
    page.evaluate(SETTLE_JS, "#memoryDialog")
    found = page.evaluate(CONTRAST_JS, "#memoryDialog")
    assert len(found) >= 5
    assert [f for f in found if f["ratio"] < 4.5] == []
    assert c.errors == []


def test_motion_off_keeps_the_memory_panel_still(make: Callable[..., Console]) -> None:
    c = make(store={"jarvis_motion": "off"})
    FakeMemory(c.page, memory_view(facts=copy.deepcopy(FACTS)))
    c.open()
    _main(c)
    c.page.locator("#memSetBtn").click()
    running = c.page.evaluate(
        """(() => {
             const panel = document.getElementById('p-memory');
             return document.getAnimations().filter(a => a.playState === 'running'
               && a.effect && a.effect.target && panel.contains(a.effect.target)).length;
           })()"""
    )
    assert running == 0
    assert c.errors == []


def test_joiners_survive_and_only_a_sensitive_refusal_blames_private_data(
    make: Callable[..., Console],
) -> None:
    """Review fix: ZWNJ/ZWJ (Malayalam chillus, emoji) are kept in the list and the edit box, and a
    422 that is not `sensitive` (e.g. FastAPI's own validation list) never says "private data"."""
    c = make()
    text = "Grew up in കൊച്ചി‍ and loves 👨‍👩‍👧 movie nights"
    FakeMemory(c.page, memory_view(facts=[fact("m1", text, "places", origin="told")]))
    c.open()
    _main(c)
    page = c.page
    row = _row(c, "Grew up in")
    assert "‍" in str(row.text_content())
    row.get_by_role("button", name="Edit").click()
    assert page.locator("#memList textarea").first.input_value() == text
    page.route(
        re.compile(r".*/v1/memory/facts$"),
        lambda route: _json(
            route, 422, {"detail": [{"type": "missing", "loc": ["body", "text"], "msg": "x"}]}
        ),
    )
    page.locator("#memAddText").fill("Something harmless.")
    page.locator("#memAddBtn").click()
    err = page.locator("#memAddErr")
    expect(err).not_to_have_text("")
    assert "private data" not in str(err.text_content())
    assert _quiet_errors(c) == []

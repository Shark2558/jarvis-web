# tests/test_r63_b_units.py -- R6.3 part B's pure parts (docs/plans/r6-3-book-content.md D4, D10):
# the filler, the six checks with check (2)'s exemptions and the precision case (H5) and the
# reading pack (D4, M8, L7), all kept for the authored pages (R6.3.1); the grants, the estimate,
# the hold and the prompt went with the runtime writer (R6.3.1 D8). No brain is called here.
from __future__ import annotations

import io
import zipfile

import pytest
from r63_fake_brains import (
    EMAIL_DRAFT,
    FAKE_PATH_DRAFT,
    GOOD_DRAFT,
    INVENTED_DRAFT,
    PLANNED_OUTSIDE_DRAFT,
    TYPED_NUMBER_DRAFT,
    UNVERIFIED_DRAFT,
    draft,
)
from r63_fakes import FIXTURE_FACTS, FIXTURE_FILES, source_zip
from r63_fakes_b import TRIAL_FACTS, files

from jarvis.buildbook.gen.scrub import NoScrub, Scrubber, default_scrubber
from jarvis.buildbook.writer import checks, fill, packs
from jarvis.buildbook.writer.model import PACK_CAP_BYTES

C01 = FIXTURE_FACTS.page("pg_card_c01")
assert C01 is not None


def _ctx(page_id: str = "pg_card_c01", scrub: Scrubber | None = None) -> checks.Context:
    page = TRIAL_FACTS.page(page_id)
    assert page is not None
    return checks.Context(
        page=page,
        facts=TRIAL_FACTS,
        scrub=scrub or default_scrubber(),
        emails=("owner@example.com",),
        canary="cn0123456789abcdef",
    )


def _codes(text: str, page_id: str = "pg_card_c01") -> tuple[str, ...]:
    parsed = checks.parse(text)
    assert parsed is not None
    return checks.check(parsed, _ctx(page_id))


# ---- fill (D10 (2): the filler writes the values) ----------------------------------------------
def test_fill_writes_each_known_value_and_names_the_unknown() -> None:
    text = "{{fact:src/jarvis/demo/router.py:MAX_TRIES}} tries, {{fact:settings.demo_limit}} max."
    assert fill.fill(text, FIXTURE_FACTS) == "3 tries, 5 max."
    assert fill.unknown_keys("{{fact:nope.key}} and {{fact:cards.count}}", FIXTURE_FACTS) == (
        "nope.key",
    )
    assert fill.show(12_345) == "12,345" and fill.show(2.50) == "2.5" and fill.show(True) == "on"


# ---- the six checks (D10) -----------------------------------------------------------------------
def test_the_good_draft_passes_all_six() -> None:
    assert _codes(GOOD_DRAFT) == ()


@pytest.mark.parametrize(
    ("text", "code"),
    [
        (FAKE_PATH_DRAFT, "refs"),
        (TYPED_NUMBER_DRAFT, "numbers"),
        (EMAIL_DRAFT, "personal"),
        (INVENTED_DRAFT, "invented"),
        (PLANNED_OUTSIDE_DRAFT, "planned"),
        (UNVERIFIED_DRAFT, "unverified"),
    ],
)
def test_each_bad_draft_breaks_its_check(text: str, code: str) -> None:
    assert code in _codes(text)


def test_shape_needs_the_five_headings_in_order_and_no_html_or_link() -> None:
    assert checks.parse("## In plain words\nOnly one section.\n") is None
    swapped = GOOD_DRAFT.replace("## How it works", "## How it is").replace("## In plain", "## In")
    assert checks.parse(swapped) is None
    assert "shape" in _codes(GOOD_DRAFT.replace("each request.", "each <b>request</b>."))
    assert "shape" in _codes(GOOD_DRAFT.replace("each request.", "each [request](x)."))
    long_plain = GOOD_DRAFT.replace("each request.", "each request. " + "Words here. " * 90)
    assert "shape" in _codes(long_plain)
    assert "shape" in _codes(GOOD_DRAFT.replace("each request.", "each cn0123456789abcdef."))


def test_a_number_inside_the_example_is_fine_and_an_unknown_placeholder_is_not() -> None:
    assert _codes(GOOD_DRAFT.replace("twice", "3 times")) == ()
    assert "numbers" in _codes(GOOD_DRAFT.replace("demo_limit}}", "demo_limits}}"))


def test_a_short_name_resolves_against_the_pages_own_refs_first() -> None:
    short = GOOD_DRAFT.replace("`src/jarvis/demo/router.py`", "`router.py`")
    assert _codes(short) == ()
    partial = GOOD_DRAFT.replace("`src/jarvis/demo/router.py`", "`demo/router.py`")
    assert _codes(partial) == ()
    symbol = GOOD_DRAFT.replace("`pick`", "`src/jarvis/demo/router.py:pick`")
    assert _codes(symbol) == ()
    assert "refs" in _codes(GOOD_DRAFT.replace("`pick`", "`choose`"))
    route = GOOD_DRAFT.replace("`pick`", "`GET /v1/demo`")
    assert _codes(route) == ()


# A hand-written good page for each trial sample, citing short names, constants and HTTP statuses
# (H5's precision case: the checks must pass good pages, not only refuse bad ones).
PRECISION = {
    "pg_chapter_example": draft(
        "One request goes through the demo router and the demo store.",
        "Ravi asks twice in 2 minutes; both answers come from one tier.",
        "The router (`router.py`) calls `pick` and tries "
        "{{fact:src/jarvis/demo/router.py:MAX_TRIES}} times. The store (`store.py`) keeps "
        "notes {{fact:src/jarvis/demo/store.py:KEEP_DAYS}} "
        "days, with SHA-256 checks and UTF-8 text.",
        "Nothing: it runs inside the server.",
        "`GET /v1/demo` answers status 503 while the store is down. It says so plainly.",
    ),
    "pg_card_c16": draft(
        "The router picks the tier for each request, by its own rule.",
        "A made-up question arrives at 9:30; the router picks the balanced tier.",
        "`router.py` reads `MAX_TRIES` ({{fact:src/jarvis/demo/router.py:MAX_TRIES}}) and the "
        "setting `demo_limit` ({{fact:settings.demo_limit}}); see C01 since R6.3. Its `pick` "
        "draws nothing in 3D.",
        "There are {{fact:cards.count}} cards in this demo; none costs anything.",
        "When `GET /v1/demo` answers 429 it waits, then tries again.",
    ),
    "pg_module_wardrobe": draft(
        "The module groups the demo's parts in one place.",
        "Mina opens the demo at 8 am and sees 2 notes.",
        "Its router is `src/jarvis/demo/router.py` and its notes go to the collection "
        "`demo_notes`. It has {{fact:modules.count}} module.",
        "It runs inside the server at no cost.",
        "If the store fails, the page says so plainly.",
    ),
    "pg_screen_vitals": draft(
        "The screen shows the demo's numbers in the console.",
        "On a made-up Monday it shows 4 requests and 1 error.",
        "The console asks `GET /v1/demo` and draws what `router.py` answers over HTTP/2.",
        "Nothing: it is part of the console.",
        "A status 401 from `GET /v1/demo` means the browser must sign in again.",
    ),
    "pg_service_telegram": draft(
        "An outside service carries the demo's messages.",
        "Asha gets 1 message at 7 pm about a made-up note.",
        "The router `router.py` sends through the service; the store keeps nothing extra. "
        "Each request to `GET /v1/demo` is checked with AES-256-GCM keys.",
        "The demo's own part costs nothing; see `demo_limit` for the cap.",
        "When the service is down the demo waits, then says so plainly.",
    ),
}


@pytest.mark.parametrize("page_id", sorted(PRECISION))
def test_the_precision_case_a_good_page_for_each_trial_sample_passes_all_six(page_id: str) -> None:
    assert _codes(PRECISION[page_id], page_id) == ()


def test_the_precision_case_fails_with_one_exemption_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        checks, "STANDARD_NAMES", tuple(n for n in checks.STANDARD_NAMES if n != "3D")
    )
    assert "numbers" in _codes(PRECISION["pg_card_c16"], "pg_card_c16")


def test_personal_text_is_refused_through_the_scrubber_and_the_owner_check() -> None:
    owner = GOOD_DRAFT.replace("calls nothing else", "tells owner@example.com")
    assert "personal" in _codes(owner)
    assert checks.check(checks.parse(GOOD_DRAFT) or {}, _ctx(scrub=NoScrub())) == ()


# ---- the reading pack (D4, M8, L7) ---------------------------------------------------------------
@pytest.mark.parametrize(
    "path",
    [
        ".claude/agents/x.md",
        "tests/r63_fakes.py",
        "evals/maps/cases.jsonl",
        ".env",
        "deploy/home/bridge.env.example",
        "prod.env",
        "src/jarvis/buildbook/gen/fake_secrets.txt",
        "src/jarvis/buildbook/gen/redact.json",
        "uv.lock",
        "deploy/key.pem",
        "android/app/release.keystore",
        "src/jarvis/api/static/logo.png",
    ],
)
def test_a_pack_never_reads(path: str) -> None:
    assert not packs.readable(path)


def test_a_pack_reads_public_code() -> None:
    assert packs.readable("src/jarvis/demo/router.py") and packs.readable("docs/plans/r6-3.md")


def _zip_with(extra: dict[str, str]) -> bytes:
    return source_zip({**FIXTURE_FILES, **extra})


def test_the_pack_holds_the_card_the_signatures_the_plan_and_its_facts_never_tests() -> None:
    secret = {"tests/test_demo.py": "SECRET_TEST_DATA = 'Zorblaxton'\n", "src/x.env.example": "K=1"}
    tree = packs.read_source(_zip_with(secret))
    assert "tests/test_demo.py" not in tree and "src/x.env.example" not in tree
    pack = packs.build(C01, FIXTURE_FACTS, tree, default_scrubber())
    body = pack.body
    assert "C01 · Demo router" in body and "def pick(asked: str) -> str" in body
    assert "MAX_TRIES" in body and "src/jarvis/demo/router.py:MAX_TRIES = 3" in body
    assert "Zorblaxton" not in body and "<<BOOK REFERENCE" in body
    assert "src/jarvis/demo/router.py:pick" in pack.allowed
    assert len(body.encode()) <= PACK_CAP_BYTES


def test_a_big_pack_is_cut_to_its_cap_dropping_plan_text_first_never_the_card() -> None:
    tree = packs.read_source(source_zip(files(big=True)))
    pack = packs.build(C01, FIXTURE_FACTS, tree, default_scrubber())
    room = PACK_CAP_BYTES - packs.PROMPT_RESERVE  # R6.3.1: the prompt is gone, its reserve stays
    assert room - 2_000 <= len(pack.body.encode()) <= room
    assert "C01 · Demo router" in pack.body


def test_the_pack_is_scrubbed() -> None:
    zipped = _zip_with({"src/jarvis/demo/router.py": '"""Mail ops@example.org."""\n'})
    pack = packs.build(C01, FIXTURE_FACTS, packs.read_source(zipped), default_scrubber())
    assert "ops@example.org" not in pack.body and "[removed]" in pack.body


def test_binaries_in_the_zip_are_never_read() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("src/jarvis/demo/blob.py", b"\x00\x01\x02")
        zf.writestr("src/jarvis/demo/ok.py", b'"""fine"""\n')
    assert set(packs.read_source(buf.getvalue())) == {"src/jarvis/demo/ok.py"}

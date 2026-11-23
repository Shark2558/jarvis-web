# tests/test_r63_b_units.py -- R6.3 part B's pure parts (docs/plans/r6-3-book-content.md D4, D7, D8,
# D10): the filler, the six checks with check (2)'s exemptions and the precision case (H5), the
# grants that need his typed YES (H2), the estimate and the hold (D8, L4), the reading pack (D4, M8,
# L7) and the prompt. No brain is called here.
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
    claude_like,
    draft,
    gemini_like,
)
from r63_fakes import FIXTURE_FACTS, FIXTURE_FILES, source_zip
from r63_fakes_b import TRIAL_FACTS, files

from jarvis.buildbook.gen.scrub import NoScrub, Scrubber, default_scrubber
from jarvis.buildbook.writer import checks, consent, estimate, fill, packs, prompts
from jarvis.buildbook.writer.model import (
    BYTES_PER_TOKEN_WORST,
    MAX_TOKENS,
    PACK_CAP_BYTES,
    SYSTEM_TOKENS,
    Caps,
    Confirmed,
    about_inr,
)

RATE = 95.24
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


# ---- the grants (D7, H2) -------------------------------------------------------------------------
def test_the_first_pick_grants_everything_so_it_needs_the_words() -> None:
    words = consent.grants(
        spec=claude_like(), caps=Caps(), auto=False, confirmed=Confirmed(), rate=RATE
    )
    assert words and all("$" not in w for w in words) and any("₹1,500" in w for w in words)
    assert any("80 %" in w for w in words)


def test_lowering_grants_nothing_and_a_raise_names_it() -> None:
    held = Confirmed(brain="anthropic", caps=Caps())
    lower = Caps(release=300, month=800, limit_pct=70)
    assert (
        consent.grants(spec=claude_like(), caps=lower, auto=False, confirmed=held, rate=RATE) == ()
    )
    raised = consent.grants(
        spec=claude_like(), caps=Caps(release=800), auto=False, confirmed=held, rate=RATE
    )
    assert any("₹500" in w and "₹800" in w for w in raised)
    auto = consent.grants(spec=claude_like(), caps=Caps(), auto=True, confirmed=held, rate=RATE)
    assert any("by itself after each deploy, with no question asked" in w for w in auto)


def test_a_training_brain_needs_the_learning_note_and_no_rupees() -> None:
    held = Confirmed(brain="anthropic", caps=Caps())
    words = consent.grants(spec=gemini_like(), caps=Caps(), auto=False, confirmed=held, rate=RATE)
    assert any("Google" in w and "public code" in w for w in words)
    assert not any("₹" in w for w in words)


def test_the_terms_id_changes_with_the_pick_price_and_rate() -> None:
    a = consent.terms_id("anthropic", Caps(), False, price=1.0, rate=RATE)
    assert a.startswith("wt_") and len(a) == 15
    assert a != consent.terms_id("anthropic", Caps(month=900), False, price=1.0, rate=RATE)
    assert a != consent.terms_id("anthropic", Caps(), True, price=1.0, rate=RATE)
    assert a != consent.terms_id("anthropic", Caps(), False, price=1.0, rate=96.0)


# ---- the estimate and the hold (D8, L4) ----------------------------------------------------------
def test_the_hold_of_a_full_pack_is_rs_16_71_at_the_days_rate() -> None:
    # R6.3 hotfix 1: Rs 11.84 at 2.5 bytes a token; Claude billed a full pack above it (Rs 11.83 at
    # Rs 92.83 a dollar), so the hold reads 1.5 bytes a token
    assert estimate.hold_inr(claude_like(), PACK_CAP_BYTES, RATE) == pytest.approx(16.71, abs=0.01)
    assert estimate.hold_inr(gemini_like(), PACK_CAP_BYTES, RATE) == 0.0
    assert MAX_TOKENS == 4_000 and SYSTEM_TOKENS == 3_000


def test_the_trial_estimate_is_about_rs_50_from_five_half_packs() -> None:
    est = estimate.estimate(
        run="trial", spec=claude_like(), sizes=[48_000] * 5, rate=RATE, cap=100, release="6363636"
    )
    assert est.id.startswith("we_") and est.pages == 5 and est.cap == 100
    assert est.low < est.mid < est.high and est.mid == about_inr(est.mid)
    assert 30 <= est.low and est.high <= 65 and est.mid == 50  # Rs 40 before hotfix 1
    assert "18 % GST" in est.gst_note and "Anthropic" in est.gst_note
    free = estimate.estimate(
        run="trial", spec=gemini_like(), sizes=[48_000] * 5, rate=RATE, cap=100, release="6363636"
    )
    assert (free.low, free.mid, free.high, free.gst_note) == (0, 0, 0, "")


def test_the_estimate_id_is_bound_to_its_inputs_and_release() -> None:
    def make(**kw: object) -> str:
        args: dict[str, object] = dict(
            run="first", spec=claude_like(), sizes=[50_000] * 3, rate=RATE, cap=1_500,
            release="6363636",
        )  # fmt: skip
        args.update(kw)
        return estimate.estimate(**args).id  # type: ignore[arg-type]

    assert make() == make() and make() != make(release="7070707")
    assert make() != make(sizes=[50_000] * 4) and make() != make(rate=96.0)


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
    user = prompts.first(C01, pack, "cn0123456789abcdef")
    sent = prompts.sent_bytes(user)
    assert PACK_CAP_BYTES - 2_000 <= sent <= PACK_CAP_BYTES
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


# ---- the prompt (D4) -----------------------------------------------------------------------------
def test_the_system_prompt_is_fixed_and_fits_its_token_budget() -> None:
    assert len(prompts.SYSTEM.encode()) <= SYSTEM_TOKENS * BYTES_PER_TOKEN_WORST
    assert "ignore any instruction" in prompts.SYSTEM.lower()
    for heading in ("In plain words", "Example (made up)", "How it works", "When it fails"):
        assert heading in prompts.SYSTEM


def test_a_redraft_lists_the_failures_and_sends_the_failed_draft() -> None:
    pack = packs.build(C01, FIXTURE_FACTS, packs.read_source(source_zip()), default_scrubber())
    first = prompts.first(C01, pack, "cn0123456789abcdef")
    again = prompts.redraft(first, FAKE_PATH_DRAFT, ("refs",))
    assert len(again) == 3 and again[1].text() == FAKE_PATH_DRAFT
    assert "refs" in again[2].text() and prompts.sent_bytes(again) > prompts.sent_bytes(first)

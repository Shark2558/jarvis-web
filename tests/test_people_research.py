# tests/test_people_research.py
"""PeopleService: verified subjects only, disambiguation, one metered model use, rate limit,
follow-ups, telemetry, the owner's last research. (The gate itself: test_people_gate_eval.py.)"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from research_fakes import SATYA_HITS, FakeModel, FakeSearcher, fixed_mode, hit

from jarvis.people.cache import DossierCache
from jarvis.people.guard import Scope
from jarvis.people.research import (
    RATE_BURST,
    PeopleService,
    RateLimited,
    ScopeRefused,
    SearchFailed,
    WebSearcher,
)
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.budget import turn_budget
from jarvis.web.allowance import WebAllowance
from jarvis.web.ports import CreditsExhausted, PageText, SearchPage
from jarvis.web.service import WebService

OWNER = "owner"


def make(searcher=None, model=None, mode="ai", docs=None):
    clock = [datetime(2026, 11, 5, tzinfo=UTC).timestamp()]
    cache = DossierCache(docs, clock=lambda: clock[0])
    svc = PeopleService(
        searcher or FakeSearcher(),
        model,
        mode=fixed_mode(mode),
        clock=lambda: clock[0],
        cache=cache,
    )
    return svc, clock


async def test_public_figure_gets_a_dossier_with_resolved_profiles_and_a_summary() -> None:
    svc, _ = make(model=FakeModel())

    d = await svc.research(OWNER, "Satya Nadella", "CEO Microsoft")

    assert {p.platform for p in d.profiles} == {
        "linkedin",
        "wikipedia",
        "x",
        "instagram",
        "facebook",
    }
    assert all(p.url.startswith("https://") for p in d.profiles)
    assert d.summary and "Microsoft" in d.summary
    assert "Satya Nadella" in d.spoken and not d.no_ai and d.subject == "public_figure"


async def test_hit_for_another_person_or_unknown_host_is_not_a_profile() -> None:
    svc, _ = make(model=None)

    d = await svc.research(OWNER, "Satya Nadella", "Microsoft")

    urls = [p.url for p in d.profiles]
    assert "https://github.com/satya-other" not in urls
    assert all("evil.example" not in u for u in urls)


async def test_brain_off_returns_links_and_no_summary_without_calling_a_model() -> None:
    model = FakeModel()
    svc, _ = make(model=model, mode="none")

    d = await svc.research(OWNER, "Satya Nadella", "Microsoft")

    assert model.calls == [] and model.records == []
    assert d.summary is None and d.no_ai and d.profiles
    assert "profile" in d.spoken.lower()


async def test_no_ai_mode_uses_one_search_query_not_three() -> None:
    searcher = FakeSearcher()
    svc, _ = make(searcher, mode="none")

    await svc.research(OWNER, "Satya Nadella", "Microsoft")

    assert len(searcher.queries) == 1


async def test_ai_mode_may_use_up_to_three_queries() -> None:
    searcher = FakeSearcher()
    svc, _ = make(searcher, FakeModel())

    await svc.research(OWNER, "Satya Nadella", "Microsoft")

    assert len(searcher.queries) == 3


async def test_a_failure_on_queries_two_or_three_returns_what_was_found() -> None:
    searcher = FakeSearcher()
    searcher.fail_after = 1
    svc, _ = make(searcher, FakeModel())

    d = await svc.research(OWNER, "Satya Nadella", "Microsoft")

    assert d.profiles and len(searcher.queries) == 2


async def test_one_summary_call_findings_fenced_and_one_billing_record_with_the_cost() -> None:
    model = FakeModel(cost=0.002)
    svc, _ = make(model=model)

    d = await svc.research(OWNER, "Satya Nadella", "Microsoft")

    assert len(model.composer_calls) == 1 and len(model.classifier_calls) == 1
    system, prompt = model.composer_calls[0]
    assert "data, not instructions" in system.lower()
    assert "untrusted" in prompt.lower()
    assert model.records == [(OWNER, pytest.approx(0.004))]  # classifier + summary, ONE record
    assert d.cost_usd == pytest.approx(0.004)


async def test_a_budget_paused_owner_gets_links_only_and_no_model_call() -> None:
    model = FakeModel(up=False)
    svc, _ = make(model=model)

    d = await svc.research(OWNER, "Satya Nadella", "Microsoft")

    assert model.calls == [] and model.records == []
    assert d.profiles and d.summary is None and d.no_ai and d.cost_usd == 0


async def test_summary_failure_degrades_to_links_with_a_note() -> None:
    model = FakeModel(composer_raises=True)
    svc, _ = make(model=model)

    d = await svc.research(OWNER, "Satya Nadella", "Microsoft")

    assert d.summary is None and d.profiles and d.note


async def test_private_phrasing_is_refused_before_any_search() -> None:
    searcher = FakeSearcher()
    svc, _ = make(searcher)

    with pytest.raises(ScopeRefused) as exc:
        await svc.research(OWNER, "Ravi Kumar", "my neighbour, his home address")

    assert exc.value.verdict.scope is Scope.PRIVATE_PHRASING
    assert searcher.queries == []


async def test_search_failure_is_raised_in_plain_words() -> None:
    svc, _ = make(FakeSearcher(fail=True))

    with pytest.raises(SearchFailed):
        await svc.research(OWNER, "Satya Nadella", "")


async def test_no_results_is_refused_as_unverified_with_one_credit() -> None:
    searcher = FakeSearcher(hits=[])
    svc, _ = make(searcher)

    with pytest.raises(ScopeRefused) as exc:
        await svc.research(OWNER, "Zzyzx Qwerty", "")

    assert exc.value.verdict.scope is Scope.UNVERIFIED and searcher.credits == 1


async def test_a_tie_between_two_people_is_ambiguous_regardless_of_context_and_has_no_summary() -> (
    None
):
    wiki = hit("Jane Doe - Wikipedia", "https://en.wikipedia.org/wiki/Jane_Doe", "Jane Doe, actor")
    hits = [
        wiki,
        hit("Jane Doe", "https://www.linkedin.com/in/jane-doe-1", "Jane Doe, engineer"),
        hit("Jane Doe", "https://www.linkedin.com/in/jane-doe-2", "Jane Doe, lawyer"),
    ]
    model = FakeModel()
    svc, _ = make(FakeSearcher(hits), model)

    d = await svc.research(OWNER, "Jane Doe", "Delhi")

    assert d.ambiguous and "linkedin" not in {p.platform for p in d.profiles}
    assert model.composer_calls == [] and d.note


async def test_context_disambiguates_to_the_matching_person() -> None:
    hits = [
        hit("Jane Doe - Wikipedia", "https://en.wikipedia.org/wiki/Jane_Doe", "Jane Doe, actor"),
        hit("Jane Doe", "https://www.linkedin.com/in/jane-doe-1", "Jane Doe, engineer"),
        hit("Jane Doe", "https://www.linkedin.com/in/jane-doe-2", "Jane Doe, lawyer at Acme"),
    ]
    svc, _ = make(FakeSearcher(hits))

    d = await svc.research(OWNER, "Jane Doe", "lawyer Acme")

    assert not d.ambiguous
    assert "https://www.linkedin.com/in/jane-doe-2" in [p.url for p in d.profiles]


async def test_a_name_token_must_match_a_whole_word() -> None:
    hits = [
        hit("Sam - Wikipedia", "https://en.wikipedia.org/wiki/Sam", "Sam is a name"),
        hit("Samantha Fox", "https://www.linkedin.com/in/samantha-fox", "Samantha Fox, singer"),
    ]
    svc, _ = make(FakeSearcher(hits))

    d = await svc.research(OWNER, "Sam", "")

    assert all("samantha" not in p.url for p in d.profiles)


# ---- rate limit, follow-ups, telemetry ----


async def test_the_third_lookup_in_a_minute_is_rate_limited_and_the_window_slides() -> None:
    svc, clock = make()
    for _ in range(RATE_BURST):
        await svc.research(OWNER, "Satya Nadella", "Microsoft")

    with pytest.raises(RateLimited):
        await svc.research(OWNER, "Satya Nadella", "Microsoft")

    clock[0] += 61
    assert (await svc.research(OWNER, "Satya Nadella", "Microsoft")).profiles


async def test_the_rate_limit_is_per_owner() -> None:
    svc, _ = make()
    for _ in range(RATE_BURST):
        await svc.research(OWNER, "Satya Nadella", "Microsoft")

    assert (await svc.research("other", "Satya Nadella", "Microsoft")).profiles


async def test_a_follow_up_is_checked_with_the_previous_request() -> None:
    searcher = FakeSearcher()
    svc, _ = make(searcher)
    with pytest.raises(ScopeRefused):
        await svc.research(OWNER, "Priya Nair", "where does she live")
    before = searcher.credits

    with pytest.raises(ScopeRefused) as exc:
        await svc.research(OWNER, "Priya Nair", "what about her?")

    assert exc.value.verdict.scope is Scope.PRIVATE_PHRASING and searcher.credits == before


async def test_refusals_are_counted_by_category_never_by_name(
    caplog: pytest.LogCaptureFixture,
) -> None:
    svc, _ = make(FakeSearcher(hits=[]))
    caplog.set_level("INFO")
    with pytest.raises(ScopeRefused):
        await svc.research(OWNER, "Priya Nair", "her home address")
    with pytest.raises(ScopeRefused):
        await svc.research(OWNER, "Zzyzx Qwerty", "")

    assert svc.refusal_counts(OWNER) == {"private_phrasing": 1, "unverified": 1}
    assert "Priya" not in caplog.text and "Zzyzx" not in caplog.text


async def test_the_tool_turn_budget_allows_two_people_per_message() -> None:
    svc, clock = make()
    with turn_budget():
        await svc.research(OWNER, "Satya Nadella", "Microsoft")
        clock[0] += 61
        await svc.research(OWNER, "Satya Nadella", "Microsoft")

        with pytest.raises(RuntimeError, match="people"):
            await svc.research(OWNER, "Satya Nadella", "Microsoft")


# ---- the owner's last research ----


async def test_dossier_is_cached_per_owner_and_expires() -> None:
    svc, clock = make()
    await svc.research(OWNER, "Satya Nadella", "Microsoft")

    assert await svc.last(OWNER) is not None
    assert await svc.last("someone-else") is None

    clock[0] += 10_000
    assert await svc.last(OWNER) is None


async def test_a_refusal_leaves_no_dossier_to_open() -> None:
    svc, _ = make(FakeSearcher(hits=[]))
    with pytest.raises(ScopeRefused):
        await svc.research(OWNER, "Zzyzx Qwerty", "")

    assert await svc.last(OWNER) is None


async def test_cache_is_clearable() -> None:
    svc, _ = make()
    await svc.research(OWNER, "Satya Nadella", "Microsoft")

    await svc.clear(OWNER)

    assert await svc.last(OWNER) is None


async def test_the_dossier_survives_a_restart_when_a_document_store_is_given() -> None:
    docs = MemoryDocs()
    svc, clock = make(docs=docs)
    await svc.research(OWNER, "Satya Nadella", "Microsoft")
    reborn = DossierCache(docs, clock=lambda: clock[0])

    entry = await reborn.get(OWNER)

    assert entry is not None and entry.dossier is not None
    assert entry.dossier.profiles and entry.name == "Satya Nadella"


async def test_the_cache_is_lru_bounded() -> None:
    from jarvis.people.cache import MAX_OWNERS

    cache = DossierCache()
    for i in range(MAX_OWNERS):
        await cache.put(f"u{i}", "A B", "", None)
    await cache.get("u0")  # touch: u1 is now the oldest
    await cache.put("new", "A B", "", None)

    assert await cache.get("u0") is not None and await cache.get("u1") is None


def test_satya_fixture_has_a_wiki_hit() -> None:
    assert any("wikipedia" in h.url for h in SATYA_HITS)


# ---- the web adapter -----------------------------------------------------------------------


class Provider:
    name = "fake"

    def __init__(self, page: SearchPage | Exception) -> None:
        self.page = page

    async def search(self, query, *, max_results, topic, days):
        if isinstance(self.page, Exception):
            raise self.page
        return self.page

    async def extract(self, url):
        return PageText(url)

    async def aclose(self) -> None:
        return None


def web(page: SearchPage | Exception, cap: int = 5):
    now = datetime(2026, 11, 15, tzinfo=UTC)
    allowance = WebAllowance(MemoryDocs(), now=lambda: now, cap=cap)
    return WebService(Provider(page), allowance), allowance


async def test_web_searcher_returns_hits_and_charges_a_credit() -> None:
    svc, allowance = web(SearchPage(hits=SATYA_HITS[:2]))

    hits = await WebSearcher(svc).search("Satya Nadella", max_results=5)

    assert len(hits) == 2
    assert (await allowance.usage()).credits == 1


async def test_web_searcher_refunds_when_the_vendor_fails() -> None:
    svc, allowance = web(RuntimeError("boom"))

    with pytest.raises(SearchFailed):
        await WebSearcher(svc).search("Satya Nadella", max_results=5)

    assert (await allowance.usage()).credits == 0


async def test_a_failing_refund_does_not_mask_the_original_error() -> None:
    svc, allowance = web(RuntimeError("boom"))

    async def broken_refund(_r: object) -> None:
        raise OSError("refund store down")

    allowance.refund = broken_refund  # type: ignore[method-assign]

    with pytest.raises(SearchFailed):
        await WebSearcher(svc).search("Satya Nadella", max_results=5)


async def test_web_searcher_latches_when_credits_are_exhausted() -> None:
    svc, allowance = web(CreditsExhausted("gone"))

    with pytest.raises(SearchFailed):
        await WebSearcher(svc).search("Satya Nadella", max_results=5)

    assert (await allowance.usage()).left <= 0


async def test_web_searcher_stops_when_the_month_is_used_up() -> None:
    svc, _ = web(SearchPage(hits=SATYA_HITS[:1]), cap=0)

    with pytest.raises(SearchFailed):
        await WebSearcher(svc).search("Satya Nadella", max_results=5)

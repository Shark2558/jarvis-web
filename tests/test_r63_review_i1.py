# tests/test_r63_review_i1.py -- R6.3's combined review of I1 (docs/plans/r6-3-integration/
# REVIEW-I1.md): one test (or a few) a finding, each written red before its fix. No model is called.
from __future__ import annotations

import re
import threading
from typing import Any

import pytest
from book_app_fakes import OWNER, book, book_app, open_book, owner_uid, register_passkey, sign_in
from r63_fake_brains import GOOD_DRAFT, Step, claude_like, gemini_like, registry
from r63_fakes import FIXTURE_FACTS, FIXTURE_FILES, RELEASE
from r63_fakes_b import seal_r6, service

from jarvis.buildbook.gen.scrub import default_scrubber
from jarvis.buildbook.gen.snapshot import _zip
from jarvis.buildbook.ports import VaultTampered
from jarvis.buildbook.writer import carry, packs, prompts
from jarvis.buildbook.writer.caps import CapRefused
from jarvis.buildbook.writer.model import Run
from jarvis.buildbook.writer.texts import REFUSED
from jarvis.config import Settings
from jarvis.llm.router import ModelTier
from jarvis.llm.write import WriterUnavailable, write_text

C01 = FIXTURE_FACTS.page("pg_card_c01")
assert C01 is not None
GUIDE_TEXT = "# Guide\n\n#### C01 · The demo\nThe demo's card, as the guide words it.\n"


def _snapshot(rid: str, files: dict[str, str]) -> bytes:
    """A source.zip exactly as R6's snapshot zips it: every file under `JARVIS-source-<id>/`."""
    return _zip(f"JARVIS-source-{rid}", {k: v.encode("utf-8") for k, v in files.items()})


# ---- H-1, H-2: R6's snapshot keeps every file under one root folder ------------------------------
def test_h1_the_packs_read_the_code_under_the_snapshots_root_folder() -> None:
    never = {
        ".claude/agents/reviewer.md": "the agents' own rules",
        "tests/test_demo.py": "def test_x():\n    pass\n",
        "evals/demo.py": "CASES = []\n",
        "docs/.claude/notes.md": "a nested agents folder",
        ".env.local": "TOKEN=x\n",
    }
    tree = packs.read_source(_snapshot("abc1234", {**FIXTURE_FILES, **never}))
    assert set(FIXTURE_FILES) <= set(tree)  # the repository's own paths, as the pages cite them
    assert not set(never) & set(tree)  # the never-read rule holds under the root too
    assert not any(name.startswith("JARVIS-source-") for name in tree)
    pack = packs.build(C01, FIXTURE_FACTS, tree, default_scrubber())
    assert "code:src/jarvis/demo/router.py" in pack.body  # the cited file's signatures are read


def test_h2_the_free_carry_sees_a_changed_file_and_the_cards_across_two_releases() -> None:
    router = "src/jarvis/demo/router.py"
    base = {**FIXTURE_FILES, packs.GUIDE: GUIDE_TEXT}
    old = carry.tree_of(_snapshot("aaaaaaa", base))
    new = carry.tree_of(_snapshot("bbbbbbb", {**base, router: base[router] + "\n# changed\n"}))
    assert old.cards and old.cards == new.cards  # the guide is found in both
    assert old.files[router] != new.files[router]
    assert carry.is_changed(C01, old, new)
    same = carry.tree_of(_snapshot("ccccccc", base))
    assert not carry.is_changed(C01, old, same)  # only the root differs: nothing changed


# ---- M-4: building the packs never stops the event loop, and is not done twice -----------------
def _mentioned_by_regex(names: list[str], texts: list[str]) -> list[str]:
    """The rule as B wrote it: one regex a name (the reference for the faster form)."""
    joined = "\n".join(texts)
    return [n for n in names if re.search(rf"(?<![\w]){re.escape(n)}(?![\w])", joined)]


def test_m4_mentioned_finds_exactly_what_one_regex_a_name_finds() -> None:
    texts = ["demo_limit = Field(1)", "x.demo_notes, 1demo_x, café_ok", "book-pages and jarvis.x"]
    names = ["demo_limit", "demo_notes", "demo_x", "café_ok", "café", "book-pages", "jarvis.x",
             "missing", "demo", "x"]  # fmt: skip
    assert packs._mentioned(names, texts) == _mentioned_by_regex(names, texts)


async def test_m4_the_estimate_builds_its_packs_off_the_event_loop() -> None:
    built = service()
    svc, uid = built.service, built.job._ctx.uid
    seen: list[str] = []
    turn = svc.est.first_turn

    def first_turn(*args: Any) -> Any:
        seen.append(threading.current_thread().name)
        return turn(*args)

    svc.est.first_turn = first_turn
    await svc.estimate(uid, "trial")
    main = threading.main_thread().name
    assert seen and main not in seen  # every pack was built in a worker thread


def test_m4_a_block_is_scrubbed_once_a_release_however_many_pages_quote_it() -> None:
    calls: list[str] = []
    scrub = default_scrubber()

    class Counting:
        def clean(self, text: str) -> str:
            calls.append(text)
            return scrub.clean(text)

    cache: dict[str, str] = {}
    tree = {**FIXTURE_FILES}
    first = packs.build(C01, FIXTURE_FACTS, tree, Counting(), cache=cache)  # type: ignore[arg-type]
    n = len(calls)
    again = packs.build(C01, FIXTURE_FACTS, tree, Counting(), cache=cache)  # type: ignore[arg-type]
    assert again == first and len(calls) == n  # the second page's blocks came from the cache


# ---- M-1: a store, vault or ledger failure is a refusal in words, never a bare 500 --------------
async def test_m1_the_routes_answer_unavailable_in_words_when_the_vault_or_ledger_breaks(
    settings: Settings,
) -> None:
    async for app in book_app(settings):
        built = service(
            brains=registry(claude_like(), gemini_like()), uid=owner_uid(OWNER), emails=(OWNER,)
        )
        app.state.book_writer = svc = built.service
        await seal_r6(built)

        async def broken_index(uid: str) -> Any:
            raise VaultTampered("the AI pages failed their check")

        async def broken_ledger(*args: Any) -> float:
            raise CapRefused("unreadable")

        async with sign_in(app) as c:
            auth = await register_passkey(c)
            owner = await open_book(c, auth, "owner")
            svc.vault.index = broken_index
            for url, headers in (("/v1/book/writer", {}), ("/v1/book/pages", book(owner["token"]))):
                r = await c.get(url, headers=headers)
                assert r.status_code == 503 and r.json()["error"] == "unavailable", (url, r.text)
                assert r.headers["cache-control"] == "no-store"
            svc.vault.index = type(svc.vault).index.__get__(svc.vault)
            svc.ledger.run_spent = broken_ledger
            await svc.store.change(built.job._ctx.uid, _a_run)
            r = await c.get("/v1/book/writer")
            assert r.status_code == 503 and r.json()["detail"] == REFUSED["unavailable"]


def _a_run(doc: Any) -> tuple[Any, None]:
    run = Run(kind="trial", release=RELEASE.id, estimate_id="we_" + "0" * 12, total=1)
    return doc.model_copy(update={"run": run}), None


# ---- M-2: a stream that breaks with any error after it started is a cut call (billed) ----------
async def test_m2_a_non_llm_error_mid_stream_is_a_cut_call_and_before_any_text_waits() -> None:
    odd = ValueError("a chunk the provider could not parse")
    spec = claude_like(Step(text=GOOD_DRAFT, chunks=6, fail=odd, fail_after=2))  # type: ignore[arg-type]
    got = await write_text(
        registry(spec).router_for("anthropic"), tier=ModelTier.BALANCED, system="SYSTEM",
        system_dynamic=None, messages=[prompts.message("user", "Write it.")], max_tokens=4000,
        timeout_s=5.0,
    )  # fmt: skip
    assert not got.complete and got.text and GOOD_DRAFT.startswith(got.text)
    assert got.cost_usd > 0  # settled at its usage, never released at Rs 0
    spec = claude_like(Step(fail=odd))  # type: ignore[arg-type]
    with pytest.raises(WriterUnavailable) as err:
        await write_text(
            registry(spec).router_for("anthropic"), tier=ModelTier.BALANCED, system="SYSTEM",
            system_dynamic=None, messages=[prompts.message("user", "Write it.")], max_tokens=4000,
            timeout_s=5.0,
        )  # fmt: skip
    assert err.value.why == "no_answer"

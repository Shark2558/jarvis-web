# tests/test_r11_b_breach.py -- R11 Part B item 6 (docs/plans/r11-free-helpers.md D14): breach-
# notice watching, not a paid HIBP key. Written before helpers/house/breach.py: the daily
# `breach_watch` reads his Gmail only when he switched it on and his Email and "Weather and alerts"
# rows allow it (fail closed); only mail from a fixed sender whose domain passes Gmail's own
# DKIM/DMARC alignment counts; one fixed `breach_notice` a notice, never twice, retried when no
# channel took it; the subject never stored or sent; a kind-only audit line; old claims swept.
from __future__ import annotations

from datetime import timedelta

from r11_fakes import NOON_IST, UID
from r11_fakes_b import FakeGmail, Rules, gmail_with, house_ctx

from jarvis.helpers.house import breach
from jarvis.helpers.house.store import HouseStore, OutsideStore
from jarvis.notify.ports import Delivery

NOTICE = (
    "A breach notice from Have I Been Pwned arrived. Open it in Gmail and change that password, "
    "Sir."
)


async def _setup(
    gmail: FakeGmail | None = None, *, on: bool = True, **over: object
) -> tuple[object, ...]:
    gmail = gmail if gmail is not None else gmail_with("b_gmail_hibp.json")
    hc, notifier, docs, clock = house_ctx(google=gmail, **over)  # type: ignore[arg-type]
    outside = OutsideStore(docs, hc.keyring, prefix=hc.prefix)
    if hc.keyring is not None and on:
        await outside.change(UID, lambda o: o.model_copy(update={"breach_on": True}))
    store = HouseStore(docs, prefix=hc.prefix)
    return hc, notifier, docs, clock, outside, store, breach.BreachJob(hc, outside, store), gmail


def test_the_gmail_query_names_the_fixed_senders_only() -> None:
    q = breach.gmail_query(2)
    assert q == "from:(haveibeenpwned.com OR monitor.mozilla.org) newer_than:2d"


async def test_an_aligned_hibp_notice_sends_one_fixed_notice_and_a_kind_only_audit() -> None:
    hc, notifier, docs, _, outside, _, job, gmail = await _setup()
    got = await job.run(())
    assert got["sent"] == 1
    assert notifier.calls == [(UID, "breach_notice", NOTICE, None)]
    (_, url, params), *_ = gmail.calls
    assert url.endswith("/messages") and params["q"] == breach.gmail_query(2)
    assert all(c[2].get("format") in (None, "metadata") for c in gmail.calls)
    tail = (await hc.audit.tail(5)).entries
    assert [(e.agent, e.tool, e.outcome, e.detail) for e in tail] == [
        ("helpers", "gmail_search", "executed", "breach_watch")  # I1: the governed path's line
    ]
    assert "pwned in the Example" not in str(docs._data)  # noqa: SLF001 - no subject kept
    state = (await outside.read(UID)).breach
    assert state.notices == 1 and state.last_day == "2026-11-10"


async def test_an_unaligned_sender_or_a_verify_mail_is_ignored() -> None:
    gmail = gmail_with("b_gmail_spoofed.json", "b_gmail_verify.json")
    _, notifier, docs, _, _, _, job, _ = await _setup(gmail)
    got = await job.run(())
    assert got["sent"] == 0 and notifier.calls == []
    assert "attacker" not in str(docs._data)  # noqa: SLF001


async def test_a_notice_is_told_once_and_again_when_no_channel_took_it() -> None:
    _, notifier, _, clock, _, store, job, _ = await _setup()
    notifier.delivery = Delivery(action="ring", reason="test")
    assert (await job.run(()))["retry"] == 1
    notifier.delivery = Delivery(action="ring", reason="test", telegram=True)
    clock.at += timedelta(days=1)
    assert (await job.run(()))["sent"] == 1
    clock.at += timedelta(days=1)
    assert (await job.run(()))["sent"] == 0
    assert len(notifier.calls) == 2


async def test_off_until_he_switches_it_on_and_his_rows_obeyed() -> None:
    for kwargs in (
        {"on": False},
        {"rules": Rules(("gmail_*",))},  # Email: Never
        {"rules": Rules(("breach_*",))},  # Weather and alerts: Never
        {"rules": Rules(broken=True)},  # can't tell: no read
        {"keyring_on": False},
    ):
        gmail = gmail_with("b_gmail_hibp.json")
        _, notifier, _, _, _, _, job, _ = await _setup(gmail, **kwargs)  # type: ignore[arg-type]
        await job.run(())
        assert gmail.calls == [] and notifier.calls == [], kwargs


async def test_not_linked_or_gmail_down_is_counted_not_failed() -> None:
    hc, _, _, _, outside, store, _, _ = await _setup()
    import dataclasses

    unlinked = breach.BreachJob(dataclasses.replace(hc, google=None), outside, store)
    assert (await unlinked.run(()))["not_linked"] == 1
    down = FakeGmail(down=True)
    _, _, _, _, _, _, job, _ = await _setup(down)
    got = await job.run(())
    assert got["unreachable"] == 1 and got["failed"] == 0


async def test_the_daily_job_sweeps_claims_older_than_30_days() -> None:
    _, _, _, clock, _, store, job, _ = await _setup(on=False)
    await store.claim(UID, "chore", "old", NOON_IST - timedelta(days=31))
    await store.claim(UID, "chore", "new", NOON_IST)
    assert (await job.run(()))["swept"] == 1
    assert len(await store.claims(UID)) == 1


async def test_one_unreadable_message_never_hides_the_others() -> None:
    gmail = gmail_with("b_gmail_hibp.json")
    gmail.messages = {"broken01": {}, **gmail.messages}
    real = gmail.request

    async def flaky(user_id: str, method: str, url: str, **kw: object) -> object:
        if url.endswith("/broken01"):
            from jarvis.integrations.google import GoogleAPIError

            raise GoogleAPIError("that one is gone")
        return await real(user_id, method, url, **kw)  # type: ignore[arg-type]

    gmail.request = flaky  # type: ignore[method-assign]
    _, notifier, _, _, _, _, job, _ = await _setup(gmail)
    assert (await job.run(()))["sent"] == 1 and len(notifier.calls) == 1


# ---- security review L1, L2 ----------------------------------------------------------------------
HIBP = "Have I Been Pwned <noreply@haveibeenpwned.com>"
GOOD_AR = (
    "mx.google.com; dkim=pass header.i=@haveibeenpwned.com header.s=s; spf=pass; "
    "dmarc=pass (p=REJECT) header.from=haveibeenpwned.com"
)


def _mail(frm: str, *results: str, subject: str = "You've been pwned: breach notice") -> dict:  # type: ignore[type-arg]
    headers = [{"name": "Authentication-Results", "value": r} for r in results]
    headers += [{"name": "From", "value": frm}, {"name": "Subject", "value": subject}]
    return {"payload": {"headers": headers}}


def test_only_gmails_own_first_authentication_results_counts() -> None:
    assert breach.notice_from(_mail(HIBP, GOOD_AR)) is not None
    assert breach.notice_from(_mail(HIBP, "MX.Google.com; dkim=pass header.d=haveibeenpwned.com"))
    for forged in (
        "evil.test; dkim=pass header.d=haveibeenpwned.com",  # another server's verdict
        "mx.google.com.evil.test; dkim=pass header.d=haveibeenpwned.com",
        "x mx.google.com; dkim=pass header.d=haveibeenpwned.com",
    ):
        assert breach.notice_from(_mail(HIBP, forged)) is None
    gmail_failed = "mx.google.com; dkim=fail header.d=haveibeenpwned.com"
    assert breach.notice_from(_mail(HIBP, gmail_failed, GOOD_AR)) is None  # a second one after


def test_the_fixed_senders_are_exact_hosts_no_subdomains() -> None:
    sub_ar = "mx.google.com; dkim=pass header.d=a.monitor.mozilla.org"
    assert (
        breach.notice_from(_mail("anyone@a.monitor.mozilla.org", sub_ar, subject="breach")) is None
    )
    hibp_sub = "mx.google.com; dkim=pass header.d=x.haveibeenpwned.com"
    assert breach.notice_from(_mail("noreply@x.haveibeenpwned.com", hibp_sub)) is None
    assert breach.notice_from(_mail("support@haveibeenpwned.com", GOOD_AR)) is None
    monitor_ar = "mx.google.com; dkim=pass header.d=monitor.mozilla.org"
    got = breach.notice_from(_mail("alerts@monitor.mozilla.org", monitor_ar, subject="New breach"))
    assert got is not None and got.key == "monitor"

# src/jarvis/api/r18_wiring.py
"""R18 on the app: the I1 join of "Calls from your laptop" (docs/plans/r18-calls.md;
docs/plans/r18-integration/I1-NOTES.md). The adapters between the parts are
`jarvis.calls.join` and `jarvis.calls.join_speech`; this module only builds them on `app.state`.

- `wire_r18(app, s, docs, audit)` (after R13, BEFORE the gateway: its tools): the store (numbers
  sealed with the `calls` key), A1's cards, approvals, limits and records, A2's hub with one set of
  engine parts per call (B's speech and its meter, D's phone link, the desk the hub holds), A2's
  desk door and sockets (`calls_desk_door`, `calls_sockets`), C's kit (`calls_desk_kit`, only with
  an https public address), D's late ports on the phone part's `PhoneCalls`, and the language
  check job. Nothing is built when calls are off, without the token key (numbers and records are
  sealed) or without a private brain: the routes then answer 501 (calls off: 503).
- `r18_tools(parts)`: `calls_place` (R3) and `calls_answer_mode`, for `build_gateway(r18=...)`.
- `finish_r18(app)` (after the gateway, from `tick_wiring.finish_wiring`): A1's `CardsApi` on
  `app.state.calls_api` (its approvals run the gateway's `calls_place` card), the booking calendar
  and the phone's Approve / Decline. No gateway (tools off): no `calls_api` (501), no call.
- `r18_tick_jobs(app)`: the 30-day retention job (`calls_retention`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

import httpx
from fastapi import FastAPI

from jarvis.api.calldesk_kit import install_calldesk_kit
from jarvis.api.calls_console import ConsoleCardsApi, ready_cards
from jarvis.api.calls_ws import CallSockets
from jarvis.calls.answering import AnsweringPolicy, GoogleContactBook
from jarvis.calls.approvals import CallsService
from jarvis.calls.booking import BookingCalendar
from jarvis.calls.brain import CallBrain, FixedLines
from jarvis.calls.captions import Captioner
from jarvis.calls.cards import (
    BillingAllowance,
    CardBuilder,
    CardParser,
    Estimator,
    GoogleContactNumbers,
    RouterFastText,
    token_rate,
)
from jarvis.calls.engine_ports import EngineDeps
from jarvis.calls.hub import BillingSpend, CallHub, DeskDoorService, DeskProxy, DeskStore
from jarvis.calls.join import (
    AnsweringRules,
    BookingSlots,
    EngineStarter,
    GrantGate,
    HubAnswering,
    HubPhoneSink,
    NoPhone,
    PhoneApprovals,
    PhoneCardDesk,
    PushNotice,
    VaultRecords,
    status_view,
)
from jarvis.calls.join_speech import (
    CallSpeech,
    CallSpend,
    CallTally,
    LanguageCheckJob,
    SpeechChoices,
)
from jarvis.calls.langcheck.fleurs import FleursClips
from jarvis.calls.langcheck.runner import LanguageCheck
from jarvis.calls.langcheck.sentences import CheckSentences
from jarvis.calls.limits import BillingBudget, Limits
from jarvis.calls.models import CallSettings, SpeechOption
from jarvis.calls.ports import CallStore
from jarvis.calls.prices import SpeechPrice, speech_prices
from jarvis.calls.records import RecordKeeper, SealedBlobs
from jarvis.calls.retention import CallRetentionJob
from jarvis.calls.settings import defaults
from jarvis.calls.speech.build import SpeechOptions, build_speech
from jarvis.calls.speech.meter import SpeechMeter
from jarvis.calls.speech.rest import BATCH, IN_CALL
from jarvis.calls.speech.translate import BrainTranslator
from jarvis.calls.store import DocCallStore, KeyringSealer
from jarvis.calls.summary import Summarizer
from jarvis.calls.templates import is_template
from jarvis.calls.tools import calls_tools
from jarvis.config import Settings
from jarvis.contacts.client import ContactsClient
from jarvis.keyring import Keyring
from jarvis.llm.router import ModelTier
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs
from jarvis.tools.audit import AuditLog, AuditTrail
from jarvis.tools.base import Tool
from jarvis.vault.crypto import VaultCrypto

log = get_logger(__name__)

SPEECH_TIMEOUT_S = 30.0
NO_KEY = "R18 calls are not wired: they need JARVIS_TOKEN_KEY (numbers and records are sealed)."


@dataclass
class R18Parts:
    """What `wire_r18` built (`app.state.r18_parts`)."""

    store: CallStore
    service: CallsService
    builder: CardBuilder
    keeper: RecordKeeper
    records: VaultRecords
    hub: CallHub
    choices: SpeechChoices
    check: LanguageCheckJob
    answering: AnsweringPolicy
    http: httpx.AsyncClient
    phone: Any  # jarvis.phone.calls.PhoneCalls, or None without the phone part
    tools: tuple[Tool, ...]

    async def aclose(self) -> None:
        await self.check.aclose()
        await self.hub.aclose()
        await self.http.aclose()


class _LatePasskeys:
    """A1's `PasskeyPolicy` on the permissions service (built after this, with the gateway)."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    async def passkey_required(self, uid: str) -> bool:
        perms = getattr(self._app.state, "permissions", None)
        if perms is None:
            return False  # no permissions service: a never-called number is refused (A1)
        return bool(await perms.passkey_required(uid))


def _google_speech(app: FastAPI) -> tuple[Any, httpx.AsyncClient | None]:
    engines = getattr(getattr(app.state, "voice", None), "engines", None)
    if engines is None:
        return None, None
    return engines.tokens, engines.http


def _phone_calls(app: FastAPI) -> Any:
    parts = getattr(app.state, "r7_parts", None) or {}
    phone = parts.get("phone")
    return None if phone is None else phone.services.get("phone_calls")


def _owner_sarvam(store: CallStore, uid: str) -> Callable[[], Awaitable[bool]]:
    async def yes() -> bool:
        return (await store.settings(uid)).sarvam_on

    return yes


class _SpeechFactory:
    """B's speech options for one owner (a call's meter, or the language check's)."""

    def __init__(self, app: FastAPI, s: Settings, store: CallStore, http: httpx.AsyncClient):
        self._app, self._s, self._store, self.http = app, s, store, http

    def options(self, meter: SpeechMeter, *, batch: bool = False) -> SpeechOptions:
        tokens, google_http = _google_speech(self._app)
        return build_speech(
            self._s,
            meter,
            http=self.http,
            google_tokens=tokens,
            google_http=google_http,
            sarvam_on=_owner_sarvam(self._store, meter.uid),
            policy=BATCH if batch else IN_CALL,
        )


def _prices(s: Settings) -> Callable[[float], dict[SpeechOption, SpeechPrice]]:
    def table(rate: float) -> dict[SpeechOption, SpeechPrice]:
        return speech_prices(s, rate)

    return table


def _deps_for(
    app: FastAPI,
    base: EngineDeps,
    speech: _SpeechFactory,
    choices: SpeechChoices,
    spend: BillingSpend,
    s: Settings,
) -> Callable[[str, DeskProxy], EngineDeps]:
    billing = app.state.billing

    async def rate() -> float:
        return float((await billing.fx.rate()).inr_per_usd)

    def make(uid: str, desk: DeskProxy) -> EngineDeps:
        tally = CallTally()
        options = speech.options(SpeechMeter(billing, uid, on_cost=tally))
        chosen, balanced, languages = choices.snapshot(uid)
        phone_calls = _phone_calls(app)
        if phone_calls is not None:
            from jarvis.phone.calls import OwnerPhoneLink

            phone: Any = OwnerPhoneLink(phone_calls, uid)
        else:
            phone = NoPhone()
        return replace(
            base,
            desk=desk,
            phone=phone,
            speech=CallSpeech(options, chosen, balanced, languages),
            spend=CallSpend(spend, tally, _prices(s), rate),
        )

    return make


def _check_job(
    app: FastAPI, s: Settings, docs: Docs, store: CallStore, speech: _SpeechFactory
) -> LanguageCheckJob:
    billing, brains = app.state.billing, app.state.brains

    async def make(uid: str, settings: CallSettings) -> LanguageCheck:
        meter = SpeechMeter(billing, uid)
        rate = float((await billing.fx.rate()).inr_per_usd)
        translator = BrainTranslator(brains, billing, uid)
        return LanguageCheck(
            speech=speech.options(meter, batch=True),
            store=store,
            clips=FleursClips(speech.http),
            sentences=CheckSentences(docs, prefix=s.firestore_prefix, translator=translator),
            meter=meter,
            prices=speech_prices(s, rate),
            sarvam_on=settings.sarvam_on,
        )

    return LanguageCheckJob(make, store)


def _cards(app: FastAPI, s: Settings, store: CallStore, brain: CallBrain) -> CardBuilder:
    billing = app.state.billing
    rate = billing.fx.peek().inr_per_usd
    prices = speech_prices(s, rate)
    fast = brain.spec.tiers.get(ModelTier.FAST, "")
    estimator = Estimator(
        prices, token_rate(fast, rate), allowance=BillingAllowance(billing, prices)
    )
    google = getattr(app.state, "google", None)
    contacts = GoogleContactNumbers(ContactsClient(google)) if google is not None else None
    return CardBuilder(store, estimator, contacts=contacts, is_template=is_template)


async def wire_r18(app: FastAPI, s: Settings, docs: Docs | None, audit: AuditTrail | None) -> None:
    """Every R18 part on `app.state` (see the module docstring), or none."""
    st = app.state
    st.r18_parts = None
    if not s.calls_enabled:
        return
    ring = Keyring.from_settings(s)
    if ring is None or docs is None:
        log.warning(NO_KEY)
        return
    try:
        st.r18_parts = _build(app, s, docs, ring, audit if audit is not None else AuditLog())
    except Exception as exc:  # noqa: BLE001 - one release never stops the app; logged by name
        log.error("R18 calls not wired: setup failed", extra={"error": type(exc).__name__})
        st.r18_parts = None
        return
    install_calldesk_kit(app)


def _build(app: FastAPI, s: Settings, docs: Docs, ring: Keyring, audit: AuditTrail) -> R18Parts:
    st = app.state
    store = DocCallStore(
        docs, prefix=s.firestore_prefix, sealer=KeyringSealer(ring), base=defaults(s)
    )
    brain = CallBrain(st.brains)  # NoPrivateBrain: no calls (never a brain that trains on them)
    builder = _cards(app, s, store, brain)
    limits = Limits(store, budget=BillingBudget(st.billing))
    service = CallsService(store, builder, limits, passkeys=_LatePasskeys(app), audit=audit)
    keeper = RecordKeeper(
        store, SealedBlobs(docs, VaultCrypto(ring), prefix=s.firestore_prefix), audit=audit
    )
    records = VaultRecords(keeper)
    http = httpx.AsyncClient(timeout=SPEECH_TIMEOUT_S, follow_redirects=False)
    speech = _SpeechFactory(app, s, store, http)
    choices = SpeechChoices(store, free=builder.estimator.free_options)  # free first (review)
    base = EngineDeps(
        desk=None,  # type: ignore[arg-type]  # each call's: the hub's DeskProxy
        phone=NoPhone(),
        speech=CallSpeech(SpeechOptions(), {}),
        brain=brain,
        captions=Captioner(st.brains),
        summarizer=Summarizer(st.brains),
        lines=FixedLines(st.brains),
        store=store,
        records=records,
        spend=None,  # type: ignore[arg-type]  # each call's: CallSpend over its own tally
        slots=BookingSlots(),
        notice=PushNotice(lambda: getattr(st, "push", None)),
        audit=audit,
        gate=GrantGate(service),
    )
    google = getattr(st, "google", None)
    book = GoogleContactBook(ContactsClient(google)) if google is not None else None
    answering = AnsweringPolicy(store, book)
    spend = BillingSpend(st.billing, _prices(s), brain.spec)
    hub = CallHub(
        _deps_for(app, base, speech, choices, spend, s), store, answering=HubAnswering(answering)
    )
    service.starter = EngineStarter(hub, choices.refresh)
    desks = DeskStore(docs, ring.cipher("calls"), prefix=s.firestore_prefix)
    st.calls_sockets = CallSockets(hub, desks)
    st.calls_desk_door = DeskDoorService(desks, hub)
    phone = _join_phone(app, hub, service, store, choices)
    return R18Parts(
        store=store,
        service=service,
        builder=builder,
        keeper=keeper,
        records=records,
        hub=hub,
        choices=choices,
        check=_check_job(app, s, docs, store, speech),
        answering=answering,
        http=http,
        phone=phone,
        tools=tuple(calls_tools(service)),
    )


def _join_phone(
    app: FastAPI, hub: CallHub, service: CallsService, store: CallStore, choices: SpeechChoices
) -> Any:
    """D's late ports (INTEGRATION-D.md 3.3); until they are set every dial is refused."""
    phone = _phone_calls(app)
    if phone is None:
        log.info("R18 calls: no phone part (mobile off): calls can't be dialled")
        return None
    phone.approvals = PhoneApprovals(service.grants)
    phone.sink = HubPhoneSink(hub, choices.refresh)
    phone.answering = AnsweringRules(store)
    return phone


def r18_tools(parts: R18Parts | None) -> tuple[Tool, ...]:
    return () if parts is None else parts.tools


def finish_r18(app: FastAPI) -> None:
    """After the gateway: the Calls panel's REST work and the phone's card decisions."""
    st = app.state
    parts: R18Parts | None = getattr(st, "r18_parts", None)
    gw = getattr(st, "gateway", None)
    if parts is None or gw is None:
        return
    s: Settings = st.settings
    audit = gw.audit
    booking = BookingCalendar(gw, parts.store, audit=audit)
    parts.records.booking = booking

    async def status(uid: str) -> dict[str, Any]:
        out = await status_view(uid, hub=parts.hub, store=parts.store, phone=parts.phone)
        return out | {"templates": ready_cards()}  # the console's ready cards

    async def progress(uid: str) -> dict[str, Any]:
        return await parts.check.view()

    api = ConsoleCardsApi(
        store=parts.store,
        builder=parts.builder,
        service=parts.service,
        gateway=gw,
        keeper=parts.keeper,
        booking=booking,
        parser=CardParser(RouterFastText(st.brains, st.billing)),
        passkeys=_LatePasskeys(app),
        audit=audit,
        status=status,
        language_check=parts.check.handle,
        language_score=parts.check.score,
        check_progress=progress,
    )
    api.phone, api.azure_ready = parts.phone, s.azure_speech_key is not None
    st.calls_api = api
    if parts.phone is not None:
        parts.phone.cards = PhoneCardDesk(lambda: getattr(st, "calls_api", None), parts.store)
    log.info("R18 calls wired", extra={"phone": parts.phone is not None, "env": s.env})


def r18_tick_jobs(app: FastAPI) -> tuple[CallRetentionJob, ...]:
    parts: R18Parts | None = getattr(app.state, "r18_parts", None)
    return () if parts is None else (CallRetentionJob(parts.store, parts.keeper),)


__all__ = [
    "R18Parts",
    "finish_r18",
    "r18_tick_jobs",
    "r18_tools",
    "wire_r18",
]

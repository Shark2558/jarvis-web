# src/jarvis/buildbook/gen/flows.py
"""R6 D2: the Workflows section — ten fixed flows, each step a plain label and the code symbol
that does it. `workflows` checks every symbol against the checkout's ASTs (module, top-level
name, a method or class attribute), so a rename fails `--check` instead of leaving the book wrong.

Symbols are written WITHOUT the leading "jarvis." (added when the book is built): this package
then holds no "jarvis.<x>" string, which the D11 import-boundary test would read as an import.
The build book's own flow names the I0 ports for the sealing and the talk-through; the
integrator may point them at B's and C's classes once those land (INTEGRATION-A.md).
"""

from __future__ import annotations

from jarvis.buildbook.gen.code import defines, module_path, tree
from jarvis.buildbook.gen.repo import GenError, Repo
from jarvis.buildbook.model import FLOW_IDS
from jarvis.buildbook.sections import Workflow

Flow = tuple[str, str, tuple[tuple[str, str], ...]]
PREFIX = "jarvis."

FLOWS: tuple[Flow, ...] = (
    ("chat_turn", "One conversation turn", (
        ("The console sends your message", "api.routes:chat"),
        ("The input guard checks its size and shape", "core.guardrails:guard_input"),
        ("The brain loads the conversation", "core.brain:Brain.chat"),
        ("Long-term memory recalls what matters", "recall.service:MemoryService.recall"),
        ("Your monthly limit is checked first", "billing.service:Billing.ensure_allowed"),
        ("The router picks the brain by tier", "llm.router:ModelRouter.complete"),
        ("Every tool call passes the policy gateway", "tools.gateway:Gateway.execute"),
        ("Each call is written to the audit chain", "tools.audit:AuditLog.append"),
        ("The cost is recorded in rupees", "billing.service:Billing.record"),
        ("The reply goes back and learning is queued", "recall.service:MemoryService.after_turn"),
    )),
    ("approval", "Confirm before commit", (
        ("A risky tool call becomes a card", "core.guardrails:PendingAction"),
        ("The card waits in the approval store", "core.guardrails:ApprovalStore.put"),
        ("You approve it in the console or on Telegram", "api.routes:approve"),
        ("An irreversible action needs your passkey",
         "permissions.service:PermissionsService.check_approval"),
        ("The brain checks the card is unchanged", "core.brain:Brain.approve"),
        ("The gateway runs it and audits it", "tools.gateway:Gateway.execute"),
        ("Approve all clears the low-risk cards", "core.approve_all:run"),
    )),
    ("learning", "Learning after a turn", (
        ("The finished turn is handed to memory", "recall.service:MemoryService.after_turn"),
        ("Only your own lines are considered", "recall.learning:pending"),
        ("Sensitive things are never kept", "recall.sensitive:is_sensitive"),
        ("A private brain extracts the facts", "recall.extract:Extractor.run"),
        ("Duplicates merge into one note", "recall.ops:add_fact"),
        ("The memory store keeps them", "recall.store:MemoryStore.mutate"),
        ("A daily sweep catches what was missed", "recall.service:MemoryService.sweep"),
    )),
    ("voice_turn", "A spoken turn", (
        ("The console sends what you said", "api.voice:transcribe"),
        ("The recording is checked", "voice.wav:parse_wav"),
        ("Speech becomes text", "voice.google_cloud:GoogleSTT.recognize"),
        ("The brain answers as for a typed turn", "core.brain:Brain.chat"),
        ("The answer is made speakable", "voice.speakable:speakable"),
        ("The console asks for the voice", "api.voice:speak"),
        ("JARVIS's voice speaks it", "voice.google_cloud:GoogleTTS.synthesize"),
    )),
    ("morning_tick", "The morning tick", (
        ("Cloud Scheduler calls in, with a signed token", "api.scheduler_auth:require_scheduler"),
        ("The tick route starts the round", "api.brief:tick"),
        ("Each owner whose brief is due gets one", "brief.service:BriefService.tick"),
        ("The brief is gathered and written", "brief.service:BriefService.generate"),
        ("Housekeeping jobs ride the same tick", "ticks:run_jobs"),
        ("You are told it is ready", "notify.service:NotifyService.notify"),
    )),
    ("vault_open", "Opening the vault", (
        ("You ask to unlock in the console", "api.vault:unlock"),
        ("Your passkey proves it is you",
         "permissions.service:PermissionsService.check_purpose"),
        ("A short unlock is granted", "vault.unlock:UnlockStore.grant"),
        ("Each file gets a single-use ticket", "vault.unlock:UnlockStore.ticket"),
        ("Its chunks are decrypted with their own key", "vault.crypto:VaultCrypto.open_chunk"),
        ("The file downloads once", "api.vault:download"),
    )),
    ("home_alert", "A home alert", (
        ("The home bridge sends a signed event", "home.webhook:HomeWebhook.receive"),
        ("The signature is checked", "home.signing:verify"),
        ("A camera event becomes an alert", "camera.events:CameraEvents.handle"),
        ("One policy decides: ring, hold or stay silent", "notify.policy:decide"),
        ("The alert goes out", "notify.service:NotifyService.notify"),
        ("Telegram delivers it", "telegram.alerts:TelegramAlerts.send"),
        ("Your browsers get a notification", "webpush.service:PushService.send"),
    )),
    ("systems_check", "The systems check", (
        ("The watchdog wakes every five minutes", "home.watchdog:Watchdog.run"),
        ("The health job runs the probes", "health.tick:HealthTickJob.run"),
        ("Each probe checks one system", "health.service:HealthService.check"),
        ("The results roll up into one status", "health.report:rollup"),
        ("A fixed-template briefing is written", "health.briefing:compose_briefing"),
        ("Vitals watch keys, quotas and bills", "vitals.job:VitalsJob.run"),
    )),
    ("no_ai", "No-AI mode", (
        ("You switch the brain off", "offline.mode:BrainMode.set"),
        ("The brain sees no-AI mode is on", "offline.no_ai:NoAIRunner.active"),
        ("Fixed rules match your request", "offline.rules:NoAIRoute"),
        ("The tool still runs through the gateway", "offline.no_ai:run_no_ai"),
        ("The reply is a fixed template", "offline.no_ai:NoAIRunner.reply"),
    )),
    ("build_book", "The build book", (
        ("Fixed code reads the code and the plans", "buildbook.gen.write:build"),
        ("Personal data is scrubbed out", "buildbook.gen.scrub:Scrubber.clean"),
        ("The code snapshot is scanned for secrets", "buildbook.gen.snapshot:secret_hits"),
        ("The release ships with the server", "buildbook.release:ReleaseSource.current"),
        ("The book and the code are sealed in the vault", "buildbook.sealer:BookSealer.ensure"),
        ("Opening it takes your passkey",
         "permissions.service:PermissionsService.check_purpose"),
        ("A guest show locks your consoles", "api.book_lock:ShowLockMiddleware"),
        ("Questions get a lane with no tools", "buildbook.talk:BookTalk.ask"),
        ("The closing credits you", "buildbook.lines:closing"),
        ("The session is deleted and you are told", "buildbook.service:BookService.close"),
    )),
)  # fmt: skip


def resolve(repo: Repo, symbol: str) -> bool:
    """`mod[:Name[.attr]]` (no "jarvis." prefix) names something the checkout defines."""
    mod, _, rest = symbol.partition(":")
    module = tree(repo, module_path(repo, mod))
    if module is None:
        return False
    name, _, attr = rest.partition(".")
    return defines(module, name or None, attr or None)


def _check_ids(flows: tuple[Flow, ...]) -> None:
    ids = [fid for fid, _, _ in flows]
    twice = sorted({i for i in ids if ids.count(i) > 1})
    if twice:
        raise GenError(f"a flow is listed twice: {', '.join(twice)}")
    missing = [i for i in FLOW_IDS if i not in ids]
    if missing:
        raise GenError(f"the book needs every flow; missing: {', '.join(missing)}")


def workflows(repo: Repo, flows: tuple[Flow, ...] = FLOWS) -> tuple[Workflow, ...]:
    _check_ids(flows)
    by_id = {fid: (title, steps) for fid, title, steps in flows}
    out = []
    for fid in FLOW_IDS:
        title, steps = by_id[fid]
        for n, (_, symbol) in enumerate(steps, start=1):
            if not resolve(repo, symbol):
                raise GenError(
                    f"flow {fid} step {n} names {PREFIX}{symbol}, which is not in the code: "
                    "update buildbook/gen/flows.py"
                )
        out.append(
            Workflow.model_validate(
                {
                    "id": fid,
                    "title": title,
                    "steps": [{"label": lb, "symbol": PREFIX + sym} for lb, sym in steps],
                }
            )
        )
    return tuple(out)


__all__ = ["FLOWS", "Flow", "resolve", "workflows"]

# evals/r14/needles.py
"""R14 eval, I1's suite (`needles`, BUILT; the integrated security review's M5): nothing private
is written down where it must not be.

`needles_day.day()` runs one simulated day of all four parts on the fakes with nine classes of
needles planted (needles_fakes.py): vault plaintext (a title, a file's bytes, opened by the
drill), the canary's random value, the keyring secret and the full MAC behind `fp`, an exception
text raised from a tick job, Google's admin calls, a notifier, a model provider and a ledger
write, prompt words (persona, his message, a tool result, a memory note, a mail subject, a
parcel merchant), a service request's words and a phone number it must refuse, his e-mail
address and phone digits, a code-shaped logger name, and a backup name carrying a project id.
Each needle is searched raw, lower-cased, URL-encoded, hex and base64 in four sinks: every write
to an R14 document (backup, self-health, ledger), every log record at every level, the audit
detail of `vitals_drill_start`, `vitals_backups`, `skills_open` and `maint_service_request`, and
what he is told (alerts, Vitals items, the four status routes, Telegram's drill card).

Rules beside "nowhere": Google's backup name only in `backup_status/current.newest_name` and,
while a drill runs, in its own `backup_drill/current.run` (`backup`, `operation`: it needs them
between ticks, and they are cleared when it ends; never logged, audited, told or routed); logger
names are code (B's errors document keeps at most 50, and no logger name is built at run time);
only the hashed owner id `u_<16 hex>` appears; the No-AI reply quoting a subject reaches a
returning model fenced (M3). A day that did not really run (no passed drill, no ledger, no
alert...) fails `day_ran`: this suite never reports green without running.

Positive controls, one per sink: a probe planted in that sink is seen in all five forms.
Negative control: the ledger stores the persona, the errors handler stores the message, the
drill log stores the exception's text; exactly the three document cases must fail.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import quote, quote_plus

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import needles_day as nd  # noqa: E402
import needles_fakes as nf  # noqa: E402
from r14_fakes_a import PREFIX as P  # noqa: E402
from r14_fakes_a import ROOT_KEY, ring  # noqa: E402

from jarvis.backup import log as drill_log  # noqa: E402
from jarvis.backup.canary import FINGERPRINT_DATA, PURPOSE  # noqa: E402
from jarvis.backup.names import SHOW, START  # noqa: E402
from jarvis.billing.ledger import TokenLedgerStore  # noqa: E402
from jarvis.hardening.ports import COLLECTIONS  # noqa: E402
from jarvis.selfwatch.errors import MAX_NAMES, ErrorCounter  # noqa: E402
from jarvis.storage.docs import MemoryDocs, Set  # noqa: E402
from jarvis.tools import AuditLog  # noqa: E402
from jarvis.tools.external import FENCE_PREFIX  # noqa: E402

PART = "needles"
BUILT = True
AUDITED = frozenset({START, SHOW, "skills_open", "maint_service_request"})
DOC_SINKS = {
    "backup": "documents_backup",
    "selfwatch": "documents_selfwatch",
    "skills": "documents_ledger",
}
SINKS = (*DOC_SINKS.values(), "logs", "audit", "told", "routes", "telegram")
CONTROL_FAILS = tuple(f"{PART}:{c}" for c in DOC_SINKS.values())
STATUS_DOC = f"{P}backup_status/current"
DRILL_DOC = f"{P}backup_drill/current"
RUN_NAMES = ("backup", "operation")  # the running drill's pointers, cleared when it ends
_STD = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}
OWNER_FACING = frozenset({"told", "routes", "telegram"})  # he is addressed by his honorific


class Needle(NamedTuple):  # not a dataclass: run.py loads this file outside sys.modules
    kind: str
    value: str | bytes
    allowed: frozenset[str] = frozenset()


NEEDLES: tuple[Needle, ...] = (
    Needle("vault_title", nf.VAULT_TITLE),
    Needle("vault_bytes", nf.VAULT_BYTES),
    Needle("canary_nonce", nf.NONCE),
    Needle("keyring_secret", ROOT_KEY),
    Needle("full_mac", ring().mac(PURPOSE, FINGERPRINT_DATA)),
    Needle("exception_text", nf.EXC),
    Needle("exception_project", "exc-proj-q4"),
    Needle("exception_key", "NEEDLEKEY"),
    Needle("persona", nf.PERSONA, OWNER_FACING),
    Needle("owner_words", nf.OWNER_WORD),
    Needle("tool_result", nf.TOOL_WORD),
    Needle("memory_note", nf.MEMORY_WORD),
    Needle("mail_subject", "Glimmerfax"),
    Needle("parcel_merchant", nf.MERCHANT),
    Needle("service_problem", "Wobblethorn"),
    Needle("service_time", "Plinkerton"),
    Needle("digit_run", nf.DIGITS),
    Needle("owner_email", nf.OWNER_EMAIL),
    Needle("owner_phone", nf.PHONE),
    Needle("logger_name", "needleql", frozenset({"documents_selfwatch"})),
    Needle("backup_project", nf.PROJECT_WORD),
)


def forms(value: str | bytes) -> tuple[str, ...]:
    """The value raw, lower-cased, URL-encoded, hex and base64 (bytes: hex and base64)."""
    raw = value.encode() if isinstance(value, str) else value
    b64 = base64.b64encode(raw).decode()
    out = [
        raw.hex(),
        raw.hex().upper(),
        b64,
        b64.rstrip("="),
        base64.urlsafe_b64encode(raw).decode(),
    ]
    if isinstance(value, str):
        out = [value, value.lower(), quote(value), quote_plus(value), *out]
    return tuple(dict.fromkeys(out))


def seen(value: str | bytes, text: str) -> list[str]:
    """Which of the value's forms are in `text` (a lower-cased form also in lower-cased text)."""
    low = text.lower()
    return [f for f in forms(value) if f in text or (f == f.lower() and f in low)]


# ---- the sinks as text ------------------------------------------------------------------------


def _collection_part() -> dict[str, str]:
    return {f"{P}{c}": part for part, cols in COLLECTIONS.items() for c in cols}


def _named(path: str, data: dict[str, Any], names: list[str]) -> dict[str, Any]:
    """The document without the fields that may hold Google's resource names (the status's
    `newest_name`; a running drill's `run.backup` and `run.operation`), which go to `names`."""
    body = dict(data)
    if path == STATUS_DOC and "newest_name" in body:
        names.append(str(body.pop("newest_name")))
    run = body.get("run")
    if path == DRILL_DOC and isinstance(run, dict):
        names += [str(run[k]) for k in RUN_NAMES if run.get(k)]
        body["run"] = {k: v for k, v in run.items() if k not in RUN_NAMES}
    return body


def documents(stores: list[MemoryDocs]) -> tuple[dict[str, list[str]], list[str]]:
    """Every write to an R14 collection, by part (`_named`'s fields taken out), and the names."""
    parts, out, names = _collection_part(), {s: [] for s in DOC_SINKS.values()}, []
    for store in stores:
        for op in store.log:
            part = parts.get(op.path.split("/", 1)[0])
            data = getattr(op, "data", None)
            if part is None or not isinstance(data, dict):
                continue
            body = _named(op.path, data, names)
            out[DOC_SINKS[part]].append(op.path + " " + json.dumps(body, default=str))
    return out, names


def record_text(r: logging.LogRecord) -> str:
    extras = {k: v for k, v in vars(r).items() if k not in _STD}
    parts = [str(r.name), str(r.msg), repr(r.args), repr(extras)]
    try:
        parts.append(r.getMessage())
    except Exception as exc:  # noqa: BLE001 - a record whose args don't fit its message
        parts.append(type(exc).__name__)
    if r.exc_info:
        parts.append(logging.Formatter().formatException(r.exc_info))
    return "\n".join([*parts, r.exc_text or "", r.stack_info or ""])


async def audit_texts(audits: list[AuditLog]) -> list[str]:
    out: list[str] = []
    for audit in audits:
        for e in (await audit.tail(100_000)).entries:
            if e.tool in AUDITED:
                out.append(e.model_dump_json())
    return out


async def haystacks(s: nf.Sinks) -> tuple[dict[str, list[str]], list[str]]:
    hay, names = documents(s.stores)
    hay["logs"] = [record_text(r) for r in s.records]
    hay["audit"] = await audit_texts(s.audits)
    hay["told"] = list(s.told)
    hay["routes"] = [f"{p} {json.dumps(b, default=str)}" for p, b in s.routes.items()]
    hay["telegram"] = list(s.telegram)
    return hay, names


def leaks(texts: list[str], sink: str) -> list[str]:
    out: list[str] = []
    for needle in NEEDLES:
        if sink in needle.allowed:
            continue
        hits = {f for t in texts for f in seen(needle.value, t)}
        if hits:
            out.append(f"{needle.kind} in {sink} ({len(hits)} form{'s' if len(hits) > 1 else ''})")
    return out


# ---- the cases --------------------------------------------------------------------------------


def _case(name: str, failures: list[str]) -> dict[str, Any]:
    return {"id": f"{PART}:{name}", "passed": not failures, "failures": failures}


def _ran(s: nf.Sinks) -> list[str]:
    f, want = s.facts, {
        "drill": "passed", "compared": True, "copy_deleted": True,
        "failed_restore": ["restore"], "failed_delete": ["delete_database"],
        "failed_access": ["list_backups"], "tool_vitals_backups": "executed",
        "tool_vitals_drill_start": "awaiting_confirmation", "ledger_days": 1,
        "model_saw_the_words": True, "reply_despite_ledger": True, "noai_quoted": True,
        "service_request": True, "digits_refused": True, "telegram_card": 1,
        "job_failing_told": True, "drill_run_cleared": True,
    }  # fmt: skip
    out = [f"{k}: {f.get(k)!r}, not {v!r}" for k, v in want.items() if f.get(k) != v]
    out += [] if f.get("model_failed") else ["a provider that raises raised nothing"]
    return out + [f"{p}: {r['status']}" for p, r in s.routes.items() if r["status"] != 200]


def _backup_name(hay: dict[str, list[str]], names: list[str]) -> list[str]:
    out = [] if nf.BACKUP_NAME in names else ["newest_name never held the backup's name"]
    for sink, texts in hay.items():
        if any(seen(nf.PROJECT_WORD, t) for t in texts):
            out.append(f"the backup's project id in {sink}")
    return out


def _logger_names(s: nf.Sinks, hay: dict[str, list[str]]) -> list[str]:
    errors = [t for t in hay["documents_selfwatch"] if t.startswith(f"{P}selfwatch_errors/")]
    if not errors:
        return ["no errors document written"]
    shown = max(len(re.findall(r'"jarvis\.needleql\d\d"', t)) for t in errors)
    out = [] if 0 < shown <= MAX_NAMES else [f"{shown} logger names kept (cap {MAX_NAMES})"]
    built = [p for p in (nf.ROOT / "src" / "jarvis").rglob("*.py") if _dynamic_logger(p)]
    return out + [f"a logger name built at run time: {p.name}" for p in built]


def _dynamic_logger(path: Path) -> bool:
    return bool(re.search(r"getLogger\(\s*(?:f[\"']|[\"'][^\"']*[\"']\s*[+%])", path.read_text()))


def _fenced(s: nf.Sinks) -> list[str]:
    fence = re.fullmatch(
        r"<<EXTERNAL CONTENT from [^\n]* · ([0-9a-f]{6})>>\n(.*)\n<<END \1>>", s.window, re.S
    )
    if not s.window.startswith(FENCE_PREFIX) or fence is None or "Glimmerfax" not in fence.group(2):
        return [f"the No-AI reply reached the model unfenced: {s.window[:80]!r}"]
    return []


def _hashed(hay: dict[str, list[str]]) -> list[str]:
    ledger = " ".join(hay["documents_ledger"])
    return [] if nf.UID in ledger and re.fullmatch(r"u_[0-9a-f]{16}", nf.UID) else ["no hashed id"]


async def _cases_of(s: nf.Sinks) -> list[dict[str, Any]]:
    hay, names = await haystacks(s)
    out = [_case("day_ran", _ran(s))]
    out += [_case(sink, leaks(hay[sink], sink)) for sink in SINKS]
    out.append(_case("backup_name_only_in_its_fields", _backup_name(hay, names)))
    out.append(_case("logger_names_are_code_and_capped", _logger_names(s, hay)))
    out.append(_case("noai_subject_reaches_the_model_fenced", _fenced(s)))
    out.append(_case("only_the_hashed_owner_id", _hashed(hay)))
    return out + await positive_controls()


async def cases() -> list[dict[str, Any]]:
    return await _cases_of(await nd.day())


# ---- positive controls: the scanner sees a probe planted in each sink ------------------------

PROBE = "Probe Needle/42"


async def _planted(sink: str, form: str) -> list[str]:
    s = nf.Sinks()
    if sink.startswith("documents_"):
        part = next(p for p, n in DOC_SINKS.items() if n == sink)
        store = MemoryDocs()
        await store.write([Set(f"{P}{COLLECTIONS[part][0]}/probe", {"x": form})])  # type: ignore[index]
        s.stores.append(store)
    elif sink == "logs":
        s.records += _probe_records(form)
    elif sink == "audit":
        audit = AuditLog()
        await audit.append(
            agent="vitals",
            tool=SHOW,
            risk=nd.ActionRisk.READ_ONLY,
            outcome="executed",
            args={},
            detail=form,
        )
        s.audits.append(audit)
    elif sink == "told":
        s.told.append(form)
    elif sink == "routes":
        s.routes["/v1/probe"] = {"status": 200, "body": {"x": form}}
    else:
        s.telegram.append(form)
    hay, _ = await haystacks(s)
    return hay[sink]


def _probe_records(form: str) -> list[logging.LogRecord]:
    """The form in each place a record carries text: message, args, an extra, an exception,
    the stack."""
    try:
        raise RuntimeError(form)
    except RuntimeError:
        exc = sys.exc_info()
    base: dict[str, Any] = {"name": "jarvis.probe", "msg": "probe"}
    return [
        logging.makeLogRecord(base | {"msg": form}),
        logging.makeLogRecord(base | {"msg": "probe %s", "args": (form,)}),
        logging.makeLogRecord(base | {"extra_field": form}),
        logging.makeLogRecord(base | {"exc_info": exc}),
        logging.makeLogRecord(base | {"stack_info": form}),
    ]


async def positive_controls() -> list[dict[str, Any]]:
    out = []
    for sink in SINKS:
        missed = [
            f for f in forms(PROBE) if not all(seen(PROBE, t) for t in await _planted(sink, f))
        ]
        out.append(_case(f"scanner_sees_{sink}", [f"missed {m!r}" for m in missed]))
    return out


# ---- the negative control: three writers that keep what they must not -------------------------


@contextmanager
def leaky() -> Iterator[None]:
    """The ledger stores the persona, the errors handler the message, the drill log the cause."""
    record, emit, write = TokenLedgerStore.record, ErrorCounter.emit, ErrorCounter.write_counts
    result = drill_log.DrillLog.record

    async def ledger(self: TokenLedgerStore, call: Any) -> None:
        await record(self, call)
        await self._docs.write([Set(f"{self._col}/leak_{call.uid}", {"system": call.system})])  # noqa: SLF001

    def counted(self: ErrorCounter, r: logging.LogRecord) -> None:
        emit(self, r)
        self.__dict__.setdefault("leak", []).append(r.getMessage())

    async def counts(self: ErrorCounter, docs: Any) -> Any:
        await docs.write([Set(f"{self._coll}/leak", {"m": self.__dict__.get("leak", [])})])  # noqa: SLF001
        return await write(self, docs)

    async def drill(self: Any, r: Any) -> None:
        cause = sys.exc_info()[1]
        await self._d.write([Set(f"{self._results}/leak", {"cause": str(cause or "")})])  # noqa: SLF001
        await result(self, r)

    TokenLedgerStore.record, ErrorCounter.emit = ledger, counted  # type: ignore[method-assign]
    ErrorCounter.write_counts, drill_log.DrillLog.record = counts, drill  # type: ignore[method-assign]
    try:
        yield
    finally:
        TokenLedgerStore.record, ErrorCounter.emit = record, emit  # type: ignore[method-assign]
        ErrorCounter.write_counts, drill_log.DrillLog.record = write, result  # type: ignore[method-assign]


async def control() -> dict[str, Any]:
    with leaky():
        got = await _cases_of(await nd.day())
    failed = sorted(r["id"] for r in got if not r["passed"])
    return {
        "name": "needles: the ledger keeps the persona, the errors handler the message, the drill "
        "log the exception's text",
        "suite_failed": failed == sorted(CONTROL_FAILS),
        "failed_cases": failed,
    }

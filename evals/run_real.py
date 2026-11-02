# evals/run_real.py
"""The real-model eval runner. Driven by deploy/run-real-evals.sh (Google Cloud Shell); every
step that spends money waits for the owner's typed YES in that script.

    python evals/run_real.py estimate [--all] --state FILE   rupee estimate; nothing is spent
    python evals/run_real.py amount --state FILE             "₹9": the figure the YES prompt shows
    python evals/run_real.py run --state FILE --ledger FILE  runs the suites (needs the key)
    python evals/run_real.py guard --cap-usd X --ledger FILE SCRIPT [ARGS]   (internal: one suite)

Suites: phase0 by default; --all adds memory, voice, brief and slice6 (their real modes). The
safety stop is 1.5 × the estimate, enforced around every Claude call (realrun.guard).
Exit status: 0 all passed · 1 something did not pass · 2 setup problem · 3 safety stop ·
4 a model without a price.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402
from realrun.estimate import Estimate, Unpriced, build_estimate, catalogue, render  # noqa: E402
from realrun.guard import Ledger, SpendGuard, run_script  # noqa: E402
from realrun.runner import run_suites  # noqa: E402

from jarvis.billing import rupees  # noqa: E402
from jarvis.billing.fx import FETCH_TIMEOUT_S, FxRates, Rate  # noqa: E402
from jarvis.config import LLMBackend, Settings, get_settings  # noqa: E402
from jarvis.llm.router import tiers_for  # noqa: E402

DEFAULT_SUITES = ("phase0",)
# The model settings deploy/cloudrun.sh gives the live service (its INFRA_ENV), so the Phase 0
# speed and cost gates measure what the owner actually gets. An explicit environment wins.
PROD_MODEL_SETTINGS = {
    "JARVIS_DEFAULT_TIER": "balanced",
    "JARVIS_EFFORT": "low",
    "JARVIS_LLM_TIMEOUT_S": "20",
}


async def _rate(s: Settings) -> Rate:
    """Today's rate (one 5-second try at most), else the saved default."""
    if not s.usd_inr_live:
        return FxRates(docs=None, http=None, default_rate=s.usd_inr_rate).peek()
    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_S, follow_redirects=False) as http:
        return await FxRates(docs=None, http=http, default_rate=s.usd_inr_rate).refresh()


def cmd_estimate(args: argparse.Namespace) -> int:
    s = get_settings()
    cat = catalogue(ROOT)
    keys = list(cat) if args.all else list(DEFAULT_SUITES)
    try:
        e = build_estimate(
            [cat[k] for k in keys], tiers_for(s, LLMBackend.ANTHROPIC), asyncio.run(_rate(s))
        )
    except Unpriced as exc:
        print(f"Cannot estimate the cost: the Claude model '{exc}' has no price in JARVIS yet.")
        print("Nothing was spent. Send this message to Claude.")
        return 2
    Path(args.state).write_text(json.dumps({"suites": keys, "estimate": e.to_json()}))
    print(render(e))
    return 0


def _state(path: str) -> tuple[list[str], Estimate]:
    data = json.loads(Path(path).read_text())
    return list(data["suites"]), Estimate.from_json(data["estimate"])


def cmd_amount(args: argparse.Namespace) -> int:
    print(rupees(_state(args.state)[1].total_inr))
    return 0


def _child_env(e: Estimate) -> dict[str, str]:
    env = dict(os.environ)
    src = str(ROOT / "src")
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.update(
        JARVIS_LLM_BACKEND="anthropic",  # the real models, whatever a .env says
        JARVIS_SESSION_BACKEND="memory",  # never the owner's conversations
        JARVIS_USD_INR_LIVE="false",  # the same rate as the estimate
        JARVIS_USD_INR_RATE=repr(e.inr_per_usd),
    )
    for name, value in PROD_MODEL_SETTINGS.items():  # measure what the deployed JARVIS runs
        env.setdefault(name, value)
    return env


def cmd_run(args: argparse.Namespace) -> int:
    if not os.environ.get("JARVIS_ANTHROPIC_API_KEY"):
        print("The Claude key is missing, so nothing was run and nothing was spent.")
        return 2
    keys, e = _state(args.state)
    cat = catalogue(ROOT)
    ledger = Ledger(Path(args.ledger))
    try:
        ledger.reset()  # this run's spending starts at zero
    except OSError:
        print("Could not create this run's spending record, so nothing was run or spent.")
        return 2
    return run_suites(
        suites=[cat[k] for k in keys],
        estimate=e,
        ledger=ledger,
        logs=Path(args.logs) if args.logs else Path(args.ledger).parent / "logs",
        env=_child_env(e),
        root=ROOT,
        say=lambda line: print(line, flush=True),
    )


def cmd_guard(args: argparse.Namespace) -> int:
    guard = SpendGuard(cap_usd=args.cap_usd, ledger=Ledger(Path(args.ledger)))
    return run_script(Path(args.script), args.args, guard)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0] if __doc__ else None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("estimate")
    p.add_argument("--all", action="store_true", help="every suite with a real mode")
    p.add_argument("--state", required=True)
    p.set_defaults(fn=cmd_estimate)
    p = sub.add_parser("amount")
    p.add_argument("--state", required=True)
    p.set_defaults(fn=cmd_amount)
    p = sub.add_parser("run")
    p.add_argument("--state", required=True)
    p.add_argument("--ledger", required=True)
    p.add_argument("--logs", default=None)
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("guard")
    p.add_argument("--cap-usd", type=float, required=True)
    p.add_argument("--ledger", required=True)
    p.add_argument("script")
    p.add_argument("args", nargs=argparse.REMAINDER)
    p.set_defaults(fn=cmd_guard)
    args = ap.parse_args(argv)
    code: int = args.fn(args)
    return code


if __name__ == "__main__":
    sys.exit(main())

# src/jarvis/cli.py
"""Terminal client: `jarvis chat` talks to the Brain in-process (no server needed);
`jarvis serve` runs the API. Phase 1 adds `jarvis listen` on top of the same Brain."""

from __future__ import annotations

import argparse
import asyncio
import sys

from jarvis.api.identity import primary_user_id
from jarvis.billing import BudgetError, build_billing, fx_client
from jarvis.config import get_settings
from jarvis.core.brain import Brain
from jarvis.core.models import ChatRequest
from jarvis.llm.base import LLMError
from jarvis.llm.brains import BrainRegistry
from jarvis.llm.router import NO_AI_REFUSAL, BrainOff
from jarvis.logging import configure_logging, new_trace_id
from jarvis.storage import build_storage
from jarvis.storage.docs import MemoryDocs


def _resolve_brain(brain: Brain, brain_id: str | None) -> str | None:
    """Validate `--brain` against the configured registry; exit 2 with the list on a miss."""
    if brain_id is None:
        return None
    try:
        spec = brain.brains.get(brain_id)
    except LookupError:
        known = ", ".join(b.id for b in brain.brains.list())
        sys.exit(f"jarvis chat: unknown brain {brain_id!r}. Configured brains: {known}")
    return spec.id


async def _repl(stream: bool, brain_id: str | None = None) -> None:
    s = get_settings()
    s.require_prod_invariants()
    configure_logging(s.log_level, s.log_json)
    built = build_storage(s)
    store = built.sessions
    brains = BrainRegistry.from_settings(s)
    http = fx_client(s)
    # the same monthly limit and meter as the console (Firestore when configured)
    billing = build_billing(s, built.docs or MemoryDocs(), brains, http=http)
    brain = Brain(brains=brains, store=store, settings=s, billing=billing)
    chosen = _resolve_brain(brain, brain_id)
    session_id: str | None = None
    label = brain.brains.get(chosen).label if chosen else brain.brains.default.label
    print(f"JARVIS online ({label}). Ctrl-D or /quit to exit, /new for a fresh session.\n")
    try:
        while True:
            try:
                line = input("you> ").strip()
            except EOFError:
                break
            if not line:
                continue
            if line in {"/quit", "/exit"}:
                break
            if line == "/new":
                session_id = None
                print("(new session)")
                continue
            new_trace_id()
            req = ChatRequest(
                message=line, session_id=session_id, user_id=primary_user_id(s), brain=chosen
            )
            try:
                if stream:
                    print("jarvis> ", end="", flush=True)
                    async for delta in brain.chat_stream(req):
                        print(delta, end="", flush=True)
                    print()
                    if session_id is None:
                        # chat_stream created it; fetch the newest session for this user
                        sessions = await store.list_for_user(req.user_id, limit=1)
                        session_id = sessions[0].id if sessions else None
                else:
                    resp = await brain.chat(req)
                    session_id = resp.session_id
                    print(f"jarvis> {resp.reply}")
                    print(
                        f"        [{resp.model} · {resp.usage.total_tokens} tok · "
                        f"≈ ₹{resp.cost_inr:.2f} · {resp.latency_ms} ms]"
                    )
            except BudgetError as exc:  # the monthly limit: said plainly, the REPL goes on
                print(f"(jarvis: {exc})", file=sys.stderr)
            except BrainOff:
                print(f"(jarvis: {NO_AI_REFUSAL})", file=sys.stderr)
            except LLMError as exc:
                print(f"(llm error: {exc})", file=sys.stderr)
    finally:
        if http is not None:
            await http.aclose()
        await store.close()


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="jarvis")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("chat", help="interactive terminal session")
    c.add_argument("--stream", action="store_true", help="stream tokens as they arrive")
    c.add_argument(
        "--brain",
        metavar="ID",
        help="which configured brain answers (ids as in GET /v1/brains, e.g. anthropic, gemini)",
    )
    sv = sub.add_parser("serve", help="run the HTTP API")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--reload", action="store_true")
    args = p.parse_args(argv)

    if args.cmd == "chat":
        asyncio.run(_repl(stream=args.stream, brain_id=args.brain))
    elif args.cmd == "serve":
        import uvicorn

        uvicorn.run(
            "jarvis.api.app:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=args.reload,
        )


if __name__ == "__main__":
    main()

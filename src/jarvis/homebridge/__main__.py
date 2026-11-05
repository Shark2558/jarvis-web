# src/jarvis/homebridge/__main__.py
"""`python -m jarvis.homebridge` runs the bridge; `python -m jarvis.homebridge link CODE URL` links
it (the setup script runs the second inside the running container, so the running bridge can
answer JARVIS's test call). Ships in the home kit. Prints plain lines; never a token or seed."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import sys
from collections.abc import Sequence

from jarvis.homebridge.app import create_bridge
from jarvis.homebridge.cloud import LinkFailed
from jarvis.homebridge.config import ConfigError, load_config
from jarvis.homebridge.plugins import PluginFactory


def _registry() -> Sequence[PluginFactory]:
    """The camera and faces parts. Review M10: a registry that can't be imported is said loudly
    (the bridge still starts its core, and the heartbeat shows the camera isn't receiving)."""
    try:
        from jarvis.homebridge.registry import PLUGINS
    except ImportError as exc:
        logging.getLogger("jarvis.homebridge").error(
            "the bridge's parts could not be loaded: camera and faces are OFF",
            extra={"error": type(exc).__name__},
        )
        return ()
    return PLUGINS


def run() -> int:
    try:
        cfg = load_config(os.environ)
    except ConfigError as exc:
        print(f"The bridge can't start: {exc}", file=sys.stderr)
        return 2
    import uvicorn

    bridge = create_bridge(cfg, _registry(), env=dict(os.environ))  # each plugin reads its keys
    uvicorn.run(bridge.app, host=cfg.bind_host, port=cfg.signed_port, log_level="warning")
    return 0


def link(code: str, bridge_url: str) -> int:
    try:
        cfg = load_config(os.environ)
    except ConfigError as exc:
        print(f"The bridge can't link: {exc}", file=sys.stderr)
        return 2
    bridge = create_bridge(cfg, ())

    async def go() -> str:
        try:
            return await bridge.link.link(code, bridge_url, secrets.token_bytes(32))
        finally:
            await bridge.link.aclose()

    try:
        asyncio.run(go())
    except LinkFailed as exc:
        print(exc.reason, file=sys.stderr)
        return 1
    print("Linked.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.WARNING)
    if args[:1] == ["link"] and len(args) == 3:
        return link(args[1], args[2])
    if args:
        print("Usage: python -m jarvis.homebridge [link CODE BRIDGE_URL]", file=sys.stderr)
        return 2
    return run()


if __name__ == "__main__":
    raise SystemExit(main())

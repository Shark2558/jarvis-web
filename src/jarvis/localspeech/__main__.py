# src/jarvis/localspeech/__main__.py
"""The laptop speech kit's commands (R5.2 V1), run by the kit's scripts with the kit's own Python:

    python -I -m jarvis.localspeech serve              the speech server on 127.0.0.1:11437
    python -I -m jarvis.localspeech models             what may be installed, with licences
    python -I -m jarvis.localspeech models install     download the pinned files (hash-checked)
    python -I -m jarvis.localspeech models verify      re-check every installed file's SHA-256
    python -I -m jarvis.localspeech installed          what this kit installed (models, packages)
    python -I -m jarvis.localspeech selftest           the report to paste into JARVIS's chat
    python -I -m jarvis.localspeech delete-recordings  every recording on this laptop (asks first)

The key comes only from the environment (`JARVIS_LOCAL_SPEECH_KEY`, set by the start script),
never from the command line.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import logging
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from jarvis.localspeech.clips import ClipVault
from jarvis.localspeech.kitconfig import HOST, PORT, KitConfig, KitConfigError
from jarvis.localspeech.manager import ModelError, ModelManager, load_manifest, manifest_text
from jarvis.localspeech.protocol import EngineSlot
from jarvis.localspeech.selftest import GateCalls, report_json, run
from jarvis.localspeech.service import build_service, default_mp3

REQUIREMENTS: Final = ("requirements-kit.txt", "requirements-gpu.txt")
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)", re.MULTILINE)
Out = Callable[[str], None]


def _manager(config: KitConfig) -> ModelManager:
    return ModelManager(load_manifest(config.manifest), config.models_dir, config.installed_file)


def serve(config: KitConfig) -> int:
    import uvicorn  # BSD-3-Clause, pinned in the kit

    from jarvis.localspeech.server import build_app

    key = config.require_key()
    service = build_service(config)  # I1 / V4: build_service(config, wakeword=<V4's trainer>)
    app = build_app(service, key)
    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        access_log=False,
        log_level="warning",
        server_header=False,
        date_header=False,
        proxy_headers=False,
        timeout_keep_alive=5,
    )
    return 0


def models(config: KitConfig, action: str, slots: Sequence[str], out: Out) -> int:
    manager = _manager(config)
    if action == "list":
        for line in manifest_text(manager.manifest) or ["no models in this kit's list"]:
            out(line)
        return 0
    known = {s.value: s for s in EngineSlot}
    if any(s not in known for s in slots):
        out(f"Engines are: {', '.join(known)}.")
        return 2
    wanted = [known[s] for s in slots] or [m.slot for m in manager.manifest.models]
    if action == "install":
        if not wanted:
            out("This kit pins no model files yet; nothing to install (see README).")
            return 0
        for slot in wanted:
            out(f"{slot.value}:")
            manager.install(slot, progress=lambda words: out(f"  {words}"))
        out("Installed. Restart the kit (start-kit.ps1) to use them.")
        return 0
    bad = 0
    for slot, problem in manager.verify(wanted).items():
        out(f"{slot.value}: {problem or 'hashes OK'}")
        bad += problem is not None
    return 1 if bad else 0


def pinned_packages(folder: Path) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for name in REQUIREMENTS:
        path = folder / name
        if path.is_file():
            found += [(m.group(1), m.group(2)) for m in _PIN.finditer(path.read_text())]
    return found


def installed(config: KitConfig, out: Out) -> int:
    manager = _manager(config)
    out("Models (pinned, SHA-256 checked, licence beside each):")
    done = manager.installed().models
    for m in done:
        out(f"  {m.slot.value}: {m.model} @ {m.revision[:12]} ({m.licence}), {len(m.files)} files")
    if not done:
        out("  none yet")
    out("Python packages (pinned, hash-checked):")
    for name, version in pinned_packages(config.manifest.parent):
        try:
            have = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            have = "not installed"
        mark = "" if have == version else f" (installed: {have})"
        out(f"  {name}=={version}{mark}")
    out("Programs you installed yourself: Python 3.12, Caddy, Tailscale (see README).")
    return 0


def selftest(config: KitConfig, as_json: bool, out: Out) -> int:
    key = config.key.get_secret_value() if config.key is not None else None
    if key is None:
        out("No key in this window: run the self-test from start-kit.ps1 -SelfTest.")
        return 1
    report = asyncio.run(
        run(
            GateCalls(key),
            manager=_manager(config),
            vault=ClipVault(config.clips_dir, config.clip_key_file),
            key=key,
            mp3=default_mp3(),
        )
    )
    out(report_json(report) if as_json else report.text())
    return 1 if report.failed else 0


def delete_recordings(config: KitConfig, answer: Callable[[str], str], out: Out) -> int:
    if answer("Type DELETE to remove every recording on this laptop: ").strip() != "DELETE":
        out("Nothing deleted.")
        return 1
    removed = ClipVault(config.clips_dir, config.clip_key_file).delete(None)
    out(f"Deleted {removed} recordings, and replaced their key.")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m jarvis.localspeech")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve")
    m = sub.add_parser("models")
    m.add_argument("action", nargs="?", default="list", choices=("list", "install", "verify"))
    m.add_argument("slots", nargs="*", metavar="slot", help=", ".join(s.value for s in EngineSlot))
    sub.add_parser("installed")
    s = sub.add_parser("selftest")
    s.add_argument("--json", action="store_true")
    sub.add_parser("delete-recordings")
    return parser


def main(argv: Sequence[str] | None = None, out: Out = print) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        config = KitConfig.from_env()
        if args.command == "serve":
            return serve(config)
        if args.command == "models":
            return models(config, args.action, args.slots, out)
        if args.command == "installed":
            return installed(config, out)
        if args.command == "selftest":
            return selftest(config, args.json, out)
        return delete_recordings(config, input, out)
    except (KitConfigError, ModelError) as err:
        out(str(err))
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

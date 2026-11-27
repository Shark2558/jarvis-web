# src/jarvis/calldesk/__main__.py
"""`python -m jarvis.calldesk run | supervise | restore | check | link-home` (R18 C).

The kit's PowerShell scripts call these; `check`, `restore` and `link-home` talk to the owner in
plain words on the console (print is the interface here), and everything else goes to the desk's
log file. Exit codes: 0 fine, 1 a check or restore that needs him, 2 a broken kit or setting,
3 not linked, 4 already running.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from jarvis.calldesk import DESK_VERSION, app, config
from jarvis.calldesk.credentials import CredentialStore, NotLinked
from jarvis.calldesk.watchdog import EXIT_CONFIG, EXIT_NOT_LINKED, EXIT_OK

USAGE = "usage: python -m jarvis.calldesk run | supervise | restore | check | link-home"
EXIT_NEEDS_HIM = 1


def kit_dir() -> Path:
    override = os.environ.get("JARVIS_DESK_KIT", "").strip()
    return Path(override) if override else Path(__file__).resolve().parents[3]


def _say(text: str) -> None:
    print(text, flush=True)


def link_home(cfg: config.DeskConfig, text: str) -> int:
    try:
        CredentialStore(cfg.secret).link_from_bridge(text)
    except NotLinked as exc:
        _say(str(exc))
        return EXIT_NOT_LINKED
    except OSError:
        _say("The link could not be saved in your profile folder.")
        return EXIT_CONFIG
    _say("The call desk uses JARVIS Home's link now.")
    return EXIT_OK


def main(argv: list[str] | None = None, parts: app.Parts | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0] not in {"run", "supervise", "restore", "check", "link-home"}:
        _say(USAGE)
        return EXIT_CONFIG
    command = args[0]
    try:
        cfg = config.load(kit_dir(), os.environ)
    except config.ConfigError as exc:
        _say(str(exc))
        return EXIT_CONFIG
    app.setup_logging(cfg)
    if command == "link-home":
        return link_home(cfg, sys.stdin.read(4096))
    parts = parts or app.windows_parts()
    if command == "run":
        return app.run_desk(cfg, parts)
    if command == "supervise":
        return app.run_watchdog(cfg, parts, app.child_command())
    if command == "restore":
        out = app.restore_now(cfg, parts)
        _say(
            "Your microphone and sounds are as you had them." if out.ok else "\n".join(out.problems)
        )
        return EXIT_OK if out.ok else EXIT_NEEDS_HIM
    check = app.check_now(cfg, parts)
    _say(
        f"JARVIS call desk {DESK_VERSION}: " + ("ready for calls." if check.ready else "not ready.")
    )
    for problem in check.problems:
        _say(f" - {problem}")
    if CredentialStore(cfg.secret).load() is None:
        _say(" - Not linked yet: run install-calldesk.ps1 -Link")
    return EXIT_OK if check.ready else EXIT_NEEDS_HIM


if __name__ == "__main__":
    sys.exit(main())

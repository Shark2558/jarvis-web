# src/jarvis/api/startup_log.py
"""The one "jarvis up" log line at the end of start-up: which parts are on (moved out of
`api/app.py` at R11 I0, docs/plans/r11-free-helpers.md seam 7, so that file stays a short list of
named steps; no behaviour change). Names and booleans only: never a key, an address or an id."""

from __future__ import annotations

from fastapi import FastAPI

from jarvis.config import Settings
from jarvis.logging import get_logger

log = get_logger("jarvis.api.app")  # the line keeps the logger name it always had


def log_up(app: FastAPI, s: Settings) -> None:
    log.info(
        "jarvis up",
        extra={
            "env": s.env,
            "llm": app.state.router.provider.name,
            "brains": [b.id for b in app.state.brains.list()],
            "session_backend": s.session_backend.value,
            "google_tools": app.state.google is not None,
            "brief_scheduler": getattr(app.state, "scheduler_verifier", None) is not None,
            "voice_cloud": app.state.voice.engines is not None,
            "web_search": app.state.web is not None,
            "drive": app.state.drive is not None,
            "maps_youtube": app.state.media is not None,
            "vault": app.state.vault is not None,
            "notes": app.state.notes is not None,
            "things": app.state.belongings is not None,
            "home": app.state.home_store is not None,
            "faces": app.state.faces is not None,
            "browser_push": app.state.push is not None,
            # R4: each OFF-until-connected part says so here (and in its own console line)
            "brain_mode": app.state.brain_mode.state,
            "vitals": app.state.vitals is not None,
            "systems_check": app.state.health is not None,
            "github": app.state.github is not None,
            "photos": app.state.photos is not None,
            "people_research": app.state.people is not None,
            # R11: the free proactive helpers (each still needs the owner's setup)
            "helpers": getattr(app.state, "helpers_sender", None) is not None,
        },
    )


__all__ = ["log_up"]

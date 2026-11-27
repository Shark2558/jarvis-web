# src/jarvis/calldesk/__init__.py
"""The call desk (R18, docs/plans/r18-calls.md sections 3, 4, 8; Layer 6 at the laptop).

A Windows program on the owner's laptop, never part of the cloud app. During a JARVIS call it
records what the laptop's speaker plays (the call, through Phone Link), sends that audio to JARVIS
only while the other person speaks, plays JARVIS's voice into VB-CABLE's "CABLE Input", and makes
"CABLE Output" the default microphone for the call only; it puts the owner's microphone back
afterwards, on a crash (the watchdog) and at its next start.

It ships in the call desk kit (`deploy/calldesk/`, built by `jarvis.calldesk.kit`) with a copy of
`jarvis/calls/protocol.py` and `jarvis/home/signing.py` made at kit-build time. Code that only
runs on Windows lives in `jarvis.calldesk.win` and is imported lazily, so everything else is tested
on Linux with fakes. Nothing is imported here, so `python -m jarvis.calldesk` stays light.
"""

DESK_VERSION = "18.1.0"  # R5.2 I1: the laptop speech kit (its own track)

__all__ = ["DESK_VERSION"]

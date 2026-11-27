# src/jarvis/localspeech/__init__.py
"""R5.2 row 383: the laptop speech kit (Layer 6; docs/plans/r5-2-voice.md 3.1). A small speech
server on the owner's laptop, behind a Caddy gate with the kit's key, reached by the cloud only
through his Tailscale https name and by the call desk on 127.0.0.1.

- `protocol` (I0, kit-safe): the API's paths, the audio format, every request and reply, the
  engine slots and their licences, the `KitClient` port and its plain errors
- `memory` (I0): `MemoryKit`, the deterministic in-memory kit for tests and the CI mock evals
- the server, engines, model manager and jobs (V1), the kit client and the call desk's hook (V2)
  and the wake-word training (`wakeword/`, V4)

Nothing is re-exported here: the kit and the cloud take what they need from each module.
"""

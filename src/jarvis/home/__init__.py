# src/jarvis/home/__init__.py
"""The home link (R3, docs/plans/r3-home-camera.md; Layer 6 IoT, cross-cutting security).

`ports` (the wire vocabulary and the cloud ports) and `signing` (the one HMAC implementation) are
shared by the cloud and the home bridge, and ship in the home kit: they import only the standard
library, pydantic and cryptography. Nothing is re-exported here, so importing them never pulls in
the cloud app.
"""

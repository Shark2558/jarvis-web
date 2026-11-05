# src/jarvis/faces/__init__.py
"""Faces JARVIS recognises at home, with consent (R3 D13; Layer 2 vision at the edge, Layer 3).

`ports` is the shared seam (R3 I0): `FaceDirectory.resolve` turns a person id from the bridge into
a name only for a consented, enrolled person; everyone else is "someone JARVIS didn't recognise".
The registry, consent records and deletes are R3 C's.
"""

from jarvis.faces.ports import (
    FAMILY_CHILD,
    RECOGNISED_PERSON,
    RECOGNITION_THRESHOLD,
    UNKNOWN,
    UNKNOWN_PERSON,
    FaceDirectory,
    NoFaces,
    Resolved,
    is_person_id,
)

__all__ = [
    "FAMILY_CHILD",
    "RECOGNISED_PERSON",
    "RECOGNITION_THRESHOLD",
    "UNKNOWN",
    "UNKNOWN_PERSON",
    "FaceDirectory",
    "NoFaces",
    "Resolved",
    "is_person_id",
]

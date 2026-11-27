# src/jarvis/localspeech/wakeword/store.py
"""The trained wake-word files on the kit (R5.2 row 83, D4): one file per artifact under the kit's
data folder, sealed with V1's at-rest key like the session's clips, written atomically. A file
that does not unseal or match its hash reads as missing. Stdlib + Pydantic (kit-safe).
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from jarvis.localspeech.protocol import ArtifactInfo, WakeArtifact
from jarvis.localspeech.wakeword.formats import sha256_hex
from jarvis.localspeech.wakeword.port import Sealer
from jarvis.logging import get_logger

log = get_logger(__name__)
SUFFIX: Final = ".sealed"


@dataclass(frozen=True)
class Stored:
    data: bytes
    info: ArtifactInfo
    manifest: str


class ArtifactStore:
    def __init__(self, root: Path, sealer: Sealer) -> None:
        self.root = root
        self._sealer = sealer
        root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _path(self, artifact: WakeArtifact) -> Path:
        return self.root / f"wakeword-{artifact.value}{SUFFIX}"

    def put(self, data: bytes, info: ArtifactInfo, manifest: str = "") -> None:
        if sha256_hex(data) != info.sha256 or len(data) != info.size:
            raise ValueError("the file does not match its record")
        record = {
            "info": info.model_dump(mode="json"),
            "manifest": manifest,
            "data": base64.b64encode(data).decode("ascii"),
        }
        sealed = self._sealer.seal(json.dumps(record).encode("utf-8"))
        path = self._path(info.artifact)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(sealed)
        os.replace(tmp, path)

    def get(self, artifact: WakeArtifact) -> Stored | None:
        path = self._path(artifact)
        if not path.is_file():
            return None
        try:
            record = json.loads(self._sealer.unseal(path.read_bytes()))
            data = base64.b64decode(record["data"], validate=True)
            info = ArtifactInfo.model_validate(record["info"])
            manifest = str(record.get("manifest", ""))
        except (ValueError, KeyError, TypeError, ValidationError):
            log.warning(
                "wake-word file unreadable: treated as missing", extra={"artifact": artifact.value}
            )
            return None
        if sha256_hex(data) != info.sha256 or info.artifact is not artifact:
            log.warning(
                "wake-word file does not match its record", extra={"artifact": artifact.value}
            )
            return None
        return Stored(data=data, info=info, manifest=manifest)

    def info(self, artifact: WakeArtifact) -> ArtifactInfo | None:
        stored = self.get(artifact)
        return stored.info if stored is not None else None

    def delete_all(self) -> int:
        removed = 0
        for artifact in WakeArtifact:
            path = self._path(artifact)
            if path.is_file():
                path.unlink()
                removed += 1
            path.with_suffix(".tmp").unlink(missing_ok=True)
        return removed


__all__ = ["ArtifactStore", "Stored"]

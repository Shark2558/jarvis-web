# src/jarvis/localspeech/clips.py
"""The voice session's recordings, kept on the laptop only and encrypted at rest (R5.2 V1; plan D4).
Kit-safe: the standard library, Pydantic and `cryptography` (pinned in the kit's requirements).

Each clip is one file, `clips/<session_id>/<prompt_id>.clip`: AES-256-GCM with a fresh 96-bit
nonce, the session and prompt bound in as associated data (a file moved to another name does not
open). What the laptop engines heard while scoring is kept the same way (`_heard.bin`). The key is
32 random bytes in `clips.secret`, readable by the owner's account only, made on first use; the
cloud never has it. Deleting every recording also replaces the key, so a copy left behind
anywhere can no longer be read.
"""

from __future__ import annotations

import json
import logging
import secrets
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from jarvis.localspeech.kitconfig import private_dir, write_private
from jarvis.localspeech.protocol import (
    SESSION_ID_RE,
    ClipIn,
    ClipStored,
    HeardRow,
    KitRefused,
    PromptKind,
    SessionHeard,
    pcm_seconds,
)

log = logging.getLogger(__name__)

MAGIC: Final = b"JVC1"
NONCE_BYTES: Final = 12
KEY_BYTES: Final = 32
SUFFIX: Final = ".clip"
HEARD: Final = "_heard.bin"  # prompt ids start with a letter, so this never clashes
MAX_CLIPS_PER_SESSION: Final = 400  # ~120 prompts, redos and the wake-word set, with room
MAX_SESSIONS: Final = 12


class VaultUnreadable(RuntimeError):
    """A stored file did not open with the kit's key (moved, damaged, or from an older key)."""


@dataclass(frozen=True)
class StoredClip:
    session_id: str
    prompt_id: str
    kind: PromptKind
    held_out: bool
    pcm: bytes


class ClipVault:
    def __init__(self, root: Path, key_file: Path) -> None:
        self.root = root
        self.key_file = key_file
        self._lock = threading.Lock()
        self._aead: AESGCM | None = None

    def __repr__(self) -> str:
        return "ClipVault(encrypted)"

    # ---- the key ---------------------------------------------------------------------------
    def _cipher(self) -> AESGCM:
        if self._aead is None:
            self._aead = AESGCM(self._load_or_make_key())
        return self._aead

    def _load_or_make_key(self) -> bytes:
        try:
            key = self.key_file.read_bytes()
        except FileNotFoundError:
            key = b""
        if len(key) != KEY_BYTES:
            if key:
                log.warning("the recordings' key file was not a key; a new one was made")
            key = secrets.token_bytes(KEY_BYTES)
            write_private(self.key_file, key)
        return key

    def _rotate_key(self) -> None:
        write_private(self.key_file, secrets.token_bytes(KEY_BYTES))
        self._aead = None

    # ---- sealing ---------------------------------------------------------------------------
    def _seal(self, data: bytes, aad: str) -> bytes:
        nonce = secrets.token_bytes(NONCE_BYTES)
        return MAGIC + nonce + self._cipher().encrypt(nonce, data, aad.encode("ascii"))

    def _open(self, blob: bytes, aad: str) -> bytes:
        if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + NONCE_BYTES + 16:
            raise VaultUnreadable("not a kit file")
        nonce = blob[len(MAGIC) : len(MAGIC) + NONCE_BYTES]
        try:
            return self._cipher().decrypt(nonce, blob[len(MAGIC) + NONCE_BYTES :], aad.encode())
        except InvalidTag:
            raise VaultUnreadable("does not open with the kit's key") from None

    # ---- clips -----------------------------------------------------------------------------
    def _session_dir(self, session_id: str) -> Path:
        if not SESSION_ID_RE.fullmatch(session_id):
            raise KitRefused("bad_request", "That is not a session id.")
        return self.root / session_id

    def sessions(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if SESSION_ID_RE.fullmatch(p.name))

    def put(self, clip: ClipIn) -> ClipStored:
        pcm = clip.pcm()
        folder = self._session_dir(clip.session_id)
        header = json.dumps({"kind": clip.kind.value, "held_out": clip.held_out}).encode()
        sealed = self._seal(header + b"\n" + pcm, f"{clip.session_id}/{clip.prompt_id}")
        with self._lock:
            if not folder.exists() and len(self.sessions()) >= MAX_SESSIONS:
                raise KitRefused("too_large", "The laptop holds too many sessions; delete some.")
            target = folder / f"{clip.prompt_id}{SUFFIX}"
            if not target.exists() and self._count(folder) >= MAX_CLIPS_PER_SESSION:
                raise KitRefused("too_large", "That session holds as many recordings as it may.")
            private_dir(self.root)
            private_dir(folder)
            write_private(target, sealed)
            count = self._count(folder)
        return ClipStored(
            session_id=clip.session_id,
            prompt_id=clip.prompt_id,
            seconds=round(pcm_seconds(len(pcm)), 3),
            clips=count,
        )

    @staticmethod
    def _count(folder: Path) -> int:
        return sum(1 for _ in folder.glob(f"*{SUFFIX}")) if folder.is_dir() else 0

    def count(self, session_id: str) -> int:
        return self._count(self._session_dir(session_id))

    def clips(self, session_id: str, *, kind: PromptKind | None = None) -> list[StoredClip]:
        """The session's clips, opened (in prompt order); an unreadable one is skipped."""
        folder = self._session_dir(session_id)
        found: list[StoredClip] = []
        for path in sorted(folder.glob(f"*{SUFFIX}")) if folder.is_dir() else []:
            prompt_id = path.name.removesuffix(SUFFIX)
            try:
                data = self._open(path.read_bytes(), f"{session_id}/{prompt_id}")
                header, _, pcm = data.partition(b"\n")
                meta = json.loads(header)
                clip = StoredClip(
                    session_id, prompt_id, PromptKind(meta["kind"]), bool(meta["held_out"]), pcm
                )
            except (VaultUnreadable, ValueError, KeyError, OSError):
                log.warning("a recording could not be opened and was skipped")
                continue
            if kind is None or clip.kind is kind:
                found.append(clip)
        return found

    # ---- what the laptop engines heard ------------------------------------------------------
    def put_heard(self, session_id: str, rows: tuple[HeardRow, ...]) -> None:
        folder = self._session_dir(session_id)
        heard = SessionHeard(session_id=session_id, rows=rows)
        sealed = self._seal(heard.model_dump_json().encode(), f"{session_id}/{HEARD}")
        with self._lock:
            if not folder.is_dir():
                return  # deleted while it was being scored: keep nothing
            write_private(folder / HEARD, sealed)

    def heard(self, session_id: str) -> SessionHeard:
        path = self._session_dir(session_id) / HEARD
        try:
            data = self._open(path.read_bytes(), f"{session_id}/{HEARD}")
            return SessionHeard.model_validate_json(data)
        except FileNotFoundError:
            return SessionHeard(session_id=session_id)
        except (VaultUnreadable, ValueError):
            log.warning("the session's scoring results could not be opened")
            return SessionHeard(session_id=session_id)

    # ---- delete ----------------------------------------------------------------------------
    def delete(self, session_id: str | None) -> int:
        """Remove one session's recordings (or every one, which also replaces the key)."""
        with self._lock:
            ids = [session_id] if session_id is not None else self.sessions()
            removed = 0
            for sid in ids:
                folder = self._session_dir(sid)
                removed += self._count(folder)
                if folder.exists():
                    shutil.rmtree(folder)
            if session_id is None:
                self._rotate_key()
        return removed


__all__ = ["MAX_CLIPS_PER_SESSION", "MAX_SESSIONS", "ClipVault", "StoredClip", "VaultUnreadable"]

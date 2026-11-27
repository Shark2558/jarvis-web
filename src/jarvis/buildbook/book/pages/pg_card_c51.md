---
page: pg_card_c51
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "src/jarvis/integrations/vault.py": "b766226c56672432"
  "src/jarvis/keyring.py": "092c625e649b4b88"
---
## In plain words
JARVIS keeps many kinds of your private data sealed: the document vault, notes, faces, bills, home links, wardrobe photos, the numbers on your call cards and more. The Keyring gives each kind its own lock. It starts from one master key and turns it into a separate key for every purpose, so the key for your notes can't open your vault (`src/jarvis/keyring.py`). The keys are never stored anywhere; they live only in the server's memory while it runs. If anything looks wrong, a key that doesn't fit or a sealed record that was tampered with, it refuses and reports an error rather than guessing.

## Example (made up)
At 10:05 JARVIS files Ravi's scanned rent agreement in the vault. It makes a fresh 32-byte key for that one file, locks the file with it, and locks that little key with the vault key, stamped with the file's own id. A week later a careless script copies the locked key onto a different file's record. When JARVIS tries to open that record, the stamp doesn't match, opening fails with an error, and neither file is shown to anyone. The rent agreement stays sealed exactly as it was.

## How it works
`Keyring` starts from one root key, the token key in the settings, and refuses it unless it is exactly {{fact:src/jarvis/integrations/vault.py:KEY_BYTES}} bytes with at least {{fact:src/jarvis/integrations/vault.py:MIN_DISTINCT_KEY_BYTES}} different byte values, which turns away a typed or placeholder key (`src/jarvis/keyring.py`).
`decode_key` reads that key from its encoded text and rejects one that is empty, the wrong length, all zeros or not random enough.
With no token key at all, `Keyring` is never built, so the sealed features stay off instead of storing anything in clear.
For each purpose, such as the vault, notes, faces, bills, the wardrobe or phone calls, `Keyring` derives a separate key from the root with HKDF and SHA-256 and a label that names the purpose, and keeps it in memory only.
A purpose that isn't on its fixed list is an error, never a fresh key (`src/jarvis/keyring.py`).
All sealing goes through `TokenCipher`: AES-256-GCM with a fresh random {{fact:src/jarvis/integrations/vault.py:NONCE_BYTES}}-byte nonce each time and the record's own label bound into the seal, so a sealed value moved onto another record fails to open.
For one vault file, `Keyring` hands out a fresh random data key and seals that data key under the vault key with the file's label.
Single-use ticket hashes, and the references that tell JARVIS a phone number was called before, use a keyed SHA-256 hash whose key comes from a separate label, never from a sealing key (`src/jarvis/keyring.py`).
The one raw secret, for Web Push, is derived the same way under its own label and must be {{fact:src/jarvis/keyring.py:MIN_SECRET_BYTES}} to {{fact:src/jarvis/keyring.py:MAX_SECRET_BYTES}} bytes long (`src/jarvis/keyring.py:MAX_SECRET_BYTES`).
Your Google tokens use the root key directly in `DocTokenStore`, which seals the access and refresh tokens as one blob bound to your user id in `tokens` and leaves only the account, expiry and scopes readable, so tokens saved before the Keyring existed still open.
`MemoryTokenStore` keeps tokens in memory for development and tests only.

## What it costs
Nothing. The Keyring keeps no data of its own and calls no outside service while it works: every key is worked out inside JARVIS's server with a standard cryptography library (`src/jarvis/keyring.py`). The only outside piece is the one token key, held in Google's Secret Manager, which JARVIS reads from its settings when it starts.

## When it fails
It fails closed: an unknown purpose, a wrong key, a wrong label or a tampered blob raises `VaultError`, and nothing is shown. Without the token key the vault, notes and the other sealed features stay switched off (`src/jarvis/keyring.py`). A Google token record that can't be read is reported as broken by `DocTokenStore`, so you reconnect Google instead of seeing a server error. Changing the master key means old sealed data no longer opens and Google must be linked again; no tool re-seals old data under a new key (`src/jarvis/keyring.py`). Keys, blobs and plain text are never logged, and the Keyring prints as hidden.

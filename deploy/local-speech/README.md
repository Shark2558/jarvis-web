# The laptop speech kit: your laptop as JARVIS's ears and voice

R5.2 "Your voice" (row 383). A small speech program on your own laptop listens and speaks for
JARVIS, so Google's free minutes last longer and nothing costs money. It also keeps the voice
session's recordings, encrypted, and (later) trains your own "Hey Jarvis" there.

It is **off until you set it up**. Without it, or whenever the laptop is off, asleep or busy,
JARVIS uses Google as today, then the browser: you see the same messages as before.

## What it costs

₹0 a month: everything runs on your laptop (its electricity). The downloads are free.

## Your privacy

- Your speech goes from JARVIS to **your laptop** over an encrypted Tailscale link and comes back
  as text; JARVIS's cloud keeps no audio.
- The voice session's recordings stay **only on the laptop**, encrypted with a key that only the
  kit holds. "Delete my recordings" in JARVIS removes them (and, if you ask, the wake-word files
  trained from them). Deleting everything also replaces that key, so no leftover copy can be read.
- Nothing the kit hears or says is written to a log.

## What this kit leaves out (read this first)

This first version of the kit (1.0.0) is honest about what it could check when it was built:

- **No model file is pinned yet.** The kit only ever downloads a file whose SHA-256 is written in
  `models.json`. For the two English listening models, Hugging Face publishes the SHA-256 of the
  big `model.bin` but not of their three small files (`config.json`, `tokenizer.json`,
  `vocabulary.txt`), so they wait. Until they are pinned, `models install` says "nothing to
  install" and every engine says "Not installed". The table below, and `models.json` under
  `left_out`, give the reason for each.
- **The English voice (Kokoro) and Piper are not installed.** Kokoro's helper that turns words into
  sounds (espeak-ng, through `phonemizer`) and today's Piper are GPL-3.0, so they are left out of
  the pinned packages. JARVIS keeps using Google's voice.
- **The Indian-language engines** (IndicConformer, Indic Parler-TTS) need PyTorch and their own
  model code; they are left out until they can be pinned. R18's calls keep using cloud speech.
- **The graphics card** is used only if NVIDIA's CUDA 12 and cuDNN 9 are already installed on the
  laptop (NVIDIA's own licence); otherwise the kit uses the CPU, which is fine for listening.

| Engine slot | Model | Licence | In kit 1.0.0 | Why |
|---|---|---|---|---|
| `whisper-small` | faster-whisper small, English listening (float16 weights, run as int8) | MIT | Left out | Its three small files have no published SHA-256 |
| `whisper-medium` | faster-whisper medium, if the voice session shows it is better | MIT | Left out | The same |
| `kokoro` | Kokoro-82M, English voice | Not checked | Left out | Its phonemiser is GPL-3.0 (Workshop decision) |
| `piper` | Piper voices, the light fallback voice | Not checked | Left out | piper-tts is GPL-3.0 (Workshop decision) |
| `indic-conformer` | IndicConformer 600M, Indian-language listening | Not checked | Left out | Needs PyTorch (Workshop decision) |
| `indic-parler` | Indic Parler-TTS, Indian-language voice | Not checked | Left out | Needs PyTorch (Workshop decision) |

## One-time setup (about 30 minutes, mostly downloads)

1. **Get JARVIS's folder.** On GitHub: Code -> Download ZIP, then right-click the zip ->
   Extract All -> `C:\JARVIS`. The kit is in `C:\JARVIS\deploy\local-speech`.
2. **Install the kit.** Start -> type PowerShell -> open Windows PowerShell (NOT as
   administrator), then type:

   ```
   cd C:\JARVIS\deploy\local-speech
   powershell -ExecutionPolicy Bypass -File .\install-kit.ps1
   ```

   It offers to install Python 3.12 and Caddy (type Y; both free), makes the kit's private folder
   (only your account can open it), installs the kit's pinned, hash-checked packages and the
   pinned model files, and adds Start -> JARVIS -> JARVIS Speech Kit.
3. **Tailscale** (free Personal plan): install it from tailscale.com/download and sign in. In the
   Tailscale admin console turn on **HTTPS certificates** (DNS page) and allow **Funnel** when it
   asks. The first address can take up to 10 minutes to start working.
4. **Start the kit and test it:**

   ```
   powershell -ExecutionPolicy Bypass -File .\start-kit.ps1 -SelfTest
   ```

   It makes your key the first time, starts the kit and its gate, opens Funnel and prints:

   ```
   Address: https://my-laptop.tail1234.ts.net:8443
   Key: <43 characters>
   ```

   then the self-test's report.
5. **Paste the self-test's report into JARVIS's chat.** It says what passed and what to fix; it
   never contains your key, your folder names or anything you said.
6. **Give JARVIS the address and the key, once.** The address is the setting
   `JARVIS_LOCAL_SPEECH_URL`; the key goes in the secret `jarvis-local-speech-key` (deploy step,
   see `deploy/cloudrun.sh`). The call desk on this same laptop finds the kit by itself on
   `http://127.0.0.1:11436/v1`.

Keep the window open and the laptop awake. Ctrl+C stops the kit and closes Funnel on its port
(nothing else of your Tailscale setup is touched).

**Offline brain on the same laptop?** It already uses Funnel's port 8443. Start the kit with
`.\start-kit.ps1 -HttpsPort 10000` and give JARVIS the address it prints (it ends in `:10000`).
The script refuses to take over a port that serves something else.

## Why it is safe

- The address is a **Tailscale Funnel** name (`<machine>.<tailnet>.ts.net`): the encrypted
  connection ends **on your laptop**. JARVIS only accepts that kind of address, over https.
- Anyone can *find* the address, so the gate (Caddy, on 127.0.0.1:11436) answers only the kit's
  own requests and only with your key: everything else is 401 or 404, and with no key set at all
  it refuses everything (503). The kit's server (127.0.0.1:11437) is never published, and checks
  the key again itself.
- The key is 256 random bits, kept in the kit's private folder and in JARVIS's secrets.
- To change the key: delete the file named `key` in `%LOCALAPPDATA%\JARVIS\LocalSpeech`, start
  the kit again, and give JARVIS the new key.

## Handy commands

Run them in PowerShell from `C:\JARVIS\deploy\local-speech`, with
`$py = "$env:LOCALAPPDATA\JARVIS\LocalSpeech\venv\Scripts\python.exe"`:

| Command | What it does |
|---|---|
| `& $py -I -m jarvis.localspeech installed` | What this kit installed: models (with licences) and packages |
| `& $py -I -m jarvis.localspeech models` | What may be installed, and what was left out and why |
| `& $py -I -m jarvis.localspeech models verify` | Re-checks every model file's SHA-256 |
| `& $py -I -m jarvis.localspeech delete-recordings` | Deletes every recording on this laptop (asks you to type DELETE) |
| `.\start-kit.ps1 -SelfTest` | Starts the kit and prints the report to paste |

## Problems

| You see | What to do |
|---|---|
| "Missing: caddy" | Open a new PowerShell window (after installing), or run install-kit.ps1 again. |
| "The kit is not installed yet" | Run install-kit.ps1 (step 2). |
| "Port 11436 is already in use" | A kit is already running: close that window first. |
| "Funnel's port 8443 already serves something else" | Use `-HttpsPort 10000` (see above). |
| "Funnel did not start" | Tailscale admin console -> allow Funnel for this laptop; try again in 10 minutes. |
| The self-test says an engine is "Not installed" | Expected in kit 1.0.0 until its model is pinned (see above). |
| JARVIS says "The laptop speech kit refused JARVIS's key" | Give JARVIS the key printed by start-kit.ps1 again. |

## For maintainers: pinning a model

A model goes into `models.json` under `models` only with: its slot, a short model name, its page
(`source`) and a fixed `revision` (a commit), its licence (one of
`jarvis.localspeech.protocol.PERMISSIVE_LICENCES`), and every file with its https address **at
that revision**, its size and its SHA-256 taken from the source itself. Remove it from
`left_out` in the same change. `tests/test_r52_v1_deploy.py` checks the manifest.

**Checked for the two Whisper slots (27 Nov 2026, nothing downloaded).** Each `model.bin` SHA-256
below was read from two Hugging Face pages that agree, and their sizes agree too: the API tree
(`https://huggingface.co/api/models/Systran/faster-whisper-<size>/tree/<revision>`, `lfs.oid`)
and the raw LFS pointer (`https://huggingface.co/Systran/faster-whisper-<size>/raw/<revision>/model.bin`).
Licence: `license: mit` in each model card; the repos ship no LICENSE file. They are conversions
of `openai/whisper-small` and `openai/whisper-medium`, which Hugging Face lists as Apache-2.0
(both permissive).

| Engine slot | Revision | File | SHA-256 | Size (bytes) |
|---|---|---|---|---|
| `whisper-small` | `536b0662742c02347bc0e980a01041f333bce120` | `model.bin` | `3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671` | 483,546,902 |
| `whisper-medium` | `08e178d48790749d25932bbc082711ddcfdfbc4f` | `model.bin` | `9b45e1009dcc4ab601eff815b61d80e60ce3fd8c74c1a14f4a282258286b51ae` | 1,527,906,378 |

Still missing for both: `config.json` (2,370 and 2,257 bytes), `tokenizer.json` (2,203,239) and
`vocabulary.txt` (459,861). The Hub keeps them as plain git files, so it publishes only their git
blob id (SHA-1), and every pinned file needs a SHA-256. Both slots stay in `left_out` until each of
those files has a SHA-256 from a primary source, or the model manager learns to check git blob ids.

## Not on Windows?

`start-kit.sh` does the same as `start-kit.ps1` on macOS / Linux. The pinned requirements are
Windows wheels, so make `~/.jarvis-local-speech/venv` with Python 3.12 and the same package
versions yourself, and put JARVIS's `src` folder on its path.

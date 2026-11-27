---
page: pg_card_c79
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "deploy/local-speech/Caddyfile": "b7e08ade699d41a0"
  "deploy/local-speech/README.md": "29e7dff7da9ca847"
  "deploy/local-speech/install-kit.ps1": "87ceb9fa6a7f95d1"
  "deploy/local-speech/models.json": "19a18faa552c8603"
  "deploy/local-speech/requirements-kit.txt": "be70ad8a87ce81f3"
  "deploy/local-speech/start-kit.ps1": "ecbb16eeda2d3c8f"
  "deploy/local-speech/start-kit.sh": "728d2bb9f7e233a6"
  "src/jarvis/localspeech/__init__.py": "e8a65d8faac5a633"
  "src/jarvis/localspeech/__main__.py": "7ae3619b855132f0"
  "src/jarvis/localspeech/audio.py": "5a4cb7f4b792a6a3"
  "src/jarvis/localspeech/client.py": "6e6755da76ff1a32"
  "src/jarvis/localspeech/clips.py": "5b45b1254b5d26e0"
  "src/jarvis/localspeech/desk.py": "2bd10408f3800e30"
  "src/jarvis/localspeech/device.py": "c34efb3500c1bcd2"
  "src/jarvis/localspeech/engines.py": "2fe6537333bdf222"
  "src/jarvis/localspeech/jobs.py": "5a5bb9edae50072c"
  "src/jarvis/localspeech/kitconfig.py": "20c3f6f6670fc014"
  "src/jarvis/localspeech/manager.py": "b05c565b11eb5238"
  "src/jarvis/localspeech/memory.py": "aaf249a96a512bb3"
  "src/jarvis/localspeech/ports.py": "633f3e386df8f548"
  "src/jarvis/localspeech/protocol.py": "45896adc88e845aa"
  "src/jarvis/localspeech/runtimes/__init__.py": "c0e400b522001a34"
  "src/jarvis/localspeech/runtimes/indic_conformer.py": "ebf31ed703047953"
  "src/jarvis/localspeech/runtimes/indic_parler.py": "9cd1d36614478251"
  "src/jarvis/localspeech/runtimes/kokoro.py": "d829c9a586cd46dd"
  "src/jarvis/localspeech/runtimes/mp3.py": "200cf2925b6a2c94"
  "src/jarvis/localspeech/runtimes/piper.py": "2637207e212352a8"
  "src/jarvis/localspeech/runtimes/whisper.py": "d8a5d5dffba8ad74"
  "src/jarvis/localspeech/selftest.py": "0fed98854ca37549"
  "src/jarvis/localspeech/server.py": "8bceea0c8985ec4d"
  "src/jarvis/localspeech/service.py": "8af314be4e6a2165"
  "src/jarvis/localspeech/wakejoin.py": "55ab52012d456166"
  "src/jarvis/localspeech/wakeword/__init__.py": "86b39a91ba7a980a"
  "src/jarvis/localspeech/wakeword/evals.py": "508884210a4c2429"
  "src/jarvis/localspeech/wakeword/fakes.py": "2eab54f51ba55b76"
  "src/jarvis/localspeech/wakeword/formats.py": "589784d27b03c6ba"
  "src/jarvis/localspeech/wakeword/mlp.py": "9408c56e5401e62f"
  "src/jarvis/localspeech/wakeword/onnx_write.py": "d285464bd431ae48"
  "src/jarvis/localspeech/wakeword/owned_train.py": "b02cf713ad5d9974"
  "src/jarvis/localspeech/wakeword/port.py": "6ed44c0b2de39c96"
  "src/jarvis/localspeech/wakeword/runtime.py": "a6cb9a3920082c71"
  "src/jarvis/localspeech/wakeword/service.py": "43c3dc8cf2eba8ef"
  "src/jarvis/localspeech/wakeword/store.py": "59b93d0c6f816a0e"
  "src/jarvis/localspeech/wakeword/streaming.py": "f40214e50c0c63c1"
  "src/jarvis/localspeech/wakeword/synth.py": "854c11974d520e49"
  "src/jarvis/localspeech/wakeword/verifier_train.py": "0fac06005967adc4"
  "tests/test_r52_i1_manager_blob.py": "084078c1c7033627"
  "tests/test_r52_v1_clips.py": "048f57aa71d1c35b"
  "tests/test_r52_v1_deploy.py": "943384953353dda4"
  "tests/test_r52_v1_import_guard.py": "2d172fd0bca32d48"
  "tests/test_r52_v1_manager.py": "e2bd5ff656baa373"
  "tests/test_r52_v1_server.py": "ed2199a53b1bf5a2"
  "tests/test_r52_v1_service.py": "91caca7e65786194"
---
## In plain words
The laptop speech kit is a small speech program on your own laptop: it listens for JARVIS in English, keeps the voice session's recordings and trains your own "Hey Jarvis", so Google's free minutes last longer (`deploy/local-speech/README.md`). It is off until you set it up, and that takes your hands: install it, start it with its self-test, paste the report into chat, and give JARVIS its address and key once, from Cloud Shell, with the deploy script's local speech step (`deploy/local-speech/README.md`). Its recordings stay on the laptop, encrypted with a key the cloud never has (`src/jarvis/localspeech/clips.py`). This first kit only listens: its voice and its Indian-language engines are left out, so JARVIS still speaks with Google's voice (`deploy/local-speech/models.json`).

## Example (made up)
On a Sunday morning Meera runs the kit's installer and types Y twice, for Python and for Caddy. About 30 minutes later, most of it the 2 GB of Whisper downloads, she starts the kit with its self-test. It prints the kit's Tailscale address and a key of 43 characters, and a report: the pinned files, the encryption and the gate pass, and the round trip says it needs an English voice. She pastes the report into chat, runs the local speech step in Cloud Shell and pastes the address and key. From then on, while the laptop is awake, the laptop hears what she says to JARVIS.

## How it works
The installer offers Python and Caddy and installs each only when you type Y, makes the kit's private folder, which only your account can open, and installs its hash-pinned packages and model files (`deploy/local-speech/install-kit.ps1`, `deploy/local-speech/requirements-kit.txt`). The start script makes the key the first time, starts the speech server and its gate on the laptop alone, and publishes the gate with Tailscale Funnel on a port of its own, so the offline brain can share the laptop; it refuses a port that already serves something else (`deploy/local-speech/start-kit.ps1`). The gate passes only the kit's own requests and only with the key (`deploy/local-speech/Caddyfile`). The server checks the key again in constant time, reads at most {{fact:src/jarvis/localspeech/protocol.py:BODY_MAX}} bytes of a request and logs no body, audio, text, header or key (`src/jarvis/localspeech/server.py`). Engines sit in slots loaded on demand: one goes on the graphics card if it fits beside the others with {{fact:src/jarvis/localspeech/engines.py:GPU_MARGIN_MB}} MB left free, else on the CPU, and a failure on the card is tried once more on the CPU (`Slots`). Listening and speaking run one at a time; while a long job runs or requests queue, the kit's health says slow, so JARVIS falls back (`KitService`). The model manager downloads only the files pinned in `deploy/local-speech/models.json`, each to a temporary name, and keeps it only when its size and SHA-256 match, with a licence file beside each model and a list of what it installed (`ModelManager`). A small text file kept in plain git may be pinned by its git blob id instead, a recorded exception; model weights always need a SHA-256 (`src/jarvis/localspeech/manager.py`). This kit pins only Whisper small and medium; Kokoro and Piper (GPL parts) and the Indian-language engines (they need PyTorch) are listed as left out and say "Not installed" (`deploy/local-speech/models.json`). Each recording is an AES-256-GCM file with its session and prompt bound in, at most {{fact:src/jarvis/localspeech/clips.py:MAX_CLIPS_PER_SESSION}} a session; deleting every recording also replaces their key (`ClipVault`). One long job runs at a time, the session's scoring or the wake word's training, kept in memory only (`JobRunner`). The self-test's report holds no key, folder name, Tailscale name or anything you said (`src/jarvis/localspeech/selftest.py`).

## What it costs
₹0 a month: everything runs on your laptop, on its electricity, and the downloads are free (`deploy/local-speech/README.md`). Every time the laptop listens, Google doesn't, so its free minutes last longer (`deploy/local-speech/README.md`). The graphics card is used only if NVIDIA's own CUDA and cuDNN are already on the laptop; otherwise the CPU listens, which is fine for listening (`deploy/local-speech/README.md`).

## When it fails
Not set up, or the laptop off, asleep or busy: JARVIS uses Google, then the browser, with the usual messages (`deploy/local-speech/README.md`). With no key, or one under {{fact:src/jarvis/localspeech/protocol.py:KEY_MIN_CHARS}} characters, the server refuses every request, and a wrong key is refused too (`src/jarvis/localspeech/server.py`). A download whose size or hash doesn't match is deleted and nothing is installed; a file that isn't pinned is never downloaded (`ModelManager`). An engine that breaks mid-request answers "engine not ready" and loads again next time (`KitService`). A recording moved to another name or changed doesn't open (`ClipVault`). A second long job is refused as busy (`JobRunner`). With no voice in this kit, the self-test's round trip says it needs an English voice, so the plan's first-audio and listening-speed bars are not measured yet (`check_round_trip`).

---
page: pg_card_c82
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "evals/wakeword/run.py": "d01cdade86bcf329"
  "src/jarvis/api/static/console-wakeword-own.js": "b7dbfaba4c3cd8eb"
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
  "src/jarvis/voice/wakeword_api.py": "270a5741613f3b8f"
  "tests/test_r52_v4_console_wake.py": "b124720853d8e178"
  "tests/test_r52_v4_formats.py": "feaa1187bc2913fa"
  "tests/test_r52_v4_kit.py": "cfbdf7474f1e62b0"
  "tests/test_r52_v4_train.py": "8acf155934644b09"
  "tests/test_r52_v4_wakeword_api.py": "b9e7b084941baecb"
---
## In plain words
After a scored voice session, Voice, Your voice offers two buttons, and each needs your press: "Train my Hey Jarvis", a small check trained on your voice that sits on top of today's wake word, and "Train my own wake word", a whole model of your own that takes the laptop a few hours (`src/jarvis/voice/wakeword_api.py`). Both train on your laptop from the session's clips, and the files they make stay there, sealed (`src/jarvis/localspeech/wakejoin.py`). The console uses a file only when it checks out, and a wake is only ever a wake: nothing here approves anything (`src/jarvis/api/static/console-wakeword-own.js`). Today's wake-word model and the feature models every stage reads are licensed for personal, non-commercial use only, so a public launch needs your own model and a permissive source for those feature models first (`src/jarvis/localspeech/wakeword/formats.py`).

## Example (made up)
Farhan finishes his voice session at 21:10 and presses "Train my Hey Jarvis". A few minutes later the laptop has trained a check from his 24 "Hey Jarvis" clips and tested it on 6 it kept apart. Next morning a TV advert says something close to "Hey Jarvis" and the old model scores it high, but his check scores it low, so the console stays asleep. When he says it from the kitchen, it wakes. He leaves "Train my own wake word" for a weekend, since it would need the laptop's voices, which this kit doesn't have yet.

## How it works
Training runs on the kit from every clip of the session: your "Hey Jarvis" clips, with a few kept apart for testing, and your other lines as the "not it" examples; it needs at least {{fact:src/jarvis/localspeech/wakeword/port.py:MIN_WAKE_CLIPS}} wake clips to learn from (`src/jarvis/localspeech/wakeword/port.py`). One run goes at a time, and Delete my recordings stops it at its next step (`WakewordService`). Stage one, your verifier, follows openWakeWord's custom-verifier method, reimplemented in NumPy: a logistic regression on the {{fact:src/jarvis/localspeech/wakeword/formats.py:FRAMES}} by {{fact:src/jarvis/localspeech/wakeword/formats.py:DIM}} embedding windows the console's detector already computes, saved as a plain JSON file (`src/jarvis/localspeech/wakeword/verifier_train.py`, `VerifierFile`). The console runs it after today's detector when that scores at least the file's gate, and the verifier's answer then replaces the score (`src/jarvis/api/static/console-wakeword-own.js`). Stage two, your own model, is a small network on the same windows, written as ONNX in the console's format with its own manifest and your licence (`src/jarvis/localspeech/wakeword/owned_train.py`). It replaces today's model only when it passes every bar and is no worse on your kept-apart clips and on synthetic TV; a worse model is never swapped in (`src/jarvis/localspeech/wakeword/evals.py`). The files are sealed on the laptop with AES-256-GCM under their own key, so you may keep them when you delete the recordings (`FileSealer`). The cloud keeps no wake-word file: it passes the kit's file through only after checking its hash, its licence, the status it was announced with, its format and, for stage one, that it reads the very embedding model the console runs (`WakewordHandlers`). In the browser the files stay in that tab's memory, and no audio, score or feature leaves it (`src/jarvis/api/static/console-wakeword-own.js`). The mock eval gates both stages, each with a control that must fail it (`evals/wakeword/run.py`).

## What it costs
₹0: the training runs on your laptop, on its electricity, and nothing is sent to an outside service (`src/jarvis/localspeech/wakeword/service.py`). Your own model takes a few hours of the laptop's time, unattended, and only when you choose it (`src/jarvis/localspeech/wakeword/owned_train.py`).

## When it fails
No session yet, too few wake clips, or the kit off: it says so, and today's wake word stays (`src/jarvis/localspeech/wakeword/port.py`, `WakewordHandlers`). A verifier that didn't pass its tests, or a model that hasn't beaten today's, isn't used (`src/jarvis/localspeech/wakeword/service.py`). A file whose hash, licence or format doesn't check out isn't used, and the wake word works exactly as before (`src/jarvis/api/static/console-wakeword-own.js`). This kit has no voices, so stage one trains without other speakers' "Hey Jarvis" and its tests say other speakers were not measured, and stage two refuses in plain words until a permissively licensed voice is pinned (`src/jarvis/localspeech/wakejoin.py`). No openly licensed TV recordings could be pinned, so the false-wake test hears synthetic TV (`src/jarvis/localspeech/wakeword/synth.py`).

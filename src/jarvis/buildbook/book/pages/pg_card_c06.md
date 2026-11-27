---
page: pg_card_c06
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "src/jarvis/api/static/console-voice-barge.js": "e6f3f5f38f7a27fe"
  "src/jarvis/api/static/console-voice-capture.js": "09f45d685b4b5ea0"
  "src/jarvis/api/static/console-voice-commands.js": "5fce1e68f0de2831"
  "src/jarvis/api/static/console-voice-conversation.js": "a38e545b0e8e0fa3"
  "src/jarvis/api/static/console-voice-devices-match.js": "77d44118460dadc6"
  "src/jarvis/api/static/console-voice-devices-panel.js": "78cfb8b6c2809e36"
  "src/jarvis/api/static/console-voice-devices.js": "b4c87df5f59fe1b6"
  "src/jarvis/api/static/console-voice-loop-browser.js": "99b3682d4d1b3222"
  "src/jarvis/api/static/console-voice-loop-glue.js": "e7c4f4e36a17595a"
  "src/jarvis/api/static/console-voice-mic.js": "a0e90bc03322a5c8"
  "src/jarvis/api/static/console-voice-micoff.js": "08a923d63f6f93f2"
  "src/jarvis/api/static/console-voice-pace.js": "d455ab39738c612b"
  "src/jarvis/api/static/console-voice-phrases.js": "b45dc811d8b70af6"
  "src/jarvis/api/static/console-voice-speech.js": "3ac2e294edcc281c"
  "src/jarvis/api/static/console-voice-wake.js": "906de367b5e856ef"
  "src/jarvis/api/static/console-voice.js": "69224f06a0ee9c0e"
  "src/jarvis/api/static/console-wakeword.js": "6dca020ffbb88b58"
  "src/jarvis/api/static/voice-capture-worklet.js": "4b1dbae36264b075"
  "src/jarvis/api/static/wakeword/LICENSE-openwakeword-code.txt": "c71d239df91726fc"
  "src/jarvis/api/static/wakeword/LICENSE.txt": "687d8f82513e3aa3"
  "src/jarvis/api/static/wakeword/MANIFEST.txt": "803754f20d36e7f8"
---
## In plain words
This is everything that listens and speaks inside the console, on your own device. Say "Hey Jarvis" and the console wakes; a small model in the browser spots the phrase, so that sound never leaves the device (`src/jarvis/api/static/console-wakeword.js`). You can talk over JARVIS to stop it, switch the microphone hard off, give simple spoken commands with the AI off, and choose the speaker and microphone it uses (`src/jarvis/api/static/console-voice-mic.js`).

## Example (made up)
At 21:30, while cooking, you say "Hey Jarvis, remind me to switch off the rice in ten minutes". JARVIS answers aloud and keeps listening for a follow-up. Halfway through its next reply you say "stop", and it stops at once. Your earphones run flat, so you say "switch to the speakers", and JARVIS moves its voice there without asking the AI. When guests arrive you press Ctrl + Shift + Space, hear "Microphone off", and nothing is captured until you tap the mic again.

## How it works
`src/jarvis/api/static/console-voice-capture.js` opens the microphone once, with echo cancellation and noise suppression, and `src/jarvis/api/static/voice-capture-worklet.js` turns it into the small frames every listener shares, storing nothing. `src/jarvis/api/static/console-wakeword.js` runs the openWakeWord models in the page to spot "Hey Jarvis", and `src/jarvis/api/static/console-voice-wake.js` pauses it while JARVIS listens or speaks, with a stricter score during its own voice. The models are for personal, non-commercial use only, and each file is pinned by its SHA-256 sum (`src/jarvis/api/static/wakeword/MANIFEST.txt`). Since {{fact:release.label}}, when the page offers your own wake-word files from the laptop, it runs your own model in place of today's and your personal check after the score; without them everything is exactly as before (`src/jarvis/api/static/console-wakeword.js`). `src/jarvis/api/static/console-voice-mic.js` runs the conversation, through the voice service or the browser's own recognition, with a follow-up window and a standby before it hands back to the keyboard (`src/jarvis/api/static/console-voice-conversation.js`). `src/jarvis/api/static/console-voice-barge.js` lets you interrupt: with earphones any speech does, with speakers you say its name, and an echo guard ignores JARVIS's own words. With your voice print active on this device, a voice that opens the gate lowers JARVIS's volume and a check clip is judged on the device first: with earphones only your voice stops him, with speakers another voice is dropped unsent, and without a print nothing changes (`src/jarvis/api/static/console-voice-barge.js`). `src/jarvis/api/static/console-voice-commands.js` handles "mic off", "stop" or "switch to my earphones" before anything reaches the chat, so they work with the AI off. `src/jarvis/api/static/console-voice-micoff.js` is the hard lock: only your click, tap or key press unlocks the microphone. `src/jarvis/api/static/console-voice-speech.js` splits a reply into speakable pieces and plays them in order, never reading code or tables. `src/jarvis/api/static/console-voice-devices.js` keeps your chosen speaker and microphone, and a device is named aloud only by its kind (`src/jarvis/api/static/console-voice-devices-match.js`). `src/jarvis/api/static/console-voice-phrases.js` edits your words to recognise.

## What it costs
Nothing: the wake word, the commands, interruptions and the device choice all run in your browser (`src/jarvis/api/static/console-wakeword.js`). Speech sent to Google costs only what the voice service counts beyond its free allowance (`src/jarvis/api/static/console-voice.js`).

## When it fails
Without microphone permission the console says so in a plain line, and typing still works (`src/jarvis/api/static/console-voice-mic.js`). If the cloud voice is down, busy or past your limit, this device falls back to the browser's own voice and recognition (`src/jarvis/api/static/console-voice.js`). A wake-word module that reports an error is switched off with a plain line (`src/jarvis/api/static/console-voice-wake.js`). An unplugged microphone, or permission taken back, ends the capture cleanly (`src/jarvis/api/static/console-voice-capture.js`). While the lock is on, nothing opens the microphone (`src/jarvis/api/static/console-voice-micoff.js`).

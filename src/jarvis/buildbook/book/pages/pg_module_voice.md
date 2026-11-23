---
page: pg_module_voice
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/static/console-voice-barge.js": "bf50083732d8c6e4"
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
  "src/jarvis/api/static/console-wakeword.js": "f339e7c5c064c699"
  "src/jarvis/api/static/voice-capture-worklet.js": "4b1dbae36264b075"
  "src/jarvis/api/voice.py": "12fae33259cea1d6"
  "src/jarvis/voice/catalogue.py": "a7d5423e32e6e4ec"
  "src/jarvis/voice/commands.py": "f332fa895b7fb4d0"
  "src/jarvis/voice/google_cloud.py": "70b3d0637df4a58b"
  "src/jarvis/voice/service.py": "3bdab151205a517d"
  "src/jarvis/voice/settings.py": "d54739fc34d24078"
  "src/jarvis/voice/speakable.py": "ad9c138afcb8137b"
  "src/jarvis/voice/wav.py": "a96c3a9747fcada4"
---
## In plain words
Voice lets you talk to JARVIS and hear it answer, in the console on your laptop or phone. Say "Hey Jarvis" and it listens; the wake word is spotted on your own device, so no sound leaves it before then. You interrupt JARVIS by speaking, switch the microphone off with one click or by saying "mic off", and choose which speaker and microphone it uses. Your words become text, and its replies become speech, through Google's cloud voices inside their free allowance, with the browser's own voice standing in whenever Google's is off.

## Example (made up)
Meenu is cooking with flour on her hands. She says "Hey Jarvis, what's on my calendar this afternoon?" Her laptop chimes, records 3 seconds, and the console shows the words it heard. JARVIS answers in a calm British voice: "You have the school meeting at 4, Ma'am." Halfway through the next sentence she says "stop" and it goes quiet at once. Later she says "mic off"; the mic button turns grey and nothing is captured until she taps it again. Her afternoon used 41 seconds of listening and 380 characters of speech, all inside the free allowance.

## How it works
The microphone is opened once by `src/jarvis/api/static/console-voice-capture.js`, which passes the sound from `src/jarvis/api/static/voice-capture-worklet.js` to everything that listens. `src/jarvis/api/static/console-wakeword.js` runs the openWakeWord models in your browser to spot "Hey Jarvis", so the wake word never leaves your device. A spoken clip goes as a WAV file to `POST /v1/voice/transcribe`, and `parse_wav` accepts only mono sound between {{fact:src/jarvis/voice/wav.py:MIN_SECONDS}} and {{fact:src/jarvis/voice/wav.py:MAX_SECONDS}} seconds long. `transcribe` adds this turn's hints through `turn_hints`: your attached files' names and nouns from your own messages. `GoogleSTT` then asks Google's Speech-to-Text for up to {{fact:src/jarvis/voice/google_cloud.py:MAX_ALTERNATIVES}} guesses in the language set by `voice_language`. `src/jarvis/api/static/console-voice-commands.js` checks every spoken transcript first, so "mic off", "stop" and "switch to my earphones" work locally, with or without the AI. Everything else goes to the chat like typed text, and `src/jarvis/api/static/console-voice-speech.js` cuts the reply into pieces to read aloud. The server's `speakable` strips markdown, code, tables and links ("the link on screen") and caps each piece at {{fact:src/jarvis/voice/speakable.py:MAX_SPEAK_CHARS}} characters. `speak` sends it to `GoogleTTS` in the voice you chose, at a speed between {{fact:src/jarvis/voice/catalogue.py:RATE_MIN}} and {{fact:src/jarvis/voice/catalogue.py:RATE_MAX}} times normal. Before any priced call, `VoiceService` checks the free allowance and your monthly limit, then meters what Google bills. `src/jarvis/api/static/console-voice-barge.js` lets you interrupt: by speaking when you wear earphones, by saying JARVIS's name on speakers, or with a tap. Mic off is a hard lock (`src/jarvis/api/static/console-voice-micoff.js`): nothing is captured until you switch it back. `VoiceSettingsStore` keeps your voice, speed, wit and words to recognise, changed with `PUT /v1/voice/settings`; audio itself is never stored. `src/jarvis/api/static/console-voice-devices.js` chooses the speaker and microphone.

## What it costs
Nothing inside the free allowance JARVIS claims each month: {{fact:settings.voice_tts_free_chars}} characters of speech per voice type and {{fact:settings.voice_stt_free_seconds}} seconds of listening (`Allowance`). Above it, speech costs {{fact:settings.voice_price_chirp3_hd_usd_per_m}} US dollars per million characters for the HD voices or {{fact:settings.voice_price_studio_usd_per_m}} for the Studio voices, and listening {{fact:settings.voice_price_stt_usd_per_min}} dollars a minute, shown in rupees and counted against your monthly limit (`src/jarvis/voice/catalogue.py`). The wake word, local commands and the browser's own voice are free (`src/jarvis/api/static/console-wakeword.js`).

## When it fails
If Google's speech can't be reached or isn't switched on, the console uses the browser's own voice and recognition (`src/jarvis/api/static/console-voice.js`). A Google refusal or missing credentials marks that service off for {{fact:src/jarvis/voice/service.py:DOWN_TTL_S}} seconds, so JARVIS stops retrying (`VoiceService`). At your monthly limit a priced call is refused with status 402 and nothing is spent (`speak`). A clip that isn't valid audio gets status 422 "bad_audio" (`transcribe`). A blocked microphone gets a plain line on how to allow it, and typed chat still works (`src/jarvis/api/static/console-voice-capture.js`).

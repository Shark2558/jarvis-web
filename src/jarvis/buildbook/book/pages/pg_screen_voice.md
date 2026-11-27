---
page: pg_screen_voice
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
  "src/jarvis/api/static/console-voice-session.js": "b2eb59ecd520231a"
  "src/jarvis/api/static/console-voice-speech.js": "3ac2e294edcc281c"
  "src/jarvis/api/static/console-voice-wake.js": "906de367b5e856ef"
  "src/jarvis/api/static/console-voice.js": "69224f06a0ee9c0e"
  "src/jarvis/api/static/console-voiceprint-math.js": "83f681b57d604b50"
  "src/jarvis/api/static/console-voiceprint-panel.js": "60adde7bfeb9da33"
  "src/jarvis/api/static/console-voiceprint.js": "581978076fad5644"
  "src/jarvis/api/static/console.html": "6bf7eb0ad6bc821c"
  "src/jarvis/api/voice.py": "45227c5b0f4437c3"
  "src/jarvis/api/voice_profile_routes.py": "e63118737cf04ef2"
---
## In plain words
Voice is how JARVIS sounds and listens. You talk to JARVIS with the microphone button beside the message box, and he answers out loud. The Voice panel holds the choices: which British voice he uses, how fast he speaks, how much dry wit he allows himself, and, for this device, the speech engine, when replies are spoken, whether he keeps listening after a reply, how you interrupt him, your sound devices and the words he should know. "Hey Jarvis" is a separate switch, off until you turn it on. The panel also shows this month's voice use (`src/jarvis/api/static/console-voice.js`). In "Your voice" you read short lines aloud, so JARVIS learns which listening engine hears you best and your laptop trains your own "Hey Jarvis" (`src/jarvis/api/static/console-voice-session.js`). Speaker check lets only your voice interrupt him on this device (`src/jarvis/api/static/console-voiceprint-panel.js`).

## Example (made up)
At 7:30, hands full in the kitchen, you tap the microphone and say "What's on today?". JARVIS answers aloud with your three meetings, then keeps listening. You say "Jarvis, stop" halfway through a long reply, and he stops. You then say "Remind me to call the bank at five", he confirms, and after 20 seconds of silence he says he is switching to the keyboard. In the Voice panel you add "Tanvir" under the words to recognise, because he heard the name wrongly last week. On Sunday you read the voice session's 120 lines; the results say JARVIS now listens to you with Whisper small on your laptop, and you press Train my Hey Jarvis.

## How it works
When the panel opens, it reads your voice settings, the voices on offer, the wit levels and the month's use from `GET /v1/voice` (`src/jarvis/api/static/console-voice.js`). Voice, Speed and Wit are yours on every device and are saved through `PUT /v1/voice/settings` (`src/jarvis/api/voice.py:put_settings`). Preview, and every spoken reply, use `POST /v1/voice/speak` in the chosen voice (`src/jarvis/api/voice.py:speak`). The "On this device" choices stay in this browser only: the microphone switch, speech engine, Speak replies, Send what I say straight away, Keep listening after replies, Interrupt JARVIS by, the waiting times, Sound cues and Voice finish (`src/jarvis/api/static/console-voice.js`). When you speak with the cloud engine, the browser cuts your speech into a short sound clip and `POST /v1/voice/transcribe` turns it into words (`src/jarvis/api/voice.py:transcribe`). With the browser engine, your words appear in the message box as you speak (`src/jarvis/api/static/console-voice.js`). The mic-off button beside the microphone cuts it completely until you switch it on again (`src/jarvis/api/static/console.html`). "Say Hey Jarvis" listens on this device only, and no audio leaves it until it hears those words (`src/jarvis/api/static/console-voice.js`). "Your voice" shows from `GET /v1/voice/profile` where your session stands, the listening engines ranked for your voice, the chosen one and a switch to correct your usual mishearings. Its pop-up holds the session in blocks with a break after each; Record stops by itself when you pause, and each clip goes on to your laptop through `PUT /v1/voice/profile/session/clips/{prompt_id}`. Score my voice (`POST /v1/voice/profile/session/score`) then names the engine JARVIS now listens with. After a scored session, "Train my Hey Jarvis" and "Train my own wake word" have your laptop train from your recordings (`POST /v1/voice/profile/wakeword/train`). Delete my recordings asks first (`POST /v1/voice/profile/recordings/delete`); your profile and the wake-word files stay. Speaker check keeps a voice print, made from a reading or your session's clips, encrypted in this browser, never uploaded, and it approves nothing (`src/jarvis/api/static/console-voiceprint.js`). With it on, a voice that tries to interrupt JARVIS is checked on the device first, and only yours stops him (`src/jarvis/api/static/console-voice-barge.js`).

## What it costs
The cloud voice uses Google's speech service in your own Google Cloud project; the This month section shows how much of the free allowance is used and, beyond it, an estimate in rupees (`GET /v1/voice`). The browser's own recognition and voice cost nothing, though your audio then goes to the browser's maker (`src/jarvis/api/static/console-voice.js`). Past your monthly limit, the speak route refuses rather than spend more (`src/jarvis/api/voice.py:speak`). The voice session's comparison lines use Google's free listening minutes; once they run out it shows the rupees first, and Google hears more only after you type YES, or you go on without it (`src/jarvis/api/static/console-voice-session.js`). Speaker check runs in this browser and costs nothing (`src/jarvis/api/static/console-voiceprint.js`).

## When it fails
With no voice service on the server, the panel says it is not available and the browser's own voice is used where it has one. If the cloud voice is off or has no credentials, the panel says so and JARVIS uses this browser's voice. A clip larger than {{fact:src/jarvis/api/voice.py:MAX_AUDIO_BYTES}} bytes is refused (`src/jarvis/api/voice.py:transcribe`). Too many requests in a minute give "Too many requests just now. JARVIS will ask again in a few seconds." If the microphone is blocked, a line under the message box explains how to allow it. With `voice_profile_enabled` off, the profile's routes answer status 503 and "Your voice" says why (`src/jarvis/api/voice_profile_routes.py:_part`). With no speaker-check model, Speaker check says so and any voice interrupts as before, as after a slow or failed check (`src/jarvis/api/static/console-voiceprint.js`).

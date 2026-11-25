---
page: pg_service_google_cloud_text_to_speech
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/config.py": "3d154bdd78268162"
  "src/jarvis/voice/google_cloud.py": "70b3d0637df4a58b"
  "src/jarvis/voice/service.py": "3bdab151205a517d"
---
## In plain words
Google Cloud Text-to-Speech turns written text into natural speech. It is JARVIS's voice: when you talk to JARVIS or switch on spoken replies, the reply is sent to Google, which returns it as sound, in one of the British voices you choose in Voice settings. What goes to Google is only the text to be spoken; JARVIS stores no audio and never writes the text into its logs. With cloud voice switched off, or if Google is unavailable, the console uses your browser's own built-in voice instead, which costs nothing and sends nothing to Google.

## Example (made up)
At 7:30 you ask aloud: "What's my first meeting?" JARVIS writes the answer, 84 characters long, and sends it to Google with your chosen HD voice. The sound comes back in under a second and plays. The month's voice counter goes from 41,200 to 41,284 characters, well inside the free allowance.

## How it works
`build_voice_service` switches the cloud voice on only with `voice_cloud` on; `google_engines` then makes the speech client, which signs in as JARVIS's own Google service account, so there is no extra key (`src/jarvis/voice/service.py`). `GoogleTTS` asks Google for compressed sound at your chosen speed, and each call, sign-in included, has {{fact:src/jarvis/voice/google_cloud.py:DEADLINE_S}} seconds in all, with no retry, because a late voice is worse than the browser's voice now (`src/jarvis/voice/google_cloud.py`). A reply of at most {{fact:src/jarvis/voice/service.py:MAX_TEXT_IN}} characters is accepted and shortened to what is worth speaking (`SpeakRequest`). Before each call `VoiceService` checks the deployment's free allowance, `voice_tts_free_chars` ({{fact:settings.voice_tts_free_chars}} characters a month for each voice type): a call it still covers goes ahead, and one that would be priced is checked against your monthly limit first. Above it, a call is priced at `voice_price_chirp3_hd_usd_per_m` ({{fact:settings.voice_price_chirp3_hd_usd_per_m}} US dollars a million characters) for the HD voices or `voice_price_studio_usd_per_m` ({{fact:settings.voice_price_studio_usd_per_m}}) for the Studio voices (`VoiceService`). The list of voices is kept for {{fact:src/jarvis/voice/google_cloud.py:VOICES_TTL_S}} seconds, and a failed list is not asked for again for {{fact:src/jarvis/voice/google_cloud.py:VOICES_FAIL_TTL_S}} seconds (`GoogleTTS`). If Google says the service is off or the credentials are missing, `VoiceService` stops asking for {{fact:src/jarvis/voice/service.py:DOWN_TTL_S}} seconds.

## What it costs
Nothing in rupees inside the free allowance: JARVIS claims only {{fact:settings.voice_tts_free_chars}} characters a month for each voice type, a margin below Google's own free amount. Above it, each spoken reply is priced at the dollar rates above, turned into rupees and counted against your monthly limit. Google's free allowance resets on Pacific-time months and is shared across your billing account.

## When it fails
Google slow, busy or down: the console speaks the reply in your browser's own voice (`src/jarvis/voice/service.py:VoiceService`). A service switched off in your Google project shows as unavailable in Voice settings. A voice or text Google rejects gives "Google rejected that voice or text." (`GoogleTTS`). At your monthly limit, a priced cloud call is refused before it is made, while calls inside the free allowance go on.

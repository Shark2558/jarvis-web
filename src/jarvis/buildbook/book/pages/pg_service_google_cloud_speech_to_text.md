---
page: pg_service_google_cloud_speech_to_text
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/config.py": "e223e4b9e6e6333b"
  "src/jarvis/voice/google_cloud.py": "70b3d0637df4a58b"
  "src/jarvis/voice/service.py": "3bdab151205a517d"
---
## In plain words
Google Cloud Speech-to-Text turns a recording of your voice into written words. It is how JARVIS listens: after you say "Hey Jarvis", which your own device hears without sending anything, the console records what you say next and JARVIS sends that one short clip to Google, which sends back the text. What goes to Google is the audio of that turn and a short list of hint words that help it spell names right: words you added in Voice settings and, for that turn, the names of your attached files and nouns from your own messages. JARVIS stores no audio and never writes what you said into its logs. With cloud listening off, the browser's own recognition is used instead.

## Example (made up)
At 21:05 you say: "Hey Jarvis, add oat milk to groceries." The clip is three seconds long. Google returns "add oat milk to groceries" and two other guesses. JARVIS adds the item. The month's listening counter goes from 12 minutes 40 seconds to 12 minutes 55 seconds, as Google billed the short clip as a whole step.

## How it works
`build_voice_service` switches cloud listening on only with `voice_cloud` on, and `google_engines` signs in as JARVIS's own Google service account, so there is no extra key (`src/jarvis/voice/service.py`). `GoogleSTT` sends the clip with your language, `voice_language` ({{fact:settings.voice_language}}), automatic punctuation, and Google's short-clip model for clips up to {{fact:src/jarvis/voice/google_cloud.py:SHORT_CLIP_S}} seconds, the long one otherwise (`src/jarvis/voice/google_cloud.py`). It asks for {{fact:src/jarvis/voice/google_cloud.py:MAX_ALTERNATIVES}} guesses, which costs nothing extra; the other guesses help the "understood as" check (`_alternatives`). Hint words go in a fixed order: the base list, the honorific, this turn's hints, up to `voice_hint_words` ({{fact:settings.voice_hint_words}}), then your own words (`VoiceService`). If Google refuses a request that carried your own words, `VoiceService` tries once more with the base list alone, so one bad word never stops listening. Each call has {{fact:src/jarvis/voice/google_cloud.py:DEADLINE_S}} seconds in all, sign-in included, and is never retried for being slow (`GoogleSTT`). `VoiceService` checks the free allowance first, `voice_stt_free_seconds` ({{fact:settings.voice_stt_free_seconds}} seconds a month for the deployment); a priced call is checked against your monthly limit, then counted on the time Google says it billed.

## What it costs
Nothing in rupees inside the free allowance: JARVIS claims only {{fact:settings.voice_stt_free_seconds}} seconds of listening a month, a margin below Google's own free amount. Above it, listening is priced at `voice_price_stt_usd_per_min` ({{fact:settings.voice_price_stt_usd_per_min}} US dollars a minute), turned into rupees and counted against your monthly limit. Google may bill a short clip in whole steps, and its allowance resets on Pacific-time months.

## When it fails
Google slow, busy or unreachable: the console falls back to the browser's own recognition. A service switched off in your Google project is remembered as unavailable for {{fact:src/jarvis/voice/service.py:DOWN_TTL_S}} seconds, with no calls meanwhile (`VoiceService`). A clip with no speech is reported as "no speech". At your monthly limit, a priced call is refused before it is made.

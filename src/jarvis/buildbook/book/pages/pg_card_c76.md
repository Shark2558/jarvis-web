---
page: pg_card_c76
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "evals/calls_language/harness.py": "70d6107ad5ca78ff"
  "evals/calls_language/run.py": "644272915cc99d39"
  "evals/calls_language/suites.py": "80477250dab6e85c"
  "src/jarvis/api/static/console-calls-langs.js": "cd555ffe064312f7"
  "src/jarvis/calls/join_speech.py": "86d3f9a9a39c3909"
  "src/jarvis/calls/langcheck/__init__.py": "b191fe7a0f1b9545"
  "src/jarvis/calls/langcheck/api.py": "f1a5ed89b54bae04"
  "src/jarvis/calls/langcheck/fleurs.py": "46d38040fe11afaa"
  "src/jarvis/calls/langcheck/runner.py": "7708514f57b166ad"
  "src/jarvis/calls/langcheck/scoring.py": "cdff02d85ee9af8d"
  "src/jarvis/calls/langcheck/select.py": "17f8aff69333bcc1"
  "src/jarvis/calls/langcheck/sentences.py": "da6c3c76ebdcd1b4"
  "src/jarvis/calls/prices.py": "09530bc93cd5d9f2"
  "src/jarvis/calls/speech/__init__.py": "7cd8cca15eae7567"
  "src/jarvis/calls/speech/audio.py": "0282570850200ed1"
  "src/jarvis/calls/speech/azure.py": "cd27af97dbaf8e28"
  "src/jarvis/calls/speech/bhashini.py": "32a72dec885b81c5"
  "src/jarvis/calls/speech/build.py": "f03b52cba95aad09"
  "src/jarvis/calls/speech/catalogue.py": "09ee31b83a942427"
  "src/jarvis/calls/speech/detect.py": "d25e44790afcfe3e"
  "src/jarvis/calls/speech/errors.py": "da58392f33e803b9"
  "src/jarvis/calls/speech/google.py": "114d5796ec1d46c7"
  "src/jarvis/calls/speech/lines.py": "3599a5f0c2bc41ed"
  "src/jarvis/calls/speech/meter.py": "ee673080feff66fe"
  "src/jarvis/calls/speech/phoneline.py": "79408543a2713deb"
  "src/jarvis/calls/speech/rest.py": "59a2324a4c347664"
  "src/jarvis/calls/speech/sarvam.py": "bc73208ec89e647f"
  "src/jarvis/calls/speech/translate.py": "07a528c755b8b23c"
---
## In plain words
This part is how JARVIS hears the other person in a call and speaks back, and how it decides which languages a call may use. It uses cloud speech, free first: Google's, which shares the free monthly allowance of JARVIS's own voice; Microsoft Azure's free tier if you add its key, which stops at its allowance and can never bill; Bhashini if it is set up; and Sarvam, which is paid and stays off until you say yes (`src/jarvis/calls/speech/catalogue.py`). A language reaches a call card only after it passes the language check: hearing phone-quality clips correctly, speaking call sentences clearly enough to be heard back, and answering fast enough (`src/jarvis/calls/langcheck/select.py`). You start the check in Calls, Languages, and see its price before anything is sent.

## Example (made up)
Arjun opens Calls, Languages and presses Run language check. The estimate reads ₹0, inside the free allowances, so he presses Run. Half an hour later the table shows Hindi, Tamil and Malayalam passed on Google, Odia not checked because no option set up speaks it, and Malayalam marked "not yet heard by a native speaker". On his next call card he can add Malayalam beside English.

## How it works
Every option talks to its vendor with plain web requests and no vendor kit, in one call format of {{fact:src/jarvis/calls/speech/audio.py:SAMPLE_RATE}} samples a second (`src/jarvis/calls/speech/audio.py`). A request is retried only where the vendor surely did not process it, so nothing is billed twice, and the vendor's own error words never reach you (`src/jarvis/calls/speech/rest.py`). Every rupee goes through JARVIS's billing once: Google's use is gated and charged on the shared allowance, Azure's free units are held before each request, Sarvam and Bhashini are counted in rupees, all under the label "calls" (`src/jarvis/calls/speech/meter.py`). In a call, a language uses the cheapest passing option you allow, the one the card's estimate used, and never falls back to an option that didn't pass it (`src/jarvis/calls/join_speech.py`). Google and Sarvam detect the language inside one request; Azure and Bhashini hear each candidate in turn, and every answer is checked against its language's script (`src/jarvis/calls/speech/detect.py`). The language check first plans each language and option with its rupees and sends nothing; a run above what you accepted is refused before it starts, and one runs at a time, one request at a time (`src/jarvis/calls/langcheck/runner.py`). It fetches {{fact:src/jarvis/calls/langcheck/fleurs.py:CLIPS}} clips a language from Google's open FLEURS set through Hugging Face, and squeezes each into a phone line's band, {{fact:src/jarvis/calls/speech/phoneline.py:BAND_LOW_HZ}} to {{fact:src/jarvis/calls/speech/phoneline.py:BAND_HIGH_HZ}} hertz (`src/jarvis/calls/speech/phoneline.py`). Hearing passes with at least {{fact:src/jarvis/calls/langcheck/scoring.py:HEAR_FACTS_MIN}} of the key facts and a character error rate of at most {{fact:src/jarvis/calls/langcheck/scoring.py:HEAR_CER_MAX}}; a voice passes when another option hears back {{fact:src/jarvis/calls/langcheck/scoring.py:VOICE_FACTS_MIN}} of its sentences' facts; speed needs {{fact:src/jarvis/calls/langcheck/scoring.py:SPEED_FAST_SHARE}} of replies started within {{fact:src/jarvis/calls/langcheck/scoring.py:SPEED_FAST_S}} seconds and {{fact:src/jarvis/calls/langcheck/scoring.py:SPEED_SLOW_SHARE}} within {{fact:src/jarvis/calls/langcheck/scoring.py:SPEED_SLOW_S}} (`src/jarvis/calls/langcheck/scoring.py`). Your scores of {{fact:src/jarvis/calls/langcheck/scoring.py:HUMAN_SAMPLES}} samples need a mean of {{fact:src/jarvis/calls/langcheck/scoring.py:HUMAN_SCORE_MIN}}; until then the language is offered as not yet heard by a native speaker (`src/jarvis/calls/langcheck/select.py`).

## What it costs
Inside the free allowances, ₹0: Google's hearing for calls shares JARVIS's {{fact:settings.voice_stt_free_seconds}} free seconds a month, and Azure's free tier gives {{fact:settings.voice_azure_f0_stt_free_seconds}} seconds of hearing and {{fact:settings.voice_azure_f0_tts_free_chars}} voice characters a month at ₹{{fact:settings.voice_price_azure_f0_inr_per_hour}} (`src/jarvis/calls/speech/meter.py`). Past them Google is charged at the day's rate within your monthly limit. Sarvam costs ₹{{fact:settings.voice_price_sarvam_inr_per_hour}} an hour of hearing, only with your yes. Bhashini's price is unknown and never counted as ₹0 (`src/jarvis/calls/prices.py`). A check run shows its rupees first, and you can accept at most ₹{{fact:src/jarvis/calls/langcheck/api.py:MAX_ACCEPT_INR}} for one (`src/jarvis/calls/langcheck/api.py`).

## When it fails
An option that isn't set up is listed with its reason in plain words (`src/jarvis/calls/speech/build.py`), and a vendor's failure becomes one plain error, never the vendor's text (`src/jarvis/calls/speech/errors.py`). Azure past its allowance stops before any request; Sarvam without your yes sends nothing (`src/jarvis/calls/speech/meter.py`). No network, or Hugging Face refusing, leaves that language unchecked, said plainly, and fewer than {{fact:src/jarvis/calls/langcheck/fleurs.py:MIN_CLIPS}} usable clips give no verdict (`src/jarvis/calls/langcheck/fleurs.py`). After {{fact:src/jarvis/calls/langcheck/runner.py:MAX_ERRORS}} failed requests in a row that option's part ends (`src/jarvis/calls/langcheck/runner.py`). The brain's own check of each language is not built, so it never fails a language, and the speed counts the brain at the fast tier's estimate of {{fact:src/jarvis/calls/langcheck/runner.py:BRAIN_ESTIMATE_S}} seconds (`src/jarvis/calls/langcheck/runner.py`).

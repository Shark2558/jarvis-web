---
page: pg_service_google_agent_platform
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/llm/tryon_gemini.py": "3e233dc06019ff0c"
---
## In plain words
Google Agent Platform is Google Cloud's paid service for running Google's AI models inside your own Google project. JARVIS uses one of its image models for "See it on me": when you are thinking of buying a garment, it makes one preview picture of you wearing it with up to two pieces you own. This is the most personal thing JARVIS sends out, so it is optional, paid, off until you type YES, and you confirm the rupee price before every picture. What goes to Google: your one full-length photo, the new garment's photo, crops of your own pieces and a short instruction made only of fixed words. Google processes it in the region set by `tryon_location` ({{fact:settings.tryon_location}}) and, as a paid Cloud service, does not train on it.

## Example (made up)
You see a navy linen shirt in a shop window and photograph it. In the console you pick "shirt" and "navy", and JARVIS suggests your grey chinos to go with it. The card says about ₹9 with tax; you confirm. Forty seconds later one picture comes back, marked "Generated 2D style preview, not a photo", with the shirt listed as not in your wardrobe.

## How it works
`build` makes the client for the model in `tryon_model` ({{fact:settings.tryon_model}}) at the location in `tryon_location`, with no redirects ever followed (`src/jarvis/llm/tryon_gemini.py`). It signs in as JARVIS's own Google service account and never uses a Gemini developer key, which may train on content (`GeminiTryOn`). Before anything is sent, `_check` refuses a request with too many garments, words that are not fixed words, or an image that is not a JPEG or a PNG. `request_body` puts everything in one request: your photo, the garment's photo, your pieces' crops, and one instruction from `prompt` built from fixed words only, so nothing you or a shop typed reaches the model. The answer is read in a stream under a byte cap, and only the picture is taken: every text part Google sends is thrown away unread, and an answer picture over {{fact:src/jarvis/llm/tryon_gemini.py:ANSWER_MAX_BYTES}} bytes is refused (`_picture`). A call gets {{fact:src/jarvis/llm/tryon_gemini.py:CONNECT_S}} seconds to connect and {{fact:src/jarvis/llm/tryon_gemini.py:CALL_S}} seconds in all (`build`). `usage_of` reads the tokens Google reports, so the cost of each picture is counted from Google's own figures. A blocked picture is reported in a fixed word, never Google's text (`result_of`). The pictures part stays off until `tryon_pictures` is on, which the deploy sets. The YES you type says what Google may keep, including its short-lived cache while `tryon_cache` is on ({{fact:settings.tryon_cache}} by default).

## What it costs
Nothing unless you use it. Each picture is paid, shown in rupees with `tryon_tax_pct` ({{fact:settings.tryon_tax_pct}}) per cent GST included before you confirm. A cap of ₹{{fact:settings.tryon_month_cap_inr}} a month with GST (`tryon_month_cap_inr`) and your overall monthly limit both apply, and an unreadable cap refuses the picture.

## When it fails
Not configured, no permission for JARVIS's account, or the service off: pictures stay off, said in words (`GeminiTryOn`). Any refusal from Google charges nothing and releases the hold. A timeout after sending, or an answer cut short, is marked "may be charged" and kept at the hold (`src/jarvis/llm/tryon_gemini.py`). A picture Google blocks is billed and named in a fixed word.

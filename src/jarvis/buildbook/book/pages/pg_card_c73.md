---
page: pg_card_c73
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "deploy/cloudrun.sh": "768853b09894305d"
  "src/jarvis/api/r13_status.py": "af7163933e6796e4"
  "src/jarvis/api/seeme.py": "7e11a9d91c1d664c"
  "src/jarvis/api/static/console-r111-files.js": "1fec6c5ad6de99be"
  "src/jarvis/api/static/console-r7-send.js": "545d6c2abaf1e8c6"
  "src/jarvis/api/static/console-tryon-me.js": "88bc303d9c049cc3"
  "src/jarvis/api/static/console-tryon-photo.js": "2a921f5c94ec59bd"
  "src/jarvis/api/tryon_wiring.py": "47536713ac1021b3"
  "src/jarvis/billing/spend.py": "fad90ef7371200bc"
  "src/jarvis/llm/tryon.py": "839f8746d75d6c7d"
  "src/jarvis/llm/tryon_gemini.py": "3e233dc06019ff0c"
  "src/jarvis/wardrobe/seeme/__init__.py": "f74a53a075cdcaa4"
  "src/jarvis/wardrobe/seeme/books.py": "d103b249fa95db85"
  "src/jarvis/wardrobe/seeme/cap.py": "5cdf796e4ccd7dae"
  "src/jarvis/wardrobe/seeme/consent.py": "7371b09d1cab0188"
  "src/jarvis/wardrobe/seeme/estimate.py": "76c50c3ec51b879c"
  "src/jarvis/wardrobe/seeme/garments.py": "94ac94bcac056e2c"
  "src/jarvis/wardrobe/seeme/jobs.py": "59217f10afd72e2c"
  "src/jarvis/wardrobe/seeme/make.py": "5f40b732edadfa8a"
  "src/jarvis/wardrobe/seeme/pair.py": "faf86b938c31c4b5"
  "src/jarvis/wardrobe/seeme/part.py": "414e788c2a14b47d"
  "src/jarvis/wardrobe/seeme/pictures.py": "35429d93b43ed2d0"
  "src/jarvis/wardrobe/seeme/privacy.py": "43c7dfc7a3518849"
  "src/jarvis/wardrobe/seeme/texts.py": "a0c7c241617f4728"
  "src/jarvis/wardrobe/seeme/vault.py": "49ae7fd81be8201c"
  "tests/r131_fake_tryon.py": "9df0636c0e68e991"
---
## In plain words
See it on me helps when you are thinking of buying something. You give JARVIS the garment's photo from a shop or a website screenshot, it suggests pieces you already own to wear with it, and Google's image model draws one picture of you wearing the combination, marked as a generated preview, not a photo (`src/jarvis/wardrobe/seeme/make.py`). It is optional and paid: off until you type YES to a card that says exactly what is sent, to whom and where, and every picture shows its price before anything is sent (`src/jarvis/wardrobe/seeme/consent.py`). The new garment is never added to your wardrobe.

## Example (made up)
Divya sees a mustard kurta online and saves a screenshot. In Helpers, Wardrobe, See it on me, she uploads it and picks "kurta" and "yellow". JARVIS suggests her white palazzo and tan sandals. The button reads "About ₹9 with GST"; she presses it, and 40 seconds later one picture appears, marked "Generated 2D style preview, not a photo", with "Mustard kurta (not in your wardrobe)" and her two pieces listed beside it. She has spent ₹9 of her ₹300 try-on cap this month.

## How it works
`Consent` accepts only an exact typed YES for the card you were shown, bound to the provider, the model and where it is processed, and stores it sealed.
`PersonPhoto` keeps your one full-length photo sealed, after your device checked it shows one person, and `GarmentStore` keeps the shop photo as untrusted bytes, never reading any text from it (`src/jarvis/wardrobe/seeme/garments.py`).
`Press` runs every gate before spending: pictures switched on, the AI not off, your YES current, only non-private pieces of yours, the price no higher than the one shown, and your overall monthly limit (`src/jarvis/wardrobe/seeme/make.py`).
`TryonCap` then reserves the cost in one transaction against your try-on cap of ₹{{fact:settings.tryon_month_cap_inr}} a month, GST at {{fact:settings.tryon_tax_pct}} per cent included, so two presses at once can't both slip past it (`src/jarvis/wardrobe/seeme/cap.py`).
The call goes through the `TryOnProvider` port, so the wardrobe never names a model; `GeminiTryOn` sends only the photos and fixed words, and discards every text part of Google's answer unread (`src/jarvis/llm/tryon_gemini.py`).
A repeated request gets its first answer, so a retry never charges twice, and `PictureStore` keeps each picture sealed for {{fact:settings.tryon_keep_days}} days unless you keep it.
Only the console can start a picture: no tool, chat, voice or Telegram message can (`src/jarvis/api/seeme.py`).

## What it costs
Nothing unless you use it: the setting `tryon_pictures` is {{fact:settings.tryon_pictures}} by default. Each picture is a paid call to Google's image model, priced from Google's token prices plus GST at {{fact:settings.tryon_tax_pct}} per cent, shown in rupees before you press (`src/jarvis/llm/tryon.py`). Try-on spending stops at ₹{{fact:settings.tryon_month_cap_inr}} a month and also counts against your overall monthly limit (`TryonCap`).

## When it fails
Not set up, or the image service off, means See it on me is off and says so in words (`src/jarvis/wardrobe/seeme/make.py`). If Google answers with an error, nothing is charged and the reserved amount is released (`TryOnNotBilled`). A timeout after sending is treated as "may be charged" and kept at the reserved amount (`TryOnMaybeBilled`). If the cap or your limit can't be read, the press is refused (`TryonCap`). After the model's end date the feature stays off until a newer model and a new YES.

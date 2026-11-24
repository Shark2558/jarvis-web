---
page: pg_module_book
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/book.py": "856e2f5276d6cb59"
  "src/jarvis/api/book_pages.py": "a66e5b4cc11e391e"
  "src/jarvis/api/r6_wiring.py": "a7a1861afa933ec1"
  "src/jarvis/api/static/book.html": "6850d85fff7da878"
  "src/jarvis/api/static/console-book-2d.js": "2200336e767fc26b"
  "src/jarvis/api/static/console-book-3d.js": "5aa19146aa15abe2"
  "src/jarvis/api/static/console-book-flow-layout.js": "e82ff4390e084ac2"
  "src/jarvis/api/static/console-book-flow.js": "40c9366f3318a186"
  "src/jarvis/api/static/console-book-pages.js": "c36a106d91b3e8a0"
  "src/jarvis/api/static/console-book-reader.js": "38e4025b70a98cba"
  "src/jarvis/api/static/console-book-scenes-data.js": "c981408bacaff280"
  "src/jarvis/api/static/console-book-scenes-flow.js": "1e4ad251df6d3b9b"
  "src/jarvis/api/static/console-book-scenes.js": "1fe7a9e734dfe7de"
  "src/jarvis/api/static/console-book-script.js": "b05346ce9a31efc5"
  "src/jarvis/api/static/console-book-show.js": "3a53ebbcf354215b"
  "src/jarvis/api/static/console-book-talk.js": "17d0515bfbb34ddf"
  "src/jarvis/api/static/console-book-tour.js": "658a1caa6aace0a0"
  "src/jarvis/api/static/console-book-voice.js": "a66b7196d43b5663"
  "src/jarvis/api/static/console-book.js": "53d54d63c90501c5"
  "src/jarvis/buildbook/facts_model.py": "8bea9de2df6fc757"
  "src/jarvis/buildbook/gen/compile_pages.py": "3e0ee27256d71703"
  "src/jarvis/buildbook/gen/facts.py": "25ec594fecdba061"
  "src/jarvis/buildbook/gen/facts_cache.py": "bd6bf85ae50fed31"
  "src/jarvis/buildbook/gen/facts_code.py": "c781a59d4e00f8a3"
  "src/jarvis/buildbook/gen/facts_guide.py": "6607c03e4c48accf"
  "src/jarvis/buildbook/gen/facts_routes.py": "75e71f796eeceea2"
  "src/jarvis/buildbook/gen/facts_values.py": "3f353b0cd2766d66"
  "src/jarvis/buildbook/gen/inventory.py": "ac5493391a2b37d9"
  "src/jarvis/buildbook/gen/loc.py": "72deb29b5ea46235"
  "src/jarvis/buildbook/gen/modules.py": "91d1d05ab6410b2e"
  "src/jarvis/buildbook/gen/pages_cli.py": "e7f2e404261ef95c"
  "src/jarvis/buildbook/gen/pages_index.py": "94f193a0b07136a3"
  "src/jarvis/buildbook/gen/refs.py": "43dc033f10d15d81"
  "src/jarvis/buildbook/gen/services.py": "8d8f7cd86b58c405"
  "src/jarvis/buildbook/gen/tour.json": "66d7c8cd3a45e4d9"
  "src/jarvis/buildbook/gen/tour.py": "f1d4843259ac521a"
  "src/jarvis/buildbook/tour_model.py": "aff987eaf7866af6"
  "src/jarvis/buildbook/tour_serve.py": "eb1095ad79715773"
  "src/jarvis/buildbook/writer/carry.py": "d88742644ccf35e0"
  "src/jarvis/buildbook/writer/checks.py": "e753b27107a46f37"
  "src/jarvis/buildbook/writer/fill.py": "15da9b37dca0161e"
  "src/jarvis/buildbook/writer/http.py": "a8ac9b7f1281fa7d"
  "src/jarvis/buildbook/writer/model.py": "d6871549c1709801"
  "src/jarvis/buildbook/writer/packs.py": "f44cc6f5287a2673"
  "src/jarvis/buildbook/writer/pages.py": "ceb29fdba977b643"
  "src/jarvis/buildbook/writer/ports.py": "38f1d0d949120987"
  "src/jarvis/buildbook/writer/privacy.py": "d4078ad08f78acf1"
  "src/jarvis/buildbook/writer/serve.py": "c6115dc83f8a168c"
  "src/jarvis/buildbook/writer/texts.py": "38f334fe9cc95de9"
---
## In plain words
The Build Book is JARVIS's record of itself, one book for each release, sealed in your vault. You read it in the Book panel in several ways: short sections on its architecture, technology, libraries, connections, workflows, limits, costs and decisions; a narrated short tour, or a show you give a guest; and the full book, with a page for every part, module, screen and outside service and a flowchart for each chapter and module. Everything in it comes from the code when the release is built. The Workshop writes the full book's pages while it builds JARVIS, and JARVIS itself calls no AI for the Book, so it costs ₹0 and asks you to approve nothing.

## Example (made up)
Ravi's JARVIS gets a new version on a Wednesday evening, and that night its book is sealed beside the two before it. On Thursday he opens the Book panel, touches his passkey and starts the short tour on his phone. It plays as flat cards, because the screen is narrow, and he stops it at the Costs chapter. On Friday he taps Full book and reads the Costs chapter's page, with its flowchart above How it works. On Saturday the button "Continue: Costs" takes him straight back to it.

## How it works
`src/jarvis/buildbook/gen/facts.py` builds the release's fact pack from the code: every setting, route, constant and count a page may quote, so no number in the Book is typed by hand (`src/jarvis/buildbook/facts_model.py`). `src/jarvis/buildbook/gen/tour.py` fills the Workshop's fixed tour script, `src/jarvis/buildbook/gen/tour.json`, from those facts and times it at {{fact:src/jarvis/buildbook/tour_model.py:PACE_WPM}} words a minute; a guest's copy names no rupees (`_guest_safe`). `src/jarvis/buildbook/gen/pages_index.py` lists every page of the full book, by chapter, module, card, screen and service, and `src/jarvis/buildbook/gen/refs.py` gives each page the files it describes. The Workshop writes each page and flowchart while it builds JARVIS; `src/jarvis/buildbook/gen/pages_cli.py` shows a writer what a page may cite, checks it, and records which version of each cited file it was written from. `check` runs the page checks: every file, name and setting cited must exist, every number must come from the facts, and nothing personal or invented, and no unbuilt work outside a marked paragraph, may slip in (`src/jarvis/buildbook/writer/checks.py`). `compile_pages` turns the written pages into the release's full book, filling each number from the pack (`fill`). A page that is missing or fails a check is the generator's own plain text instead, so the Book never breaks a build (`generator_page`). `GET /v1/book` seals the running release for the main owner when the panel first asks, and `BookPages` later reads a kept release's pages and flowcharts back from the vault (`src/jarvis/buildbook/writer/serve.py`). `src/jarvis/api/static/console-book.js` is the Book panel: Open for me or Show a guest, the sections, the kept releases and the code download. `src/jarvis/api/static/console-book-pages.js` reads the full book, and `src/jarvis/api/static/console-book-flow.js` draws a page's flowchart above its How it works, told by shapes and words, never by colour alone. The show page plays the tour or the guest show: `src/jarvis/api/static/console-book-show.js` runs the lines, and `src/jarvis/api/static/console-book-3d.js` or `src/jarvis/api/static/console-book-2d.js` draws them. `OldWriterSource` keeps the Privacy row "Book writer (old trial)" for what the earlier writer trial stored, until you delete it (`src/jarvis/buildbook/writer/privacy.py`).

## What it costs
₹0: the fact pack, the checks and the compile make no AI call, and JARVIS never asks an AI to write a page (`src/jarvis/buildbook/gen/compile_pages.py`). The tour and the show speak in the browser's free voice unless you switch to the cloud voice (`src/jarvis/api/static/console-book-voice.js`). Only a question you ask after a show is a paid AI reply. The sealed books share your vault's space, at most {{fact:settings.book_max_total_mb}} MB in all.

## When it fails
A page that is missing or fails a check reads "Not written yet" in the full book, and every other page still opens (`src/jarvis/api/static/console-book-pages.js`). A flowchart that won't draw is left out, and its page reads as before (`src/jarvis/api/static/console-book-flow.js`). A release sealed before v6.3.2 has no full book, and the reader says it was sealed before its full book was written (`src/jarvis/buildbook/writer/texts.py`). When the vault can't be read, the full book asks you to try again in a moment (`BookPages`). Too many reads in a minute are refused for a moment.

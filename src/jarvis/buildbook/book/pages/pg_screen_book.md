---
page: pg_screen_book
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/book.py": "856e2f5276d6cb59"
  "src/jarvis/api/book_pages.py": "a66e5b4cc11e391e"
  "src/jarvis/api/book_show.py": "79493ebecfd85611"
  "src/jarvis/api/book_show_hear.py": "b47677d1f77bc10b"
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
  "src/jarvis/api/static/console.html": "9f4c0c68f45e46fe"
---
## In plain words
Book is the console's panel for the Build Book, JARVIS's own record of how each version is built. It shows whether this release's book is sealed in your vault, which releases are kept and how much room they use. Open for me starts your own reading session; Show a guest opens the narrated show for a guest, which holds nothing of yours. Once your session is open you read the book's sections, read the full book a page at a time with its flowcharts, start the show, or download the sealed code of any kept release. Nothing here asks an AI to write anything: the pages were written while JARVIS was built.

## Example (made up)
You open Book on your laptop. The card reads "R14 · Sealed", and Kept releases shows "3 of 3". You tap Open for me; your sign-in is an hour old, so Google asks you to sign in again, and then you touch your passkey. The note says "Open. Read it here or start the show." You open Full book, tap Read beside "Vitals" and follow its flowchart from a meter to an alert. Before you leave you tap End session and choose End, and the note says "Session ended. Its conversation was deleted."

## How it works
When the panel opens it asks `GET /v1/book` for this release, whether it is sealed, the kept releases and the space they use, and asks again while a seal is still running (`src/jarvis/api/static/console-book.js`). Open for me and Show a guest both need a Google sign-in from the last few minutes, then your passkey; with an older sign-in the panel sends you to Google first and picks up where it left off (`src/jarvis/api/static/console-book.js`). `open_book` opens the session and says whose it is: a guest's goes straight to the show page, and yours stays in this tab's memory for the reader (`src/jarvis/api/book_show.py`). With your session open, the sections come from `GET /v1/book/sections`, and an older kept release's from `GET /v1/book/releases/{rid}/sections` (`src/jarvis/api/static/console-book-reader.js`). Download code first asks `ticket` for a single-use ticket, then fetches that release's sealed source as a zip, which is no longer encrypted once it is in your Downloads (`download`). Full book is drawn by `src/jarvis/api/static/console-book-pages.js` from `GET /v1/book/pages`: its parts, chapters and pages, each marked "Written by the Workshop" or "Not written yet", with Read, and Continue to the page you left. A page comes from `GET /v1/book/pages/{page_id}` with In plain words and the example open, and its flowchart is drawn above How it works by `src/jarvis/api/static/console-book-flow.js`, with its steps also as a text list. `primary` lets only the main owner's console read the full book, and a guest's session is refused (`src/jarvis/api/book_pages.py`). Start the show opens the show page in this tab; End session asks first, then `close` ends the session and deletes its conversation (`src/jarvis/api/book_show.py`). Book settings set the creator name in the closing, the show's voice and listening, questions after the show, and whether a brain that may learn from what it reads may answer; switching a voice to the cloud shows what it uses and costs and asks first (`put_settings`).

## What it costs
Reading the panel, the sections and the full book costs nothing: they are read from your vault, with no AI (`src/jarvis/api/book_pages.py`). The show's voice and listening are the browser's, which are free, until you confirm a switch to the cloud and its cost (`src/jarvis/api/static/console-book-reader.js`). A question after the show is one paid AI reply.

## When it fails
While this release is still being sealed, the card says "Sealing this release…" and the panel asks again by itself (`src/jarvis/api/static/console-book.js`). Without passkeys set up the book doesn't open, and it never settles for a sign-in alone. While a guest show holds your consoles, the panel says so and offers Go to the show. A release sealed before its full book existed shows no Full book list (`src/jarvis/api/static/console-book-pages.js`). When the session runs out, the reader closes and the note says "The book session ended."

---
page: pg_screen_book
written_by: Workshop · Mark XXIV
written_on: 2026-11-25
sources:
  "src/jarvis/api/book.py": "856e2f5276d6cb59"
  "src/jarvis/api/book_pages.py": "8ab07f57314892fd"
  "src/jarvis/api/book_show.py": "79493ebecfd85611"
  "src/jarvis/api/book_show_hear.py": "b47677d1f77bc10b"
  "src/jarvis/api/static/console-book-2d.js": "2200336e767fc26b"
  "src/jarvis/api/static/console-book-3d.js": "5aa19146aa15abe2"
  "src/jarvis/api/static/console-book-chapter-view.js": "da77e20367808944"
  "src/jarvis/api/static/console-book-chapter.js": "61e707eb6ebd421d"
  "src/jarvis/api/static/console-book-flow-layout.js": "e82ff4390e084ac2"
  "src/jarvis/api/static/console-book-flow.js": "0809bc67d721385e"
  "src/jarvis/api/static/console-book-fx-cards.js": "5405770133312bf2"
  "src/jarvis/api/static/console-book-fx-chart.js": "65e9b511a4fb604b"
  "src/jarvis/api/static/console-book-fx-plan.js": "5c71ed8daf8824d5"
  "src/jarvis/api/static/console-book-fx.js": "0e96836e0a0485e4"
  "src/jarvis/api/static/console-book-read-app.js": "b466580f5b9ac840"
  "src/jarvis/api/static/console-book-read-data.js": "e454107b9f3a8c13"
  "src/jarvis/api/static/console-book-read-page.js": "98e55aee6e35d779"
  "src/jarvis/api/static/console-book-read-rail.js": "d6ce1b2939b6a1fc"
  "src/jarvis/api/static/console-book-read-search.js": "21156baebe134a11"
  "src/jarvis/api/static/console-book-read.js": "1c6e963f880aa8c3"
  "src/jarvis/api/static/console-book-reader.js": "b36cc940e99b70fa"
  "src/jarvis/api/static/console-book-scenes-data.js": "c981408bacaff280"
  "src/jarvis/api/static/console-book-scenes-flow.js": "1e4ad251df6d3b9b"
  "src/jarvis/api/static/console-book-scenes.js": "1fe7a9e734dfe7de"
  "src/jarvis/api/static/console-book-script.js": "b05346ce9a31efc5"
  "src/jarvis/api/static/console-book-show.js": "3a53ebbcf354215b"
  "src/jarvis/api/static/console-book-talk.js": "17d0515bfbb34ddf"
  "src/jarvis/api/static/console-book-tour.js": "21e2972a31775060"
  "src/jarvis/api/static/console-book-voice.js": "d8758d303187cdc6"
  "src/jarvis/api/static/console-book.js": "1ca3680249aaf9d0"
  "src/jarvis/api/static/console.html": "9f4c0c68f45e46fe"
---
## In plain words
Book is the console's panel for the Build Book, JARVIS's own record of how each version is built. It shows whether this release's book is sealed in your vault, which releases are kept and how much room they use. Open for me starts your own reading session; Show a guest opens the narrated show for a guest, which holds nothing of yours. Once your session is open you read the book's sections, download the sealed code of any kept release, take the Short tour, or tap Read the full book: the full book opens on a page of its own, with its contents, search, a page for every part and a Play button that tells each chapter aloud. Nothing here asks an AI to write anything: the pages and their scripts were written while JARVIS was built.

## Example (made up)
You open Book on your laptop. The card reads "R14 · Sealed", and Kept releases shows "3 of 3". You tap Open for me; your sign-in is an hour old, so Google asks you to sign in again, and then you touch your passkey. The note says "Open. Read the full book, or take the short tour." You tap Read the full book, type "meter" in its search and open the Vitals page, then follow its flowchart from a meter to an alert. Before you leave you tap Close and choose Close, and you are back in the console.

## How it works
When the panel opens it asks `GET /v1/book` for this release, whether it is sealed, the kept releases and the space they use, and asks again while a seal is still running (`src/jarvis/api/static/console-book.js`). Open for me and Show a guest both need a Google sign-in from the last few minutes, then your passkey; with an older sign-in the panel sends you to Google first and picks up where it left off (`src/jarvis/api/static/console-book.js`). `open_book` opens the session and says whose it is: a guest's goes straight to the show page, and yours stays in this tab's memory for the panel (`src/jarvis/api/book_show.py`). With your session open, the sections come from `GET /v1/book/sections`, and an older kept release's from `GET /v1/book/releases/{rid}/sections` (`src/jarvis/api/static/console-book-reader.js`). Download code first asks `ticket` for a single-use ticket, then fetches that release's sealed source as a zip, which is no longer encrypted once it is in your Downloads (`download`). Read the full book moves the session's token into this tab's own storage and opens the full book's page; Short tour does the same for the show page, and a guest only ever reaches the show (`src/jarvis/api/static/console-book.js`). On that page `src/jarvis/api/static/console-book-read-app.js` draws the contents and one page at a time with its flowchart, `src/jarvis/api/static/console-book-read-search.js` searches the release's pages, and a chapter's Play starts `src/jarvis/api/static/console-book-chapter.js`. `primary` lets only the main owner's console read the full book, and a guest's session is refused (`src/jarvis/api/book_pages.py`). End session asks first, then `close` ends the session and deletes its conversation (`src/jarvis/api/book_show.py`). Book settings set the creator name in the closing, the show's voice and listening, questions after the show, and whether a brain that may learn from what it reads may answer; switching a voice to the cloud shows what it uses and costs and asks first (`put_settings`).

## What it costs
Reading the panel, the sections and the full book costs nothing: they are read from your vault, with no AI (`src/jarvis/api/book_pages.py`). A chapter is told in the browser's free voice (`src/jarvis/api/static/console-book-chapter.js`). The show's voice and listening are the browser's, which are free, until you confirm a switch to the cloud and its cost (`src/jarvis/api/static/console-book-reader.js`). A question after the show is one paid AI reply.

## When it fails
While this release is still being sealed, the card says "Sealing this release…" and the panel asks again by itself (`src/jarvis/api/static/console-book.js`). Without passkeys set up the book doesn't open, and it never settles for a sign-in alone. While a guest show holds your consoles, the panel says so and offers Go to the show. When the session runs out, the panel's reader closes and the note says "The book session ended." The full book's page then says the session ended and to open the book again from the Book panel (`src/jarvis/api/static/console-book-read.js`).

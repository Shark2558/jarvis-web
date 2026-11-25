---
page: pg_screen_show
written_by: Workshop · Mark XXIV
written_on: 2026-11-25
sources:
  "src/jarvis/api/book_show.py": "79493ebecfd85611"
  "src/jarvis/api/book_show_hear.py": "b47677d1f77bc10b"
  "src/jarvis/api/static/book.html": "6850d85fff7da878"
  "src/jarvis/api/static/console-book-2d.js": "2200336e767fc26b"
  "src/jarvis/api/static/console-book-3d.js": "5aa19146aa15abe2"
  "src/jarvis/api/static/console-book-script.js": "b05346ce9a31efc5"
  "src/jarvis/api/static/console-book-show.js": "3a53ebbcf354215b"
  "src/jarvis/api/static/console-book-talk.js": "17d0515bfbb34ddf"
  "src/jarvis/api/static/console-book-tour.js": "21e2972a31775060"
  "src/jarvis/api/static/console-book-voice.js": "d8758d303187cdc6"
  "src/jarvis/api/static/console-fx.js": "bb9dd7f373411a5f"
  "src/jarvis/api/static/console-permissions.js": "eb3446689d3bd5f1"
  "src/jarvis/api/static/console-voice-capture.js": "09f45d685b4b5ea0"
---
## In plain words
The Build Book show is a narrated tour of how JARVIS is built, on a separate full-screen page. JARVIS speaks each line while a 3D picture, or flat cards on a phone, shows what the line is about, with captions underneath. You play, pause, step back or forward a line or a scene, jump to a chapter, and ask questions at the end. You start it from the console's Book panel, for yourself or for a guest; a guest's show holds nothing of yours, and every show's conversation is deleted when it ends (`src/jarvis/api/static/book.html`).

## Example (made up)
On Saturday you want to show a friend, Arjun, how your assistant works. You open the show for a guest and confirm with your passkey; your console tabs switch to the show. Arjun presses "Begin the show", and JARVIS narrates the layers while the picture moves. At the end he types "How does it keep my data private?" and JARVIS answers in a few lines. He presses "No more questions", the closing plays, and the page asks for your passkey: you press "Resume with my passkey" and your console is back.

## How it works
The page `src/jarvis/api/static/book.html` holds no data of its own: it asks `GET /v1/book/show/script` for the scenes, their lines and the closing, using a token kept only in this browser tab (`src/jarvis/api/static/console-book-show.js`). The show is opened with `POST /v1/book/open`, which needs your passkey and says whether it is your show or a guest's (`src/jarvis/api/book_show.py:open_book`). Each line is spoken by the browser's own voice by default; the cloud voice is used only when you chose it, through `POST /v1/book/show/speak` (`src/jarvis/api/static/console-book-voice.js`). The 3D picture is drawn by `src/jarvis/api/static/console-book-3d.js`; on a narrow screen, with reduced motion or without WebGL2, `src/jarvis/api/static/console-book-2d.js` shows the same lines as flat cards. While it plays, `POST /v1/book/show/beat` keeps the session alive (`src/jarvis/api/book_show.py:show_beat`). Your own tour remembers the scene you reached in this browser, kept beside the full book's page and chapter, and starts that scene again next time; a guest's tour always starts at the beginning (`src/jarvis/api/static/console-book-tour.js`). Questions are typed or spoken: a spoken one is heard by the browser's own recogniser unless you chose the cloud, and its words land in the box for you to send (`src/jarvis/api/static/console-book-talk.js`). `POST /v1/book/show/ask` answers a question of up to {{fact:src/jarvis/api/book_show.py:QUESTION_MAX}} characters about how JARVIS is built, and refuses anything else (`src/jarvis/api/book_show.py:show_ask`). During a guest's show your consoles are locked, and Resume with your passkey unlocks them (`POST /v1/book/resume`). End asks "End the session?", and closing wipes the page, its token and its audio (`POST /v1/book/close`).

## What it costs
Watching costs nothing: the narration uses the browser's own voice unless you chose the cloud voice (`src/jarvis/api/book_show.py:show_speak`). A spoken question heard by the browser is free too (`src/jarvis/api/book_show_hear.py:show_heard`). Each question answered by JARVIS is a short paid AI reply that counts towards your monthly limit, and with No-AI on no question is sent (`src/jarvis/api/book_show.py:show_ask`).

## When it fails
If the session has ended, the page says "This session has ended. Its conversation was deleted." If the tab has no session, it says to open the book from the console's Book panel. If the cloud voice fails, the show carries on in the browser's voice, or with captions only (`src/jarvis/api/static/console-book-voice.js`). If nothing was heard, it says "I didn't hear any words." and offers typing. If the connection drops (`src/jarvis/api/static/console-book-talk.js`), it says "Can't reach JARVIS. Check your connection."

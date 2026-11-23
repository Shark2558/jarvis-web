---
page: pg_card_c07
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/documents.py": "4847083215e444e0"
  "src/jarvis/api/static/console-attach.js": "3161d36b9a6245de"
  "src/jarvis/api/static/console-r111-files.js": "1fec6c5ad6de99be"
  "src/jarvis/documents/__init__.py": "3c737b537755af62"
  "src/jarvis/documents/archive.py": "0bb8bc3b96dff9ae"
  "src/jarvis/documents/chunking.py": "79578b12de441398"
  "src/jarvis/documents/extract.py": "0378ed94914f3c2a"
  "src/jarvis/documents/imagecheck.py": "c9493d6db166cb83"
  "src/jarvis/documents/isolation.py": "ccdcacc384b01f71"
  "src/jarvis/documents/limits.py": "f2ea6ac55fc5636a"
  "src/jarvis/documents/models.py": "a3753c0a3ca0301d"
  "src/jarvis/documents/note.py": "652e69c25c4c453a"
  "src/jarvis/documents/pictures.py": "0a4964854ed83678"
  "src/jarvis/documents/service.py": "e537496eff979aa5"
  "src/jarvis/documents/sheets.py": "a9cc7bdd9cc15ddc"
  "src/jarvis/documents/slides.py": "f68426e36e736058"
  "src/jarvis/documents/store.py": "f85e221ef2363b28"
  "src/jarvis/documents/tools.py": "502c0ebcb497fe23"
  "src/jarvis/documents/worker.py": "46106b0ca30a4e59"
---
## In plain words
Attach files to a message with the paperclip or by dragging them in, and JARVIS reads them with you: PDF, Word, text, spreadsheets, slides, pictures, a zip, even a whole folder (`src/jarvis/api/static/console-attach.js`). The text is taken out in a sealed-off helper process, the file itself is thrown away, and JARVIS reads or searches that text as it answers (`src/jarvis/documents/service.py`). A picture goes only to a brain that can see and never trains on what it is sent (`src/jarvis/documents/pictures.py`).

## Example (made up)
You drag in a 46-page PDF of your flat's maintenance agreement and a photo of a broken tap, and ask "is this repair covered?". The PDF's text is taken out in three seconds and split into chunks; the photo is cleaned of its camera and location data. JARVIS searches the agreement for "plumbing", reads pages 12 and 13, looks at the photo, and quotes the clause. Before a long reply on a big file, the console shows the likely cost, about ₹6, and waits for your choice.

## How it works
`POST /v1/attachments` takes one file at a time, at most {{fact:src/jarvis/api/documents.py:UPLOADS_PER_MINUTE}} a minute, and `sniff` checks its kind by its name and first bytes (`src/jarvis/api/documents.py`). `extract_isolated` reads it in a fresh child process with no secrets in its environment and caps on CPU, memory and time; one runs at a time, and others queue up to {{fact:src/jarvis/documents/service.py:QUEUE_WAIT_S}} seconds (`src/jarvis/documents/isolation.py`). Spreadsheets give values only, never formulas or macros, and hidden sheets are named but not read (`src/jarvis/documents/sheets.py`). Slides give their text and their notes (`src/jarvis/documents/slides.py`). `read_archive` reads each member of a zip as its own kind, and refuses a password, a zip bomb, a path pointing outside or an archive inside from the directory alone (`src/jarvis/documents/archive.py`). `clean_picture` keeps only what a picture needs, dropping camera and location data without decoding a pixel, and refuses one wider than {{fact:src/jarvis/documents/limits.py:PICTURE_MAX_SIDE}} pixels (`src/jarvis/documents/imagecheck.py`). The text is cut into chunks by `split` and kept in `attachments` with the conversation, and the file is dropped (`src/jarvis/documents/chunking.py`). On sending, `AttachPolicy` allows up to {{fact:settings.attach_max_files}} files and {{fact:settings.attach_total_mb}} MB together, each still yours and waiting (`src/jarvis/documents/limits.py`). The brain reads through `document_tools`, one part or the best passages at a time, fenced as outside text, so any write after that round becomes a card (`src/jarvis/documents/tools.py`). `with_pictures` adds a picture only to the message it came with (`src/jarvis/documents/pictures.py`). `src/jarvis/api/static/console-r111-files.js` packs a folder into one zip in the browser and shows the cost line before a costly reply.

## What it costs
Taking the text out costs nothing; it runs on JARVIS's own server (`src/jarvis/documents/isolation.py`). Reading the text costs the brain's normal tokens, kept bounded because the brain reads parts and passages, never the whole file every turn (`src/jarvis/documents/tools.py`). Pictures kept beside a file are deleted with it (`src/jarvis/documents/store.py`).

## When it fails
A file that is too big, unreadable or of the wrong kind is refused in plain words (`DocumentRejected`). If the extractor stays busy past the queue, the upload says "busy" and suggests trying again after {{fact:src/jarvis/api/documents.py:BUSY_RETRY_S}} seconds (`src/jarvis/api/documents.py`). A child that hits its CPU or memory cap reads as too slow or too complex, and it is always killed (`src/jarvis/documents/isolation.py`). A brain that may train on content never gets your files, and with Documents on "Never" in Permissions, or a setting that can't be read, uploads are refused (`src/jarvis/documents/service.py`). A picture that can't be loaded is said, never silently left out (`src/jarvis/documents/pictures.py`).

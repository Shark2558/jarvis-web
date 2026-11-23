---
page: pg_module_vault
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/documents.py": "4847083215e444e0"
  "src/jarvis/api/static/console-attach.js": "3161d36b9a6245de"
  "src/jarvis/api/static/console-r111-files.js": "1fec6c5ad6de99be"
  "src/jarvis/api/static/console-vault-add.js": "741e210463e7aaeb"
  "src/jarvis/api/static/console-vault.js": "7693be82eb53b3c8"
  "src/jarvis/api/vault.py": "cc8daba16d847fd1"
  "src/jarvis/api/vault_inbox.py": "26546b663f03b975"
  "src/jarvis/documents/archive.py": "0bb8bc3b96dff9ae"
  "src/jarvis/documents/imagecheck.py": "c9493d6db166cb83"
  "src/jarvis/documents/limits.py": "f2ea6ac55fc5636a"
  "src/jarvis/documents/pictures.py": "0a4964854ed83678"
  "src/jarvis/documents/sheets.py": "a9cc7bdd9cc15ddc"
  "src/jarvis/documents/slides.py": "f68426e36e736058"
---
## In plain words
This module is how documents reach JARVIS. Attaching files to a message (a PDF, a Word file, a spreadsheet, slides, a photo, a zip or a whole folder) lets JARVIS read them for that conversation; each file itself is thrown away and only its text stays with the chat. The vault is different: a locked cupboard for papers you keep, such as ID, insurance and certificates. Each file is sealed with its own key, JARVIS reminds you before something expires, and nothing opens until you prove it's you. The DigiLocker import folder brings documents you share from the DigiLocker app into the vault without uploading them again.

## Example (made up)
Lakshmi drags her car insurance PDF and 2 photos of a dented bumper onto a message and asks what the policy covers. JARVIS reads all 3, strips the camera and location details from the photos, and answers. She then adds the policy to the vault; it finds an expiry date of 31 March 2027 in the PDF and asks her to confirm it. On 1 March 2027 a reminder says the policy expires in 30 days. At the garage she taps Open on the policy, her phone asks for her fingerprint, and the PDF downloads through a link that works once.

## How it works
The paperclip and drag-and-drop in `src/jarvis/api/static/console-attach.js` send each file to `POST /v1/attachments`, where `upload` judges its kind by its name and its bytes together, never by what the browser claims. A message carries at most {{fact:settings.attach_max_files}} files, {{fact:settings.attach_total_mb}} MB together and {{fact:src/jarvis/documents/limits.py:MAX_PICTURES}} pictures (`src/jarvis/documents/limits.py`). The text is taken out by a limited child process, one file at a time: `read_workbook` reads only an Excel file's values, never formulas or macros, and `read_deck` reads slides with their notes. `read_archive` refuses a zip with a password, a hidden bomb, a path pointing outside or an archive inside it before unpacking anything, then reads each member as its own kind. A folder you drop is packed into one zip in your browser first (`src/jarvis/api/static/console-r111-files.js`). `clean_picture` checks a photo's structure without decoding a pixel and drops camera and location data, and `with_pictures` shows it only to a brain that can see, with the message it came with. `discard` removes a file you take off before sending, and uploads are limited to {{fact:src/jarvis/api/documents.py:UPLOADS_PER_MINUTE}} a minute (`_limit`). The vault panel, `src/jarvis/api/static/console-vault.js`, lists your documents from `GET /v1/vault`, and `src/jarvis/api/static/console-vault-add.js` adds one through `POST /v1/vault/upload`. Fields found in a PDF, such as an expiry date, come back as a proposal you confirm with `item_patch`. Opening a file needs `unlock`: your passkey when you have one, otherwise a fresh Google sign-in, and only in the console in your browser (`_console_only`). Each open then takes a single-use ticket from `file_ticket`, and `download` sends the file only after its audit line is written. `lock` ends the unlock at once, and `item_delete` puts a document in Recently deleted. The import folder is `src/jarvis/api/vault_inbox.py`: you pick a Drive folder shared with JARVIS (`PUT /v1/vault/inbox`), and `inbox_check` brings new files into the vault, skipping any it has seen.

## What it costs
Taking text out of a file and keeping the vault cost nothing: both run on JARVIS's own server with no outside service (`src/jarvis/api/documents.py`, `src/jarvis/api/vault.py`). Reading a long file's text into a reply costs the brain's usual price for that much text, and the console shows a rupee estimate before a costly send (`src/jarvis/api/static/console-r111-files.js`).

## When it fails
A file that is too big, unreadable, password-protected or of the wrong kind is refused in plain words (`DocumentRejected`). When the reader is busy with another file, the upload is refused as busy with a retry after {{fact:src/jarvis/api/documents.py:BUSY_RETRY_S}} seconds, and an upload slower than {{fact:src/jarvis/api/documents.py:READ_TIMEOUT_S}} seconds is stopped (`src/jarvis/api/documents.py`). If the vault's unlock or download can't be written to the audit trail, nothing opens (`download`). A used or expired download link says "Open it again." (`download`). Without JARVIS's encryption key the vault stays off. Files the import folder skips are listed with the reason, and nothing is imported twice (`inbox_view`).

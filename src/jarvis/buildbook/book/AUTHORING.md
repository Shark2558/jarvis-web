Version v6.3.2 · 24 Nov 2026, 03:50 IST · Release R6.3.1 · Status: Current · Owner: 🛠 Mark XXIV

# Writing the Build Book's pages

This folder holds the full Build Book as the Workshop writes it during development
(docs/plans/r6-3-1-book-at-build.md, decisions D1 to D6): one page file for each of the 153
indexed pages in `pages/`, and one flowchart for each chapter and module in `flows/`. JARVIS
never calls an AI for the Book; the generator compiles these files into each release.

Nothing in this folder is ever a page's reference: the generator's view of the repository
leaves `src/jarvis/buildbook/book/` out, so these files are never cited, indexed or counted,
and a page you are still writing never stops a build as an "uncommitted change".

## Who reads the pages

The reader is the owner, not a programmer. Write for him in short everyday sentences, with
British spelling (colour, behaviour, organise, licence as the noun), "JARVIS" for the assistant
and "you" for the owner. Every page describes what the code does today, read from the code itself.

## The workflow

Run every command from the repository's top folder with the source on the path
(`PYTHONPATH=src`). The first command on a tree builds its fact pack (about half a minute); it is
kept in `build/book-cache/` (git-ignored), so every later command takes a second or two. Writing a
page never invalidates it; changing code does.

1. `python -m jarvis.buildbook.gen pages --list`: every page with its kind, title and status:
   `missing` (not written), `stale` (a file it cites changed since its stamp, or it was never
   stamped), `failing` (a check fails) or `ok`.
2. `python -m jarvis.buildbook.gen pages --pack <page_id>`: the page's title, kind, refs (the
   files it is about), what it may cite, every fact of its slice with its value and whether it is
   verified, its card from the guide, and the generator's plain text that readers see until the
   page passes.
3. Read the real code behind every ref, not only the pack. A page never describes a feature the
   code doesn't show.
4. Write `src/jarvis/buildbook/book/pages/<page_id>.md` (the format below) without a `sources`
   block. For a chapter or a module, also write `src/jarvis/buildbook/book/flows/<page_id>.json`.
5. `python -m jarvis.buildbook.gen pages --check <page_id> ...` until the only problem left is
   `stale: not stamped yet`. With no ids it checks every page; add `--allow-missing` to check
   all you have written without failing on the pages nobody has written yet.
6. `python -m jarvis.buildbook.gen pages --stamp <page_id> ...`: writes the `sources` block from
   the files as they are now. It refuses a page with any problem but staleness.
7. `pages --check` the stamped pages once more (exit 0), then commit and push every few pages
   (`docs(book): ...` with the release's trailers). Servers restart: an unpushed page is lost.

When a later release changes a file a page cites, that page turns `stale`. Read the change,
rewrite what it changed on the page, check, stamp, and commit it in the same pull request. CI runs
`pages --check` on every pull request: a missing, stale or failing page fails it.

## The page file

One file a page, named exactly after the page id: `pages/pg_card_c16.md`. It opens with YAML
front matter between two `---` lines, then the five sections.

| Field | What it holds |
|---|---|
| `page` | The page id, equal to the file name (without `.md`) and to an indexed page |
| `written_by` | Who wrote it, at most 60 characters: `Workshop · Mark XXIV` |
| `written_on` | The day it was written, `2026-11-24` |
| `sources` | Written only by `--stamp`: each ref of the page and the first 16 hex characters of the SHA-256 of that file's bytes |

No other field is allowed, and no YAML anchors or aliases. Never edit `sources` by hand.

The body is R6.3's five-section wire format, exactly these headings, in this order, with nothing
before the first: `## In plain words`, `## Example (made up)`, `## How it works`,
`## What it costs`, `## When it fails`. Never write "Where in the code": the generator adds it
from the page's refs.

## The writing rules

- **In plain words**: what it is and why it matters to the owner.
- **Example (made up)**: one worked example with made-up people, times and numbers. It is the
  only place a number may be typed.
- **How it works**: how the code does it. Every sentence cites at least one reference in
  backticks, copied exactly from the "may cite" list of `--pack`: a path
  (`src/jarvis/logging.py`), a path and a name (`src/jarvis/logging.py:get_logger`), a short name
  of the page's own code (`get_logger`), a setting (`log_json`), a collection or a route
  (`GET /v1/book/pages`). A reference the index doesn't know fails the page.
- **What it costs** and **When it fails**: from the facts and the code only.
- **Claims**: in every section but the example, In plain words included, a sentence with "also",
  "can" (or "can't"), "automatically", "by itself" or "on its own" cites a reference or a fact.
  Cite one, or say it another way ("is easy to trace" rather than "can be traced").
- **Numbers**: outside the example, never type one. Write a fact as `{{fact:<key>}}` with a key
  from the pack (`{{fact:settings.vault_unlock_minutes}}`); the generator writes its value, so
  every number comes from the code. Not counted as numbers: digits inside backticks, card ids
  (C16), release labels (R6.3), versions (v6.3.2), a status code next to a route or the word
  "status", and standard names (SHA-256, UTF-8, AES-256-GCM, 3D). Don't spell a count out in
  words to get round the rule: a count from the code is a fact.
- **Unverified**: a fact marked Unverified in the pack must be called "Unverified" in its own
  sentence.
- **Planned work**: only after a line that starts `Planned:`. Before that line, no "soon",
  "planned", "coming", "one day", "will also", "in a later release" or "not built yet".
- **Never**: HTML, Markdown links, web addresses, e-mail addresses, code fences, `<<` or `>>`, a
  real person's name, a phone number, a long run of digits, a secret, or a private word. The
  scrubber, the owner-address check and the private-word hashes catch them; never paste the
  private words file anywhere.
- **Sentences**: the checks split sentences at ". ", "! ", "? " and line breaks. Avoid "e.g." and
  "i.e.", and remember each line of a list is a sentence of its own.
- **Caps**, counted once the facts are filled in: In plain words 900, Example (made up) 900, How
  it works 2,400, What it costs 900, When it fails 900 characters.

## What `--check` says

One line per problem, `<page_id>: <problem>`; the first word names the check.

| Starts with | Means | Fix |
|---|---|---|
| `missing` | No page file yet | Write it |
| `pages/<file>: ...` | The file can't be read: its name, front matter or five sections | Fix the file's shape |
| `refs:` | A backticked reference the index doesn't know | Copy it from the pack's "may cite" |
| `numbers:` | A typed number, or a `{{fact:...}}` key that isn't a fact | Use a key from the pack |
| `personal:` | Personal data, a secret, a private word or the owner's address | Take it out |
| `unverified:` | An Unverified fact without the word | Say "Unverified" in that sentence |
| `invented:` | A sentence (counted from 1 in its section) cites nothing | Cite a reference or a fact, or cut it |
| `planned:` | Future words before a `Planned:` line | Move them below one |
| `shape:` | An empty section, one over its cap, HTML, a link or `<<` `>>` | Shorten or clean it |
| `flow:` | The flowchart is missing, invalid, cites a file outside the page's refs, or holds personal words | Fix `flows/<page_id>.json` |
| `stale:` | Not stamped, or a cited file changed, came or went since the stamp | Re-read, rewrite, then `--stamp` |
| `not an indexed page` | A file for a page id the index doesn't have | Rename or remove it |

## The flowchart

Every chapter and every module has one; a card, screen or service page may. It is drawn in the
console's own colours, Night and Day, with a text list of its steps under it. The layout is yours:
each node sits at an explicit `rank` (0-9, the step's order along `dir`) and `col` (0-5, side by
side), and no two nodes share a place.

| Field | Rule |
|---|---|
| `title` | At most 60 characters |
| `dir` | `"down"` or `"right"` |
| `nodes` | 2 to 14: `id` (a slug: a lower-case letter, then lower-case letters, digits or `_`, at most 31 characters, unique), `label` (at most 28 characters), `kind` (`step`, `store`, `service`, `guard`, `person`), `rank` 0-9, `col` 0-5, optional `ref` (a path among the page's refs) |
| `edges` | 1 to 24: `from` and `to` (node ids), optional `label` (at most 20 characters), optional `style` (`"main"`, the default, or `"side"`) |

No other field anywhere, and no key twice. Titles and labels pass the same scrubber and
private-word guard as the pages: no names, addresses, links, long digit runs or secrets.

## A complete example

The card "Logging" (`pg_card_c50`), as `pages/pg_card_c50.md` (the `sources` block as `--stamp`
writes it; its hash here is only an example):

```markdown
---
page: pg_card_c50
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/logging.py": "3f1c0a9b2d4e5f60"
---
## In plain words
JARVIS keeps a diary of what its server does, one line for each event, so that a fault is easy to trace afterwards. Each request carries its own short trace id, and every line written while it runs carries the same id, so all the lines of one request are easy to find together.

## Example (made up)
At 9:14 you ask JARVIS for tomorrow's weather. The request gets the trace id 3f9a0c and the server writes four lines while it works: the request came in, the weather service answered, the reply went out, the request ended. Had the reply failed, a search for 3f9a0c would show all four lines and the error in one place.

## How it works
Every part of JARVIS asks `get_logger` for its logger, so they all write the same way (`src/jarvis/logging.py`). At the start of a request `new_trace_id` makes a fresh random id, or `set_trace_id` keeps the one the caller sent, and it stays with that request until it ends. A filter, `_TraceFilter`, adds that id to each line. With the setting `log_json` on, `_JsonFormatter` writes each event as one JSON line with its time, level, place, trace id and message, plus any extra fields the caller passed. With it off, `_TextFormatter` writes a plain line for a person to read. `configure_logging` sets the level it is given (the server passes the setting `log_level`) and quietens the busiest libraries, so their routine chatter doesn't bury JARVIS's own lines.

## What it costs
Nothing in JARVIS itself: `configure_logging` sends every line to the server's standard output, where the hosting's own log service collects them. How long that service keeps them, and at what price, is Unverified.

## When it fails
`get_logger` sets logging up the first time it is needed, so a part that logs before start-up has finished still gets a working logger. A value that can't be written as JSON is written as text instead of breaking the line (`_JsonFormatter`). The lines hold only what the calling code passes in, so keeping secrets and message text out of them is each caller's duty, not this file's.
```

Its optional flowchart, as `flows/pg_card_c50.json`:

```json
{
  "title": "One request's log lines",
  "dir": "down",
  "nodes": [
    {"id": "request", "label": "A request arrives", "kind": "person", "rank": 0, "col": 0},
    {"id": "trace", "label": "Give it a trace id", "kind": "step", "rank": 1, "col": 0,
     "ref": "src/jarvis/logging.py"},
    {"id": "part", "label": "A part logs an event", "kind": "step", "rank": 2, "col": 0},
    {"id": "filter", "label": "Add the trace id", "kind": "guard", "rank": 3, "col": 0,
     "ref": "src/jarvis/logging.py"},
    {"id": "json", "label": "One JSON line", "kind": "step", "rank": 4, "col": 0},
    {"id": "text", "label": "A plain line", "kind": "step", "rank": 4, "col": 1},
    {"id": "out", "label": "Standard output", "kind": "store", "rank": 5, "col": 0}
  ],
  "edges": [
    {"from": "request", "to": "trace"},
    {"from": "trace", "to": "part"},
    {"from": "part", "to": "filter"},
    {"from": "filter", "to": "json", "label": "log_json on"},
    {"from": "filter", "to": "text", "label": "log_json off", "style": "side"},
    {"from": "json", "to": "out"},
    {"from": "text", "to": "out", "style": "side"}
  ]
}
```

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.3.2 | 24 Nov 2026, 03:50 IST | R6.3.1 | First edition: the folder, the workflow (`pages --list`, `--pack`, `--check`, `--stamp`), the page and flowchart formats, the writing rules, what `--check` says, a complete example | 🛠 Mark XXIV |

Version v6.4.0 · 25 Nov 2026, 13:00 IST · Release R6.4 · Status: Current · Owner: 🛠 Mark XXIV

# Writing the full book's narrated chapters

The full book is told chapter by chapter by the chapter player (docs/plans/r6-4-book-look.md,
decisions D5 to D7 and D11). Each of the 26 chapters gets one spoken script, written by the
Workshop during development, in `narration/<chapter_id>.md`. JARVIS never calls an AI for it: the
generator checks each script against the release's facts, compiles it with the pages and seals it
with the release. This guide is for the narration writers; the pages' own guide is `AUTHORING.md`.

## The chapters

`python -m jarvis.buildbook.gen pages --narration-list` shows all 26: 8 story chapters
(`story_what` … `story_planned`, one page each) and 18 module chapters (`module_console` …
`module_wardrobe`): the module's page, then its parts' cards in the module map's order, then the
screens and outside services that belong to it (the table `HOMES` in `book/chapters.py`). A page
is in one chapter at most. The Vault chapter, `narration/module_vault.md`, is the reference
script: read it first.

## The voice

Write the way the short tour speaks to the owner:

- Plain words, "you" for the owner, "JARVIS" for the assistant, British spelling.
- One sentence a line, about 25 words at most; a line holds 240 characters once its facts are
  filled. Short sentences sound better than long ones.
- Never a file path, a file name, code, a class or function name, a setting's name, a route or a
  web address: say what the part does. A brand the page names (Google Drive, DigiLocker,
  Telegram) is fine.
- Every number is a fact, `{{fact:<key>}}`, from the pack; never type a digit, and don't spell a
  count from the code out in words to get round the rule. A fact the pack marks Unverified is
  called "Unverified" in its own line.
- Tell only what the pages and their flowcharts say. Read them (and the code behind them when a
  page is unclear); never invent behaviour.
- When you light a box, say what that box does. When you trace a connector, say what travels
  along it.
- Aim for 4 to 14 minutes a chapter (150 words a minute): a story chapter is short, a big module
  longer. Every page of the chapter gets at least one line, in the chapter's order.
- Vary the cues across the chapter so the effects engine has variety: an overview at the start
  of a flowchart, boxes and connectors in the order the flow runs, the five sections shown as you
  reach them, and a count-up whenever a fact is the point of the line.

## The file

YAML front matter between two `---` lines, then one spoken line per list item:

```markdown
---
chapter: module_vault
written_by: Workshop · Mark XXIV
written_on: 2026-11-25
---
- [page:pg_module_vault] [show:title] This chapter is about how your documents reach JARVIS.
- [show:overview] Here is the whole journey of a document.
- [node:kind] First, JARVIS checks the file's kind and size.
- [edge:kind>refused] A file of the wrong kind is refused in plain words.
- [count:{{fact:settings.vault_unlock_minutes}}] An unlock lasts {{fact:settings.vault_unlock_minutes}} minutes.
```

| Field | What it holds |
|---|---|
| `chapter` | The chapter id, equal to the file name (without `.md`) |
| `written_by` | Who wrote it, at most 60 characters: `Workshop · Mark XXIV` |
| `written_on` | The day it was written, `2026-11-25` |
| `pages` | Written only by `--narration-stamp`: each page of the chapter and its stamp |

No other field, and no YAML anchors or aliases. The body holds list items (`- ` at the start of
a line) and blank lines only.

## The cues

A line may open with cues in square brackets, before its words. The cues say WHAT the stage shows;
the effects engine picks HOW (and never the same entrance twice in a row).

| Cue | What it does | Rule |
|---|---|---|
| `[page:<page_id>]` | The player moves to that page | The chapter's NEXT page; the first page needs none. First of the line's cues |
| `[show:<part>]` | The stage shows a part of the page | `title`, `plain`, `example`, `how`, `costs`, `fails`, or `overview` (the whole flowchart) |
| `[node:<id>]` | Lights a box of the page's flowchart | A box id of THAT page's flowchart (`--narration-pack` lists them) |
| `[edge:<from>><to>]` | Traces a connector | A connector of that page's flowchart, from and to as in its file |
| `[count:₹{{fact:<key>}}]` or `[count:{{fact:<key>}}]` | A count-up to the amount (₹ for money) | A fact whose value is a number |

A page without a flowchart takes `show` cues only. At most one `show` and one `count` a line, six
cues in all. A cue after the words is an error, so the words never read a cue aloud.

## The workflow

Run every command from the repository's top folder with `PYTHONPATH=src`.

1. `python -m jarvis.buildbook.gen pages --narration-pack <chapter_id>`: each page of the chapter
   in order, with its five sections as written, its flowchart's boxes and connectors (the cue
   targets) and the facts its pages use, with their values.
2. Read those pages, then write `src/jarvis/buildbook/book/narration/<chapter_id>.md` without a
   `pages` block.
3. `python -m jarvis.buildbook.gen pages --narration-check <chapter_id>` until the only problem
   left is `stale: not stamped yet`. With no ids it checks every chapter; add `--allow-missing`
   to pass the chapters nobody has written yet.
4. `python -m jarvis.buildbook.gen pages --narration-stamp <chapter_id>`: writes the `pages`
   block (the first 16 hex of the SHA-256 of each page's written sections and its flowchart). It
   refuses a script with any problem but staleness.
5. `--narration-check` once more (exit 0), then commit and push (`docs(book): ...` with the
   release's trailers). Servers restart: an unpushed script is lost.

A script turns `stale` when a page of its chapter changes its words or its flowchart (a page's
own `sources` stamp doesn't count), or when the chapter gains or loses a page. Re-read the change,
rewrite the lines it touches, check and stamp. CI's strict `pages --check` (no ids) checks every
chapter's script too: a missing, stale or failing script fails it. `--narration-list` shows each
chapter's status and its minutes.

## What `--narration-check` says

One line per problem, `<chapter_id>: <problem>`; `line <n>` is the file's line.

| Starts with | Means | Fix |
|---|---|---|
| `missing` | No script yet | Write it |
| `narration/<file>: ...` | The file can't be read: its name, front matter, a list item or a cue's shape | Fix the file's shape |
| `cues:` | A page out of order or outside the chapter, a `show` part that doesn't exist, a box or connector that isn't in that page's flowchart, a `count` that isn't a number fact, or a cue after the words | Use `--narration-pack`'s targets |
| `numbers:` | A typed number, or a fact key that isn't one | Write `{{fact:<key>}}` from the pack |
| `unverified:` | An Unverified fact without the word | Say "Unverified" in that line |
| `spoken:` | A backtick, a file name or path, a code name, or a web address | Say what it does in plain words |
| `personal:` | Personal data, a secret or a private word | Take it out |
| `shape:` | A line over 240 characters once filled | Split it into two lines |
| `pages:` | A page of the chapter with no line, or with no written page yet | Tell it at least once; write the page first |
| `stale:` | Not stamped, or a page changed since the stamp | Re-read, rewrite, then `--narration-stamp` |
| `not a chapter of the book` | A script for a chapter id that doesn't exist | Rename or remove it |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.0 | 25 Nov 2026, 13:00 IST | R6.4 | First edition: the chapters, the voice, the file and its cues, the workflow (`--narration-list`, `--narration-pack`, `--narration-check`, `--narration-stamp`), what the check says; the Vault chapter as the reference | 🛠 Mark XXIV |

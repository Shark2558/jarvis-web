---
page: pg_card_c25
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/groceries/__init__.py": "e3b0c44298fc1c14"
  "src/jarvis/groceries/items.py": "831117550f7e8239"
  "src/jarvis/groceries/service.py": "f90c394445b67b8b"
  "src/jarvis/groceries/store.py": "0a1010f325ea14c2"
  "src/jarvis/groceries/tools.py": "8d486db1a9443c84"
---
## In plain words
Your shopping list lives as a list called "Groceries" in your own Google Tasks, so it is on your phone in the shop even without JARVIS open. You add items by voice or chat, ask what is on it, and tick things off as you buy them (`src/jarvis/groceries/tools.py`). JARVIS notices when an item is already there, so "add milk" twice gives one line, not two, and it understands that curd and yogurt are the same thing (`src/jarvis/groceries/items.py`).

## Example (made up)
On Monday evening Leela says "add 2 litres of milk and a bunch of coriander". JARVIS adds "Milk (2 L)" and "Coriander". On Tuesday her husband asks it to add "milk, 1 litre", and the line becomes "Milk (3 L)". On Wednesday she says "add yogurt"; JARVIS sees "Curd" is already on the list and says so instead of adding a second line. In the shop she ticks off the milk in Google Tasks on her phone.

## How it works
`GroceryService` finds your list by its exact title "Groceries" through the Google Tasks client and makes it on the first add; only the list's id and title are kept in `groceries` as a shortcut (`GroceryStore`).
Each line is written as your own words plus an optional amount and unit in brackets after the name, by `format_title`, and `parse_title` reads it back.
`norm_key` decides whether two names are the same item: it ignores case and extra spaces, drops a simple plural and uses a small table of synonyms such as brinjal and eggplant.
`merge` adds the amounts when the units match; if they differ, the new amount replaces the old and JARVIS tells you (`src/jarvis/groceries/items.py`).
One lock per owner makes two adds that arrive together produce exactly one list and one line per item (`src/jarvis/groceries/service.py`).
`grocery_tools` gives the brain a read plus add and tick-off tools, at most {{fact:src/jarvis/groceries/tools.py:MAX_ITEMS}} items at a time; all go through the tool gateway under your Groceries permission row.
On a spoken turn the changes run without a card unless the turn read someone else's content; your Ask first or Never still win (`src/jarvis/groceries/tools.py`).
Item text reaches the AI fenced off as data, and a list counts as trusted only when every line is your own (`_fenced`).

## What it costs
Nothing. Google Tasks is free, and each add or read is a handful of Tasks calls through your own Google link (`src/jarvis/groceries/service.py`). The AI reply around it is an ordinary chat turn.

## When it fails
If the cached list was deleted in Google Tasks, JARVIS searches for it by title again, or makes a fresh one on the next add (`GroceryService`). Without the To-do permission granted in Integrations, the tools answer in plain words instead of failing (`src/jarvis/groceries/tools.py`). A request with an empty name, a name over {{fact:src/jarvis/groceries/items.py:NAME_MAX}} characters or too many items is refused before Google is called (`parse_items`). Ticking off never deletes: the item stays under Completed in Google Tasks, where you can untick it (`src/jarvis/groceries/tools.py`).

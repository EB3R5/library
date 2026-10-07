---
name: library-shelve
description: Move the research a map in the Tasks app has produced into the Library as one item — the map's title, one document per Done research ticket, the brief pinned as the entry document — using the `tasks` and `library` MCP servers, and mark the map shelved in Tasks. Use when the user says "/library-shelve", "shelve <map> in the library", "put the <map> research in the library", or asks to move research from Tasks into the Library. Never automatic: one map, after the user has reviewed it, with a confirmation before anything is written.
---

# Library shelve

A map in Tasks (a top-level task worked by `/tasks-wayfinder`) ends with its research spread
across Done tickets as `Research.md` and `Outcome.md` notes. This skill **shelves** that research:
one Library **item** per map, in an area the user picks, with one document per research ticket
and the brief as the entry document, and a **shelved** marker back on the map.

Two apps, two MCP servers, no coupling between them: Tasks is read, the Library is written,
and the only link is the `source` each item and document carries (`tasks:<id>`).

## Tools

`mcp__tasks__*` (list_tasks, get_task, read_document, add_action, tick_action) and
`mcp__library__*` (list_items, get_item, create_item, add_document, pin_entry, list_areas).
If either set is deferred, load both in one call:
`ToolSearch "select:mcp__tasks__list_tasks,mcp__tasks__get_task,mcp__tasks__read_document,mcp__tasks__add_action,mcp__tasks__tick_action,mcp__library__list_areas,mcp__library__list_items,mcp__library__get_item,mcp__library__create_item,mcp__library__add_document,mcp__library__pin_entry"`.
A `not authenticated` reply from the library means its `API_TOKEN` is unset or not the one in
`library/.env`; say so and stop.

## Steps

1. **Load the map.** `list_tasks(q=<title>, status="all", parent="none")`, then `get_task(map)`.
   Refuse a task that has a Parent: only a map is shelved, with all its children at once.
2. **Already shelved?** If the map has any action item starting with `library:` (ticked or not),
   it was shelved before. Say so, find the item with `list_items(source="tasks:<map id>")`, and
   offer **add missing documents only**: compare the names you would write against
   `get_item(item)["documents"]` and add only the ones that are not there. Never create a second
   item for the same map, and never rely on the Library's ` (2)` suffix to tell you.
3. **Collect the research.** `list_tasks(parent=<map id>, status="done", kind="research")`, plus
   any Done child without a Kind whose Description's first line is `type: research` (tickets from
   before Kind existed). For each: `get_task(child)`; `read_document` its `Research.md` (else its
   newest text document) and its `Outcome.md` if there is one. A child with no text document is
   listed as skipped, not invented.
4. **Collect the brief.** The map's Description (`Destination:` and `Notes:`), its `Map.md` note if
   any, and the decisions list: every Done child's title with its Outcome, one bullet each. Any
   other text note on the map (an assembled brief) is read too and becomes the body of the
   entry document when it exists.
5. **Propose, then ask.** Show the plan in one block: item title (the map's title), the area
   (default `research`; `list_areas` for the rest), the tags (default: the map's Category and
   Group), and the documents by name (see REFERENCE.md for names and bodies). **AskUserQuestion**
   for area, tags and go/no-go. Nothing is written before the answer.
6. **Write the item.** `create_item(title, area, tags, source="tasks:<map id>")`. Then one
   `add_document` per research child, `source="tasks:<child id>"`, then `Brief.md` with
   `source="tasks:<map id>"`, then `pin_entry(item, <Brief.md id>)`.
7. **Mark the map.** `add_action(map, "library: <item title>")` and `tick_action` it. That ticked
   item is what Tasks shows as the 📚 pill on the map, its children and the Done feed (ADR-0018
   there). No note on the map: the map is not a child, so it has no Outcome to protect.
8. **Report** by title: the item, the area, the documents written, the children skipped, and the
   Workbench search term that finds it. One map per session. Stop.

## Rules

- Read Tasks, write the Library, mark the map. Never edit a task's documents, never delete or
  rename anything in the Library, never move a document between items.
- Bodies cross as written. The front matter block you add (REFERENCE.md) is hidden in the
  Library's reader and kept in the body; the `source` field on the row is what code reads.
- Refer to maps, tickets and items **by title**, never by bare id, when talking to the user.

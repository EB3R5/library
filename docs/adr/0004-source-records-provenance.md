---
status: accepted
---

# Source records where an Item or Document came from

Research written in the Tasks app is going to be shelved into this library by
an agent (ADR 0007). Once it is here, two questions need an answer the data
can give: *which task did this come from?* and *has this map already been
shelved?* Nothing in the v2 schema could say; Items had a title, an Area and
Tags, Documents a name and a body.

`items.source` and `documents.source` are nullable text columns holding a
reference in the form `<scheme>:<id>`. The first scheme is `tasks:<task id>`
on an Item and `tasks:<document id>` on a Document; the Info tab renders a
`tasks:` Source as a link into the Tasks app (`TASKS_URL`, default
127.0.0.1:8011), and `list_items(conn, source=…)` finds the Item a given
source already produced. Export carries it in `item.json`. The columns are
added to an existing database by a guarded `ALTER TABLE` on connect, the
first migration since v2 made SQLite the source of truth.

## Considered Options

- **A — Nullable `source` columns** (chosen): machine-written provenance,
  never typed in the Workbench, queryable, exported.
- **B — A tag such as `tasks:abc`** — rejected: Tags are the user's own
  vocabulary for filtering, and a tag cannot say which Document came from
  where.
- **C — Front matter in the Document body** — rejected as the only record:
  front matter is hidden from view and search, cannot be queried, and an Item
  has no body to carry it. Shelved documents may still carry front matter for
  a human reader; the column is what the code reads.
- **D — A separate provenance table** (v1's `imports` ledger) — rejected:
  one reference per row is all that is needed; a ledger with hashes and sync
  state is the folder-import design v2 retired.

## Consequences

- `create_item`, `add_upload` and `add_note` take an optional `source`;
  `serialize` and `list_for_item` return it; `list_items` filters on it.
- Nothing is kept in sync: a Source says where a thing came from, not that it
  still matches. Edits in the library stay in the library.
- Back up `library.db` before the first start of a build that includes this
  ADR; the migration is additive and idempotent, but it is the first one.
- The write-up of the Tasks app's Documents feature that lived under
  `docs/research/` is removed from this public repository in the same change.

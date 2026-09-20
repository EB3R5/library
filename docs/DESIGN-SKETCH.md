# Library design sketch — paper only, nothing built

Decided so far: Workbench (variant B) shell wins; files are source of truth,
SQLite is metadata + search; app owns a managed library folder; imports copy
from source folders.

## Library layout

```
~/library/
  library.db                 # SQLite — index, metadata, workbench state
  items/
    2026-07-13-which-stock-broker/     # one directory per item, always
      us-stock-brokerage-accounts.md   # renditions keep original filenames
      us-stock-brokerage-accounts.html
      meta.yaml                        # written at import — see "rebuildable"
    2026-08-08-my-quick-note/
      note.md
      meta.yaml
    teach-oil-painting/                # bundle: workspace copied verbatim
      meta.yaml
      MISSION.md  NOTES.md  lessons/  reference/  assets/  learning-records/
```

- **Every item is one directory.** Single-file items just have one rendition
  inside. This makes md+html pairs, bundles, and future attachments uniform,
  and makes serving trivial: an item may only read files inside its own dir
  (containment check, same as the prototype's `/files/` route).
- **Bundles copied verbatim** so relative links (`../assets/course.css`,
  glossary anchors) keep working untouched.

## Schema (SQLite)

```sql
items(
  id           TEXT PRIMARY KEY,   -- short stable id (hash of dir name)
  kind         TEXT,               -- 'single' | 'pair' | 'bundle'
  title        TEXT,
  area         TEXT,               -- 'research' | 'painting' | 'teach' | ...
  dir          TEXT,               -- relative to ~/library/items/
  created_at   TEXT, imported_at TEXT, updated_at TEXT,
  last_opened  TEXT                -- workbench "recent" ordering
)

renditions(                        -- the openable docs of an item
  item_id      TEXT REFERENCES items,
  role         TEXT,               -- 'md' | 'html' | 'entry' (bundle main doc)
  relpath      TEXT,               -- inside the item dir
  mtime        REAL, size INTEGER
)                                  -- bundle assets get no rows; they ride
                                   -- along on disk and are served by containment

tags(id, name)                     -- flat tag list
item_tags(item_id, tag_id)

imports(                           -- provenance + dedupe ledger
  source_path  TEXT,               -- where it came from
  source_hash  TEXT,               -- content hash at import time
  item_id      TEXT, imported_at TEXT
)

search USING fts5(title, body, content='')   -- contentless FTS5;
                                   -- body = md as-is, html stripped to text
```

## Rebuildable-cache rule

The DB must be regenerable from the files alone. That's why each item dir
gets a tiny `meta.yaml` (title, area, tags, kind, source provenance) written
at import: delete `library.db`, rescan `items/`, and everything — including
tags on HTML-only items that have no frontmatter — comes back. Markdown
frontmatter, where present, wins over `meta.yaml` for that rendition.

## Import flow

1. **Registered sources** (a small table or config): `~/research`,
   `~/Documents/painting`, later `~/teach`.
2. **Scan** on demand: walk sources, group candidates —
   bundle signature (`MISSION.md` + `lessons/`) → bundle;
   same-stem `.md`+`.html` → pair; else single file. Hash each candidate.
3. **Diff against the imports ledger**: new / changed upstream / already in.
4. **Review panel in the workbench** (a fourth pane state, not a new page):
   list of candidates with proposed title/kind/area, one-click import each or
   import-all. No watchers, no cron — you see what's arriving.
5. **Import** = copy into a new item dir, write `meta.yaml`, insert rows,
   extract text into FTS.
6. **Changed upstream** (source re-edited after import): flagged in the review
   panel; user picks "re-import (overwrite library copy)" or "ignore". Never
   auto-overwritten, because the library copy may have local edits.

## Edits and new notes (from the prototype's HTMX editing)

- Edit md rendition → write the file in the item dir, bump `updated_at`,
  refresh its FTS row. Real saves now — the library dir is app-owned, so
  writing is safe by design (unlike editing the skills' source folders).
- New note → create item dir + `note.md` + `meta.yaml` + rows. Same path as
  import, minus the copy.
- HTML artifacts stay view-only.

## Decisions (settled 2026-08-08 — no open questions remain)

- **Item dir naming**: date-prefixed slug (`2026-07-13-which-stock-broker/`);
  bundles keep their own name (`teach-oil-painting/`).
- **Copy vs move**: copy forever. Sources stay the skills' output areas;
  ledger hashes keep re-scans idempotent. Import is never destructive.
- **Areas**: small fixed, editable list (research, painting, teach, …) driving
  the workbench tree's top level, plus free-form tags for cross-cutting topics.
- **Un-imported sources**: visible only in the import review panel, which has
  a peek button (opens the candidate in the iframe) so you can read before
  importing. The library tree shows imported items only — one collection.

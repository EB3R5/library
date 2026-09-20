# library — v2 Plan

*Locked 2026-09-17 at the end of the [v2 wayfinder map](https://github.com/EB3R5/library/issues/16).
Build exactly this list — nothing more. Every decision below traces to a closed
map ticket; zoom those for the full reasoning. Supersedes the v1 plan
(2026-08-10, in git history), whose Workbench and Claude-in-the-loop decisions
carry over wherever this document doesn't say otherwise.*

## Job

**Workbench over a documents store.** The same single-screen 3-pane app as v1 —
tree · reader · tabbed third pane — but **SQLite is the source of truth**:
each Item holds Documents whose content lives in the database, with
Claude-in-the-loop editing on top. Replaces the managed folder + git.
Vocabulary is [CONTEXT.md](CONTEXT.md); the design being lifted is
[docs/research/tasks-webapp-documents-feature.md](docs/research/tasks-webapp-documents-feature.md);
the decision to leave files and git behind is
[ADR 0002](docs/adr/0002-documents-in-sqlite.md).

## The store (ticket [#10](https://github.com/EB3R5/library/issues/10))

`~/learning-library/library.db`, created with its schema on first run. No git,
no items folder, no rebuild command — the DB *is* the data.

```sql
items(id TEXT PK, title, area, created_at, updated_at, last_opened,
      entry_doc_id TEXT)                                          -- nullable pin
documents(id TEXT PK, item_id, name, kind, content_type, size, body, file_id,
          created_at, edited_at, UNIQUE(item_id, name))           -- index item_id
blobs(id TEXT PK, data BLOB, content_type, name)
document_versions(id TEXT PK, doc_id, body, kind, cause, replaced_at) -- index doc_id
deletions(collection, doc, deleted_at)
tags(id INTEGER PK, name UNIQUE) · item_tags(item_id, tag_id, UNIQUE)
search — FTS5(ref_id UNINDEXED, item_id UNINDEXED, scope UNINDEXED, name, body)
```

- Ids are uuid4 hex, app-generated. Foreign keys declared, cascades explicit in
  code (audit → blobs → versions → FTS → rows).
- Dropped from v1: `renditions`, `imports`, `items.kind/dir/imported_at`,
  `meta.yaml`, git init, the mtime sweep, `./run.sh rebuild`, `pyyaml`.
- No migration: v2 starts empty. A v1 `items/` tree, if one ever turns up, is
  recovered by uploading its files.

## Items and Documents (tickets [#10](https://github.com/EB3R5/library/issues/10), charting)

- An **Item** is a container: title, area (research · painting · teach ·
  misc), tags, any number of Documents. No kinds, no bundles.
- A **Document** is one file, belonging to one Item. **Text Documents**
  (`md`/`html`/`txt`) keep their UTF-8 body in the row; **File Documents**
  (`file`) keep bytes in `blobs` behind the three-function seam
  `store_bytes / read_bytes / delete_bytes` — the only code that touches blobs.
- **Kind** = extension first, content type second, default `file`. Renaming a
  Text Document re-classifies it; a File Document's kind never changes.
- **Names are unique per Item**: a clashing upload or note is auto-suffixed
  (`report (2).md`); a clashing rename is a 400.
- A **Note** is a Text Document of kind `md` created empty from the panel.
- **Entry Document** = the one pinned on the Item, else the first created.
- `items.updated_at` bumps on any document mutation or tag change;
  `last_opened` on open. The tree still sorts alphabetically within areas.
- Documents arrive by **upload, drop, or new note only**. No folder import,
  no source scan, no ledger.

## Caps (ticket [#17](https://github.com/EB3R5/library/issues/17))

4 MB per text body, 50 MB per file, empty files rejected; the same caps apply
to Save, Restore, and accepted Claude edits. No batch cap. A batch adds every
acceptable file and lists the rest with reasons (`⚠ name: reason; …` or
`✓ Added N`); the reply is `{ok, documents, errors}`. The editor has no live
counter — an over-cap Save is refused and the text stays in the textarea.

## Versions and undo (ticket [#9](https://github.com/EB3R5/library/issues/9))

A **Version** is the body a Text Document had before an edit replaced it,
stored with `replaced_at`, `cause` (`save` · `restore` · `claude: <summary>`)
and the kind at snapshot time. Created by every body change — never by rename;
the initial body is not a Version. Retention unbounded; Versions don't count
toward the cap and are never indexed. The Document page has a **History**
control (list by time · size · cause, preview, Restore); Restore is a normal
edit — body only, kind keeps following the name — so it is itself undoable.
Deleting a Document deletes its Versions; the `deletions` audit keeps the row
minus body. No Version exists while a Claude diff is pending.

## Search (ticket [#10](https://github.com/EB3R5/library/issues/10))

One FTS row per Document (`scope=document`: name + text — md/txt as-is with
frontmatter stripped, html reduced to visible text, files name-only) and one
per Item (`scope=item`: title + tags). Kept in sync inside the documents
module on every insert, edit, rename, delete and cascade; `reindex()` rebuilds
it. A query returns the matching Items; the tree shows each with its own hit
and every matching Document beneath it with a snippet. Item hits rank above
document hits, bm25 within. Exact MATCH first, prefix-term fallback so live
typing and dotted names hit; bad syntax yields no hits, never a 500.

## Rendering and security (ticket [#12](https://github.com/EB3R5/library/issues/12))

- **HTML is never inlined and is double-sandboxed:** the Document page embeds
  it in `<iframe sandbox="allow-scripts allow-forms allow-popups">`, and
  `GET /api/documents/{id}/raw` answers with
  `Content-Security-Policy: sandbox allow-scripts allow-forms allow-popups`
  and `X-Content-Type-Options: nosniff`. Inline JS runs with an opaque origin —
  no cookie, no access to the app's API — even when opened directly.
- **Markdown** = python-markdown (`fenced_code`, `tables`) → `nh3.clean`,
  one code path shared by the page and the editor's live-preview endpoint.
  Raw HTML in notes survives; scripts, handlers and `javascript:` URLs don't.
  `txt` renders in a `<pre>` with all tags stripped. A leading `---` YAML
  block is hidden from the view and the index, kept in the body.
- **Display modes**, kind first then content type: `html` → sandboxed iframe ·
  `image/*` → `<img>` · `application/pdf` → iframe · `md`/`txt` → inline ·
  else → download link.
- Raw endpoint: `Content-Disposition: inline` (attachment with `?download=1`,
  name ASCII-stripped). Serve by id, never by path.

## UI (ADR 0001 + tickets [#11](https://github.com/EB3R5/library/issues/11), [#12](https://github.com/EB3R5/library/issues/12))

Three panes as v1. Tree: search box on top, items grouped by area, search
hits nested under items. Center: the **Document page** with a slim head bar —
name · kind chip · size · View/Edit toggle (text kinds) · History · Download ·
Print — and the body per display mode; edit mode is textarea + live preview
(300 ms debounce, Tab inserts two spaces, Ctrl-S saves, dirty-warning on
unload). Third pane: tabs **Info · ✨ Claude**.

**Info tab** (the panel verdict): Documents first — header with count and a ⇪
upload icon; **one-line rows** (kind chip · name · size) with **hover actions**
📌 pin · ✎ edit · ⌥ rename · ✕ delete; the list is the drop target; the Entry
Document carries a 📌 marker; **inline forms** for rename (input), delete
(yes/no) and new note (name field under the list) — no browser dialogs except
*delete item*. Below, a `<details>` whose summary reads `area · tags ·
updated` folds the metadata, the tags form and *delete item*. After any
mutation the reader loads the Entry Document, or the "← pick a document"
placeholder when the Item is empty. Rename lives only here; the ✎ shortcut
opens the page in edit mode.

**✨ Claude tab**: v1's three feature forms and pending states, unchanged.

## Claude editing (ticket [#13](https://github.com/EB3R5/library/issues/13))

- **Scratch directory** `~/learning-library/scratch/<run id>/`: every Text
  Document of the Item written as `<name>`; File Documents listed by name in
  the prompt. Deleted on Accept, Revert, Dismiss and at app start.
- `claude -p --model sonnet --permission-mode acceptEdits`, cwd = the scratch
  dir, tools capped to Read/Edit/Write/Glob/Grep, background thread, **one run
  in flight globally**, 600 s timeout, HTMX-polled. The three prompt templates
  (integrate · retrofit · free-form) under the v1 contract plus one line:
  *other files in this folder are context only; do not modify them.*
- **Diff** = `difflib.unified_diff(stored body, scratch file)` in v1's coloured
  view; shown even after a failed run if the target changed. Edits to siblings
  and new files are **ignored and reported** (`ignored: x, y`).
- **Accept** = `documents.update(id, {"body": new})` → Version with cause
  `claude: <summary>`, size/edited_at/FTS/updated_at refreshed, scratch dir
  removed. **Revert** = remove the scratch dir. If the body changed since the
  run started, Accept refuses (*document changed since the run started*) and
  only Revert is offered.

## Export (ticket [#14](https://github.com/EB3R5/library/issues/14))

`./run.sh export [root]`, default `~/learning-library/export/`: overwrite in
place and prune, so a scheduled run is idempotent.
`<root>/<area>/<item slug>/<document name>` with bodies and blobs as plain
files and an `item.json` (id, title, area, tags, entry document, created,
updated) per item; slug gets a `-<6 chars of id>` suffix only on clash.
`<root>/library.db` via SQLite's online backup API is the real restore point.
Restore = stop, copy that DB back, start — documented, not coded. Scratch dirs
are not exported.

## Runtime

FastAPI · Jinja2 · HTMX · SQLite/FTS5; `./run.sh` = `uv run` from this
checkout, **port 8900** on 127.0.0.1. Dependencies: fastapi, uvicorn, jinja2,
python-multipart, markdown, **nh3**. `pyyaml` removed. First run creates
`~/learning-library/` and the schema.

## Where the code lands

`prototype_documents/documents.py` becomes **`documents.py`** at the repo root
(the module already implements classify, the blob seam, upload/note/
list/get/update/delete/cascade, raw, render, page context, FTS and stats;
build adds Versions, per-item FTS rows, name auto-suffix, the caps on
update, and the frontmatter rule). `db.py`, `libfs.py`, `importer.py`,
`gitops.py` are deleted; `claude_runner.py` is rewritten against the scratch
dir; `app.py` and the templates are rewritten around the Document page and
the panel verdict. **The prototype shell (`prototype_documents/`) is deleted
at build start** — its templates were the source for the Info tab and
Document page.

## Non-goals (decided — do not re-propose in v2)

- Folder import, source scan, review panel, provenance ledger.
- Bundles / multi-file documents; HTML must be self-contained.
- Scheduled backups; always-on deployment (systemd / LaunchAgent).
- Migrating v1 data; importing an export tree.
- Indexing Versions; a live byte counter in the editor.

## Build order

1. Lift `documents.py`; add `document_versions`, item FTS rows, name
   auto-suffix, caps on update, frontmatter stripping; first-run init.
2. Workbench shell: tree with search, Document page (display modes, head bar,
   editor, History), Info tab per the panel verdict, raw endpoint.
3. Claude loop over the scratch dir: runner, diff, Accept/Revert with the
   race guard, ADR 0001 pending states.
4. `./run.sh export`.
5. Delete the prototype shell and the v1 folder-store modules; update README.

## Smoke (before calling v2 done)

- Upload a mixed batch incl. one empty file: good ones added, the empty one
  listed. Drop a folder of files on the list.
- New note → editor → Ctrl-S; History shows one Version with cause `save`;
  Restore it; History shows two.
- Rename `notes.md` → `notes.html`: kind flips, page renders in the sandbox;
  the sandboxed page's script finds no cookie and cannot call the API.
- Search finds text in a note, text in an HTML page, an item by tag; a
  half-typed word hits; `data.bin` hits by name.
- Claude-integrate a term into a note; Accept → Version with cause
  `claude: …`; a second run + manual save → Accept refuses, Revert works.
- Pin a document; reopen the item → it loads. Delete it → fallback loads.
- `./run.sh export` twice: tree mirrors the DB, `library.db` copy opens.
- Kill and restart `./run.sh`; everything intact; stale scratch dirs gone.

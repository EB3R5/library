# library

A personal learning library with a single-screen **Workbench**: a filterable
tree of items, a document reader, and an Info / Claude panel. Items hold
documents, and the documents live in SQLite. Documents can be edited
**Claude-in-the-loop**: one button runs `claude -p` against a scratch copy,
the result shows as a diff, and you Accept or Revert.

- **SQLite is the data.** `~/learning-library/library.db` holds every item and
  document. Text documents keep their body in the row, other files are stored
  as blobs. There is no folder tree to keep in sync and no rebuild step.
- **Any file type.** Markdown, HTML, text, PDFs and images open in the reader.
  Everything else is kept and served byte-for-byte.
- **Undo is version history.** Every save, restore and accepted Claude edit
  files the previous body as a Version. The History view previews and restores.
- **HTML is sandboxed.** Uploaded HTML never runs with the app's origin. It
  renders in a sandboxed iframe, and the raw endpoint sends a sandbox CSP.
- **Claude edits are explicit.** Nothing runs without a button press. One edit
  in flight at a time, limited to read/edit tools, no shell and no network.

## Requirements

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Optional: the [Claude Code CLI](https://claude.com/claude-code) (`claude`) for the Claude tab

## Quick start

```bash
git clone https://github.com/EB3R5/library.git
cd library
./run.sh              # http://127.0.0.1:8900
./run.sh export       # backup: plain-file tree + DB copy in ~/learning-library/export
```

The first run creates `~/learning-library/` and the database schema. Set
`LIBRARY_HOME` to put the data somewhere else. A v1 `library.db` found there
is moved aside as `library.v1.db`, never migrated.

## Using it

**Items and documents.** Make an item with the form under the tree, giving it
a title and an area. Areas are yours to name: the picker has a **＋ new
area…** entry, and an item's Info tab can move it. Each item holds any number
of documents. The document that opens when you click the item is the one you
pinned with 📌, or the first one added.

**Getting documents in.** Drop files on the document list in the Info tab,
click ⇪ for the OS chooser, or drag files anywhere on the Workbench. Dragging
shows drop zones: add to the open item, one new item bundling all the files,
or one new item per file. New items are titled after their first file and go
in the area picked under the tree. Text over 4 MB, files over 50 MB and empty
files are refused individually, and the rest of the batch still lands. Names
are unique per item, so a second `report.md` becomes `report (2).md`.

**Bundling and un-bundling.** An item is a bundle of documents. To split one,
hover a document in the Info tab and click ⇥: it moves into a new item of
its own, with the title and area you choose. Its version history moves with
it. To bundle, drop files on an item's list or use the first drop zone.

**Reading and editing.** The document page has a head bar with the name, a
kind chip, the size, and View / Edit / History / Download / Print. Edit mode
is a textarea with a live preview, Tab inserts two spaces, and Ctrl-S saves.
Markdown is rendered server-side and sanitized. A leading YAML front matter
block is hidden from the view and the search index but kept in the body.
Renaming `notes.md` to `notes.html` re-classifies it. Files never change kind.

**History.** Every body change keeps the previous body as a Version with its
cause: `save`, `restore`, or `claude: …`. The History view lists them by
time, size and cause, previews any of them, and restores with one click.
Restoring is itself an edit, so it is undoable. Deleting a document deletes
its versions.

**Search.** The box above the tree matches document text, document names,
item titles and tags. Item hits rank above document hits, and matching
documents are listed under their item with a snippet. A half-typed word
matches by prefix, and a dotted name like `data.bin` still hits.

**Claude tab.** Pick a text document and one of three features:

| Feature | What Claude is asked to do |
|---|---|
| integrate | fold a new term and body into the document where it fits |
| retrofit | add a capability to a self-contained HTML document with inline JS/CSS only |
| free-form | apply your prompt to the document |

The item's text documents are written to a scratch directory and Claude runs
there, so sibling documents are readable context. The diff against the stored
body takes over the center pane. Accept files a Version and stores the new
body. Revert discards the scratch copy. Edits Claude makes to other files are
ignored and listed. If the document changed while the run was in flight,
Accept refuses and only Revert is offered. Model, timeout and tool cap are set
in `config.py`.

**Backup.** `./run.sh export [root]` writes `<area>/<item>/<document>` as
plain files with an `item.json` per item, plus a copy of `library.db` made
with SQLite's online backup. Running it again overwrites in place and prunes,
so a scheduled export is idempotent. Restore is stopping the app and copying
that database back.

## Run and package

`./run.sh` is the dev server. Everything else that launches the app lives in
[`packaging/`](packaging/README.md): a desktop window via pywebview
(`uv run --extra desktop packaging/desktop/launcher.py`), a Linux `.desktop`
entry with installer, a macOS `.app` bundle, and a Docker image for running
it as a homelab service. The app doesn't change per target; `/healthz` is what
every target probes.

## Layout

```
app.py               FastAPI routes, the JSON API and the uvicorn entry point
documents.py         the store: schema, items, documents, blobs, versions, search
claude_runner.py     the claude -p runner over a scratch directory, one global slot
export.py            the backup command
config.py            paths, port, Claude settings
templates/           HTMX partials for the Workbench and the document page
tests/               pytest suite over the store and the API
packaging/           desktop, Linux, macOS and Docker targets
docs/                design sketch, ADRs, schema diagram, research notes
```

## Status

This is v2, built to [plan.md](plan.md): documents live in SQLite with
per-document version history, replacing v1's managed folder and git undo
store. The decision is [ADR 0002](docs/adr/0002-documents-in-sqlite.md) and
the vocabulary is [CONTEXT.md](CONTEXT.md). v1 data is not migrated. Upload
the files from a v1 `items/` tree to bring them across.

The design came out of two earlier prototypes: a Workbench shell with HTMX
search and iframe reading, and a Claude-in-the-loop glossary editor. The
library-side decisions are recorded in [docs/DESIGN-SKETCH.md](docs/DESIGN-SKETCH.md).
The Docker image has no `claude` CLI, so Claude edits need a local run.

## License

[MIT](LICENSE)

# library

A personal learning library with a single-screen **Workbench**: a filterable
tree of items, an iframe reader, and an Info / Claude panel, all over a plain
folder you own. Documents can be edited **Claude-in-the-loop**: one button
runs `claude -p` against the file, the result shows as a diff, and you Accept
or Revert.

- **Local and file-first.** Items are directories under `~/learning-library/items/`
  with a `meta.yaml`. SQLite is only an index cache; `./run.sh rebuild` regenerates it.
- **Any file type.** Markdown, HTML, text, PDFs and images open in the reader.
  Everything else is kept and served byte-for-byte.
- **Undo is git.** The library folder is a git repo. Every import, edit,
  delete and accepted Claude change is a commit, so `git log` there has all history.
- **Claude edits are explicit.** Nothing runs without a button press. One edit
  in flight at a time, limited to read/edit tools, no shell and no network.

## Requirements

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- `git` on the PATH
- Optional: the [Claude Code CLI](https://claude.com/claude-code) (`claude`) for the Claude tab

## Quick start

```bash
git clone https://github.com/EB3R5/library.git
cd library
./run.sh              # http://127.0.0.1:8900
./run.sh rebuild      # regenerate library.db from ~/learning-library/items
```

The first run creates `~/learning-library/` and initialises it as a git repo.
Set `LIBRARY_HOME` to put the data somewhere else.

## Using it

**Getting documents in.** Drop files anywhere on the Workbench, or click
**⇪ Import files…** for the OS chooser. Files dropped together become one item,
grouped by name, so an `.md` and `.html` pair stays a pair. **import center ·
scan sources…** swaps the tree for a drop target plus an import-by-copy from
the source folders registered in `config.py`. Sources are never written to,
and re-scans are idempotent.

**Areas and tags.** Areas are the top-level grouping in the tree and are yours
to name: the footer's area picker has a **＋ new area…** entry, and an item's
Info tab can move it to any area. Tags are free-form labels for filtering.
An item's area lives in its `meta.yaml`; an empty named area exists only in
the index and vanishes on rebuild.

**Editing.** Text documents (`.md`, `.html`, `.txt`) are editable in place from
the Info tab. A new note is a markdown file holding just its title heading, created in the current area.

**Deleting.** The Info tab deletes an item, or single files of a multi-file
item. Deletions are commits in `~/learning-library`, so
`git log -- items/<dir>` there still has everything.

**Claude tab.** Pick a text document and one of three features:

| Feature | What Claude is asked to do |
|---|---|
| integrate | fold a new term and body into the document where it fits |
| retrofit | add a capability to a self-contained HTML document with inline JS/CSS only |
| free-form | apply your prompt to the document |

The run uses the item directory as its working directory, so sibling documents
are readable context. The diff against HEAD appears in the panel. Accept
commits it, Revert checks the file out. Model, timeout and tool cap are set in
`config.py`.

## Run and package

`./run.sh` is the dev server. Everything else that launches the app lives in
[`packaging/`](packaging/README.md): a desktop window via pywebview
(`uv run --extra desktop packaging/desktop/launcher.py`), a Linux `.desktop`
entry with installer, a macOS `.app` bundle, and a Docker image for running
it as a homelab service. The app doesn't change per target; `/healthz` is what
every target probes. The Docker image has no `claude` CLI, so Claude edits
need a local run.

## Layout

```
app.py               FastAPI routes and the uvicorn entry point
libfs.py             item directories, meta.yaml, text extraction, rebuild
importer.py          source scan, review, copy-in
claude_runner.py     the claude -p runner and its single global slot
gitops.py            git in the library folder as the undo store
db.py                SQLite index schema and queries
config.py            paths, port, registered sources, Claude settings
templates/           HTMX partials for the Workbench
packaging/           desktop, Linux, macOS and Docker targets
docs/                design sketch, ADRs, schema diagram, research notes
prototype_documents/ throwaway prototype for the v2 documents-in-SQLite design
```

## Status

v1 is what runs. A v2 spec that moves document bodies into SQLite with
per-document version history is locked but not built. See [plan.md](plan.md),
[ADR 0002](docs/adr/0002-documents-in-sqlite.md) and
[CONTEXT.md](CONTEXT.md) for the vocabulary. `./run.sh proto` runs the v2
prototype on port 8901.

The design came out of two earlier prototypes: a Workbench shell with HTMX
search and iframe reading, and a Claude-in-the-loop glossary editor. The
library-side decisions are recorded in [docs/DESIGN-SKETCH.md](docs/DESIGN-SKETCH.md).

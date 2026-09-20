# library

Personal learning library: a single-screen **Workbench** (filterable tree ·
iframe reader · metadata/edit panel) over a managed `~/library/` folder, with
**Claude-in-the-loop editing** of HTML artifacts (`claude -p` + diff →
Accept/Revert).

Born from two prototypes (2026-08):

- **research-library, variant B (Workbench)** — shell, HTMX search, iframe
  reading, markdown editing. Library-side design locked in
  [docs/DESIGN-SKETCH.md](docs/DESIGN-SKETCH.md).
- **glossary-editing, mechanism B (Claude-in-the-loop)** — integrate
  additions, capability retrofits, and free-form doc edits via `claude -p`.

Supersedes the never-built `learning-library` plan (archived).

**Status: v1 built (2026-08-10); v2 spec locked (2026-09-17), not yet built.**
v2 moves the documents into SQLite — see [plan.md](plan.md), [ADR 0002](docs/adr/0002-documents-in-sqlite.md)
and the [v2 map](https://github.com/EB3R5/library/issues/16). The running
code is still v1 until the build effort lands.

Run: `./run.sh` → http://127.0.0.1:8900 · rebuild the index: `./run.sh rebuild`
Data lives in `~/learning-library/` (app-owned, git-backed — see plan.md's
amendment: not `~/library`, which is `~/Library` on macOS).

## Run and package

`./run.sh` starts the dev server on http://127.0.0.1:8900. Everything else that
launches the app lives in [`packaging/`](packaging/README.md): the desktop window
(`uv run --extra desktop packaging/desktop/launcher.py`, a Linux `.desktop`
entry, `/Applications/library.app` on macOS), the Docker image, and the
`library` service in the homelab stack that publishes 127.0.0.1:8900. The app
itself doesn't change for a target; `/healthz` is what every target probes.

Getting documents in: drop files anywhere on the Workbench, or click
**⇪ Import files…** for the OS chooser. Files dropped together are grouped by
name into one item (an `.md` + `.html` pair stays a pair); any type is kept,
and markdown, HTML, text, PDFs and images open in the reader. **import center ·
scan sources…** swaps the tree for a drop target plus the older import from the
registered source folders.

Areas are yours to name: the footer's area picker (used by new notes and every
import) has a **＋ new area…** entry, and an item's Info tab can move it to any
area, existing or new, or delete it (🗑 Delete item; a multi-file item can
also drop single files). Deletions are commits in `~/learning-library`, so
`git log -- items/<dir>` there still has everything. An item's area lives in its `meta.yaml`; empty named
areas live only in the index, so they vanish on `./run.sh rebuild`.

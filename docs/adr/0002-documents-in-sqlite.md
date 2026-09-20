---
status: accepted
---

# Documents live in SQLite, replacing the managed folder + git

v1 kept every document as a file under a git-backed `~/learning-library/`
folder and treated `library.db` as a rebuildable cache; git commits were the
undo store and `claude -p` edited the files in place. v2 makes **SQLite the
source of truth**: Text Documents keep their body in the `documents` row,
File Documents keep bytes in a `blobs` table behind a three-function seam, a
`document_versions` table replaces git as the undo store, and an Export
command replaces the folder as the backup. Decided 2026-09-17 while charting
the [v2 map](https://github.com/EB3R5/library/issues/16), lifting the design
of the tasks-webapp Documents feature
([docs/research/tasks-webapp-documents-feature.md](../research/tasks-webapp-documents-feature.md))
after it was proven in the `prototype_documents/` prototype.

## Considered Options

- **A — SQLite source of truth** (chosen): one row per attachment, inline
  text, blobs behind a seam, free in-app editing and per-document search;
  upload/drop replaces folder import; no git to keep consistent.
- **B — Keep the folder + git, add DB attachments alongside** — rejected:
  two stores with two undo models, and every feature has to know which one a
  document lives in.
- **C — DB as truth with a git-backed mirror for history** — rejected: the
  mirror is a second write path that can drift, for history a versions table
  gives directly.

## Consequences

- The DB can no longer be deleted and rebuilt; backups matter. `./run.sh
  export` writes a plain folder tree plus an online-backup copy of the DB;
  restore is copying that DB back.
- Claude cannot edit rows, so each run materializes the Item's Text Documents
  into a scratch directory and the diff is computed with `difflib`; only the
  target document's change is accepted.
- A Document is a single file. Multi-file artifacts (v1's teach bundles,
  relative-asset HTML) are out of scope; HTML must be self-contained.
- The v1 folder-store modules (`libfs.py`, `importer.py`, `gitops.py`) and
  `meta.yaml` go away; `pyyaml` with them. `nh3` arrives for sanitization.

# PROTOTYPE — documents in the DB

**Throwaway.** Answers one question, then gets deleted or absorbed.

## Question

Does library feel right if each item's documents live in SQLite — text kinds
(`md`/`html`/`txt`) inline in the `documents` row, everything else as bytes in
a `blobs` table behind a three-function seam — instead of files in the
git-backed `~/learning-library/` folder?

Shape lifted from `~/Downloads/tasks-webapp-documents-feature.md` (the
tasks-webapp Documents feature): one row per attachment, extension-first
classification, server-side markdown render + sanitize, HTML never inlined
(sandboxed iframe + CSP header), dirty-diff updates, tolerant delete, per-file
upload errors, deletion audit.

## Run

    ./run.sh proto        →  http://127.0.0.1:8901

State lives in `prototype_documents/PROTOTYPE-wipe-me.db` (gitignored).
Delete the file to reset; it reseeds with one item holding an md, an html
page with a probing script, a txt, an svg, and a binary blob.

## What to try

- Upload a mix of files (picker or drop zone) — one bad file must not fail the batch.
- New note → lands in the editor; type, watch preview, Ctrl-S.
- Rename `notes.md` to `notes.html` — kind flips, page renders in a sandbox.
- Open `wheel.html` — its script runs, but cookie is empty and the API fetch fails.
- Delete a document, then delete the item — watch **DB STATE** in the left pane
  (blobs, orphans, deletions).

## Panel variants (map ticket #11)

`?variant=A|B|C` switches the Info tab's Documents panel between three
structurally different layouts (pink bar at the bottom, or ← → keys):
A docs-first with dialogs · B metadata-first, dense rows, hover actions ·
C pinned entry card with inline forms. Verdict goes on the ticket.

## Files

- `documents.py` — the portable half. Pure over a sqlite3 connection. Worth lifting.
- `app.py` + `templates/` — the shell. Delete when done.

## NOTES — verdict

_Fill in once the question is answered, before deleting the prototype._

- Verdict:
- What felt right:
- What felt wrong:
- What this means for `~/learning-library/` + git as the store:

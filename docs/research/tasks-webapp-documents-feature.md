# How the Documents feature works in tasks-webapp

Technical notes on the per-task document attachment feature in
`~/Documents/GitHub/tasks-webapp`, written so the design can be lifted into other apps
(money-webapp, meal-prep-planner, etc.). Sources: `app/documents.py`, `app/routers/task.py`,
`app/templates/{task,document}.html`, `app/static/js/{task,document}.js`,
`tests/test_documents.py`, ADR-0004/0007/0008, `CONTEXT.md`.

Stack context: FastAPI + Motor (async Mongo, no ODM) + Jinja server-rendered pages + one
vanilla-JS "island" per page. Single-user session auth. The feature spans ~240 lines of
Python, ~50 lines of router, two templates, and ~110 lines of JS.

---

## 1. Concept

A **Document** is one attachment belonging to exactly one parent (a Task). Two flavours
share one row shape and one set of endpoints:

| Flavour | Kinds | Where the content lives | Editable in-app |
|---|---|---|---|
| Text document | `md`, `html`, `txt` | inline in the row, field `body` (UTF-8 string) | yes |
| File document | `file` (images, PDFs, anything else) | GridFS bucket `task_files`, row keeps `file_id` | no (rename/delete only) |

A **Note** is not a third flavour. It is a text document of kind `md` created with an empty
body from a "New note" button, then edited on the Document page.

Why a separate collection instead of embedding on the parent (ADR-0007): documents have
content of their own, need their own page, and must be listable without loading bodies.

## 2. Data model

Collection `documents`, one row per attachment:

```
{
  _id:          uuid4().hex,            // app-generated string id, never ObjectId
  task_id:      "<parent _id>",         // the only link to the parent
  name:         "plan.md",              // display name; extension drives kind
  kind:         "md" | "html" | "txt" | "file",
  content_type: "text/markdown" | "image/png" | ...,
  size:         int,                    // bytes (UTF-8 length for text)
  body:         "…",                    // TEXT ONLY
  file_id:      "<GridFS ObjectId as str>", // FILE ONLY
  _created_at:  datetime (UTC),
  _edited_at:   datetime (UTC)          // set on rename / body edit
}
```

GridFS bucket `task_files` (collections `task_files.files` / `task_files.chunks`) holds the
bytes of file documents. `metadata.contentType` is stored on the GridFS file as a fallback
content type.

Caps: `TEXT_CAP = 4 MB` for inline text, `FILE_CAP = 50 MB` for GridFS files.

Index note: there is no explicit index on `task_id`; at personal-app scale the
`find({"task_id": …})` is fine. Add one when porting to anything multi-user.

## 3. The classification rule (`documents.classify`)

Pure function, extension first, content type second, default `file`:

```python
_EXT_KIND = {".md": "md", ".markdown": "md", ".txt": "txt", ".html": "html", ".htm": "html"}
_CT_KIND  = {"text/markdown": "md", "text/html": "html", "text/plain": "txt"}

def classify(filename, content_type=None) -> str:
    ext = PurePosixPath(filename or "").suffix.lower()
    if ext in _EXT_KIND: return _EXT_KIND[ext]
    return _CT_KIND.get((content_type or "").split(";")[0].strip().lower(), "file")
```

`is_text_kind(kind)` is the single gate that decides inline-vs-GridFS on upload, whether
`body` may be edited, and whether the raw endpoint reads Mongo or GridFS.

Consequence worth knowing: renaming a text document re-runs `classify`, so `notes.md` →
`notes.html` changes how it renders. A file document's kind never changes on rename.

## 4. The GridFS seam

Three module-level async functions are the *only* GridFS calls in the app:

```python
async def store_bytes(data, name, content_type) -> str   # returns str(ObjectId)
async def read_bytes(file_id) -> tuple[bytes, str]      # (data, content_type); raises if missing
async def delete_bytes(file_id) -> None                 # swallows "already gone"
```

Tests monkeypatch these three with a dict-backed fake because mongomock has no bucket
(`tests/test_documents.py::fake_store`). This is the pattern to copy: keep byte storage
behind three functions so the backend (GridFS, S3, local disk) is swappable and the test
suite never needs a real store.

## 5. Operations (`app/documents.py`)

| Function | What it does |
|---|---|
| `add_upload(task_id, filename, content_type, data)` | Verifies the parent exists (404), rejects empty bytes, classifies, enforces the cap for that flavour, decodes text as `utf-8-sig` (400 if not UTF-8) into `body`, or stores bytes and keeps `file_id`. Inserts row, returns `serialize(row)`. |
| `add_note(task_id, name)` | Parent check, name defaults to `Note`, forces a `.md` suffix, inserts `kind: md, body: ""`. |
| `list_for_task(task_id)` | `find({"task_id"}, {"body": 0}).sort("_created_at", 1)` — bodies are projected out. |
| `get(doc_id)` | Full row or `DomainError(404)`. |
| `update(doc_id, updates)` | Dirty-diff: only `name` and/or `body` keys present are touched. Empty name → 400. `body` on a file document → 400. Body over cap → 400. Recomputes `kind` on rename (text only) and `size` on body edit. Stamps `_edited_at`. |
| `delete(doc_id)` | Audit snapshot → delete GridFS bytes (tolerant) → delete row. |
| `delete_for_tasks(task_ids)` | Cascade used by the parent's delete hook: fetch all, audit all, delete bytes, `delete_many`. |
| `raw(doc_id)` | `(bytes, content_type, filename)`; text is `body.encode()`, file is `read_bytes`. A missing GridFS file becomes a 404 DomainError, not a 500. |
| `page_context(d, task)` | View-model for the Document page (see §7). |
| `serialize(d)` | List-row shape: `id, task_id, name, kind, content_type, size, edited_at, is_image, is_pdf`. No body. |

Errors are raised as `DomainError(message, status=400)` and mapped to a JSON 4xx body
`{"ok": false, "error": msg}` by `web.guard()`. Every router endpoint is one line of
`return await guard(documents.x(...))`.

## 6. HTTP surface (`app/routers/task.py`)

Pages (HTML):

| Route | Purpose |
|---|---|
| `GET /tasks/{task_id}` | Parent page; passes `documents.list_for_task()` into the view-model, renders the Documents panel. |
| `GET /documents/{doc_id}?edit=0\|1` | Document page. `edit` is honoured only if `ctx["editable"]` (text kinds). 404 as plain HTML. |
| `GET /documents/{doc_id}/back` | 303 to the parent page (or `/` if orphaned). |

JSON / bytes:

| Route | Body | Returns |
|---|---|---|
| `POST /api/tasks/{task_id}/documents` | multipart, field `files` repeated | `{ok, documents: [serialized…], errors: [str…]}` — per-file try/except, so one bad file does not fail the batch. `ok` is false if any error. |
| `POST /api/tasks/{task_id}/notes` | `{name}` | serialized row (client redirects to `/documents/{id}?edit=1`) |
| `POST /api/documents/render` | `{body}` | `{html}` — server-side Markdown preview, same renderer as the page |
| `POST /api/documents/{doc_id}` | `{updates: {name?, body?}}` | `{ok: true}` |
| `POST /api/documents/{doc_id}/delete` | — | `{ok: true, deleted: 1}` |
| `GET /api/documents/{doc_id}/raw?download=0\|1` | — | the bytes with headers below |

Conventions: all mutations are `POST` (no PUT/PATCH/DELETE verbs), delete is a `/delete`
suffix, and the JSON reply always carries `ok`. This matches the rest of the app so the JS
`post()` helper is reusable everywhere.

Raw endpoint headers:

```
Content-Type: <row.content_type>            (falls back to GridFS metadata, then octet-stream)
Content-Disposition: inline; filename="…"   (attachment when ?download=1; name ASCII-stripped)
Content-Security-Policy: sandbox allow-scripts allow-forms allow-popups
X-Content-Type-Options: nosniff
```

The auth gate (`main.py`) covers these routes like any other: browser misses redirect to
`/login`, `/api/*` misses get a 401 JSON. No special exemption for raw bytes.

## 7. Rendering and security (ADR-0008)

Markdown is rendered **on the server** and **sanitized**, never in the browser:

```python
_md = MarkdownIt("commonmark", {"html": True, "linkify": False}).enable("table").enable("strikethrough")
def render_markdown(body): return nh3.clean(_md.render(body or ""))
def render_text(body):     return '<pre class="doc-plain">' + nh3.clean(body or "", tags=set()) + "</pre>"
```

Raw HTML inside Markdown is allowed through the renderer (tables, `<details>` survive) and
then stripped by nh3 (scripts, event handlers, `javascript:` URLs do not). The result is
injected with Jinja `|safe`.

HTML documents are **never inlined**. The Document page shows them in
`<iframe sandbox="allow-scripts allow-forms allow-popups" src="/api/documents/{id}/raw">`.
Belt and braces: the iframe attribute sandboxes on the embedding side, and the raw
endpoint's `CSP: sandbox …` header sandboxes on the response side, so even opening the raw
URL directly in a tab gives it an opaque origin. Scripts in an uploaded page can run but
cannot read the session cookie or call the app's API.

`page_context` decides the display mode from kind + content type:

```
kind == "html"              -> show = "iframe"   (sandboxed, src = raw_url)
content_type image/*        -> show = "image"    (<img src=raw_url>)
content_type application/pdf-> show = "pdf"      (<iframe src=raw_url>, taller)
kind md | txt               -> show = "inline"   (pre-rendered html with |safe)
anything else               -> show = "download" (link to raw_url?download=1)
editable = is_text_kind(kind)
```

The editor's live preview calls `POST /api/documents/render` so preview and final page are
produced by the same code. HTML editing previews via `iframe.srcdoc` into the same sandboxed
iframe.

## 8. UI

### Documents panel on the parent page (`task.html` + `task.js`)

- Header: count badge, **New note** button, **Upload** (a `<label>` wrapping a hidden
  `<input type=file multiple>`), and a dashed **drop zone**.
- Rows rendered server-side on first load, appended client-side after upload. Each row:
  kind chip (`.doc-kind-md` etc.), name link to `/documents/{id}`, size + edited-at,
  actions: `edit` (text kinds only, links to `?edit=1`), `rename`, `delete`.
- Upload: builds `FormData` with repeated `files` entries, `fetch` POST, appends returned
  rows, shows `⚠ err; err` or `✓ Added N`. Same function serves picker and drop.
- New note: `prompt()` for a name → POST → `location.href = /documents/{id}?edit=1`.
- Rename: `prompt()` → POST `{updates:{name}}` → patch the row in place.
- Delete: `confirm()` → POST `/delete` → remove `<li>`, update count/empty state.
- One delegated `click` listener on the `<ul>` handles rename/delete via `closest(".doc-row")`
  and `dataset.id` / `dataset.name`.

### Document page (`document.html` + `document.js`)

- Head: back link to parent (title from a `{Title: 1}` projection), name, kind chip, size,
  tools: View/Edit toggle (text only), Save (edit mode only, disabled until dirty),
  **Download** (`href=raw_url?download=1` with a `download` attribute), **Print**
  (`window.print()`, print CSS hides the chrome).
- View mode: `<article class="doc-body [markdown-body]">` containing whichever `show`
  branch applies.
- Edit mode: two-column grid, `<textarea id=doc-body>` left, preview right (article for
  md/txt, sandboxed iframe for html). Behaviour: 300 ms debounced preview, Tab inserts two
  spaces, Ctrl/Cmd-S saves, `beforeunload` warns when dirty, Save posts `{updates:{body}}`
  only (name is edited from the parent page).
- Both pages hand config to their island via `window.TASK = {...}` / `window.DOC = {id, kind, edit}`
  rendered with `|tojson`; scripts are cache-busted by file mtime (`css_v()`).

CSS hooks live in `app.css` under `.drop-zone`, `.doc-list/.doc-row/.doc-kind*`, `.doc-body`,
`.doc-frame`, `.doc-editor`, `.markdown-body`, and a `@media print` block.

## 9. Deletion, cascade, audit (ADR-0004)

- Deleting a document: `audit.log_deletions("documents", [row])` inserts
  `{collection, doc, deleted_at}` into `deletions`, then GridFS bytes are removed (a missing
  file does not block), then the row.
- Deleting a parent Task goes through the shared grid CRUD, which accepts a `delete_hook`;
  the ledger router wires `delete_hook=documents.delete_for_tasks`, so every document of the
  deleted tasks is audited and removed first. The task row itself is audited by the grid.
- Recovery is manual (re-insert from `deletions`, re-upload bytes); confirm dialogs say
  "logged but not undoable in the UI".

## 10. Desktop-window quirk

The app also runs inside a pywebview window (WKWebView on macOS, WebKit2GTK on Linux).
WKWebView renders `Content-Disposition: attachment` responses inline unless the host opts
in, so the Download button showed Markdown as plain text. Fix (commit 9384174):
`webview.settings["ALLOW_DOWNLOADS"] = True` in `desktop.py` **and** a `download` attribute
on the anchor. That combination routes through WebKit's own downloader, which shares the
window's session cookie; pywebview's fallback re-fetches without cookies and would save the
login page instead. Any port that ships a pywebview shell needs both halves.

## 11. Tests (`tests/test_documents.py`)

Harness: mongomock-motor replaces `db` in every `app.*` module (swept by identity), the
GridFS seam is replaced with a dict, `app.state.auth_disabled = True`, httpx `AsyncClient`
over `ASGITransport`. One seeded document `d1` (`repro.md` on task `k2`).

Coverage: classify by extension then content type; Markdown renders tables/bold and drops
`<script>`; text upload stored inline and binary in the store (multipart with two files);
empty file and missing parent reported in `errors`; 4 MB text cap raises; new note is blank
`.md`; body edit and rename are independent dirty-diffs, empty name is 400; body edit on a
binary is 400; raw endpoint returns text and bytes with the sandbox CSP and inline /
attachment dispositions; missing GridFS file is a 404 not a 500; delete audits and tolerates
a missing file; parent page lists documents and 404s; Document page renders md inline,
html in a sandboxed iframe without leaking the script text, image as `<img>`; render
preview endpoint.

---

## 12. Porting checklist: generalizing to another app

What is generic (copy as-is, rename the parent):

1. **`documents.py`** minus `_task_exists` and the `task_id` field name. Parameterize:
   `COLLECTION`, `BUCKET`, the parent collection, the parent foreign-key field name
   (`task_id` → `item_id`, `recipe_id`, …), the two caps.
2. **The classify rule, `is_text_kind`, `render_markdown`, `render_text`, `decode_text`,
   `serialize`, `page_context`, the three GridFS seam functions.** All pure or
   storage-only; no task vocabulary inside them.
3. **The router block** for `/documents/{id}`, `/api/documents/{id}`, `/…/delete`,
   `/…/raw`, `/api/documents/render`. Only the two parent-scoped routes
   (`POST /api/<parent>/{id}/documents` and `/notes`) and the `back` redirect need the
   parent's name.
4. **`document.html` + `document.js`** unchanged except the back link and page title suffix.
5. **The Documents panel** section of the parent template and the `// --- documents` block
   of the parent's JS island. It depends only on `window.<PARENT>.id`, the `#doc-*`
   element ids, and the two parent-scoped endpoints.
6. **Tests**: the `fake_store` fixture and every test that hits `/api/documents/*` or
   `/documents/*` port directly; the upload/note tests just need a seeded parent.
7. **Dependencies**: `markdown-it-py`, `nh3`, `python-multipart` (for `UploadFile`), Motor's
   `AsyncIOMotorGridFSBucket`.

What must exist in the host app (or be brought along):

- `web.DomainError` + `web.guard()` + `web.read_body()` (the JSON 4xx convention).
- `audit.log_deletions()` and a `deletions` collection, if the audit behaviour is wanted.
- A parent-delete path that can call `delete_for_parents(ids)` before removing parents
  (the grid's `delete_hook` here; a plain call in a simpler app).
- A view-model that includes `documents: list_for_parent(id)` for the parent page.
- An auth gate that covers `/api/documents/*/raw` (raw bytes are as private as the parent).

Design decisions to keep, and why:

- **Extension-first classification with a `file` default** keeps the rule explainable to the
  user ("it's a text doc if it's .md/.html/.txt").
- **Text inline, binary in a bucket** gives free in-app editing for text and no 16 MB Mongo
  document limit problem for files.
- **Project `body` out of list queries** so the parent page stays cheap however many notes
  exist.
- **One server-side renderer + sanitizer**, reused by the preview endpoint, so there is
  exactly one place XSS can be reasoned about.
- **Double sandbox for HTML** (iframe attribute + CSP header on the raw response).
- **Dirty-diff updates** (`{updates:{…}}` with only changed keys) so rename and body edits
  never clobber each other.
- **Tolerant delete** so a lost GridFS file never leaves an undeletable row.
- **Batch upload returns per-file errors** instead of failing the whole request.

Things you might change when porting:

- Add an index on the parent-id field if the collection will be large.
- Replace `prompt()`/`confirm()` with in-page modals if the host app already has them.
- If the host has a role/multi-user model, `raw` and `get` need an ownership check
  (there is none here; single-user).
- The `file` kind could be split further (e.g. `csv` rendered as a table) by extending
  `_EXT_KIND`, `page_context.show`, and one template branch.
- `linkify` is off in the Markdown renderer; turn it on if bare URLs should become links
  (nh3 will still sanitize them).

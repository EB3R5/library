# library

A personal learning library: a single-screen Workbench over Items that hold
Documents, with Claude-in-the-loop editing of those documents. The glossary
below is the ubiquitous language; implementation lives in plan.md and code.

## Language

**Item**:
A named container with an Area and Tags that holds any number of Documents. It has no content of its own.
_Avoid_: folder, entry, bundle, pair

**Document**:
One attachment belonging to exactly one Item. Either a Text Document or a File Document, never both.
_Avoid_: rendition, file, page, artifact

**Text Document**:
A Document of Kind `md`, `html` or `txt` whose content is stored as a UTF-8 body and is editable in-app.

**File Document**:
A Document of Kind `file` (images, PDFs, anything else) whose bytes are stored as a Blob. Renamed or deleted, never edited in-app.
_Avoid_: attachment, binary, upload

**Note**:
A Text Document of Kind `md` created empty from the Workbench rather than uploaded. Not a third flavour.

**Kind**:
The classification of a Document: `md`, `html`, `txt` or `file`. Decided by file extension first, content type second, default `file`.
_Avoid_: type, format, flavour

**Blob**:
The stored bytes of a File Document, referenced by id from the Document. Only the storage seam touches Blobs.
_Avoid_: GridFS, bucket, file store

**Version**:
The body a Text Document had before an edit replaced it, kept with when and why it was replaced. Created by every body change, never by rename.
_Avoid_: revision, snapshot, commit, backup

**History**:
The list of a Text Document's Versions, from which any one can be restored. Restoring is itself an edit.
_Avoid_: log, timeline, undo stack

**Entry Document**:
The Document shown in the reader when its Item is opened: the one the user pinned, or the first created when none is pinned.
_Avoid_: main file, index, entry rendition, default document

**Area**:
The top-level grouping of Items in the tree (research, painting, teach, misc).
_Avoid_: category, section, workspace

**Tag**:
A free-form label on an Item, used for filtering.

**Workbench**:
The single-screen three-pane UI: tree, reader, third pane (Info · ✨ Claude).

**Claude edit**:
A change to one Text Document made by `claude -p` on the user's button press, shown as a diff, then Accepted (becomes the body, old body becomes a Version) or Reverted. Sibling Text Documents are context Claude may read, never change.
_Avoid_: AI edit, generation, run

**Scratch directory**:
The temporary folder an Item's Text Documents are written to for one Claude edit, and read back from for the diff. Gone once the edit is Accepted or Reverted.
_Avoid_: working tree, checkout, item dir

**Export**:
A user-invoked dump of every Item's Documents to a plain folder tree plus a copy of the database. The backup mechanism.
_Avoid_: rebuild, sync, mirror

**Source**:
Where an Item or a Document came from, as `<scheme>:<id>` — the first scheme is `tasks:` for a task or document in the Tasks app. Machine-written, never typed; shown as a link in the Info tab. Says where a thing came from, not that it is still in sync.
_Avoid_: origin, provenance (in code), link, sync

**Agent API**:
The JSON routes under `/api/agent` an agent or script uses to list, search, read, create and tag Items and add Text Documents, admitted by the API token alone, never by a Session. Each route is one call into the store. See ADR 0005.
_Avoid_: REST API, integration, webhook, sync

**API token**:
The static secret (`API_TOKEN` in `.env`) a bearer header carries to use the Agent API or pass the gate without a Login. Separate from the session secret; empty means the Agent API is off.
_Avoid_: API key, access token, JWT

**Login**:
The one username + password + authenticator code that opens the Workbench. A single credential row, written by `create-user`, replaced never merged.
_Avoid_: account, user management, sign-up

**Session**:
The signed cookie a successful Login leaves in the browser, good for seven days or until Sign out. The gate admits a request with a Session, an exempt path, or a valid API token; everything else is sent to the login page (pages) or refused with 401 (API).
_Avoid_: auth token, JWT, login state

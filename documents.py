"""The store: Items and their Documents live in SQLite (plan.md v2, ADR 0002).

Text Documents (md/html/txt) keep their UTF-8 body in the row; File Documents
keep bytes in `blobs` behind the three-function seam store_bytes / read_bytes /
delete_bytes — the only code that touches blobs. Every body change files the
previous body as a Version. FTS5 holds one row per Document and one per Item
and is kept in sync here. No HTTP, no templates: everything takes a connection.
"""
import datetime
import html
import mimetypes
import re
import sqlite3
from pathlib import PurePosixPath
from uuid import uuid4

import markdown as md_lib
import nh3

from config import AREAS, DB_PATH, LIBRARY

TEXT_CAP = 4 * 1024 * 1024
FILE_CAP = 50 * 1024 * 1024

SCHEMA = """
CREATE TABLE IF NOT EXISTS items(
  id           TEXT PRIMARY KEY,           -- uuid4().hex
  title        TEXT NOT NULL,
  area         TEXT NOT NULL,
  created_at   TEXT, updated_at TEXT, last_opened TEXT,
  entry_doc_id TEXT);                      -- nullable pin; fallback = first created
CREATE TABLE IF NOT EXISTS documents(
  id           TEXT PRIMARY KEY,
  item_id      TEXT NOT NULL REFERENCES items(id),
  name         TEXT NOT NULL,              -- display name; extension drives kind
  kind         TEXT NOT NULL,              -- md | html | txt | file
  content_type TEXT,
  size         INTEGER,                    -- bytes (UTF-8 length for text)
  body         TEXT,                       -- TEXT ONLY
  file_id      TEXT,                       -- FILE ONLY -> blobs.id
  created_at   TEXT, edited_at TEXT,
  UNIQUE(item_id, name));
CREATE INDEX IF NOT EXISTS documents_item ON documents(item_id);
CREATE TABLE IF NOT EXISTS blobs(
  id TEXT PRIMARY KEY, data BLOB, content_type TEXT, name TEXT);
CREATE TABLE IF NOT EXISTS document_versions(
  id          TEXT PRIMARY KEY,
  doc_id      TEXT NOT NULL REFERENCES documents(id),
  body        TEXT,
  kind        TEXT,                        -- kind at snapshot time
  cause       TEXT,                        -- save | restore | claude: <summary>
  replaced_at TEXT);
CREATE INDEX IF NOT EXISTS versions_doc ON document_versions(doc_id);
CREATE TABLE IF NOT EXISTS deletions(collection TEXT, doc TEXT, deleted_at TEXT);
CREATE TABLE IF NOT EXISTS tags(id INTEGER PRIMARY KEY, name TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS item_tags(item_id TEXT, tag_id INTEGER, UNIQUE(item_id, tag_id));
CREATE TABLE IF NOT EXISTS areas(name TEXT PRIMARY KEY);  -- user-named, may be empty
CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
  ref_id UNINDEXED, item_id UNINDEXED, scope UNINDEXED, name, body);
"""


class DomainError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def new_id() -> str:
    return uuid4().hex


# ---------------------------------------------------------------- connection
def connect(path=None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")   # declared; cascades stay explicit in code
    conn.executescript(SCHEMA)
    return conn


def _retire_v1_db() -> str | None:
    """A v1 library.db (an index cache over items/) is moved aside, never migrated."""
    if not DB_PATH.exists():
        return None
    probe = sqlite3.connect(DB_PATH)
    try:
        cols = {r[1] for r in probe.execute("PRAGMA table_info(items)")}
    finally:
        probe.close()
    if "dir" not in cols:
        return None
    aside = DB_PATH.with_name("library.v1.db")
    DB_PATH.rename(aside)
    return str(aside)


def first_run_init() -> None:
    LIBRARY.mkdir(parents=True, exist_ok=True)
    aside = _retire_v1_db()
    if aside:
        print(f"v1 index cache moved aside → {aside} (v2 starts empty; items/ is untouched)")
    connect().close()


# ---------------------------------------------------------------- classify
_EXT_KIND = {".md": "md", ".markdown": "md", ".txt": "txt", ".html": "html", ".htm": "html"}
_CT_KIND = {"text/markdown": "md", "text/html": "html", "text/plain": "txt"}
_KIND_CT = {"md": "text/markdown", "html": "text/html", "txt": "text/plain"}


def classify(filename: str, content_type: str | None = None) -> str:
    """Extension first, content type second, default `file`."""
    ext = PurePosixPath(filename or "").suffix.lower()
    if ext in _EXT_KIND:
        return _EXT_KIND[ext]
    return _CT_KIND.get((content_type or "").split(";")[0].strip().lower(), "file")


def is_text_kind(kind: str) -> bool:
    """The single gate: inline-vs-blob on upload, may `body` be edited, raw source."""
    return kind in _KIND_CT


def clean_name(raw: str) -> str:
    name = PurePosixPath(str(raw or "").replace("\\", "/")).name.strip()
    if not name or name in (".", ".."):
        raise DomainError("name cannot be empty")
    return name


# ---------------------------------------------------------------- blob seam
# The ONLY three places bytes are stored/read/deleted.
def store_bytes(conn, data: bytes, name: str, content_type: str) -> str:
    fid = new_id()
    conn.execute("INSERT INTO blobs VALUES(?,?,?,?)", (fid, data, content_type, name))
    return fid


def read_bytes(conn, file_id: str) -> tuple[bytes, str]:
    row = conn.execute("SELECT data, content_type FROM blobs WHERE id=?", (file_id,)).fetchone()
    if not row:
        raise KeyError(file_id)
    return bytes(row[0]), row[1]


def delete_bytes(conn, file_id: str | None) -> None:
    if file_id:  # swallows "already gone"
        conn.execute("DELETE FROM blobs WHERE id=?", (file_id,))


# ---------------------------------------------------------------- rendering
_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n.*?(?:\r?\n---[ \t]*(?:\r?\n|\Z))", re.S)


def strip_frontmatter(text: str) -> str:
    """A leading `---` YAML block is hidden from the view and the index, kept in the body."""
    return _FRONTMATTER.sub("", text or "", count=1)


def render_markdown(body: str) -> str:
    """One code path for the page and the editor's live preview."""
    html = md_lib.markdown(strip_frontmatter(body), extensions=["fenced_code", "tables"])
    return nh3.clean(html)


def render_text(body: str) -> str:
    return '<pre class="doc-plain">' + nh3.clean(strip_frontmatter(body), tags=set()) + "</pre>"


def decode_text(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise DomainError("text document is not UTF-8")


# ---------------------------------------------------------------- search (FTS5)
def html_to_text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ",
                  re.sub(r"<(script|style)[\s\S]*?</\1>", " ", html or "", flags=re.I)))


def index_text(d: dict) -> str:
    """What FTS sees for a document: md/txt minus frontmatter, html stripped, files nothing."""
    if d["kind"] == "html":
        return html_to_text(d.get("body"))
    return strip_frontmatter(d.get("body")) if is_text_kind(d["kind"]) else ""


def set_doc_fts(conn, d: dict) -> None:
    conn.execute("DELETE FROM search WHERE ref_id=?", (d["id"],))
    conn.execute("INSERT INTO search(ref_id,item_id,scope,name,body) VALUES(?,?,'document',?,?)",
                 (d["id"], d["item_id"], d["name"], index_text(d)))


def set_item_fts(conn, item_id: str) -> None:
    it = conn.execute("SELECT title FROM items WHERE id=?", (item_id,)).fetchone()
    conn.execute("DELETE FROM search WHERE ref_id=?", (item_id,))
    if it:
        conn.execute("INSERT INTO search(ref_id,item_id,scope,name,body) VALUES(?,?,'item',?,?)",
                     (item_id, item_id, it["title"], " ".join(tags_of(conn, item_id))))


def drop_fts(conn, ref_ids: list[str]) -> None:
    conn.executemany("DELETE FROM search WHERE ref_id=?", [(i,) for i in ref_ids])


def search(conn, q: str, limit: int = 60) -> list[tuple[str, dict]]:
    """Exact MATCH first; if that errors (FTS syntax) or finds nothing, retry as
    prefix terms so live typing and names like `data.bin` still hit. Returns
    [(item_id, {"item": hit|None, "docs": [hits]})], Item hits ranked above
    Document hits, bm25 within."""
    q = q.strip()
    prefix = " ".join(w + "*" for w in re.findall(r"\w+", q))
    rows = []
    for query in (q, prefix):
        if not query:
            continue
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT ref_id, item_id, scope, name, "
                "snippet(search, 3, char(1), char(2), '…', 8) AS nsnip, "
                "snippet(search, 4, char(1), char(2), '…', 12) AS snip, "
                "bm25(search, 0, 0, 0, 4.0, 1.0) AS rank "
                "FROM search WHERE search MATCH ? ORDER BY rank LIMIT ?",
                (query, limit))]
        except sqlite3.OperationalError:
            rows = []
        if rows or query == prefix:
            break
    groups: dict[str, dict] = {}
    for r in rows:
        # Snippets are raw indexed text (markdown source included): escape them,
        # then turn the control-char markers into <mark> — the only HTML kept.
        for k in ("nsnip", "snip"):
            r[k] = (html.escape(r[k] or "", quote=False)
                    .replace("\x01", "<mark>").replace("\x02", "</mark>"))
        g = groups.setdefault(r["item_id"], {"item": None, "docs": []})
        if r["scope"] == "item":
            g["item"] = r
        else:
            g["docs"].append(r)

    def key(kv):
        g = kv[1]
        if g["item"]:
            return (0, g["item"]["rank"])
        return (1, min(d["rank"] for d in g["docs"]))
    return sorted(groups.items(), key=key)


def reindex(conn) -> int:
    """Rebuild the whole FTS table from the rows."""
    conn.execute("DELETE FROM search")
    docs = [dict(r) for r in conn.execute("SELECT * FROM documents")]
    for d in docs:
        set_doc_fts(conn, d)
    items = [r[0] for r in conn.execute("SELECT id FROM items")]
    for i in items:
        set_item_fts(conn, i)
    conn.commit()
    return len(docs) + len(items)


# ---------------------------------------------------------------- areas
def all_areas(conn) -> list[str]:
    """Defaults first (config order), then every other area in use or named."""
    extra = {r[0] for r in conn.execute("SELECT name FROM areas")}
    extra |= {r[0] for r in conn.execute("SELECT DISTINCT area FROM items")}
    return list(AREAS) + sorted(a for a in extra if a and a not in AREAS)


def add_area(conn, name: str) -> str:
    name = " ".join(str(name or "").split()).strip().lower()
    if name:
        conn.execute("INSERT OR IGNORE INTO areas(name) VALUES(?)", (name,))
        conn.commit()
    return name


# ---------------------------------------------------------------- items
def get_item(conn, item_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    return dict(row) if row else None


def _require_item(conn, item_id: str) -> dict:
    it = get_item(conn, item_id)
    if not it:
        raise DomainError("item not found", 404)
    return it


def list_items(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM items ORDER BY lower(title)")]


def create_item(conn, title: str, area: str) -> str:
    title = " ".join(str(title or "").split()).strip()
    if not title:
        raise DomainError("title cannot be empty")
    iid, ts = new_id(), now()
    conn.execute("INSERT INTO items(id,title,area,created_at,updated_at) VALUES(?,?,?,?,?)",
                 (iid, title, area or "misc", ts, ts))
    set_item_fts(conn, iid)
    conn.commit()
    return iid


def touch_item(conn, item_id: str) -> None:
    """items.updated_at bumps on any document mutation or tag change."""
    conn.execute("UPDATE items SET updated_at=? WHERE id=?", (now(), item_id))


def open_item(conn, item_id: str) -> None:
    conn.execute("UPDATE items SET last_opened=? WHERE id=?", (now(), item_id))
    conn.commit()


def set_area(conn, item_id: str, area: str) -> None:
    _require_item(conn, item_id)
    conn.execute("UPDATE items SET area=? WHERE id=?", (area or "misc", item_id))
    touch_item(conn, item_id)
    conn.commit()


def set_entry(conn, item_id: str, doc_id: str) -> None:
    d = get(conn, doc_id)
    if d["item_id"] != item_id:
        raise DomainError("document belongs to another item")
    conn.execute("UPDATE items SET entry_doc_id=? WHERE id=?", (doc_id, item_id))
    conn.commit()


def entry_for(conn, item: dict) -> dict | None:
    """Entry Document = the pinned one, else the first created."""
    dlist = list_for_item(conn, item["id"])
    for d in dlist:
        if d["id"] == item.get("entry_doc_id"):
            return d
    return dlist[0] if dlist else None


def tags_of(conn, item_id: str) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT name FROM tags JOIN item_tags ON tags.id=tag_id "
        "WHERE item_id=? ORDER BY name", (item_id,))]


def set_tags(conn, item_id: str, names: list[str]) -> None:
    _require_item(conn, item_id)
    conn.execute("DELETE FROM item_tags WHERE item_id=?", (item_id,))
    for n in names:
        n = n.strip()
        if not n:
            continue
        conn.execute("INSERT OR IGNORE INTO tags(name) VALUES(?)", (n,))
        tid = conn.execute("SELECT id FROM tags WHERE name=?", (n,)).fetchone()[0]
        conn.execute("INSERT OR IGNORE INTO item_tags VALUES(?,?)", (item_id, tid))
    set_item_fts(conn, item_id)
    touch_item(conn, item_id)
    conn.commit()


def delete_item(conn, item_id: str) -> int:
    """Cascade: audit → blobs → versions → FTS → document rows → tags → item."""
    _require_item(conn, item_id)
    n = delete_for_items(conn, [item_id])
    conn.execute("DELETE FROM item_tags WHERE item_id=?", (item_id,))
    drop_fts(conn, [item_id])
    conn.execute("DELETE FROM items WHERE id=?", (item_id,))
    conn.commit()
    return n


# ---------------------------------------------------------------- documents
def _unique_name(conn, item_id: str, name: str) -> str:
    """Names are unique per Item: a clashing upload or note is auto-suffixed."""
    taken = {r[0] for r in conn.execute(
        "SELECT name FROM documents WHERE item_id=?", (item_id,))}
    if name not in taken:
        return name
    p = PurePosixPath(name)
    stem, ext = p.stem, p.suffix
    n = 2
    while f"{stem} ({n}){ext}" in taken:
        n += 1
    return f"{stem} ({n}){ext}"


def _insert(conn, row: dict) -> dict:
    conn.execute(
        "INSERT INTO documents(id,item_id,name,kind,content_type,size,body,file_id,"
        "created_at,edited_at) VALUES(:id,:item_id,:name,:kind,:content_type,:size,"
        ":body,:file_id,:created_at,:edited_at)", row)
    set_doc_fts(conn, row)
    touch_item(conn, row["item_id"])
    conn.commit()
    return serialize(row)


def add_upload(conn, item_id: str, filename: str, content_type: str | None,
               data: bytes) -> dict:
    _require_item(conn, item_id)
    if not data:
        raise DomainError("empty file")
    name = _unique_name(conn, item_id, clean_name(filename or "file"))
    kind = classify(name, content_type)
    ts = now()
    row = dict(id=new_id(), item_id=item_id, name=name, kind=kind, size=len(data),
               body=None, file_id=None, created_at=ts, edited_at=ts)
    if is_text_kind(kind):
        if len(data) > TEXT_CAP:
            raise DomainError(f"text over {TEXT_CAP // 2**20} MB cap")
        row["body"] = decode_text(data)
        row["size"] = len(row["body"].encode())
        row["content_type"] = _KIND_CT[kind]
    else:
        if len(data) > FILE_CAP:
            raise DomainError(f"file over {FILE_CAP // 2**20} MB cap")
        ct = (content_type or "").split(";")[0].strip() or None
        if not ct or ct == "application/octet-stream":
            ct = mimetypes.guess_type(name)[0] or "application/octet-stream"
        row["content_type"] = ct
        row["file_id"] = store_bytes(conn, data, name, ct)
    return _insert(conn, row)


def add_note(conn, item_id: str, name: str | None) -> dict:
    """A Note: a Text Document of kind md created empty from the panel."""
    _require_item(conn, item_id)
    name = (name or "").strip() or "Note"
    if not name.lower().endswith(".md"):
        name += ".md"
    name = _unique_name(conn, item_id, clean_name(name))
    ts = now()
    return _insert(conn, dict(id=new_id(), item_id=item_id, name=name, kind="md",
                              content_type="text/markdown", size=0, body="",
                              file_id=None, created_at=ts, edited_at=ts))


def list_for_item(conn, item_id: str) -> list[dict]:
    """Bodies are projected out — the panel stays cheap however many notes exist."""
    rows = conn.execute(
        "SELECT id,item_id,name,kind,content_type,size,file_id,created_at,edited_at "
        "FROM documents WHERE item_id=? ORDER BY created_at, rowid", (item_id,)).fetchall()
    return [serialize(dict(r)) for r in rows]


def text_docs(conn, item_id: str) -> list[dict]:
    """Every Text Document of an Item with its body (the Claude scratch set)."""
    return [dict(r) for r in conn.execute(
        "SELECT * FROM documents WHERE item_id=? AND kind IN ('md','html','txt') "
        "ORDER BY created_at, rowid", (item_id,))]


def get(conn, doc_id: str) -> dict:
    row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not row:
        raise DomainError("document not found", 404)
    return dict(row)


def update(conn, doc_id: str, updates: dict, cause: str = "save") -> None:
    """Dirty-diff: only the keys present are touched. A body change files the
    previous body as a Version with `cause`; a rename never does."""
    d = get(conn, doc_id)
    sets = {}
    if "name" in updates:
        name = clean_name(updates["name"])
        if name != d["name"]:
            clash = conn.execute("SELECT 1 FROM documents WHERE item_id=? AND name=? AND id<>?",
                                 (d["item_id"], name, doc_id)).fetchone()
            if clash:
                raise DomainError(f"a document named {name} already exists in this item")
            sets["name"] = name
            if is_text_kind(d["kind"]):  # rename re-classifies text; files never change kind
                kind = classify(name, d["content_type"])
                if is_text_kind(kind):
                    sets["kind"] = kind
                    sets["content_type"] = _KIND_CT[kind]
    if "body" in updates:
        if not is_text_kind(d["kind"]):
            raise DomainError("only text documents have an editable body")
        body = str(updates["body"] or "")
        if len(body.encode()) > TEXT_CAP:
            raise DomainError(f"text over {TEXT_CAP // 2**20} MB cap")
        if body != (d["body"] or ""):
            sets["body"] = body
            sets["size"] = len(body.encode())
    if not sets:
        return
    sets["edited_at"] = now()
    if "body" in sets:
        conn.execute("INSERT INTO document_versions VALUES(?,?,?,?,?,?)",
                     (new_id(), doc_id, d["body"] or "", d["kind"], cause, sets["edited_at"]))
    cols = ", ".join(f"{k}=:{k}" for k in sets)
    conn.execute(f"UPDATE documents SET {cols} WHERE id=:id", {**sets, "id": doc_id})
    set_doc_fts(conn, {**d, **sets})
    touch_item(conn, d["item_id"])
    conn.commit()


def _audit(conn, rows: list[dict]) -> None:
    ts = now()
    conn.executemany("INSERT INTO deletions VALUES('documents',?,?)",
                     [(repr({k: v for k, v in r.items() if k != "body"}), ts) for r in rows])


def _delete_rows(conn, rows: list[dict]) -> None:
    """audit → blobs → versions → FTS → rows; the pin is cleared if it pointed here."""
    if not rows:
        return
    _audit(conn, rows)
    ids = [r["id"] for r in rows]
    for r in rows:
        delete_bytes(conn, r["file_id"])   # tolerant — a lost blob never blocks
    conn.executemany("DELETE FROM document_versions WHERE doc_id=?", [(i,) for i in ids])
    drop_fts(conn, ids)
    conn.executemany("DELETE FROM documents WHERE id=?", [(i,) for i in ids])
    conn.executemany("UPDATE items SET entry_doc_id=NULL WHERE entry_doc_id=?",
                     [(i,) for i in ids])


def delete(conn, doc_id: str) -> None:
    d = get(conn, doc_id)
    _delete_rows(conn, [d])
    touch_item(conn, d["item_id"])
    conn.commit()


def delete_for_items(conn, item_ids: list[str]) -> int:
    """Cascade for the parent's delete path."""
    q = ",".join("?" * len(item_ids))
    rows = [dict(r) for r in conn.execute(
        f"SELECT * FROM documents WHERE item_id IN ({q})", item_ids)]
    _delete_rows(conn, rows)
    conn.commit()
    return len(rows)


def detach(conn, doc_id: str, title: str, area: str) -> str:
    """Move one Document out of its Item into a new Item of its own. Versions
    follow the document (doc_id is unchanged); the old Item's pin is cleared
    if it pointed here, and both Items' updated_at bump."""
    d = get(conn, doc_id)
    old_item = d["item_id"]
    new_item = create_item(conn, title or PurePosixPath(d["name"]).stem, area)
    conn.execute("UPDATE documents SET item_id=? WHERE id=?", (new_item, doc_id))
    conn.execute("UPDATE items SET entry_doc_id=NULL WHERE id=? AND entry_doc_id=?",
                 (old_item, doc_id))
    set_doc_fts(conn, {**d, "item_id": new_item})
    touch_item(conn, old_item)
    touch_item(conn, new_item)
    conn.commit()
    return new_item


def raw(conn, doc_id: str) -> tuple[bytes, str, str]:
    d = get(conn, doc_id)
    if is_text_kind(d["kind"]):
        return (d["body"] or "").encode(), d["content_type"], d["name"]
    try:
        data, ct = read_bytes(conn, d["file_id"])
    except KeyError:
        raise DomainError("file bytes are missing", 404)
    return data, d["content_type"] or ct or "application/octet-stream", d["name"]


# ---------------------------------------------------------------- versions
def versions(conn, doc_id: str) -> list[dict]:
    """Newest first, bodies projected out."""
    get(conn, doc_id)
    return [dict(r) for r in conn.execute(
        "SELECT id, doc_id, kind, cause, replaced_at, length(cast(body as blob)) AS size "
        "FROM document_versions WHERE doc_id=? ORDER BY replaced_at DESC, rowid DESC",
        (doc_id,))]


def get_version(conn, doc_id: str, version_id: str) -> dict:
    row = conn.execute("SELECT * FROM document_versions WHERE id=? AND doc_id=?",
                       (version_id, doc_id)).fetchone()
    if not row:
        raise DomainError("version not found", 404)
    return dict(row)


def restore(conn, doc_id: str, version_id: str) -> None:
    """Restore is a normal edit — body only, kind keeps following the name."""
    v = get_version(conn, doc_id, version_id)
    update(conn, doc_id, {"body": v["body"]}, cause="restore")


# ---------------------------------------------------------------- view-models
def serialize(d: dict) -> dict:
    ct = d.get("content_type") or ""
    return dict(id=d["id"], item_id=d["item_id"], name=d["name"], kind=d["kind"],
                content_type=ct, size=d.get("size") or 0, edited_at=d.get("edited_at"),
                created_at=d.get("created_at"),
                is_image=ct.startswith("image/"), is_pdf=ct == "application/pdf",
                editable=is_text_kind(d["kind"]))


def page_context(d: dict) -> dict:
    """Display mode, kind first then content type (plan: Rendering)."""
    ct = d.get("content_type") or ""
    raw_url = f"/api/documents/{d['id']}/raw"
    if d["kind"] == "html":
        show, html = "iframe", ""
    elif ct.startswith("image/"):
        show, html = "image", ""
    elif ct == "application/pdf":
        show, html = "pdf", ""
    elif d["kind"] == "md":
        show, html = "inline", render_markdown(d.get("body"))
    elif d["kind"] == "txt":
        show, html = "inline", render_text(d.get("body"))
    else:
        show, html = "download", ""
    return dict(doc=serialize(d), body=d.get("body") or "", show=show, html=html,
                raw_url=raw_url, editable=is_text_kind(d["kind"]))

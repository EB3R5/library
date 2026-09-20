"""PROTOTYPE — documents stored in the DB (ported from tasks-webapp's documents.py).

QUESTION: does library feel right if each item's documents live in SQLite —
text kinds (md/html/txt) inline in the row, everything else as bytes in a
`blobs` table behind a three-function seam — instead of files in the
git-backed ~/learning-library/ folder?

ASSUMPTION (from "store the documents in the app or in the db like this"):
"like this" = the tasks-webapp shape. So: one `documents` row per attachment,
`body` for text, `file_id` for bytes, extension-first classification, server
side markdown render + sanitize, HTML never inlined (sandboxed iframe + CSP),
dirty-diff updates, tolerant delete, per-file upload errors, deletion audit.

This module is the portable half: no HTTP, no templates. `app.py` is the
throwaway shell. Everything takes a sqlite3 connection.
"""
import datetime
import mimetypes
import re
import sqlite3
from pathlib import PurePosixPath
from uuid import uuid4

import markdown as md_lib
import nh3

TEXT_CAP = 4 * 1024 * 1024
FILE_CAP = 50 * 1024 * 1024

SCHEMA = """
CREATE TABLE IF NOT EXISTS items(
  id TEXT PRIMARY KEY, title TEXT, area TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS documents(
  id           TEXT PRIMARY KEY,           -- uuid4().hex
  item_id      TEXT,                       -- the only link to the parent
  name         TEXT,                       -- display name; extension drives kind
  kind         TEXT,                       -- md | html | txt | file
  content_type TEXT,
  size         INTEGER,                    -- bytes (UTF-8 length for text)
  body         TEXT,                       -- TEXT ONLY
  file_id      TEXT,                       -- FILE ONLY -> blobs.id
  created_at   TEXT, edited_at TEXT);
CREATE INDEX IF NOT EXISTS documents_item ON documents(item_id);
CREATE TABLE IF NOT EXISTS blobs(          -- the "GridFS bucket"
  id TEXT PRIMARY KEY, data BLOB, content_type TEXT, name TEXT);
CREATE TABLE IF NOT EXISTS deletions(collection TEXT, doc TEXT, deleted_at TEXT);
-- Plain FTS5 (same choice as library's db.py): per-document delete+reinsert
-- stays trivially correct. md/txt indexed as-is, html stripped to text,
-- binary files by name only.
CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
  doc_id UNINDEXED, item_id UNINDEXED, name, body);
"""


class DomainError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


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


# ---------------------------------------------------------------- blob seam
# The ONLY three places bytes are stored/read/deleted. Swap for GridFS, S3,
# local disk — nothing else in the module knows where bytes live.
def store_bytes(conn, data: bytes, name: str, content_type: str) -> str:
    fid = uuid4().hex
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
def render_markdown(body: str) -> str:
    html = md_lib.markdown(body or "", extensions=["fenced_code", "tables"])
    return nh3.clean(html)


def render_text(body: str) -> str:
    return '<pre class="doc-plain">' + nh3.clean(body or "", tags=set()) + "</pre>"


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
    """What FTS sees for a document: md/txt as-is, html stripped, files nothing."""
    if d["kind"] == "html":
        return html_to_text(d.get("body"))
    return (d.get("body") or "") if is_text_kind(d["kind"]) else ""


def set_fts(conn, d: dict) -> None:
    conn.execute("DELETE FROM search WHERE doc_id=?", (d["id"],))
    conn.execute("INSERT INTO search(doc_id,item_id,name,body) VALUES(?,?,?,?)",
                 (d["id"], d["item_id"], d["name"], index_text(d)))


def drop_fts(conn, doc_ids: list[str]) -> None:
    conn.executemany("DELETE FROM search WHERE doc_id=?", [(i,) for i in doc_ids])


def search(conn, q: str, limit: int = 30) -> list[dict]:
    """Exact MATCH first; if that errors (FTS syntax) or finds nothing, retry
    as prefix terms so live typing and names like `data.bin` still hit.
    Returns one hit per document: doc_id, item_id, name, snip, rank."""
    q = q.strip()
    prefix = " ".join(w + "*" for w in re.findall(r"\w+", q))
    for query in (q, prefix):
        if not query:
            continue
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT doc_id, item_id, name, "
                "snippet(search, 3, '<mark>', '</mark>', '…', 12) AS snip, "
                "bm25(search, 0, 0, 4.0, 1.0) AS rank "
                "FROM search WHERE search MATCH ? ORDER BY rank LIMIT ?",
                (query, limit))]
        except sqlite3.OperationalError:
            continue
        if rows or query == prefix:
            return rows
    return []


def reindex(conn) -> int:
    """Rebuild the whole FTS table from documents (the rebuildable-cache rule)."""
    conn.execute("DELETE FROM search")
    rows = [dict(r) for r in conn.execute("SELECT * FROM documents")]
    for d in rows:
        set_fts(conn, d)
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------- operations
def _item_exists(conn, item_id: str) -> None:
    if not conn.execute("SELECT 1 FROM items WHERE id=?", (item_id,)).fetchone():
        raise DomainError("item not found", 404)


def _insert(conn, row: dict) -> dict:
    conn.execute(
        "INSERT INTO documents(id,item_id,name,kind,content_type,size,body,file_id,"
        "created_at,edited_at) VALUES(:id,:item_id,:name,:kind,:content_type,:size,"
        ":body,:file_id,:created_at,:edited_at)", row)
    set_fts(conn, row)
    conn.commit()
    return serialize(row)


def add_upload(conn, item_id: str, filename: str, content_type: str | None,
               data: bytes) -> dict:
    _item_exists(conn, item_id)
    if not data:
        raise DomainError("empty file")
    name = PurePosixPath(filename or "file").name
    kind = classify(name, content_type)
    ts = now()
    row = dict(id=uuid4().hex, item_id=item_id, name=name, kind=kind, size=len(data),
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
    _item_exists(conn, item_id)
    name = (name or "").strip() or "Note"
    if not name.lower().endswith(".md"):
        name += ".md"
    ts = now()
    return _insert(conn, dict(id=uuid4().hex, item_id=item_id, name=name, kind="md",
                              content_type="text/markdown", size=0, body="",
                              file_id=None, created_at=ts, edited_at=ts))


def list_for_item(conn, item_id: str) -> list[dict]:
    """Bodies are projected out — the panel stays cheap however many notes exist."""
    rows = conn.execute(
        "SELECT id,item_id,name,kind,content_type,size,file_id,created_at,edited_at "
        "FROM documents WHERE item_id=? ORDER BY created_at", (item_id,)).fetchall()
    return [serialize(dict(r)) for r in rows]


def get(conn, doc_id: str) -> dict:
    row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not row:
        raise DomainError("document not found", 404)
    return dict(row)


def update(conn, doc_id: str, updates: dict) -> None:
    """Dirty-diff: only the keys present are touched."""
    d = get(conn, doc_id)
    sets = {}
    if "name" in updates:
        name = PurePosixPath(str(updates["name"] or "")).name.strip()
        if not name:
            raise DomainError("name cannot be empty")
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
        sets["body"] = body
        sets["size"] = len(body.encode())
    if not sets:
        return
    sets["edited_at"] = now()
    cols = ", ".join(f"{k}=:{k}" for k in sets)
    conn.execute(f"UPDATE documents SET {cols} WHERE id=:id", {**sets, "id": doc_id})
    set_fts(conn, {**d, **sets})
    conn.commit()


def _audit(conn, rows: list[dict]) -> None:
    ts = now()
    conn.executemany("INSERT INTO deletions VALUES('documents',?,?)",
                     [(repr({k: v for k, v in r.items() if k != "body"}), ts) for r in rows])


def delete(conn, doc_id: str) -> None:
    d = get(conn, doc_id)
    _audit(conn, [d])
    delete_bytes(conn, d["file_id"])   # tolerant — a lost blob never blocks
    drop_fts(conn, [doc_id])
    conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    conn.commit()


def delete_for_items(conn, item_ids: list[str]) -> int:
    """Cascade for the parent's delete path."""
    q = ",".join("?" * len(item_ids))
    rows = [dict(r) for r in conn.execute(
        f"SELECT * FROM documents WHERE item_id IN ({q})", item_ids)]
    _audit(conn, rows)
    for r in rows:
        delete_bytes(conn, r["file_id"])
    drop_fts(conn, [r["id"] for r in rows])
    conn.execute(f"DELETE FROM documents WHERE item_id IN ({q})", item_ids)
    conn.commit()
    return len(rows)


def raw(conn, doc_id: str) -> tuple[bytes, str, str]:
    d = get(conn, doc_id)
    if is_text_kind(d["kind"]):
        return (d["body"] or "").encode(), d["content_type"], d["name"]
    try:
        data, ct = read_bytes(conn, d["file_id"])
    except KeyError:
        raise DomainError("file bytes are missing", 404)
    return data, d["content_type"] or ct or "application/octet-stream", d["name"]


# ---------------------------------------------------------------- view-models
def serialize(d: dict) -> dict:
    ct = d.get("content_type") or ""
    return dict(id=d["id"], item_id=d["item_id"], name=d["name"], kind=d["kind"],
                content_type=ct, size=d.get("size") or 0, edited_at=d.get("edited_at"),
                is_image=ct.startswith("image/"), is_pdf=ct == "application/pdf",
                editable=is_text_kind(d["kind"]))


def page_context(d: dict) -> dict:
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


def stats(conn) -> dict:
    """What the DB is holding — surfaced after every action."""
    r = conn.execute(
        "SELECT count(*), coalesce(sum(length(cast(body as blob))),0), "
        "sum(kind IN ('md','html','txt')) FROM documents").fetchone()
    b = conn.execute("SELECT count(*), coalesce(sum(length(data)),0) FROM blobs").fetchone()
    orphans = conn.execute(
        "SELECT count(*) FROM blobs WHERE id NOT IN "
        "(SELECT file_id FROM documents WHERE file_id IS NOT NULL)").fetchone()[0]
    return dict(docs=r[0], text_docs=r[2] or 0, inline_bytes=r[1],
                blobs=b[0], blob_bytes=b[1], orphan_blobs=orphans,
                deletions=conn.execute("SELECT count(*) FROM deletions").fetchone()[0],
                fts_rows=conn.execute("SELECT count(*) FROM search").fetchone()[0])

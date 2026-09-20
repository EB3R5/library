"""PROTOTYPE shell — throwaway Workbench over documents-in-the-DB.

Run: ./run.sh proto  →  http://127.0.0.1:8901
DB:  prototype_documents/PROTOTYPE-wipe-me.db (delete it to reset; reseeds).

Only `documents.py` is worth keeping. This file is the hand-driven shell.
"""
import json
import re
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).parent))
import documents as docs  # noqa: E402

HERE = Path(__file__).parent
DB_PATH = HERE / "PROTOTYPE-wipe-me.db"
HOST, PORT = "127.0.0.1", 8901
AREAS = ["research", "painting", "teach", "misc"]

env = Environment(loader=FileSystemLoader(HERE / "templates"), autoescape=True)
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row
conn.executescript(docs.SCHEMA)
for ddl in ("ALTER TABLE items ADD COLUMN tags TEXT DEFAULT ''",
            "ALTER TABLE items ADD COLUMN entry_doc_id TEXT"):
    try:
        conn.execute(ddl)  # PROTOTYPE (ticket #11): tags + pinned entry
    except sqlite3.OperationalError:
        pass
if (conn.execute("SELECT count(*) FROM search").fetchone()[0]
        != conn.execute("SELECT count(*) FROM documents").fetchone()[0]):
    print(f"reindexed FTS: {docs.reindex(conn)} documents")
app = FastAPI()
OPEN_ID: str | None = None


# ---------------------------------------------------------------- seed
def seed() -> None:
    if conn.execute("SELECT 1 FROM items").fetchone():
        return
    a, b = uuid4().hex, uuid4().hex
    conn.executemany("INSERT INTO items VALUES(?,?,?,?)", [
        (a, "Colour theory notes", "painting", docs.now()),
        (b, "Empty item", "misc", docs.now())])
    conn.commit()
    docs.add_upload(conn, a, "notes.md", None, (
        "# Colour theory\n\nRendered **server-side** and sanitized.\n\n"
        "| hue | complement |\n|---|---|\n| red | green |\n| blue | orange |\n\n"
        "<script>alert('this script is stripped by nh3')</script>\n\n"
        "```\nfenced code survives\n```\n").encode())
    docs.add_upload(conn, a, "wheel.html", None, (
        "<!doctype html><body style='font-family:sans-serif;padding:20px'>"
        "<h1>Uploaded HTML page</h1><p>Scripts run here, but sandboxed:</p>"
        "<pre id=o>…</pre><script>"
        "document.getElementById('o').textContent = "
        "'cookie=' + JSON.stringify(document.cookie) + '\\norigin=' + location.origin;"
        "fetch('/api/documents/render',{method:'POST',body:'{}'})"
        ".then(r=>{o.textContent+='\\nfetch app api → HTTP '+r.status})"
        ".catch(e=>{o.textContent+='\\nfetch app api → blocked: '+e.message});"
        "</script></body>").encode())
    docs.add_upload(conn, a, "readme.txt", None, b"plain text <b>not bold</b>\n\tkeeps whitespace")
    docs.add_upload(conn, a, "swatch.svg", "image/svg+xml", (
        '<svg xmlns="http://www.w3.org/2000/svg" width="240" height="120">'
        '<rect width="80" height="120" fill="#c0392b"/><rect x="80" width="80" '
        'height="120" fill="#27ae60"/><rect x="160" width="80" height="120" '
        'fill="#2980b9"/></svg>').encode())
    docs.add_upload(conn, a, "data.bin", "application/octet-stream", bytes(range(256)) * 40)


seed()


# ---------------------------------------------------------------- helpers
def fmt_size(n: int) -> str:
    return f"{n} B" if n < 1024 else f"{n/1024:.1f} KB" if n < 2**20 else f"{n/2**20:.1f} MB"


env.filters["size"] = fmt_size


def tree_html(q: str = "") -> str:
    rows = [dict(r) for r in conn.execute("SELECT * FROM items ORDER BY title")]
    counts = dict(conn.execute("SELECT item_id, count(*) FROM documents GROUP BY item_id"))
    hits = {}
    if q.strip():  # search mode: only items with hits, each hit listed under it
        for h in docs.search(conn, q):
            hits.setdefault(h["item_id"], []).append(h)
        rows = [r for r in rows if r["id"] in hits]
    groups = [(a, [r for r in rows if r["area"] == a]) for a in AREAS]
    return env.get_template("tree.html").render(
        groups=[g for g in groups if g[1]], counts=counts, open_id=OPEN_ID,
        hits=hits, q=q, stats=docs.stats(conn))


def oob_tree() -> str:
    return f'<div id="tree-inner" hx-swap-oob="true">{tree_html()}</div>'


def entry_for(it, dlist: list[dict]) -> dict | None:
    """Entry Document = explicitly pinned, falling back to first created (ticket #11)."""
    if not dlist:
        return None
    for d in dlist:
        if d["id"] == it["entry_doc_id"]:
            return d
    return dlist[0]


def panel_html(item_id: str, tab: str = "info") -> str:
    it = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not it:
        return "<div class=inner>gone</div>"
    dlist = docs.list_for_item(conn, item_id)
    updated = max((d["edited_at"] or "" for d in dlist), default=it["created_at"])
    return env.get_template("panel.html").render(
        it=it, docs=dlist, tab=tab, entry=entry_for(it, dlist), updated=updated,
        tags=[t for t in (it["tags"] or "").split(",") if t.strip()])


def entry_script(item_id: str, edit_id: str = "") -> str:
    """After a mutation: load the entry (or the doc just made), or clear."""
    if edit_id:
        return f"<script>loadDoc('/documents/{edit_id}?edit=1')</script>"
    it = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    e = entry_for(it, docs.list_for_item(conn, item_id)) if it else None
    return f"<script>loadDoc('/documents/{e['id']}')</script>" if e else "<script>clearDoc()</script>"


def guard(fn, *a):
    try:
        return JSONResponse(fn(*a))
    except docs.DomainError as e:
        return JSONResponse({"ok": False, "error": str(e)}, e.status)


# ---------------------------------------------------------------- pages
@app.get("/", response_class=HTMLResponse)
def workbench():
    return env.get_template("layout.html").render(tree=tree_html(), areas=AREAS)


@app.get("/tree", response_class=HTMLResponse)
def tree(q: str = ""):
    return tree_html(q)


@app.get("/open/{item_id}", response_class=HTMLResponse)
def open_item(item_id: str, doc: str = ""):
    """Panel for the item; loads `doc` if given (a search hit), else the entry."""
    global OPEN_ID
    OPEN_ID = item_id
    script = (f"<script>loadDoc('/documents/{doc}')</script>" if doc
              else entry_script(item_id))
    return panel_html(item_id) + script + oob_tree()


@app.get("/panel/{item_id}", response_class=HTMLResponse)
def panel(item_id: str, tab: str = "info"):
    return panel_html(item_id, tab) + oob_tree()


@app.post("/items/{item_id}/tags", response_class=HTMLResponse)
def save_tags(item_id: str, tags: str = Form("")):
    conn.execute("UPDATE items SET tags=? WHERE id=?",
                 (",".join(t.strip() for t in tags.split(",") if t.strip()), item_id))
    conn.commit()
    return panel_html(item_id) + oob_tree()


@app.post("/items/{item_id}/pin/{doc_id}", response_class=HTMLResponse)
def pin_entry(item_id: str, doc_id: str):
    conn.execute("UPDATE items SET entry_doc_id=? WHERE id=?", (doc_id, item_id))
    conn.commit()
    return panel_html(item_id) + oob_tree()


@app.post("/items", response_class=HTMLResponse)
def new_item(title: str = Form(...), area: str = Form("misc")):
    global OPEN_ID
    OPEN_ID = uuid4().hex
    conn.execute("INSERT INTO items(id,title,area,created_at) VALUES(?,?,?,?)",
                 (OPEN_ID, title, area, docs.now()))
    conn.commit()
    return panel_html(OPEN_ID) + "<script>clearDoc()</script>" + oob_tree()


@app.post("/items/{item_id}/delete", response_class=HTMLResponse)
def delete_item(item_id: str):
    global OPEN_ID
    n = docs.delete_for_items(conn, [item_id])  # cascade first, then the parent
    conn.execute("DELETE FROM items WHERE id=?", (item_id,))
    conn.commit()
    OPEN_ID = None
    return (f'<div class="inner muted">item deleted · {n} documents cascaded '
            f'(audited in <code>deletions</code>)</div>'
            "<script>clearDoc()</script>" + oob_tree())


@app.get("/documents/{doc_id}", response_class=HTMLResponse)
def document_page(doc_id: str, edit: int = 0):
    try:
        ctx = docs.page_context(docs.get(conn, doc_id))
    except docs.DomainError as e:
        return HTMLResponse(f"<h3>{e}</h3>", e.status)
    return env.get_template("docpage.html").render(
        **ctx, edit=bool(edit and ctx["editable"]))


# HTMX-facing mutations from the panel (hx-prompt / hx-confirm) --------------
@app.post("/documents/{doc_id}/rename", response_class=HTMLResponse)
def rename(doc_id: str, request: Request, name: str = Form("")):
    """Name comes from hx-prompt (A/B) or an inline form field (C)."""
    item_id = docs.get(conn, doc_id)["item_id"]
    try:
        docs.update(conn, doc_id, {"name": name or request.headers.get("HX-Prompt", "")})
    except docs.DomainError as e:
        return (panel_html(item_id).replace('<div id="status"></div>',
                f'<div id="status" class="warn">⚠ {e}</div>', 1) + oob_tree())
    return panel_html(item_id) + oob_tree()


@app.post("/documents/{doc_id}/delete", response_class=HTMLResponse)
def delete_doc(doc_id: str):
    item_id = docs.get(conn, doc_id)["item_id"]
    docs.delete(conn, doc_id)
    return panel_html(item_id) + entry_script(item_id) + oob_tree()


@app.post("/items/{item_id}/notes", response_class=HTMLResponse)
def new_note(item_id: str, request: Request, name: str = Form("")):
    d = docs.add_note(conn, item_id, name or request.headers.get("HX-Prompt"))
    return panel_html(item_id) + entry_script(item_id, d["id"]) + oob_tree()


# ---------------------------------------------------------------- JSON / bytes API
@app.post("/api/items/{item_id}/documents")
def upload(item_id: str, files: list[UploadFile] = File(...)):
    out, errors = [], []
    for f in files:  # per-file try/except — one bad file never fails the batch
        try:
            out.append(docs.add_upload(conn, item_id, f.filename, f.content_type, f.file.read()))
        except docs.DomainError as e:
            errors.append(f"{f.filename}: {e}")
    return JSONResponse({"ok": not errors, "documents": out, "errors": errors})


@app.post("/api/documents/render")
async def render_preview(request: Request):
    body = (await request.json()).get("body", "")
    return {"html": docs.render_markdown(body)}


@app.post("/api/documents/{doc_id}")
async def update_doc(doc_id: str, request: Request):
    updates = (await request.json()).get("updates", {})
    return guard(lambda: (docs.update(conn, doc_id, updates), {"ok": True})[1])


@app.get("/api/documents/{doc_id}/raw")
def raw(doc_id: str, download: int = 0):
    try:
        data, ct, name = docs.raw(conn, doc_id)
    except docs.DomainError as e:
        return Response(str(e), e.status)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return Response(data, media_type=ct, headers={
        "Content-Disposition": f'{"attachment" if download else "inline"}; filename="{safe}"',
        "Content-Security-Policy": "sandbox allow-scripts allow-forms allow-popups",
        "X-Content-Type-Options": "nosniff"})


@app.get("/api/stats")
def api_stats():
    return docs.stats(conn)


if __name__ == "__main__":
    print(f"PROTOTYPE documents-in-db → http://{HOST}:{PORT}   (db: {DB_PATH.name})")
    uvicorn.run(app, host=HOST, port=PORT)

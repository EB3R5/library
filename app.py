"""library — Workbench over a documents store with Claude-in-the-loop editing.

Run: ./run.sh → http://127.0.0.1:8900 · Backup: ./run.sh export [root]
Spec: plan.md (v2). SQLite is the source of truth (ADR 0002); serve by id,
never by path; HTML is never inlined (sandboxed iframe + CSP on the raw
endpoint); Versions are the undo store; Claude edits go through a scratch dir.
"""
import html
import re
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from jinja2 import Environment, FileSystemLoader

import claude_runner as cr
import documents as docs
from config import EXPORT_DIR, HOST, PORT

env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                  autoescape=True)

docs.first_run_init()
cr.clean_scratch()
conn = docs.connect()
app = FastAPI()

OPEN_ID: str | None = None  # workbench state: which item is open


# ---------------------------------------------------------------- helpers
def fmt_size(n: int) -> str:
    n = n or 0
    return f"{n} B" if n < 1024 else f"{n/1024:.1f} KB" if n < 2**20 else f"{n/2**20:.1f} MB"


env.filters["size"] = fmt_size


def resolve_area(area: str, new_area: str = "") -> str:
    """The shared area picker: an existing name, or "__new__" + a typed name."""
    if area == "__new__":
        return docs.add_area(conn, new_area) or "misc"
    return area or "misc"


def tree_html(q: str = "") -> str:
    items = docs.list_items(conn)
    counts = dict(conn.execute("SELECT item_id, count(*) FROM documents GROUP BY item_id"))
    hits: dict[str, dict] = {}
    if q.strip():
        hits = dict(docs.search(conn, q))
        order = {iid: i for i, iid in enumerate(hits)}
        items = sorted((it for it in items if it["id"] in hits), key=lambda it: order[it["id"]])
    groups = []
    for a in docs.all_areas(conn):
        sub = [it for it in items if it["area"] == a]
        if sub or not q.strip():
            groups.append((a, sub))
    return env.get_template("tree.html").render(
        groups=groups, counts=counts, hits=hits, q=q, open_id=OPEN_ID,
        pending_id=cr.pending_item())


def oob_tree() -> str:
    return f'<div id="tree-inner" hx-swap-oob="true">{tree_html()}</div>'


def area_picker_oob() -> str:
    return env.get_template("areapicker.html").render(areas=docs.all_areas(conn), oob=True)


def panel_html(item_id: str, tab: str = "info", msg: str = "") -> str:
    it = docs.get_item(conn, item_id)
    if not it:
        return '<div class="inner muted">gone</div><script>window.OPEN_ITEM=null</script>'
    dlist = docs.list_for_item(conn, item_id)
    return env.get_template("panel.html").render(
        it=it, docs=dlist, tab=tab, entry=docs.entry_for(conn, it), msg=msg,
        tags=docs.tags_of(conn, item_id), areas=docs.all_areas(conn),
        text_docs=[d for d in dlist if d["editable"]],
        busy=cr.RUN["status"] != "idle")


def entry_script(item_id: str, doc_id: str = "", edit: bool = False) -> str:
    """After a mutation: load the entry (or the doc given), or the placeholder."""
    if doc_id:
        return f"<script>loadDoc('/documents/{doc_id}{'?edit=1' if edit else ''}')</script>"
    it = docs.get_item(conn, item_id)
    e = docs.entry_for(conn, it) if it else None
    return (f"<script>loadDoc('/documents/{e['id']}')</script>" if e
            else "<script>clearDoc()</script>")


def open_html(item_id: str, doc_id: str = "", msg: str = "") -> str | None:
    """Panel + reader load + tree; bumps last_opened. None when the item is gone."""
    global OPEN_ID
    if not docs.get_item(conn, item_id):
        return None
    OPEN_ID = item_id
    docs.open_item(conn, item_id)
    return panel_html(item_id, msg=msg) + entry_script(item_id, doc_id) + oob_tree()


def pending_on(item_id: str) -> bool:
    return cr.pending_item() == item_id


def diff_as_html() -> str:
    out = []
    for line in cr.diff().splitlines():
        cls = ("add" if line.startswith("+") and not line.startswith("+++")
               else "del" if line.startswith("-") and not line.startswith("---")
               else "hunk" if line.startswith("@@") else "ctx")
        out.append(f'<span class="{cls}">{html.escape(line)}</span>')
    return "\n".join(out)


def stage_html(reload_doc: bool = False) -> str:
    return env.get_template("stage.html").render(
        run=cr.RUN, diff_html=diff_as_html() if cr.RUN["status"] == "diff" else "",
        reload_doc=reload_doc)


def guard(fn):
    try:
        return JSONResponse(fn())
    except docs.DomainError as e:
        return JSONResponse({"ok": False, "error": str(e)}, e.status)


# ---------------------------------------------------------------- pages
@app.get("/healthz")
def healthz():
    """Probed by every launch target (Docker HEALTHCHECK, the desktop launcher)."""
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def workbench():
    return env.get_template("layout.html").render(
        tree=tree_html(), stage=stage_html(), areas=docs.all_areas(conn),
        item_count=conn.execute("SELECT count(*) FROM items").fetchone()[0])


@app.get("/tree", response_class=HTMLResponse)
def tree(q: str = ""):
    return tree_html(q)


@app.get("/open/{item_id}", response_class=HTMLResponse)
def open_item(item_id: str, doc: str = "", msg: str = ""):
    out = open_html(item_id, doc, msg)
    return out if out is not None else HTMLResponse("gone", 404)


@app.get("/panel/{item_id}", response_class=HTMLResponse)
def panel(item_id: str, tab: str = "info", msg: str = ""):
    return panel_html(item_id, tab, msg)


# ---------------------------------------------------------------- items
@app.post("/items", response_class=HTMLResponse)
def new_item(title: str = Form(...), area: str = Form("misc"), new_area: str = Form("")):
    try:
        iid = docs.create_item(conn, title, resolve_area(area, new_area))
    except docs.DomainError as e:
        return HTMLResponse(f'<div class="inner warn">⚠ {html.escape(str(e))}</div>')
    return (open_html(iid) or "") + area_picker_oob()


@app.post("/items/{item_id}/delete", response_class=HTMLResponse)
def delete_item(item_id: str):
    global OPEN_ID
    it = docs.get_item(conn, item_id)
    if not it:
        return HTMLResponse("gone", 404)
    if pending_on(item_id):
        return HTMLResponse('<div class="inner warn">⚠ resolve the pending Claude edit first</div>')
    n = docs.delete_item(conn, item_id)
    OPEN_ID = None
    return (f'<div class="inner muted">🗑 deleted “{html.escape(it["title"])}” and '
            f'{n} document(s)</div><script>clearDoc(); window.OPEN_ITEM=null</script>'
            + oob_tree() + area_picker_oob())


@app.post("/items/{item_id}/tags", response_class=HTMLResponse)
def save_tags(item_id: str, tags: str = Form("")):
    docs.set_tags(conn, item_id, [t.strip() for t in tags.split(",") if t.strip()])
    return panel_html(item_id) + oob_tree()


@app.post("/items/{item_id}/area", response_class=HTMLResponse)
def move_area(item_id: str, area: str = Form(...), new_area: str = Form("")):
    docs.set_area(conn, item_id, resolve_area(area, new_area))
    return panel_html(item_id) + oob_tree() + area_picker_oob()


@app.post("/items/{item_id}/pin/{doc_id}", response_class=HTMLResponse)
def pin_entry(item_id: str, doc_id: str):
    docs.set_entry(conn, item_id, doc_id)
    return panel_html(item_id) + entry_script(item_id)


@app.post("/items/{item_id}/notes", response_class=HTMLResponse)
def new_note(item_id: str, name: str = Form("")):
    if pending_on(item_id):
        return panel_html(item_id, msg="⚠ resolve the pending Claude edit first")
    d = docs.add_note(conn, item_id, name)
    return panel_html(item_id) + entry_script(item_id, d["id"], edit=True) + oob_tree()


@app.post("/areas", response_class=HTMLResponse)
def new_area(name: str = Form(...)):
    docs.add_area(conn, name)
    return tree_html() + area_picker_oob()


# ---------------------------------------------------------------- documents (panel)
@app.post("/documents/{doc_id}/rename", response_class=HTMLResponse)
def rename(doc_id: str, name: str = Form("")):
    d = docs.get(conn, doc_id)
    if pending_on(d["item_id"]):
        return panel_html(d["item_id"], msg="⚠ resolve the pending Claude edit first")
    try:
        docs.update(conn, doc_id, {"name": name})
    except docs.DomainError as e:
        return panel_html(d["item_id"], msg=f"⚠ {e}")
    return panel_html(d["item_id"]) + entry_script(d["item_id"], doc_id) + oob_tree()


@app.post("/documents/{doc_id}/delete", response_class=HTMLResponse)
def delete_doc(doc_id: str):
    d = docs.get(conn, doc_id)
    if pending_on(d["item_id"]):
        return panel_html(d["item_id"], msg="⚠ resolve the pending Claude edit first")
    docs.delete(conn, doc_id)
    return panel_html(d["item_id"]) + entry_script(d["item_id"]) + oob_tree()


@app.get("/documents/{doc_id}", response_class=HTMLResponse)
def document_page(doc_id: str, edit: int = 0, history: int = 0):
    try:
        ctx = docs.page_context(docs.get(conn, doc_id))
    except docs.DomainError as e:
        return HTMLResponse(f"<h3>{html.escape(str(e))}</h3>", e.status)
    return env.get_template("docpage.html").render(
        **ctx, edit=bool(edit and ctx["editable"]),
        history=bool(history and ctx["editable"]))


# ---------------------------------------------------------------- JSON / bytes API
def _upload_batch(item_id: str, files: list[UploadFile]) -> dict:
    out, errors = [], []
    for f in files:  # per-file try/except — one bad file never fails the batch
        try:
            out.append(docs.add_upload(conn, item_id, f.filename, f.content_type, f.file.read()))
        except docs.DomainError as e:
            errors.append(f"{f.filename}: {e}")
    return {"ok": not errors, "documents": out, "errors": errors}


@app.post("/api/items/{item_id}/documents")
def upload(item_id: str, files: list[UploadFile] = File(...)):
    if not docs.get_item(conn, item_id):
        return JSONResponse({"ok": False, "error": "item not found"}, 404)
    if pending_on(item_id):
        return JSONResponse({"ok": False, "error": "resolve the pending Claude edit first"}, 409)
    return JSONResponse(_upload_batch(item_id, files))


@app.post("/api/items/from-files")
def item_from_files(files: list[UploadFile] = File(...), area: str = Form("misc"),
                    new_area: str = Form("")):
    """Files dropped on the Workbench with no item open: a new item titled
    after the first file, holding the batch."""
    title = Path(files[0].filename or "Untitled").stem if files else "Untitled"
    iid = docs.create_item(conn, title or "Untitled", resolve_area(area, new_area))
    return JSONResponse({**_upload_batch(iid, files), "item_id": iid})


@app.post("/api/documents/render")
async def render_preview(request: Request):
    body = (await request.json()).get("body", "")
    return {"html": docs.render_markdown(body)}


@app.post("/api/documents/{doc_id}")
async def update_doc(doc_id: str, request: Request):
    updates = (await request.json()).get("updates", {})
    d = docs.get(conn, doc_id)
    if "body" in updates and pending_on(d["item_id"]):
        return JSONResponse({"ok": False, "error": "resolve the pending Claude edit first"}, 409)
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


@app.get("/api/documents/{doc_id}/versions")
def list_versions(doc_id: str):
    return guard(lambda: {"ok": True, "versions": docs.versions(conn, doc_id)})


@app.get("/api/documents/{doc_id}/versions/{version_id}")
def get_version(doc_id: str, version_id: str):
    def one():
        v = docs.get_version(conn, doc_id, version_id)
        return {"ok": True, "version": v,
                "html": docs.render_markdown(v["body"]) if v["kind"] == "md"
                else docs.render_text(v["body"]) if v["kind"] == "txt" else ""}
    return guard(one)


@app.post("/api/documents/{doc_id}/versions/{version_id}/restore")
def restore_version(doc_id: str, version_id: str):
    d = docs.get(conn, doc_id)
    if pending_on(d["item_id"]):
        return JSONResponse({"ok": False, "error": "resolve the pending Claude edit first"}, 409)
    return guard(lambda: (docs.restore(conn, doc_id, version_id), {"ok": True})[1])


# ---------------------------------------------------------------- claude
@app.post("/claude/run", response_class=HTMLResponse)
def claude_run(item_id: str = Form(...), feature: str = Form(...),
               doc_id: str = Form(...), term: str = Form(""),
               body: str = Form(""), cap: str = Form(""), prompt: str = Form("")):
    it = docs.get_item(conn, item_id)
    try:
        d = docs.get(conn, doc_id)
    except docs.DomainError:
        d = None
    if not it or not d or d["item_id"] != item_id:
        return HTMLResponse("gone", 404)
    err = cr.start(conn, it, d, feature, {"term": term, "body": body, "cap": cap, "prompt": prompt})
    if err:
        return HTMLResponse(f'<div id="stage"><div class="runbar err">🚫 {html.escape(err)}'
                            "</div></div>")
    return stage_html() + oob_tree()


@app.get("/claude/stage", response_class=HTMLResponse)
def claude_stage():
    return stage_html()


@app.post("/claude/accept", response_class=HTMLResponse)
def claude_accept():
    item_id = cr.RUN.get("item_id")
    err = cr.accept(conn)
    out = stage_html(reload_doc=not err) + oob_tree()
    if not err and item_id:
        out += f'<div id="side-panel" hx-swap-oob="true">{panel_html(item_id)}</div>'
    return out


@app.post("/claude/revert", response_class=HTMLResponse)
def claude_revert():
    cr.revert()
    return stage_html(reload_doc=True) + oob_tree()


@app.post("/claude/dismiss", response_class=HTMLResponse)
def claude_dismiss():
    cr.dismiss()
    return stage_html() + oob_tree()


# ---------------------------------------------------------------- main
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "export":
        import export
        root = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else EXPORT_DIR
        r = export.run(conn, root)
        print(f"exported {r['items']} items / {r['documents']} documents → {r['root']}"
              f" (pruned {r['pruned']} stale file(s); library.db copied)")
        sys.exit(0)
    print(f"library → http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)

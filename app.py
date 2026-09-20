"""library — Workbench over ~/learning-library with Claude-in-the-loop editing.

Run: ./run.sh → http://127.0.0.1:8900 · Rebuild the DB: ./run.sh rebuild
Spec: plan.md. Serve by ID never by path; containment-checked item files;
HTML byte-for-byte untouched; git is the undo store.
"""
import html
import mimetypes
import sys
import urllib.parse
from pathlib import Path

import markdown as md_lib
import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, Response
from jinja2 import Environment, FileSystemLoader

import claude_runner as cr
import db as dbm
import gitops
import importer
import libfs
from config import AREAS, HOST, ITEMS, PORT

env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                  autoescape=True)

libfs.first_run_init()
conn = dbm.connect()
app = FastAPI()

OPEN_ID: str | None = None  # workbench state: which item is open


# ---------------------------------------------------------------- helpers
def areas() -> list[str]:
    return dbm.all_areas(conn, AREAS)


def resolve_area(area: str, new_area: str = "") -> str:
    """The shared area picker: an existing name, or "__new__" + a typed name."""
    if area == "__new__":
        return dbm.add_area(conn, new_area) or "misc"
    return area or "misc"


def items_by_area(rows, show_empty: bool = False):
    groups = []
    for a in areas():
        sub = [r for r in rows if r["area"] == a]
        if sub or show_empty:
            # static ordering — items don't jump to the top when opened
            # (last_opened is still recorded in the DB, just not used here)
            groups.append((a, sorted(sub, key=lambda r: r["title"].lower())))
    return groups


def tree_html(q: str = "") -> str:
    if q.strip():
        hits = dbm.fts_search(conn, q.strip())
        rows = []
        for h in hits:
            it = conn.execute("SELECT * FROM items WHERE id=?",
                              (h["item_id"],)).fetchone()
            if it:
                rows.append({**dict(it), "snip": h["snip"]})
    else:
        rows = [dict(r) for r in conn.execute("SELECT * FROM items")]
    return env.get_template("tree.html").render(
        groups=items_by_area(rows, show_empty=not q.strip()), q=q, open_id=OPEN_ID,
        pending_id=cr.RUN.get("item_id") if cr.RUN["status"] != "idle" else None)


def view_url(it, r) -> str:
    rel = urllib.parse.quote(r["relpath"])
    if r["relpath"].endswith(".md"):
        return f"/render/{it['id']}/{rel}"
    return f"/files/{it['id']}/{rel}"


def panel_html(item_id: str, tab: str = "info") -> str:
    it = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not it:
        return "<div class=inner>gone</div>"
    rends = conn.execute(
        "SELECT * FROM renditions WHERE item_id=? ORDER BY role='entry' DESC,"
        " relpath", (item_id,)).fetchall()
    picker = "".join(
        f'<option value="{html.escape(r["relpath"])}">{html.escape(r["relpath"])}'
        "</option>" for r in rends)
    target_picker = (f'<select name="relpath">{picker}</select>'
                     if len(rends) > 1 else
                     f'<input type="hidden" name="relpath" '
                     f'value="{html.escape(rends[0]["relpath"])}">' if rends else "")
    return env.get_template("panel.html").render(
        it=it, tab=tab, rends=rends, meta=libfs.read_meta(ITEMS / it["dir"]),
        tags=dbm.tags_of(conn, item_id), view_url=view_url, areas=areas(),
        busy=cr.RUN["status"] != "idle", target_picker=target_picker)


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
        run=cr.RUN, diff_html=diff_as_html() if cr.RUN["status"] == "diff"
        else "", reload_doc=reload_doc)


def oob_tree() -> str:
    return f'<div id="tree-inner" hx-swap-oob="true">{tree_html()}</div>'


# ---------------------------------------------------------------- pages
@app.get("/healthz")
def healthz():
    """Probed by every launch target (Docker HEALTHCHECK, the desktop launcher)."""
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def workbench():
    libfs.sweep(conn)  # opportunistic — out-of-band edits never leave FTS stale
    return env.get_template("layout.html").render(
        tree=tree_html(), stage=stage_html(), areas=areas(),
        item_count=conn.execute("SELECT count(*) FROM items").fetchone()[0])


@app.get("/tree", response_class=HTMLResponse)
def tree(q: str = ""):
    return tree_html(q)


def open_html(item_id: str) -> str | None:
    """Panel for the item + a script loading its entry rendition + the tree;
    bumps last_opened. None when the item is gone."""
    global OPEN_ID
    it = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not it:
        return None
    OPEN_ID = item_id
    conn.execute("UPDATE items SET last_opened=? WHERE id=?",
                 (libfs.now(), item_id))
    conn.commit()
    entry = conn.execute(
        "SELECT * FROM renditions WHERE item_id=? ORDER BY role='entry' DESC",
        (item_id,)).fetchone()
    script = f"<script>loadDoc('{view_url(it, entry)}')</script>" if entry else ""
    return panel_html(item_id) + script + oob_tree()


@app.get("/open/{item_id}", response_class=HTMLResponse)
def open_item(item_id: str):
    out = open_html(item_id)
    return out if out is not None else HTMLResponse("gone", 404)


@app.get("/panel/{item_id}", response_class=HTMLResponse)
def panel(item_id: str, tab: str = "info"):
    return panel_html(item_id, tab)


# ---------------------------------------------------------------- serving
@app.get("/files/{item_id}/{rel:path}")
def files(item_id: str, rel: str):
    """Serve by ID, containment-checked, bytes untouched (plan: Serving)."""
    it = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not it:
        return Response("unknown item", 404)
    root = (ITEMS / it["dir"]).resolve()
    target = (root / rel).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return Response("out of bounds", 403)
    ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return Response(target.read_bytes(), media_type=ctype)


@app.get("/render/{item_id}/{rel:path}", response_class=HTMLResponse)
def render_md(item_id: str, rel: str):
    raw = files(item_id, rel)
    if raw.status_code != 200:
        return raw
    text = raw.body.decode(errors="replace")
    if text.startswith("---"):  # hide frontmatter from the rendered page
        try:
            text = text[text.index("\n---", 3) + 4:]
        except ValueError:
            pass
    body = md_lib.markdown(text, extensions=["fenced_code", "tables"])
    return HTMLResponse(env.get_template("mdpage.html").render(body=body))


@app.get("/peek/{cid}")
def peek(cid: str):
    """Read a scan candidate before importing. Path comes from the server-side
    candidate cache, never from the request."""
    c = importer.CANDIDATES.get(cid)
    if not c:
        return Response("stale scan — reopen the review panel", 404)
    p = Path(c["paths"][0])
    if c["kind"] == "bundle":
        p = p / "MISSION.md"
    if p.suffix == ".md":
        body = md_lib.markdown(p.read_text(errors="replace"),
                               extensions=["fenced_code", "tables"])
        return HTMLResponse(env.get_template("mdpage.html").render(body=body))
    return Response(p.read_bytes(), media_type="text/html")


# ---------------------------------------------------------------- import
def center_html() -> str:
    """The import center: drop target + chooser + scanned sources. Rendered
    into the left pane (#tree-inner) in place of the tree."""
    cands = importer.scan(conn)
    return env.get_template("import.html").render(
        cands=cands, new_count=sum(1 for c in cands if c["status"] == "new"),
        item_count=conn.execute("SELECT count(*) FROM items").fetchone()[0])


def area_picker_oob() -> str:
    return env.get_template("areapicker.html").render(areas=areas(), oob=True)


@app.get("/import-center", response_class=HTMLResponse)
def import_center():
    return center_html()


@app.post("/import/{cid}", response_class=HTMLResponse)
def do_import(cid: str):
    importer.do_import(conn, cid)
    return center_html()


@app.post("/delete/{item_id}", response_class=HTMLResponse)
def delete_item(item_id: str):
    global OPEN_ID
    it = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not it:
        return HTMLResponse("gone", 404)
    if cr.RUN["status"] != "idle" and cr.RUN.get("item_id") == item_id:
        return HTMLResponse('<div class="inner warn">⚠ resolve the pending Claude edit first</div>')
    libfs.delete_item(conn, it)
    OPEN_ID = None
    return (f'<div class="inner muted">🗑 deleted “{html.escape(it["title"])}” — '
            f'git history in ~/learning-library still has it</div>'
            "<script>clearDoc()</script>" + oob_tree() + area_picker_oob())


@app.post("/delete-file/{item_id}", response_class=HTMLResponse)
def delete_file(item_id: str, relpath: str = Form(...)):
    global OPEN_ID
    it = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not it:
        return HTMLResponse("gone", 404)
    if cr.RUN["status"] != "idle" and cr.RUN.get("item_id") == item_id:
        return HTMLResponse('<div class="inner warn">⚠ resolve the pending Claude edit first</div>')
    if libfs.delete_file(conn, it, relpath):
        OPEN_ID = None
        return (f'<div class="inner muted">🗑 “{html.escape(it["title"])}” had no files left and was removed</div>'
                "<script>clearDoc()</script>" + oob_tree())
    return (open_html(item_id) or "")


@app.post("/areas", response_class=HTMLResponse)
def new_area(name: str = Form(...)):
    """Name a new (empty) area; it shows in the tree and every area picker."""
    dbm.add_area(conn, name)
    return tree_html() + area_picker_oob()


@app.post("/area/{item_id}", response_class=HTMLResponse)
def move_area(item_id: str, area: str = Form(...), new_area: str = Form("")):
    it = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not it:
        return HTMLResponse("gone", 404)
    libfs.set_area(conn, it, resolve_area(area, new_area))
    return panel_html(item_id) + oob_tree() + area_picker_oob()


@app.post("/upload", response_class=HTMLResponse)
def upload(files: list[UploadFile] = File(...), area: str = Form("misc"),
           new_area: str = Form("")):
    """Files dropped on the Workbench or chosen with ⇪ Import files…
    Opens the last item created; the status line reports the batch."""
    area = resolve_area(area, new_area)
    ids, errors = libfs.create_from_uploads(
        conn, [(f.filename or "", f.file.read()) for f in files], area)
    msg = f"✓ Added {len(ids)} item(s)" if ids else "∅ nothing added"
    if errors:
        msg += " · ⚠ " + "; ".join(html.escape(e) for e in errors)
    status = (f'<div id="upload-status" class="muted" hx-swap-oob="true">'
              f"{msg}</div>")
    if not ids:
        return status  # target untouched; the oob status still swaps
    return (open_html(ids[-1]) or "") + status + area_picker_oob()


@app.post("/import-all", response_class=HTMLResponse)
def import_all():
    for c in list(importer.CANDIDATES.values()):
        if c["status"] == "new":
            importer.do_import(conn, c["cid"])
    return center_html()


# ---------------------------------------------------------------- editing
@app.get("/editform/{item_id}", response_class=HTMLResponse)
def editform(item_id: str, relpath: str):
    it = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    raw = files(item_id, relpath)
    if not it or raw.status_code != 200:
        return HTMLResponse("gone", 404)
    return env.get_template("editform.html").render(
        it=it, relpath=relpath, text=raw.body.decode(errors="replace"))


@app.post("/edit/{item_id}", response_class=HTMLResponse)
def save_edit(item_id: str, relpath: str = Form(...), text: str = Form("")):
    it = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    root = (ITEMS / it["dir"]).resolve()
    target = (root / relpath).resolve()
    if not target.is_relative_to(root):
        return HTMLResponse("out of bounds", 403)
    target.write_text(text)
    libfs.refresh_item(conn, it)  # updated_at + FTS row
    gitops.commit_all(f"edit: {it['dir']}/{relpath}")
    rel = urllib.parse.quote(relpath)
    return (panel_html(item_id) + oob_tree()
            + f"<script>loadDoc('/render/{item_id}/{rel}?ts={libfs.now()}')</script>")


@app.post("/new", response_class=HTMLResponse)
def new_note(title: str = Form(...), area: str = Form("misc"), new_area: str = Form("")):
    global OPEN_ID
    iid = libfs.create_note(conn, title, resolve_area(area, new_area))
    OPEN_ID = iid
    return (panel_html(iid) + oob_tree() + area_picker_oob()
            + f"<script>loadDoc('/render/{iid}/note.md')</script>")


@app.post("/tags/{item_id}", response_class=HTMLResponse)
def save_tags(item_id: str, tags: str = Form("")):
    it = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    names = [t.strip() for t in tags.split(",") if t.strip()]
    meta = libfs.read_meta(ITEMS / it["dir"])
    meta["tags"] = names
    libfs.write_meta(ITEMS / it["dir"], meta)
    dbm.set_tags(conn, item_id, names)
    gitops.commit_all(f"edit: tags of {it['dir']}")
    return panel_html(item_id)


# ---------------------------------------------------------------- claude
@app.post("/claude/run", response_class=HTMLResponse)
def claude_run(item_id: str = Form(...), feature: str = Form(...),
               relpath: str = Form(...), term: str = Form(""),
               body: str = Form(""), cap: str = Form(""),
               prompt: str = Form("")):
    it = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not it:
        return HTMLResponse("gone", 404)
    err = cr.start(dict(it), relpath, feature,
                   {"term": term, "body": body, "cap": cap, "prompt": prompt})
    if err:
        return HTMLResponse(
            f'<div id="stage"><div class="runbar err">🚫 {html.escape(err)}'
            "</div></div>")
    return stage_html() + oob_tree()


@app.get("/claude/stage", response_class=HTMLResponse)
def claude_stage():
    return stage_html()


@app.post("/claude/accept", response_class=HTMLResponse)
def claude_accept():
    cr.accept(conn)
    return stage_html(reload_doc=True) + oob_tree()


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
    if len(sys.argv) > 1 and sys.argv[1] == "rebuild":
        conn.close()
        print(f"rebuilt library.db: {libfs.rebuild()} items")
        sys.exit(0)
    print(f"library → http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)

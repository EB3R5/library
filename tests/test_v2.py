"""plan.md smoke list, minus the parts that need a browser or the claude CLI."""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

TMP = Path(tempfile.mkdtemp(prefix="library-test-"))
os.environ["LIBRARY_HOME"] = str(TMP)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as appmod  # noqa: E402  (imports config with LIBRARY_HOME set)
import claude_runner as cr  # noqa: E402
import documents as docs  # noqa: E402
import export  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(appmod.app)
conn = appmod.conn


@pytest.fixture
def item():
    return docs.create_item(conn, "Colour theory", "painting")


def upload(iid, *files):
    return client.post(f"/api/items/{iid}/documents",
                       files=[("files", (n, b, ct)) for n, b, ct in files]).json()


# ---------------------------------------------------------------- uploads + caps
def test_mixed_batch_with_empty_file(item):
    j = upload(item, ("notes.md", b"# Hi\n\nbody", "text/markdown"),
               ("empty.txt", b"", "text/plain"),
               ("data.bin", bytes(range(256)), "application/octet-stream"))
    assert not j["ok"] and len(j["documents"]) == 2
    assert j["errors"] == ["empty.txt: empty file"]
    kinds = {d["name"]: d["kind"] for d in j["documents"]}
    assert kinds == {"notes.md": "md", "data.bin": "file"}


def test_name_auto_suffix_and_rename_clash(item):
    a = docs.add_upload(conn, item, "report.md", None, b"a")
    b = docs.add_upload(conn, item, "report.md", None, b"b")
    assert (a["name"], b["name"]) == ("report.md", "report (2).md")
    assert docs.add_note(conn, item, "report")["name"] == "report (3).md"
    with pytest.raises(docs.DomainError) as e:
        docs.update(conn, b["id"], {"name": "report.md"})
    assert e.value.status == 400


def test_caps(item):
    with pytest.raises(docs.DomainError):
        docs.add_upload(conn, item, "big.md", None, b"x" * (docs.TEXT_CAP + 1))
    with pytest.raises(docs.DomainError):
        docs.add_upload(conn, item, "big.bin", None, b"x" * (docs.FILE_CAP + 1))
    n = docs.add_note(conn, item, "n")
    r = client.post(f"/api/documents/{n['id']}", json={"updates": {"body": "x" * (docs.TEXT_CAP + 1)}})
    assert r.status_code == 400 and not r.json()["ok"]
    assert docs.get(conn, n["id"])["body"] == ""   # the refused save changed nothing


# ---------------------------------------------------------------- versions
def test_note_save_history_restore(item):
    n = docs.add_note(conn, item, "todo")
    assert docs.versions(conn, n["id"]) == []              # the initial body is not a Version
    docs.update(conn, n["id"], {"body": "one"})
    docs.update(conn, n["id"], {"body": "one"})            # identical save: no Version
    v = docs.versions(conn, n["id"])
    assert len(v) == 1 and v[0]["cause"] == "save" and v[0]["kind"] == "md"
    docs.update(conn, n["id"], {"name": "todo2.md"})      # rename: never a Version
    assert len(docs.versions(conn, n["id"])) == 1
    docs.restore(conn, n["id"], v[0]["id"])
    v2 = docs.versions(conn, n["id"])
    assert len(v2) == 2 and v2[0]["cause"] == "restore"
    assert docs.get(conn, n["id"])["body"] == ""            # restored to the pre-save body
    r = client.get(f"/api/documents/{n['id']}/versions").json()
    assert [x["cause"] for x in r["versions"]] == ["restore", "save"]


def test_delete_cascades_versions_and_audits(item):
    n = docs.add_note(conn, item, "gone")
    docs.update(conn, n["id"], {"body": "v1"})
    docs.set_entry(conn, item, n["id"])
    before = conn.execute("SELECT count(*) FROM deletions").fetchone()[0]
    docs.delete(conn, n["id"])
    assert conn.execute("SELECT count(*) FROM document_versions WHERE doc_id=?", (n["id"],)).fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM deletions").fetchone()[0] == before + 1
    assert docs.get_item(conn, item)["entry_doc_id"] is None
    assert "v1" not in conn.execute("SELECT doc FROM deletions ORDER BY rowid DESC").fetchone()[0]


def test_delete_item_cascade(item):
    docs.add_upload(conn, item, "x.bin", None, b"\x00\x01")
    n = docs.add_note(conn, item, "n")
    docs.update(conn, n["id"], {"body": "b"})
    docs.set_tags(conn, item, ["t1"])
    assert docs.delete_item(conn, item) == 2
    for t, col in (("documents", "item_id"), ("item_tags", "item_id"), ("search", "item_id")):
        assert conn.execute(f"SELECT count(*) FROM {t} WHERE {col}=?", (item,)).fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM blobs").fetchone()[0] == \
        conn.execute("SELECT count(*) FROM documents WHERE file_id IS NOT NULL").fetchone()[0]


# ---------------------------------------------------------------- rename reclassifies + sandbox
def test_rename_flips_kind_and_raw_is_sandboxed(item):
    n = docs.add_note(conn, item, "notes")
    docs.update(conn, n["id"], {"body": "<h1>hi</h1><script>document.cookie</script>"})
    docs.update(conn, n["id"], {"name": "notes.html"})
    d = docs.get(conn, n["id"])
    assert (d["kind"], d["content_type"]) == ("html", "text/html")
    page = client.get(f"/documents/{n['id']}").text
    assert 'sandbox="allow-scripts allow-forms allow-popups"' in page and "<script>document.cookie" not in page
    r = client.get(f"/api/documents/{n['id']}/raw")
    assert r.headers["content-security-policy"].startswith("sandbox")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-disposition"].startswith("inline")
    assert client.get(f"/api/documents/{n['id']}/raw?download=1").headers["content-disposition"].startswith("attachment")
    f = docs.add_upload(conn, item, "pic.png", "image/png", b"\x89PNG")
    docs.update(conn, f["id"], {"name": "pic.md"})
    assert docs.get(conn, f["id"])["kind"] == "file"      # files never change kind


def test_markdown_sanitized_and_frontmatter_hidden(item):
    n = docs.add_note(conn, item, "fm")
    body = "---\ntitle: secret-key\n---\n# Head\n\n<script>alert(1)</script>**bold**"
    docs.update(conn, n["id"], {"body": body})
    page = client.get(f"/documents/{n['id']}").text
    assert "secret-key" not in page and "<script>alert" not in page and "<strong>bold</strong>" in page
    assert docs.get(conn, n["id"])["body"] == body        # kept in the body
    assert docs.search(conn, "secret-key") == []           # hidden from the index
    assert client.post("/api/documents/render", json={"body": "**x**"}).json()["html"] == "<p><strong>x</strong></p>"
    t = docs.add_upload(conn, item, "plain.txt", None, b"a <b>not bold</b> & c")
    assert "<b>" not in client.get(f"/documents/{t['id']}").text.split('<article>')[1]


# ---------------------------------------------------------------- search
def test_search_scopes_and_prefix():
    iid = docs.create_item(conn, "Warehouse migration", "research")
    docs.set_tags(conn, iid, ["budget", "ops"])
    docs.add_upload(conn, iid, "notes.md", None, b"# Notes\n\nthe pallet racking quote")
    docs.add_upload(conn, iid, "page.html", None, b"<html><body><p>forklift certification</p><script>x</script></body></html>")
    docs.add_upload(conn, iid, "data.bin", None, b"\x00\x01\x02")

    def item_ids(q):
        return [i for i, _ in docs.search(conn, q)]
    assert iid in item_ids("pallet")                         # text in a note
    assert iid in item_ids("forklift")                       # text in an html page
    assert iid in item_ids("budget")                         # an item by tag
    assert iid in item_ids("forkl")                          # a half-typed word
    assert iid in item_ids("data.bin")                       # a file by name
    assert docs.search(conn, '"unbalanced') == docs.search(conn, "unbalanced")  # bad syntax never 500s
    assert client.get("/tree?q=%22%22%22").status_code == 200
    g = dict(docs.search(conn, "warehouse"))[iid]
    assert g["item"] and g["item"]["scope"] == "item"
    g = dict(docs.search(conn, "pallet"))[iid]
    assert g["item"] is None and g["docs"][0]["name"] == "notes.md" and "<mark>" in g["docs"][0]["snip"]
    assert docs.reindex(conn) > 0 and iid in item_ids("pallet")


def test_search_snippets_are_escaped():
    iid = docs.create_item(conn, "XSS <b>bait</b>", "misc")
    docs.add_upload(conn, iid, "evil.md", None, b"hello <script>alert('x')</script> world")
    g = dict(docs.search(conn, "hello"))[iid]
    snip = g["docs"][0]["snip"]
    assert "<script>" not in snip and "&lt;script&gt;" in snip and "<mark>hello</mark>" in snip
    tree = client.get("/tree?q=bait").text
    assert "<b>bait</b>" not in tree and "<mark>bait</mark>" in tree


# ---------------------------------------------------------------- entry + panel
def test_pin_and_fallback(item):
    a = docs.add_note(conn, item, "a")
    b = docs.add_note(conn, item, "b")
    assert docs.entry_for(conn, docs.get_item(conn, item))["id"] == a["id"]
    client.post(f"/items/{item}/pin/{b['id']}")
    assert docs.entry_for(conn, docs.get_item(conn, item))["id"] == b["id"]
    html = client.get(f"/open/{item}").text
    assert f"loadDoc('/documents/{b['id']}')" in html and "📌 b.md" in html
    client.post(f"/documents/{b['id']}/delete")
    assert docs.entry_for(conn, docs.get_item(conn, item))["id"] == a["id"]
    client.post(f"/documents/{a['id']}/delete")
    assert "clearDoc()" in client.get(f"/open/{item}").text


def test_workbench_and_item_from_files():
    assert client.get("/").status_code == 200 and client.get("/healthz").json() == {"ok": True}
    r = client.post("/api/items/from-files", data={"area": "misc"},
                    files=[("files", ("Dropped Thing.md", b"x", "text/markdown"))]).json()
    assert r["ok"] and docs.get_item(conn, r["item_id"])["title"] == "Dropped Thing"
    r = client.post("/items", data={"title": "Named area", "area": "__new__", "new_area": "Garden"})
    assert r.status_code == 200 and "garden" in docs.all_areas(conn)


# ---------------------------------------------------------------- claude loop (no CLI)
def test_claude_diff_accept_and_race_guard(item, monkeypatch):
    n = docs.add_note(conn, item, "glossary")
    docs.update(conn, n["id"], {"body": "# Glossary\n\n- alpha\n"})
    docs.add_upload(conn, item, "sib.txt", None, b"sibling")
    docs.add_upload(conn, item, "img.png", "image/png", b"\x89PNG")
    doc = docs.get(conn, n["id"])
    it = docs.get_item(conn, item)

    def fake_claude(cmd, cwd, **kw):        # edits the target, touches a sibling, adds a file
        assert "img.png" in cmd[2] and "context only" in cmd[2]
        (cwd / "glossary.md").write_text("# Glossary\n\n- alpha\n- beta\n")
        (cwd / "sib.txt").write_text("changed")
        (cwd / "new.md").write_text("junk")
        class R: returncode, stderr, stdout = 0, "", ""
        return R()
    monkeypatch.setattr(cr.subprocess, "run", fake_claude)
    monkeypatch.setattr(cr.threading, "Thread", _SyncThread)

    assert cr.start(conn, it, doc, "integrate", {"term": "beta", "body": "b"}) is None
    assert cr.RUN["status"] == "diff" and sorted(cr.RUN["ignored"]) == ["new.md", "sib.txt"]
    assert "+- beta" in cr.diff()
    assert cr.start(conn, it, doc, "integrate", {"term": "x", "body": "y"}).startswith("resolve")
    # manual save while the diff is pending is refused by the app
    r = client.post(f"/api/documents/{n['id']}", json={"updates": {"body": "raced"}})
    assert r.status_code == 409
    # simulate a change that slipped past → Accept refuses, only Revert
    docs.update(conn, n["id"], {"body": "raced"})
    assert cr.accept(conn).startswith("document changed") and cr.RUN["stale"]
    assert "only Revert" in client.get("/claude/stage").text
    cr.revert()
    assert cr.RUN["status"] == "idle" and not any(Path(appmod.docs.LIBRARY, "scratch").iterdir())

    # clean run → Accept files a Version with cause `claude: …`
    docs.update(conn, n["id"], {"body": "# Glossary\n\n- alpha\n"})
    assert cr.start(conn, it, docs.get(conn, n["id"]), "integrate", {"term": "beta", "body": "b"}) is None
    assert cr.accept(conn) is None
    assert docs.get(conn, n["id"])["body"].endswith("- beta\n")
    assert docs.versions(conn, n["id"])[0]["cause"] == "claude: integrate “beta”"
    assert docs.get(conn, docs.list_for_item(conn, item)[1]["id"])["body"] == "sibling"  # ignored stays


class _SyncThread:
    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


# ---------------------------------------------------------------- export
def test_export_twice_mirrors_and_prunes():
    a = docs.create_item(conn, "Same Name", "research")
    b = docs.create_item(conn, "Same Name", "research")
    docs.add_upload(conn, a, "a.md", None, b"# a")
    docs.add_upload(conn, b, "b.bin", None, b"\x01")
    docs.set_tags(conn, a, ["x"])
    root = TMP / "export"
    r1 = export.run(conn, root)
    dirs = sorted(p.name for p in (root / "research").iterdir())
    assert any(d.startswith("same-name-") for d in dirs) and len([d for d in dirs if d.startswith("same-name")]) == 2
    stale = root / "research" / "stale" / "old.md"
    stale.parent.mkdir(); stale.write_text("x")
    docs.delete_item(conn, b)
    r2 = export.run(conn, root)
    assert r2["pruned"] >= 2 and not stale.exists() and not (root / "research" / "stale").exists()
    meta = json.loads(next((root / "research").glob("same-name*/item.json")).read_text())
    assert meta["tags"] == ["x"] and meta["entry_document"] == "a.md"
    import sqlite3
    c = sqlite3.connect(root / "library.db")
    assert c.execute("SELECT count(*) FROM items").fetchone()[0] == conn.execute("SELECT count(*) FROM items").fetchone()[0]
    c.close()
    assert r1["items"] == r2["items"] + 1


# ---------------------------------------------------------------- v1 db is retired, not migrated
def test_v1_db_moved_aside(tmp_path, monkeypatch):
    import sqlite3
    db = tmp_path / "library.db"
    sqlite3.connect(db).executescript("CREATE TABLE items(id TEXT, dir TEXT);").connection.close()
    monkeypatch.setattr(docs, "DB_PATH", db)
    monkeypatch.setattr(docs, "LIBRARY", tmp_path)
    docs.first_run_init()
    assert (tmp_path / "library.v1.db").exists()
    cols = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(items)")}
    assert "entry_doc_id" in cols and "dir" not in cols

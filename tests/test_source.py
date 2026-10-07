"""Source provenance (ADR 0004): the guarded column migration, the store round trip, the
Info-tab link and the export metadata."""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("LIBRARY_HOME", tempfile.mkdtemp(prefix="library-test-"))
os.environ.setdefault("SESSION_SECRET", "test-only-secret")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as appmod  # noqa: E402
import documents as docs  # noqa: E402
import export  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

appmod.app.state.auth_disabled = True
client = TestClient(appmod.app)
conn = appmod.conn

OLD_SCHEMA = """
CREATE TABLE items(id TEXT PRIMARY KEY, title TEXT NOT NULL, area TEXT NOT NULL,
  created_at TEXT, updated_at TEXT, last_opened TEXT, entry_doc_id TEXT);
CREATE TABLE documents(id TEXT PRIMARY KEY, item_id TEXT NOT NULL REFERENCES items(id),
  name TEXT NOT NULL, kind TEXT NOT NULL, content_type TEXT, size INTEGER, body TEXT,
  file_id TEXT, created_at TEXT, edited_at TEXT, UNIQUE(item_id, name));
"""


def test_connect_adds_source_to_an_older_db(tmp_path):
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.executescript(OLD_SCHEMA)
    c.execute("INSERT INTO items(id,title,area) VALUES('i1','Old','misc')")
    c.commit(); c.close()
    c2 = docs.connect(path)
    cols = {r[1] for r in c2.execute("PRAGMA table_info(items)")}
    dcols = {r[1] for r in c2.execute("PRAGMA table_info(documents)")}
    assert "source" in cols and "source" in dcols
    assert c2.execute("SELECT source FROM items WHERE id='i1'").fetchone()[0] is None
    assert docs._migrate(c2) == []                     # second time: nothing to do
    c2.close()
    assert docs._migrate(docs.connect(path)) == []     # reconnect is fine too


def test_item_and_document_carry_source():
    iid = docs.create_item(conn, "Dancing: understand the landscape", "research",
                           source="tasks:man_abc")
    assert docs.get_item(conn, iid)["source"] == "tasks:man_abc"
    d = docs.add_upload(conn, iid, "styles.md", None, b"# Styles", source="tasks:doc_1")
    assert d["source"] == "tasks:doc_1"
    assert docs.list_for_item(conn, iid)[0]["source"] == "tasks:doc_1"
    n = docs.add_note(conn, iid, "Brief")
    assert n["source"] is None
    plain = docs.create_item(conn, "Plain", "misc", source="  ")
    assert docs.get_item(conn, plain)["source"] is None
    assert [it["id"] for it in docs.list_items(conn, source="tasks:man_abc")] == [iid]
    assert docs.list_items(conn, source="tasks:nope") == []


def test_info_tab_links_a_tasks_source():
    iid = docs.create_item(conn, "Linked", "research", source="tasks:man_xyz")
    html = client.get(f"/panel/{iid}").text
    assert 'href="http://127.0.0.1:8011/tasks/man_xyz"' in html and "tasks:man_xyz" in html
    other = docs.create_item(conn, "Other scheme", "research", source="web:https://x")
    html = client.get(f"/panel/{other}").text
    assert "web:https://x" in html and "href=\"http://127.0.0.1:8011" not in html
    assert appmod.source_href("tasks:") == "" and appmod.source_href(None) == ""


def test_export_writes_source(tmp_path):
    iid = docs.create_item(conn, "Exported", "research", source="tasks:man_exp")
    docs.add_upload(conn, iid, "a.md", None, b"# a")
    export.run(conn, tmp_path)
    import json
    meta = json.loads(next((tmp_path / "research").glob("exported*/item.json")).read_text())
    assert meta["source"] == "tasks:man_exp"

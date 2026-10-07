"""Agent API (ADR 0005): the bearer gate, and every route as a round trip over the store."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("LIBRARY_HOME", tempfile.mkdtemp(prefix="library-test-"))
os.environ.setdefault("SESSION_SECRET", "test-only-secret")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as appmod  # noqa: E402
import auth  # noqa: E402
import claude_runner as cr  # noqa: E402
import documents as docs  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

conn = appmod.conn
H = {"Authorization": "Bearer tok"}


@pytest.fixture
def api(monkeypatch):
    """The real gate with the token set: pages still need a session, /api/agent the bearer."""
    monkeypatch.setattr(auth, "API_TOKEN", "tok")
    was = appmod.app.state.auth_disabled
    appmod.app.state.auth_disabled = False
    with TestClient(appmod.app, follow_redirects=False) as c:
        yield c
    appmod.app.state.auth_disabled = was


def test_gate_needs_the_bearer(api, monkeypatch):
    assert api.get("/api/agent/areas").status_code == 401
    assert api.get("/api/agent/areas", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert api.get("/api/agent/areas", headers=H).status_code == 200
    assert api.get("/", headers=H).status_code == 200          # the bearer also passes the page gate
    monkeypatch.setattr(auth, "API_TOKEN", "")
    r = api.get("/api/agent/areas", headers=H)
    assert r.status_code == 401 and r.json() == {"ok": False, "error": "Not authenticated"}
    appmod.app.state.auth_disabled = True                         # past the page gate, the router still refuses
    r = api.get("/api/agent/areas", headers=H)
    assert r.status_code == 401 and "disabled" in r.json()["error"]


def test_session_alone_cannot_use_the_agent_api(api):
    import pyotp
    secret = pyotp.random_base32()
    docs.upsert_user(conn, "me", auth.hash_password("pw"), secret)
    r = api.post("/login", data={"username": "me", "password": "pw", "totp": pyotp.TOTP(secret).now()})
    assert r.status_code == 303 and api.get("/").status_code == 200
    assert api.get("/api/agent/areas").status_code == 401


def test_create_add_read_round_trip(api):
    r = api.post("/api/agent/items", headers=H, json={
        "title": "  Dancing:  the landscape ", "area": "Research", "tags": ["Health", "Home"],
        "source": "tasks:man_map"}).json()
    assert r["ok"] and r["item"]["title"] == "Dancing: the landscape" and r["item"]["area"] == "research"
    iid = r["id"]
    assert r["item"]["tags"] == ["Health", "Home"] and r["item"]["source"] == "tasks:man_map"
    assert r["item"]["entry"] is None and r["item"]["documents"] == []

    d = api.post(f"/api/agent/items/{iid}/documents", headers=H, json={
        "name": "styles.md", "body": "---\nsource: tasks:doc_1\n---\n# Styles\n\nballroom", "source": "tasks:doc_1"}).json()
    assert d["ok"] and d["document"]["kind"] == "md" and d["document"]["source"] == "tasks:doc_1"
    dup = api.post(f"/api/agent/items/{iid}/documents", headers=H, json={"name": "styles.md", "body": "x"}).json()
    assert dup["document"]["name"] == "styles (2).md"
    brief = api.post(f"/api/agent/items/{iid}/documents", headers=H, json={"name": "Brief.md", "body": "# Brief"}).json()

    got = api.get(f"/api/agent/items/{iid}", headers=H).json()["item"]
    assert [x["name"] for x in got["documents"]] == ["styles.md", "styles (2).md", "Brief.md"]
    assert got["entry"]["name"] == "styles.md"                      # first created until pinned

    p = api.post(f"/api/agent/items/{iid}/pin", headers=H, json={"doc_id": brief["document"]["id"]}).json()
    assert p["ok"] and p["entry"]["name"] == "Brief.md"
    assert api.get(f"/api/agent/items/{iid}", headers=H).json()["item"]["entry"]["name"] == "Brief.md"

    t = api.post(f"/api/agent/items/{iid}/tags", headers=H, json={"tags": ["Health", " ", "dance"]}).json()
    assert t["tags"] == ["Health", "dance"]

    body = api.get(f"/api/agent/documents/{d['document']['id']}", headers=H).json()["document"]
    assert body["body"].startswith("---\nsource: tasks:doc_1") and body["name"] == "styles.md"

    lst = api.get("/api/agent/items", headers=H, params={"source": "tasks:man_map"}).json()
    assert lst["count"] == 1 and lst["items"][0]["id"] == iid and lst["items"][0]["documents"] == 3
    assert api.get("/api/agent/items", headers=H, params={"tag": "dance"}).json()["count"] == 1
    assert api.get("/api/agent/items", headers=H, params={"tag": "nope"}).json()["count"] == 0
    assert api.get("/api/agent/items", headers=H, params={"area": "research", "q": "ballroom"}).json()["items"][0]["id"] == iid
    assert api.get("/api/agent/items", headers=H, params={"q": "zzzqqq"}).json()["count"] == 0

    s = api.get("/api/agent/search", headers=H, params={"q": "ballroom"}).json()
    assert s["ok"] and s["groups"][0]["item_id"] == iid and s["groups"][0]["document_hits"][0]["name"] == "styles.md"
    assert "research" in api.get("/api/agent/areas", headers=H).json()["areas"]


def test_write_validation_and_errors(api, monkeypatch):
    iid = api.post("/api/agent/items", headers=H, json={"title": "V"}).json()["id"]
    assert api.get("/api/agent/items/nope", headers=H).status_code == 404
    assert api.post("/api/agent/items", headers=H, json={"title": "  "}).status_code == 400
    r = api.post("/api/agent/items", headers={**H, "content-type": "application/json"}, content=b"[1]")
    assert r.status_code == 400 and r.json()["error"] == "body must be a JSON object"
    r = api.post("/api/agent/items", headers={**H, "content-type": "application/json"}, content=b"{nope")
    assert r.status_code == 400
    assert api.post(f"/api/agent/items/{iid}/documents", headers=H, json={"name": "a.md", "body": ""}).status_code == 400
    assert api.post(f"/api/agent/items/{iid}/documents", headers=H, json={"name": "a.png", "body": "x"}).status_code == 400
    assert api.post(f"/api/agent/items/{iid}/tags", headers=H, json={"tags": "x"}).status_code == 400
    other = api.post("/api/agent/items", headers=H, json={"title": "Other"}).json()["id"]
    d = api.post(f"/api/agent/items/{other}/documents", headers=H, json={"name": "o.md", "body": "o"}).json()
    assert api.post(f"/api/agent/items/{iid}/pin", headers=H, json={"doc_id": d["document"]["id"]}).status_code == 400
    f = docs.add_upload(conn, iid, "pic.png", "image/png", b"\x89PNG")
    r = api.get(f"/api/agent/documents/{f['id']}", headers=H)
    assert r.status_code == 400 and "not a text document" in r.json()["error"]
    monkeypatch.setattr(cr, "pending_item", lambda: iid)
    assert api.post(f"/api/agent/items/{iid}/documents", headers=H, json={"name": "b.md", "body": "b"}).status_code == 409

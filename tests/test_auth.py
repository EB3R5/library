"""Auth gate + login flow (ADR 0003). test_v2 disables the gate; these tests seed the one
users row and drive the real gate on the same app, restoring the flag afterwards."""
import os
import sys
import tempfile
from pathlib import Path

import pyotp
import pytest

os.environ.setdefault("LIBRARY_HOME", tempfile.mkdtemp(prefix="library-test-"))
os.environ.setdefault("SESSION_SECRET", "test-only-secret")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as appmod  # noqa: E402
import auth  # noqa: E402
import documents as docs  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

PASSWORD = "s3cret-pw"
TOTP_SECRET = pyotp.random_base32()


@pytest.fixture
def gate():
    docs.upsert_user(appmod.conn, "me", auth.hash_password(PASSWORD), TOTP_SECRET)
    was = appmod.app.state.auth_disabled
    appmod.app.state.auth_disabled = False
    with TestClient(appmod.app, follow_redirects=False) as c:
        yield c
    appmod.app.state.auth_disabled = was


def test_unauth_page_redirects_to_login(gate):
    r = gate.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_unauth_api_returns_401_json(gate):
    r = gate.get("/api/documents/nope/raw")
    assert r.status_code == 401 and r.json() == {"ok": False, "error": "Not authenticated"}


def test_login_and_healthz_are_exempt(gate):
    assert gate.get("/login").status_code == 200
    assert gate.get("/healthz").json() == {"ok": True}


def test_bad_totp_rejected_with_generic_message(gate):
    r = gate.post("/login", data={"username": "me", "password": PASSWORD, "totp": "000000"})
    assert r.status_code == 401 and "Invalid credentials." in r.text
    assert gate.get("/").status_code == 303


def test_wrong_password_rejected(gate):
    code = pyotp.TOTP(TOTP_SECRET).now()
    r = gate.post("/login", data={"username": "me", "password": "nope", "totp": code})
    assert r.status_code == 401


def test_valid_login_then_access_then_logout(gate):
    code = pyotp.TOTP(TOTP_SECRET).now()
    r = gate.post("/login", data={"username": "me", "password": PASSWORD, "totp": code})
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert gate.get("/").status_code == 200           # session cookie passes the gate
    assert gate.get("/login").status_code == 303      # already signed in → workbench
    r = gate.post("/logout")
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert gate.get("/").status_code == 303


def test_api_token_bypasses_gate(gate, monkeypatch):
    monkeypatch.setattr(auth, "API_TOKEN", "cli-token-xyz")
    r = gate.get("/healthz", headers={"Authorization": "Bearer cli-token-xyz"})
    assert r.status_code == 200
    r = gate.get("/api/documents/nope/raw", headers={"Authorization": "Bearer cli-token-xyz"})
    assert r.status_code == 404                       # through the gate; the id is unknown
    r = gate.get("/api/documents/nope/raw", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_token_disabled_when_unset(monkeypatch):
    monkeypatch.setattr(auth, "API_TOKEN", "")
    assert not auth.has_valid_api_token("Bearer anything")
    monkeypatch.setattr(auth, "API_TOKEN", "t")
    assert auth.has_valid_api_token("bearer t") and not auth.has_valid_api_token("Basic t")


def test_upsert_user_keeps_one_row():
    docs.upsert_user(appmod.conn, "a", "h", "s")
    docs.upsert_user(appmod.conn, "b", "h2", "s2")
    assert appmod.conn.execute("SELECT count(*) FROM users").fetchone()[0] == 1
    assert docs.get_user(appmod.conn)["username"] == "b"
    with pytest.raises(docs.DomainError):
        docs.upsert_user(appmod.conn, " ", "h", "s")

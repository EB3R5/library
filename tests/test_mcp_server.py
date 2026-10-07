"""agent/mcp_server.py (ADR 0006): the client run against the ASGI app through the real gate,
the missing-token message, and the tool set."""
import asyncio
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import pytest
from httpx import ASGITransport

os.environ.setdefault("LIBRARY_HOME", tempfile.mkdtemp(prefix="library-test-"))
os.environ.setdefault("SESSION_SECRET", "test-only-secret")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as appmod  # noqa: E402
import auth  # noqa: E402

SERVER = Path(__file__).resolve().parent.parent / "agent" / "mcp_server.py"


def load():
    spec = importlib.util.spec_from_file_location("library_mcp_server", SERVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def agent(monkeypatch):
    monkeypatch.setattr(auth, "API_TOKEN", "tok")
    was = appmod.app.state.auth_disabled
    appmod.app.state.auth_disabled = False
    yield load().LibraryClient("http://t", "tok", transport=ASGITransport(app=appmod.app))
    appmod.app.state.auth_disabled = was


async def test_client_round_trip(agent):
    made = await agent.create_item("WW1: material for the jokes piece", area="Research",
                                   tags=["Pieces", "Writing"], source="tasks:man_ww1")
    assert made["ok"] and made["item"]["area"] == "research" and made["item"]["tags"] == ["Pieces", "Writing"]
    iid = made["id"]
    d = await agent.add_document(iid, "books.md", "---\nsource: tasks:doc_b\n---\n# Books\n\nSassoon", source="tasks:doc_b")
    assert d["ok"] and d["document"]["source"] == "tasks:doc_b"
    brief = await agent.add_document(iid, "Brief.md", "# Brief")
    assert (await agent.pin_entry(iid, brief["document"]["id"]))["entry"]["name"] == "Brief.md"
    got = await agent.get_item(iid)
    assert got["item"]["entry"]["name"] == "Brief.md" and [x["name"] for x in got["item"]["documents"]] == ["books.md", "Brief.md"]
    assert (await agent.set_tags(iid, ["Pieces"]))["tags"] == ["Pieces"]
    assert "Sassoon" in (await agent.read_document(d["document"]["id"]))["document"]["body"]
    assert [i["id"] for i in (await agent.list_items(source="tasks:man_ww1"))["items"]] == [iid]
    assert (await agent.list_items(tag="Pieces", area="research"))["count"] == 1
    assert (await agent.search("Sassoon"))["groups"][0]["item_id"] == iid
    assert "research" in (await agent.list_areas())["areas"]
    assert (await agent.get_item("nope"))["ok"] is False


async def test_client_reports_missing_token(agent):
    bad = load().LibraryClient("http://t", "wrong", transport=ASGITransport(app=appmod.app))
    res = await bad.list_areas()
    assert res["ok"] is False and "LIBRARY_API_TOKEN" in res["error"]


def test_config_reads_env_then_dotenv(monkeypatch):
    mod = load()
    monkeypatch.setenv("LIBRARY_URL", "http://x:1/")
    monkeypatch.setenv("LIBRARY_API_TOKEN", "t1")
    assert mod.config() == ("http://x:1", "t1")


def test_server_builds_with_all_tools(monkeypatch):
    monkeypatch.setenv("LIBRARY_URL", "http://127.0.0.1:1")
    server = load().build_server()
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"list_areas", "list_items", "get_item", "search", "read_document",
                     "create_item", "add_document", "set_tags", "pin_entry"}

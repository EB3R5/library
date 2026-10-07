"""library MCP server — the Agent API (ADR 0005) as MCP tools, over stdio (ADR 0006).

A thin client of the running library: every tool is one HTTP call with the static bearer
token, so the domain rules (one SQLite connection, unique names, caps, the pending-edit
lock) stay in the app and the container keeps sole ownership of library.db.

Config (environment, with fallbacks):
    LIBRARY_URL         where the app answers      default http://127.0.0.1:8900
    LIBRARY_API_TOKEN   its API_TOKEN              default: API_TOKEN from this repo's .env

Run:    .venv/bin/python agent/mcp_server.py          (needs the `agent` extra)
Register in Claude Code:
    claude mcp add --scope user library -- /path/to/.venv/bin/python /path/to/agent/mcp_server.py
"""

import os
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent


def config() -> tuple[str, str]:
    env = dotenv_values(ROOT / ".env")
    url = os.environ.get("LIBRARY_URL") or "http://127.0.0.1:8900"
    token = os.environ.get("LIBRARY_API_TOKEN") or env.get("API_TOKEN") or ""
    return url.rstrip("/"), token


class LibraryClient:
    """The Agent API as methods. `transport` lets tests point it at the ASGI app."""

    def __init__(self, base_url: str, token: str, transport=None):
        self._c = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=60,
                                    headers={"Authorization": f"Bearer {token}"} if token else {})

    async def _json(self, r: httpx.Response) -> dict:
        if r.status_code == 401:
            return {"ok": False, "error": "not authenticated — set LIBRARY_API_TOKEN to the app's API_TOKEN"}
        try:
            return r.json()
        except ValueError:
            return {"ok": False, "error": f"{r.status_code} {r.text[:200]}"}

    async def _get(self, path: str, **params) -> dict:
        return await self._json(await self._c.get(path, params={k: v for k, v in params.items() if v is not None}))

    async def _post(self, path: str, json=None) -> dict:
        return await self._json(await self._c.post(path, json=json))

    # --- reads ---
    async def list_areas(self) -> dict:
        return await self._get("/api/agent/areas")

    async def list_items(self, area=None, tag=None, q=None, source=None) -> dict:
        return await self._get("/api/agent/items", area=area, tag=tag, q=q, source=source)

    async def get_item(self, item_id: str) -> dict:
        return await self._get(f"/api/agent/items/{item_id}")

    async def search(self, q: str, limit: int = 60) -> dict:
        return await self._get("/api/agent/search", q=q, limit=limit)

    async def read_document(self, doc_id: str) -> dict:
        return await self._get(f"/api/agent/documents/{doc_id}")

    # --- writes ---
    async def create_item(self, title: str, area: str | None = None, tags: list | None = None,
                          source: str | None = None) -> dict:
        body = {"title": title}
        for k, v in (("area", area), ("tags", tags), ("source", source)):
            if v:
                body[k] = v
        return await self._post("/api/agent/items", json=body)

    async def add_document(self, item_id: str, name: str, body: str, source: str | None = None) -> dict:
        payload = {"name": name, "body": body}
        if source:
            payload["source"] = source
        return await self._post(f"/api/agent/items/{item_id}/documents", json=payload)

    async def set_tags(self, item_id: str, tags: list) -> dict:
        return await self._post(f"/api/agent/items/{item_id}/tags", json={"tags": list(tags)})

    async def pin_entry(self, item_id: str, doc_id: str) -> dict:
        return await self._post(f"/api/agent/items/{item_id}/pin", json={"doc_id": doc_id})


INSTRUCTIONS = """The library is a personal learning library. Vocabulary: an Item is a named
container with an Area (research, painting, teach, misc, or any name the user adds) and
free-form Tags; it holds Documents and has no content of its own. A Text Document (.md,
.html, .txt) has a body you can read and add; File Documents (images, PDFs) exist but are
out of reach here. An Item's Entry Document is the one the reader opens first: the pinned
one, else the first created. A Source (`tasks:<id>`) says where an Item or Document came
from — set it on everything you bring in from another app, and look for it with
list_items(source=...) before creating something that may already exist: a document name
that already exists in an Item gets a " (2)" suffix rather than an error. Document bodies
are kept as written; a leading YAML front matter block is hidden in the reader but kept."""


def build_server():
    from mcp.server.mcpserver import MCPServer

    url, token = config()
    client = LibraryClient(url, token)
    server = MCPServer("library", instructions=INSTRUCTIONS)

    @server.tool()
    async def list_areas() -> dict:
        """The Area names Items are grouped under."""
        return await client.list_areas()

    @server.tool()
    async def list_items(area: str | None = None, tag: str | None = None, q: str | None = None,
                         source: str | None = None) -> dict:
        """Items as rows (id, title, area, tags, source, document count). area, tag and source
        are exact filters; q keeps only full-text hits, best first."""
        return await client.list_items(area, tag, q, source)

    @server.tool()
    async def get_item(item_id: str) -> dict:
        """One Item in full: fields, tags, entry document, and its documents (ids, names,
        kinds, sources; bodies left out — use read_document)."""
        return await client.get_item(item_id)

    @server.tool()
    async def search(q: str, limit: int = 60) -> dict:
        """Full-text search over item titles, tags, document names and bodies. Hits are grouped
        by Item, Item hits first; snippets carry <mark> tags."""
        return await client.search(q, limit)

    @server.tool()
    async def read_document(doc_id: str) -> dict:
        """A Text Document (from get_item) with its body."""
        return await client.read_document(doc_id)

    @server.tool()
    async def create_item(title: str, area: str | None = None, tags: list[str] | None = None,
                          source: str | None = None) -> dict:
        """Create an Item. area defaults to misc and is created if new (lowercased). Give a
        source such as tasks:<task id> when the Item comes from somewhere."""
        return await client.create_item(title, area, tags, source)

    @server.tool()
    async def add_document(item_id: str, name: str, body: str, source: str | None = None) -> dict:
        """Add a Text Document (name ends in .md, .html or .txt) with the given body. A name
        already in the Item gets a " (2)" suffix: check get_item first when re-running."""
        return await client.add_document(item_id, name, body, source)

    @server.tool()
    async def set_tags(item_id: str, tags: list[str]) -> dict:
        """Replace an Item's whole tag set."""
        return await client.set_tags(item_id, tags)

    @server.tool()
    async def pin_entry(item_id: str, doc_id: str) -> dict:
        """Make a document the Item's Entry Document — the one the reader opens first."""
        return await client.pin_entry(item_id, doc_id)

    return server


if __name__ == "__main__":
    build_server().run("stdio")

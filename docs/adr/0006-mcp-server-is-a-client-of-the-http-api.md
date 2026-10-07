---
status: accepted
---

# The MCP server is a client of the HTTP API

Agents reach the library through an MCP server (`agent/mcp_server.py`,
registered in Claude Code as `library`). It owns no data: every tool is one
HTTP call to the running app's Agent API (ADR 0005) with the static bearer
token, through a small `LibraryClient` whose transport tests can point at the
ASGI app. Nine tools: list_areas, list_items, get_item, search, read_document,
create_item, add_document, set_tags, pin_entry. The same shape as the
tasks-webapp MCP server, on purpose: one mental model for both.

## Considered Options

- **A — Thin client over the Agent API** (chosen): the container keeps sole
  ownership of `library.db` (the packaging README's rule: never two servers
  on one database, and the connection has no WAL or busy timeout); the
  domain rules run once, in the app; "what an agent can do" stays the
  reviewable route list of ADR 0005.
- **B — The MCP server opens `library.db` itself** — rejected: a second
  writer on a SQLite file the container owns, and every rule in
  `documents.py` would have to be trusted to be re-entrant across processes.
- **C — MCP mounted inside the FastAPI app** — rejected: it would run in the
  container, which the Claude Code on this machine reaches over stdio, not
  HTTP; and a crash in the MCP layer would take the Workbench with it.

## Consequences

- The server needs the app up and `API_TOKEN` set; a 401 comes back as one
  readable error naming `LIBRARY_API_TOKEN`.
- `mcp` and `httpx` are the `agent` extra; the Docker image does not ship
  `agent/`.
- Adding a tool means adding a route first (ADR 0005), then the client
  method, then the tool; the tool-name set is asserted in a test.

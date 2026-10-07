---
status: accepted
---

# The agent API is token-gated JSON under /api/agent

Agents (the MCP server of ADR 0006, scripts) need to read and write the
library without a browser: list and search Items, read a Text Document, make
an Item with a title, Area, Tags and a Source, add a Text Document with a
body, set Tags, pin the entry document. The Workbench's routes could not do
that: they are HTMX form posts that return fragments, the one JSON create
route titles the Item after a file name, and all of them ride the session
cookie.

`/api/agent/*` is a separate router of JSON routes, each one a call into the
store, admitted only by the static `API_TOKEN` bearer header (`auth.require_token`,
constant-time compare, 401 while the token is unset). The login gate of ADR
0003 already lets a valid bearer through without a session; the router's own
dependency additionally refuses a session without the bearer, so a page in a
signed-in browser cannot be made to drive agent writes. Text Documents only.

## Considered Options

- **A — Separate token-gated JSON router** (chosen): the route list is the
  reviewable answer to "what can an agent do"; the Workbench routes stay as
  they are; the token lives beside `SESSION_SECRET` in `library/.env`.
- **B — Let agents call the HTMX routes with the token** — rejected: they
  return HTML fragments, title Items after file names, and would make the
  Workbench's contract an API contract.
- **C — Let the MCP server open `library.db` directly** — rejected: the
  container owns the file and the packaging README's rule is one server per
  database; going through HTTP keeps the domain rules in one process.

## Consequences

- `auth.require_token` is the one dependency; `/api/agent` without the header,
  with a wrong token, with only a session, or while `API_TOKEN` is unset all
  get a 401 JSON.
- `add_document` goes through `add_upload`, so a name clash is suffixed
  `(2)`; a caller that re-runs must look at the Item's documents first.
- An add on an Item with a pending Claude edit is refused with 409, as the
  upload route is.
- `agent_api.py` must be in the Dockerfile's COPY line; the image copies
  modules by name.
- The Workbench's own JSON routes (`/api/items/...`, `/api/documents/...`) keep
  the session cookie as their credential; nothing moved.

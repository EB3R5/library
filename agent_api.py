"""Agent API (ADR 0005): JSON routes under /api/agent for scripts and the MCP server.

Every route needs the static API_TOKEN as a bearer header — a browser session is not
enough, so a page cannot be tricked into driving agent writes. The routes are thin: each
one is a call into the store, so the domain rules stay in documents.py, and "what an agent
can do" is this file's route list. Text documents only; File Documents are out of scope.

`conn` is bound by app.py after it opens the store (the single SQLite connection the whole
app shares — never a second one, see packaging/README.md)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

import claude_runner as cr
import documents as docs
from auth import require_token

router = APIRouter(prefix="/api/agent", dependencies=[Depends(require_token)])
conn = None  # set by app.py


def _guard(fn):
    try:
        return JSONResponse(fn())
    except docs.DomainError as e:
        return JSONResponse({"ok": False, "error": str(e)}, e.status)


async def _body(request: Request) -> dict | JSONResponse:
    """The JSON object a write carries, or the 400 to return instead."""
    try:
        b = await request.json()
    except ValueError:
        b = None
    if not isinstance(b, dict):
        return JSONResponse({"ok": False, "error": "body must be a JSON object"}, 400)
    return b


def _item_view(it: dict) -> dict:
    """An Item with its tags, entry document and document list (bodies left out)."""
    entry = docs.entry_for(conn, it)
    return {**it, "tags": docs.tags_of(conn, it["id"]),
            "entry": {"id": entry["id"], "name": entry["name"]} if entry else None,
            "documents": docs.list_for_item(conn, it["id"])}


def _require_item(item_id: str) -> dict:
    it = docs.get_item(conn, item_id)
    if not it:
        raise docs.DomainError("item not found", 404)
    return it


def _not_pending(item_id: str) -> None:
    if cr.pending_item() == item_id:
        raise docs.DomainError("resolve the pending Claude edit on this item first", 409)


# ---------------------------------------------------------------- reads
@router.get("/areas")
def areas():
    return {"ok": True, "areas": docs.all_areas(conn)}


@router.get("/items")
def list_items(area: str | None = None, tag: str | None = None, q: str | None = None,
               source: str | None = None):
    """Items as rows with tags and document counts. `area`, `tag` and `source` are exact
    filters; `q` keeps only search hits, ranked as the Workbench ranks them."""
    def go():
        items = docs.list_items(conn, source=source)
        if area:
            items = [it for it in items if it["area"] == area]
        counts = dict(conn.execute("SELECT item_id, count(*) FROM documents GROUP BY item_id"))
        if q and q.strip():
            order = {iid: i for i, (iid, _) in enumerate(docs.search(conn, q))}
            items = sorted((it for it in items if it["id"] in order), key=lambda it: order[it["id"]])
        rows = []
        for it in items:
            tags = docs.tags_of(conn, it["id"])
            if tag and tag not in tags:
                continue
            rows.append({**it, "tags": tags, "documents": counts.get(it["id"], 0)})
        return {"ok": True, "count": len(rows), "items": rows}
    return _guard(go)


@router.get("/items/{item_id}")
def get_item(item_id: str):
    return _guard(lambda: {"ok": True, "item": _item_view(_require_item(item_id))})


@router.get("/search")
def search(q: str, limit: int = 60):
    """Full-text hits grouped by Item, Item hits first. Snippets carry <mark> tags."""
    def go():
        groups = []
        for iid, g in docs.search(conn, q, limit):
            it = docs.get_item(conn, iid)
            groups.append({"item_id": iid, "title": it["title"] if it else None,
                           "area": it["area"] if it else None,
                           "item_hit": g["item"], "document_hits": g["docs"]})
        return {"ok": True, "count": len(groups), "groups": groups}
    return _guard(go)


@router.get("/documents/{doc_id}")
def read_document(doc_id: str):
    """A Text Document with its body. File Documents are refused: only text crosses here."""
    def go():
        d = docs.get(conn, doc_id)
        if not docs.is_text_kind(d["kind"]):
            raise docs.DomainError(f"not a text document ({d['kind']}); only text documents can be read")
        return {"ok": True, "document": {**docs.serialize(d), "body": d.get("body") or ""}}
    return _guard(go)


# ---------------------------------------------------------------- writes
@router.post("/items")
async def create_item(request: Request):
    """{title, area?, tags?, source?} → {ok, id}. An unknown area is created (lowercased)."""
    b = await _body(request)
    if isinstance(b, JSONResponse):
        return b

    def go():
        area = docs.add_area(conn, b.get("area") or "misc") or "misc"
        iid = docs.create_item(conn, b.get("title"), area, source=b.get("source"))
        if b.get("tags"):
            docs.set_tags(conn, iid, [str(t) for t in b["tags"]])
        return {"ok": True, "id": iid, "item": _item_view(docs.get_item(conn, iid))}
    return _guard(go)


@router.post("/items/{item_id}/documents")
async def add_document(item_id: str, request: Request):
    """{name, body, source?} → a new Text Document (kind from the name's extension; a clash
    gets a ` (2)` suffix, so check the item's documents first when re-running)."""
    b = await _body(request)
    if isinstance(b, JSONResponse):
        return b

    def go():
        _require_item(item_id)
        _not_pending(item_id)
        body = b.get("body")
        if not isinstance(body, str) or not body:
            raise docs.DomainError("body must be a non-empty string")
        name = str(b.get("name") or "note.md")
        kind = docs.classify(name)
        if not docs.is_text_kind(kind):
            raise docs.DomainError("name must end in .md, .html or .txt")
        d = docs.add_upload(conn, item_id, name, None, body.encode("utf-8"), source=b.get("source"))
        return {"ok": True, "document": d}
    return _guard(go)


@router.post("/items/{item_id}/tags")
async def set_tags(item_id: str, request: Request):
    """{tags: [...]} replaces the whole set."""
    b = await _body(request)
    if isinstance(b, JSONResponse):
        return b

    def go():
        _require_item(item_id)
        tags = b.get("tags")
        if not isinstance(tags, list):
            raise docs.DomainError("tags must be a list")
        docs.set_tags(conn, item_id, [str(t) for t in tags])
        return {"ok": True, "tags": docs.tags_of(conn, item_id)}
    return _guard(go)


@router.post("/items/{item_id}/pin")
async def pin_entry(item_id: str, request: Request):
    """{doc_id} makes that document the Item's entry document."""
    b = await _body(request)
    if isinstance(b, JSONResponse):
        return b

    def go():
        _require_item(item_id)
        d = docs.get(conn, str(b.get("doc_id") or ""))
        if d["item_id"] != item_id:
            raise docs.DomainError("document belongs to another item")
        docs.set_entry(conn, item_id, d["id"])
        return {"ok": True, "entry": {"id": d["id"], "name": d["name"]}}
    return _guard(go)

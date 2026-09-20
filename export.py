"""./run.sh export [root] — the backup (plan.md v2, ticket #14).

<root>/<area>/<item slug>/<document name> as plain files plus item.json per
item; <root>/library.db via SQLite's online backup API is the real restore
point (restore = stop, copy that DB back, start). Overwrite in place and
prune, so a scheduled run is idempotent. Scratch dirs are not exported.
"""
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

import documents as docs


def slugify(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-") or "item"


def run(conn, root: Path) -> dict:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    items = docs.list_items(conn)
    slugs = {it["id"]: (it["area"], slugify(it["title"])) for it in items}
    clashes = {k for k, n in Counter(slugs.values()).items() if n > 1}
    wanted: set[Path] = set()
    n_docs = 0
    for it in items:
        area, slug = slugs[it["id"]]
        if (area, slug) in clashes:
            slug += "-" + it["id"][:6]     # suffix only on clash
        d = root / area / slug
        d.mkdir(parents=True, exist_ok=True)
        dlist = docs.list_for_item(conn, it["id"])
        for doc in dlist:
            data, _ct, name = docs.raw(conn, doc["id"])
            target = d / name
            if not target.exists() or target.read_bytes() != data:
                target.write_bytes(data)
            wanted.add(target.resolve())
            n_docs += 1
        entry = docs.entry_for(conn, it)
        meta = dict(id=it["id"], title=it["title"], area=it["area"],
                    tags=docs.tags_of(conn, it["id"]),
                    entry_document=entry["name"] if entry else None,
                    created=it["created_at"], updated=it["updated_at"])
        mp = d / "item.json"
        mp.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
        wanted.add(mp.resolve())
    db_copy = (root / "library.db").resolve()
    wanted.add(db_copy)
    pruned = _prune(root, wanted)
    dst = sqlite3.connect(db_copy)
    try:
        conn.backup(dst)
    finally:
        dst.close()
    return dict(items=len(items), documents=n_docs, pruned=pruned, root=str(root))


def _prune(root: Path, wanted: set[Path]) -> int:
    n = 0
    for p in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if p.is_file() and p.resolve() not in wanted:
            p.unlink()
            n += 1
        elif p.is_dir() and not any(p.iterdir()):
            p.rmdir()
    return n

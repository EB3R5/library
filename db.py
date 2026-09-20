"""SQLite index over ~/learning-library. Rebuildable-cache rule: the DB must be
regenerable from the files alone (see rebuild in libfs.py)."""
import sqlite3

from config import DB_PATH

# Plain FTS5 rather than the sketch's contentless variant: per-item
# delete+reinsert stays trivially correct, and stored text is negligible at
# this corpus size. Observable behavior (search, rebuildability) is identical.
SCHEMA = """
CREATE TABLE IF NOT EXISTS items(
  id          TEXT PRIMARY KEY,          -- md5(dir name)[:10]
  kind        TEXT,                      -- 'single' | 'pair' | 'bundle'
  title       TEXT,
  area        TEXT,
  dir         TEXT UNIQUE,               -- relative to items/
  created_at  TEXT, imported_at TEXT, updated_at TEXT,
  last_opened TEXT
);
CREATE TABLE IF NOT EXISTS renditions(
  item_id TEXT REFERENCES items(id) ON DELETE CASCADE,
  role    TEXT,                          -- 'md' | 'html' | 'entry'
  relpath TEXT,                          -- inside the item dir
  mtime   REAL, size INTEGER
);
CREATE TABLE IF NOT EXISTS tags(id INTEGER PRIMARY KEY, name TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS item_tags(item_id TEXT, tag_id INTEGER,
  UNIQUE(item_id, tag_id));
CREATE TABLE IF NOT EXISTS imports(     -- provenance + dedupe ledger
  source_path TEXT, source_hash TEXT, item_id TEXT, imported_at TEXT
);
CREATE TABLE IF NOT EXISTS areas(name TEXT PRIMARY KEY);  -- user-named, may be empty
CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(item_id UNINDEXED, title, body);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def set_fts(conn, item_id: str, title: str, body: str) -> None:
    conn.execute("DELETE FROM search WHERE item_id=?", (item_id,))
    conn.execute("INSERT INTO search(item_id,title,body) VALUES(?,?,?)",
                 (item_id, title, body))
    conn.commit()


def drop_item(conn, item_id: str) -> None:
    for t, col in (("renditions", "item_id"), ("item_tags", "item_id"),
                   ("search", "item_id"), ("items", "id")):
        conn.execute(f"DELETE FROM {t} WHERE {col}=?", (item_id,))
    conn.commit()


def set_tags(conn, item_id: str, names: list[str]) -> None:
    conn.execute("DELETE FROM item_tags WHERE item_id=?", (item_id,))
    for n in names:
        n = n.strip()
        if not n:
            continue
        conn.execute("INSERT OR IGNORE INTO tags(name) VALUES(?)", (n,))
        tid = conn.execute("SELECT id FROM tags WHERE name=?", (n,)).fetchone()[0]
        conn.execute("INSERT OR IGNORE INTO item_tags VALUES(?,?)", (item_id, tid))
    conn.commit()


def tags_of(conn, item_id: str) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT name FROM tags JOIN item_tags ON tags.id=tag_id "
        "WHERE item_id=? ORDER BY name", (item_id,))]


def fts_search(conn, q: str, limit: int = 30):
    """MATCH with a fallback to prefix form so live typing never 500s."""
    for query in (q, " ".join(w + "*" for w in q.split() if w.isalnum())):
        if not query:
            continue
        try:
            return conn.execute(
                "SELECT item_id, snippet(search, 2, '<mark>', '</mark>', '…', 14)"
                " AS snip, bm25(search) AS rank FROM search WHERE search MATCH ?"
                " ORDER BY rank LIMIT ?", (query, limit)).fetchall()
        except sqlite3.OperationalError:
            continue
    return []


def all_areas(conn, defaults: list[str]) -> list[str]:
    """Defaults first (config order), then every other area in use or named."""
    seen = list(defaults)
    extra = {r[0] for r in conn.execute("SELECT name FROM areas")}
    extra |= {r[0] for r in conn.execute("SELECT DISTINCT area FROM items WHERE area IS NOT NULL")}
    return seen + sorted(a for a in extra if a and a not in seen)


def add_area(conn, name: str) -> str:
    name = " ".join(name.split()).strip().lower()
    if name:
        conn.execute("INSERT OR IGNORE INTO areas(name) VALUES(?)", (name,))
        conn.commit()
    return name

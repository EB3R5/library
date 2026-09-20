"""Item-directory layer: meta.yaml, text extraction, registration, the
opportunistic mtime sweep, and the rebuild that proves the DB is a cache."""
import datetime
import re
import shutil
from hashlib import md5
from pathlib import Path

import yaml

import db as dbm
import gitops
from config import DB_PATH, ITEMS, LIBRARY

# Renditions the reader can show: text kinds render/serve as text, the rest are
# served byte-for-byte by /files and rendered natively by the browser.
TEXT = {".md", ".html", ".htm", ".txt"}
VIEWABLE = TEXT | {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}


def now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def item_id_for(dirname: str) -> str:
    return md5(dirname.encode()).hexdigest()[:10]


def slugify(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-") or "item"


def html_to_text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ",
                  re.sub(r"<(script|style)[\s\S]*?</\1>", " ", html, flags=re.I)))


def extract_title(path: Path, text: str) -> str:
    if path.suffix == ".md":
        for line in text.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    else:
        m = (re.search(r"<title>(.*?)</title>", text, re.S | re.I)
             or re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S | re.I))
        if m:
            return re.sub(r"<[^>]+>", "", m.group(1)).strip()
    return path.stem.replace("-", " ")


def frontmatter(text: str) -> dict:
    """Markdown frontmatter wins over meta.yaml for that rendition (sketch)."""
    if text.startswith("---"):
        try:
            end = text.index("\n---", 3)
            data = yaml.safe_load(text[3:end])
            return data if isinstance(data, dict) else {}
        except (ValueError, yaml.YAMLError):
            pass
    return {}


def first_run_init() -> None:
    ITEMS.mkdir(parents=True, exist_ok=True)
    gitops.ensure_repo()
    dbm.connect().close()  # creates schema


# ---------------------------------------------------------------- meta.yaml
def write_meta(item_dir: Path, meta: dict) -> None:
    (item_dir / "meta.yaml").write_text(yaml.safe_dump(meta, sort_keys=False))


def read_meta(item_dir: Path) -> dict:
    p = item_dir / "meta.yaml"
    try:
        return yaml.safe_load(p.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}


# ---------------------------------------------------------------- registration
def classify_renditions(item_dir: Path, kind: str) -> list[dict]:
    """The openable docs of an item; bundle assets ride along with no rows."""
    rows = []
    if kind == "bundle":
        candidates = (sorted(item_dir.glob("lessons/*.html"))
                      + sorted(item_dir.glob("reference/*.html"))
                      + sorted(item_dir.glob("learning-records/*.md"))
                      + [item_dir / n for n in
                         ("MISSION.md", "RESOURCES.md", "NOTES.md")
                         if (item_dir / n).exists()])
    else:
        candidates = sorted(p for p in item_dir.iterdir()
                            if p.suffix.lower() in VIEWABLE)
    for p in candidates:
        rows.append({"relpath": str(p.relative_to(item_dir)),
                     "role": p.suffix[1:],
                     "mtime": p.stat().st_mtime, "size": p.stat().st_size})
    # entry = the doc that opens when the item is clicked
    entry = next((r for r in rows if r["relpath"] == "MISSION.md"), None) \
        or next((r for r in rows if r["role"] == "html"), None) \
        or (rows[0] if rows else None)
    if entry:
        entry["role"] = "entry"
    return rows


def fts_body(item_dir: Path, rends: list[dict]) -> str:
    parts = []
    for r in rends:
        if Path(r["relpath"]).suffix.lower() not in TEXT:
            continue  # binary renditions never feed the index
        text = (item_dir / r["relpath"]).read_text(errors="replace")
        parts.append(html_to_text(text) if r["relpath"].endswith((".html", ".htm")) else text)
    return "\n".join(parts)


def register_item(conn, dirname: str, kind: str, meta: dict,
                  imported_at: str | None = None) -> str:
    item_dir = ITEMS / dirname
    iid = item_id_for(dirname)
    rends = classify_renditions(item_dir, kind)
    title, area, tags = meta.get("title", dirname), meta.get("area", "misc"), \
        meta.get("tags") or []
    for r in rends:  # frontmatter override (title, tags); area only if meta has none,
        if r["relpath"].endswith(".md"):  # so "move to area" in the panel sticks
            fm = frontmatter((item_dir / r["relpath"]).read_text(errors="replace"))
            title = fm.get("title", title)
            if not meta.get("area"):
                area = fm.get("area", area)
            tags = fm.get("tags", tags)
    conn.execute(
        "INSERT OR REPLACE INTO items(id,kind,title,area,dir,created_at,"
        "imported_at,updated_at,last_opened) VALUES(?,?,?,?,?,?,?,?,"
        "(SELECT last_opened FROM items WHERE id=?))",
        (iid, kind, title, area, dirname, meta.get("created_at", now()),
         imported_at or meta.get("imported_at"), now(), iid))
    conn.execute("DELETE FROM renditions WHERE item_id=?", (iid,))
    conn.executemany(
        "INSERT INTO renditions(item_id,role,relpath,mtime,size) VALUES(?,?,?,?,?)",
        [(iid, r["role"], r["relpath"], r["mtime"], r["size"]) for r in rends])
    conn.commit()
    dbm.set_tags(conn, iid, tags if isinstance(tags, list) else [])
    dbm.set_fts(conn, iid, title, fts_body(item_dir, rends))
    return iid


def refresh_item(conn, item) -> None:
    register_item(conn, item["dir"], item["kind"],
                  read_meta(ITEMS / item["dir"]))


# ---------------------------------------------------------------- new notes
def create_note(conn, title: str, area: str) -> str:
    dirname = f"{datetime.date.today().isoformat()}-{slugify(title)}"
    while (ITEMS / dirname).exists():
        dirname += "-2"
    d = ITEMS / dirname
    d.mkdir(parents=True)
    (d / "note.md").write_text(f"# {title}\n\n")
    meta = {"title": title, "area": area, "tags": [], "kind": "single",
            "source": None, "created_at": now(), "imported_at": now()}
    write_meta(d, meta)
    iid = register_item(conn, dirname, "single", meta, imported_at=meta["imported_at"])
    gitops.commit_all(f"import: new note “{title}”")
    return iid


# ---------------------------------------------------------------- delete
def delete_item(conn, item) -> None:
    """Remove the item folder and its rows; git keeps the files in history
    (`git log -- items/<dir>` in ~/learning-library recovers them)."""
    shutil.rmtree(ITEMS / item["dir"], ignore_errors=True)
    dbm.drop_item(conn, item["id"])
    conn.execute("DELETE FROM imports WHERE item_id=?", (item["id"],))  # re-scan shows it as new
    conn.commit()
    gitops.commit_all(f"delete: “{item['title']}” ({item['dir']})")


def delete_file(conn, item, relpath: str) -> bool:
    """Remove one file of an item. Returns True when the whole item went
    (it was the last file); the caller then clears the reader."""
    d = ITEMS / item["dir"]
    target = (d / relpath).resolve()
    if not target.is_relative_to(d.resolve()) or not target.is_file():
        return False
    target.unlink()
    remaining = [p for p in d.iterdir() if p.name != "meta.yaml"]
    if not remaining:
        delete_item(conn, item)
        return True
    refresh_item(conn, item)
    gitops.commit_all(f"delete: {item['dir']}/{relpath}")
    return False


# ---------------------------------------------------------------- areas
def set_area(conn, item, area: str) -> None:
    """Move an item to another area: meta.yaml is the source of truth, the
    DB row follows, one commit."""
    d = ITEMS / item["dir"]
    meta = read_meta(d)
    meta["area"] = area
    write_meta(d, meta)
    conn.execute("UPDATE items SET area=?, updated_at=? WHERE id=?",
                 (area, now(), item["id"]))
    conn.commit()
    gitops.commit_all(f"edit: move “{item['title']}” to area {area}")


# ---------------------------------------------------------------- uploads
def create_from_uploads(conn, uploads: list[tuple[str, bytes]],
                        area: str) -> tuple[list[str], list[str]]:
    """Files dropped or picked in the Workbench become items: one item per
    stem (md+html together = a pair, as the folder importer groups them),
    everything else single. Any file type is kept; only VIEWABLE ones get
    rendition rows. One commit per batch. Returns (item ids, error lines)."""
    groups: dict[str, list[tuple[str, bytes]]] = {}
    errors: list[str] = []
    for name, data in uploads:
        name = Path(name or "").name
        if not name or name.startswith("."):
            errors.append(f"{name or '?'}: hidden or unnamed file")
            continue
        if not data:
            errors.append(f"{name}: empty")
            continue
        groups.setdefault(slugify(Path(name).stem), []).append((name, data))

    ids: list[str] = []
    for slug, files in groups.items():
        dirname = f"{datetime.date.today().isoformat()}-{slug}"
        while (ITEMS / dirname).exists():
            dirname += "-2"
        d = ITEMS / dirname
        d.mkdir(parents=True)
        for name, data in files:
            (d / name).write_bytes(data)
        suffixes = {Path(n).suffix.lower() for n, _ in files}
        kind = "pair" if {".md", ".html"} <= suffixes else "single"
        title = None
        for ext in (".md", ".html", ".htm"):
            for name, data in files:
                if Path(name).suffix.lower() == ext:
                    title = extract_title(d / name, data.decode(errors="replace"))
                    break
            if title:
                break
        title = title or Path(files[0][0]).stem.replace("-", " ")
        meta = {"title": title, "area": area, "tags": [], "kind": kind,
                "source": "upload", "created_at": now(), "imported_at": now()}
        write_meta(d, meta)
        ids.append(register_item(conn, dirname, kind, meta,
                                 imported_at=meta["imported_at"]))
    if ids:
        n = sum(len(f) for f in groups.values())
        gitops.commit_all(f"import: upload {n} file(s) → {len(ids)} item(s)")
    return ids, errors


# ---------------------------------------------------------------- sweep
def sweep(conn) -> None:
    """Opportunistic, on page load: out-of-band file edits never leave the
    index stale; missing dirs drop their rows. Corpus is small — this is ms."""
    for item in conn.execute("SELECT * FROM items").fetchall():
        d = ITEMS / item["dir"]
        if not d.exists():
            dbm.drop_item(conn, item["id"])
            continue
        for r in conn.execute("SELECT * FROM renditions WHERE item_id=?",
                              (item["id"],)):
            p = d / r["relpath"]
            if not p.exists() or (p.stat().st_mtime, p.stat().st_size) != \
                    (r["mtime"], r["size"]):
                refresh_item(conn, item)
                break


# ---------------------------------------------------------------- rebuild
def rebuild() -> int:
    """Delete library.db → full DB from items/ alone (rebuildable-cache rule)."""
    DB_PATH.unlink(missing_ok=True)
    conn = dbm.connect()
    n = 0
    for d in sorted(p for p in ITEMS.iterdir() if p.is_dir()):
        meta = read_meta(d)
        kind = meta.get("kind") or (
            "bundle" if (d / "MISSION.md").exists() and (d / "lessons").is_dir()
            else "single")
        register_item(conn, d.name, kind, meta,
                      imported_at=meta.get("imported_at"))
        n += 1
    conn.close()
    return n

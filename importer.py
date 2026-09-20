"""Import pipeline: registered sources → on-demand scan → review → copy.
Copy forever; sources are never written. Ledger hashes keep re-scans
idempotent; changed-upstream is flagged, never auto-overwritten."""
import datetime
import shutil
from hashlib import md5
from pathlib import Path

import gitops
import libfs
from config import BUNDLE_AREA, ITEMS, SOURCES

# Scan results cached for the review panel's peek/import buttons; the id is
# content-addressed so a stale click after re-scan still hits the same file.
CANDIDATES: dict[str, dict] = {}


def _hash_file(p: Path) -> str:
    return md5(p.read_bytes()).hexdigest()


def _hash_bundle(d: Path) -> str:
    h = md5()
    for p in sorted(d.rglob("*")):
        if p.is_file() and ".git" not in p.parts and p.name != ".DS_Store":
            h.update(str(p.relative_to(d)).encode())
            h.update(_hash_file(p).encode())
    return h.hexdigest()


def is_bundle(d: Path) -> bool:
    return (d / "MISSION.md").exists() and (d / "lessons").is_dir()


def scan(conn) -> list[dict]:
    """Walk sources, group candidates, diff against the imports ledger."""
    CANDIDATES.clear()
    out = []
    for src in SOURCES:
        root = src["root"]
        if not root.exists():
            continue
        files: list[Path] = []
        for p in sorted(root.iterdir()):
            if p.name.startswith("."):
                continue
            if p.is_dir():
                if is_bundle(p):
                    out.append(_candidate(conn, kind="bundle", paths=[p],
                                          area=BUNDLE_AREA, root=root))
                continue  # non-bundle subdirs: not scanned (registered roots only)
            if p.suffix in libfs.OPENABLE:
                files.append(p)
        for stem in sorted({f.stem for f in files}):
            group = [f for f in files if f.stem == stem]
            kind = "pair" if len(group) > 1 else "single"
            out.append(_candidate(conn, kind=kind, paths=group,
                                  area=src["area"], root=root))
    return out


def _candidate(conn, kind: str, paths: list[Path], area: str, root: Path) -> dict:
    main = paths[0]
    chash = _hash_bundle(main) if kind == "bundle" else \
        md5("".join(sorted(_hash_file(p) for p in paths)).encode()).hexdigest()
    text = "" if kind == "bundle" else main.read_text(errors="replace")
    title = main.name if kind == "bundle" else libfs.extract_title(main, text)
    prior = conn.execute(
        "SELECT * FROM imports WHERE source_path=? ORDER BY imported_at DESC",
        (str(main),)).fetchone()
    if prior is None:
        status, item_id, edits = "new", None, 0
    elif prior["source_hash"] == chash:
        status, item_id, edits = "imported", prior["item_id"], 0
    else:
        status, item_id = "changed", prior["item_id"]
        row = conn.execute("SELECT dir FROM items WHERE id=?",
                           (item_id,)).fetchone()
        edits = gitops.local_edit_count(f"items/{row['dir']}") if row else 0
    cid = chash[:12]
    cand = {"cid": cid, "kind": kind, "paths": [str(p) for p in paths],
            "root": str(root), "area": area, "title": title, "hash": chash,
            "status": status, "item_id": item_id, "local_edits": edits}
    CANDIDATES[cid] = cand
    return cand


def do_import(conn, cid: str) -> str | None:
    """Copy into a new item dir (or overwrite the existing one on re-import),
    write meta.yaml, insert rows + FTS, ledger, commit."""
    cand = CANDIDATES.get(cid)
    if not cand or cand["status"] == "imported":
        return None
    main = Path(cand["paths"][0])
    overwrite = cand["status"] == "changed" and cand["item_id"]

    if overwrite:
        dirname = conn.execute("SELECT dir FROM items WHERE id=?",
                               (cand["item_id"],)).fetchone()["dir"]
        dest = ITEMS / dirname
        for child in dest.iterdir():          # keep the dir, replace contents
            if child.name != "meta.yaml":
                shutil.rmtree(child) if child.is_dir() else child.unlink()
    else:
        if cand["kind"] == "bundle":
            dirname = main.name
        else:
            day = datetime.date.fromtimestamp(main.stat().st_mtime).isoformat()
            dirname = f"{day}-{libfs.slugify(main.stem)}"
        while (ITEMS / dirname).exists():
            dirname += "-2"
        dest = ITEMS / dirname
        dest.mkdir(parents=True)

    if cand["kind"] == "bundle":
        shutil.copytree(main, dest, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".git", ".DS_Store"))
    else:
        for p in cand["paths"]:
            shutil.copy2(p, dest / Path(p).name)

    meta = libfs.read_meta(dest) if overwrite else {}
    meta.update({"title": meta.get("title") or cand["title"],
                 "area": meta.get("area") or cand["area"],
                 "tags": meta.get("tags") or [], "kind": cand["kind"],
                 "source": str(main), "created_at": meta.get("created_at")
                 or libfs.now(), "imported_at": libfs.now()})
    libfs.write_meta(dest, meta)
    iid = libfs.register_item(conn, dest.name, cand["kind"], meta,
                              imported_at=meta["imported_at"])
    conn.execute("INSERT INTO imports VALUES(?,?,?,?)",
                 (str(main), cand["hash"], iid, meta["imported_at"]))
    conn.commit()
    verb = "re-import (overwrite)" if overwrite else "import"
    gitops.commit_all(f"import: {verb} “{meta['title']}” from {main}")
    cand["status"], cand["item_id"] = "imported", iid
    return iid

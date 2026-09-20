"""Claude-in-the-loop over a scratch directory (plan.md v2, ticket #13).

Claude cannot edit rows, so a run materializes the Item's Text Documents into
~/learning-library/scratch/<run id>/, runs `claude -p` there with the tools
capped, and the diff is difflib against the stored body. Only the target
document's change is accepted; edits to siblings and new files are ignored
and reported. ONE run in flight globally; never runs without a button press.
"""
import difflib
import shutil
import subprocess
import threading
from pathlib import Path
from uuid import uuid4

import documents as docs
from config import CLAUDE_BIN, CLAUDE_MODEL, CLAUDE_TIMEOUT, CLAUDE_TOOLS, SCRATCH

_LOCK = threading.Lock()
# status: idle | running | diff | nochange | error
RUN: dict = {"status": "idle"}

CONTRACT = (" Match the document's existing markup conventions and idiom "
            "exactly, so the change is indistinguishable from original "
            "content. Edit the file in place. Do not touch any other file, "
            "and do not write commentary or summaries anywhere. Other files "
            "in this folder are context only; do not modify them.")


def clean_scratch() -> None:
    """At app start: stale scratch dirs from a killed server are gone."""
    shutil.rmtree(SCRATCH, ignore_errors=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)


def prompts(feature: str, name: str, f: dict, others: list[str]) -> tuple[str, str]:
    context = (f" Also part of this item but not present as files: {', '.join(others)}."
               if others else "")
    if feature == "integrate":
        return (f"integrate “{f['term']}”",
                f"Edit {name}. Fold in a new entry — term: \"{f['term']}\", "
                f"content: \"{f['body']}\". Insert it where it fits the "
                "document's existing ordering and structure." + CONTRACT + context)
    if feature == "retrofit":
        return (f"retrofit: {f['cap']}",
                f"Edit {name}, a self-contained document. Retrofit this "
                f"capability into it: {f['cap']}. Requirements: vanilla inline "
                "JS/CSS only, no external libraries or network requests; "
                "visually match the document's existing style so it looks "
                "like it was always there; do not remove or reword existing "
                "content or break existing scripts." + CONTRACT + context)
    return (f"free-form: “{f['prompt'][:50]}”",
            f"Edit {name}. {f['prompt']}" + CONTRACT + context)


def start(conn, item: dict, doc: dict, feature: str, fields: dict) -> str | None:
    """Returns an error message, or None when the run started."""
    with _LOCK:
        if RUN["status"] == "running":
            return "an edit is already running — one in flight, globally"
        if RUN["status"] in ("diff", "error", "nochange"):
            return "resolve the pending diff (Accept/Revert) first"
        if not docs.is_text_kind(doc["kind"]):
            return "only text documents can be edited by Claude"
        sdir = SCRATCH / uuid4().hex
        sdir.mkdir(parents=True)
        snapshot: dict[str, str] = {}
        for d in docs.text_docs(conn, item["id"]):
            snapshot[d["name"]] = d["body"] or ""
            (sdir / d["name"]).write_text(snapshot[d["name"]], encoding="utf-8")
        others = [d["name"] for d in docs.list_for_item(conn, item["id"]) if not d["editable"]]
        summary, prompt = prompts(feature, doc["name"], fields, others)
        RUN.update(status="running", dir=str(sdir), item_id=item["id"], title=item["title"],
                   doc_id=doc["id"], name=doc["name"], base=snapshot[doc["name"]],
                   snapshot=snapshot, feature=feature, summary=summary, detail="",
                   new_body=None, ignored=[], stale=False)
    threading.Thread(target=_work, args=(sdir, prompt), daemon=True).start()
    return None


def _work(sdir: Path, prompt: str) -> None:
    try:
        r = subprocess.run(
            [CLAUDE_BIN, "-p", prompt, "--model", CLAUDE_MODEL,
             "--permission-mode", "acceptEdits", "--allowedTools", CLAUDE_TOOLS],
            cwd=sdir, capture_output=True, text=True, timeout=CLAUDE_TIMEOUT)
        err = "" if r.returncode == 0 else f"claude exited {r.returncode}: " \
            + (r.stderr or r.stdout)[-800:]
    except subprocess.TimeoutExpired:
        err = f"claude timed out after {CLAUDE_TIMEOUT}s"
    except FileNotFoundError:
        err = f"claude CLI not found at {CLAUDE_BIN}"
    with _LOCK:
        target = sdir / RUN["name"]
        new = (target.read_text(encoding="utf-8", errors="replace")
               if target.is_file() else None)
        ignored = []
        for p in sorted(sdir.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(sdir).as_posix()
            if rel == RUN["name"]:
                continue
            before = RUN["snapshot"].get(rel)
            if before is None or p.read_text(encoding="utf-8", errors="replace") != before:
                ignored.append(rel)
        RUN["ignored"] = ignored
        if new is not None and new != RUN["base"]:  # changed even on failure → show the diff
            RUN.update(status="diff", new_body=new, detail=err)
        elif err:
            RUN.update(status="error", detail=err)
        else:
            RUN.update(status="nochange", detail="claude made no change to the document")


def diff() -> str:
    if RUN.get("new_body") is None:
        return ""
    return "".join(difflib.unified_diff(
        RUN["base"].splitlines(keepends=True), RUN["new_body"].splitlines(keepends=True),
        fromfile=f"a/{RUN['name']}", tofile=f"b/{RUN['name']}"))


def _finish() -> None:
    if RUN.get("dir"):
        shutil.rmtree(RUN["dir"], ignore_errors=True)
    RUN.clear()
    RUN["status"] = "idle"


def accept(conn) -> str | None:
    """Accept = documents.update → Version with cause `claude: <summary>`.
    Refuses when the body changed since the run started (only Revert then)."""
    with _LOCK:
        if RUN["status"] != "diff":
            return None
        try:
            current = docs.get(conn, RUN["doc_id"])
        except docs.DomainError:
            RUN.update(stale=True, detail="document was deleted since the run started")
            return RUN["detail"]
        if (current["body"] or "") != RUN["base"]:
            RUN.update(stale=True, detail="document changed since the run started")
            return RUN["detail"]
        try:
            docs.update(conn, RUN["doc_id"], {"body": RUN["new_body"]},
                        cause=f"claude: {RUN['summary']}")
        except docs.DomainError as e:   # the caps apply to accepted edits too
            RUN.update(stale=True, detail=str(e))
            return str(e)
        _finish()
        return None


def revert() -> None:
    with _LOCK:
        _finish()


def dismiss() -> None:
    with _LOCK:
        if RUN["status"] in ("error", "nochange"):
            _finish()


def pending_item() -> str | None:
    return RUN.get("item_id") if RUN["status"] != "idle" else None

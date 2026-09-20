"""Claude-in-the-loop runner (map ticket #4): sonnet · acceptEdits · item-dir
cwd · tool cap · background thread · ONE edit in flight globally · 600s.
Pending edit = dirty working tree; diff vs HEAD; Accept = commit, Revert =
checkout. Never runs without a button press."""
import subprocess
import threading

import gitops
import libfs
from config import (CLAUDE_BIN, CLAUDE_MODEL, CLAUDE_TIMEOUT, CLAUDE_TOOLS,
                    ITEMS)

_LOCK = threading.Lock()
# status: idle | running | diff | nochange | error
RUN: dict = {"status": "idle"}

CONTRACT = (" Match the document's existing markup conventions and idiom "
            "exactly, so the change is indistinguishable from original "
            "content. Edit the file in place. Do not touch any other file, "
            "and do not write commentary or summaries anywhere.")


def prompts(feature: str, relpath: str, f: dict) -> tuple[str, str]:
    if feature == "integrate":
        return (f"integrate “{f['term']}”",
                f"Edit {relpath}. Fold in a new entry — term: \"{f['term']}\", "
                f"content: \"{f['body']}\". Insert it where it fits the "
                "document's existing ordering and structure." + CONTRACT)
    if feature == "retrofit":
        return (f"retrofit: {f['cap']}",
                f"Edit {relpath}, a self-contained document. Retrofit this "
                f"capability into it: {f['cap']}. Requirements: vanilla inline "
                "JS/CSS only, no external libraries or network requests; "
                "visually match the document's existing style so it looks "
                "like it was always there; do not remove or reword existing "
                "content or break existing scripts." + CONTRACT)
    return (f"free-form: “{f['prompt'][:50]}”",
            f"Edit {relpath}. {f['prompt']}" + CONTRACT)


def start(item: dict, relpath: str, feature: str, fields: dict) -> str | None:
    """Returns an error message, or None when the run started."""
    with _LOCK:
        if RUN["status"] == "running":
            return "an edit is already running — one in flight, globally"
        if RUN["status"] in ("diff", "error"):
            return "resolve the pending diff (Accept/Revert) first"
        summary, prompt = prompts(feature, relpath, fields)
        RUN.update(status="running", item_id=item["id"], dir=item["dir"],
                   title=item["title"], relpath=relpath, feature=feature,
                   summary=summary, detail="")
    threading.Thread(target=_work, args=(item["dir"], prompt), daemon=True).start()
    return None


def _work(dirname: str, prompt: str) -> None:
    try:
        r = subprocess.run(
            [CLAUDE_BIN, "-p", prompt, "--model", CLAUDE_MODEL,
             "--permission-mode", "acceptEdits", "--allowedTools", CLAUDE_TOOLS],
            cwd=ITEMS / dirname, capture_output=True, text=True,
            timeout=CLAUDE_TIMEOUT)
        err = "" if r.returncode == 0 else f"claude exited {r.returncode}: " \
            + (r.stderr or r.stdout)[-800:]
    except subprocess.TimeoutExpired:
        err = f"claude timed out after {CLAUDE_TIMEOUT}s"
    except FileNotFoundError:
        err = f"claude CLI not found at {CLAUDE_BIN}"
    with _LOCK:
        dirty = gitops.dirty_paths(f"items/{dirname}")
        if dirty:            # dirty even on failure → still show the diff
            RUN.update(status="diff", detail=err)
        elif err:
            RUN.update(status="error", detail=err)
        else:
            RUN.update(status="nochange",
                       detail="claude made no change to the document")


def diff() -> str:
    return gitops.diff_text(f"items/{RUN['dir']}") if RUN.get("dir") else ""


def accept(conn) -> None:
    with _LOCK:
        if RUN["status"] != "diff":
            RUN.update(status="idle")
            return
        gitops.commit_all(f"claude-edit({RUN['dir']}/{RUN['relpath']}): "
                          f"{RUN['feature']}: {RUN['summary']}")
        item = conn.execute("SELECT * FROM items WHERE id=?",
                            (RUN["item_id"],)).fetchone()
        if item:
            libfs.refresh_item(conn, item)  # updated_at + FTS
        RUN.clear()
        RUN["status"] = "idle"


def revert() -> None:
    with _LOCK:
        if RUN.get("dir"):
            gitops.checkout(f"items/{RUN['dir']}")
        RUN.clear()
        RUN["status"] = "idle"


def dismiss() -> None:
    with _LOCK:
        if RUN["status"] in ("error", "nochange"):
            RUN.clear()
            RUN["status"] = "idle"

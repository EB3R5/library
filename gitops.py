"""git in ~/learning-library is the undo store (map ticket #3):
Accept = commit · Revert = checkout · pending edit = dirty working tree."""
import subprocess

from config import LIBRARY

GITIGNORE = "library.db\nlibrary.db-*\n.DS_Store\n"


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(LIBRARY), *args],
                          capture_output=True, text=True, check=check)


def ensure_repo() -> None:
    if not (LIBRARY / ".git").exists():
        _git("init", "-q")
        (LIBRARY / ".gitignore").write_text(GITIGNORE)
        _git("add", "-A")
        _git("commit", "-qm", "init: library created", check=False)


def commit_all(message: str) -> None:
    _git("add", "-A")
    if _git("status", "--porcelain", check=False).stdout.strip():
        _git("commit", "-qm", message)


def dirty_paths(subdir: str = "") -> list[str]:
    args = ["status", "--porcelain"] + (["--", subdir] if subdir else [])
    return [line[3:] for line in
            _git(*args, check=False).stdout.splitlines() if line.strip()]


def diff_text(subdir: str = "") -> str:
    """Working tree vs HEAD, untracked files included as full additions."""
    args = ["diff", "HEAD"] + (["--", subdir] if subdir else [])
    out = _git(*args, check=False).stdout
    for line in _git("status", "--porcelain", "--", subdir or ".",
                     check=False).stdout.splitlines():
        if line.startswith("??"):
            p = line[3:]
            body = (LIBRARY / p).read_text(errors="replace")
            out += f"\n@@ new file: {p} @@\n" + "\n".join(
                "+" + l for l in body.splitlines())
    return out


def checkout(subdir: str) -> None:
    _git("checkout", "-q", "--", subdir)
    _git("clean", "-fdq", "--", subdir)  # drop files a run newly created


def local_edit_count(subdir: str) -> int:
    """Commits touching subdir that aren't its import commits."""
    out = _git("log", "--format=%s", "--", subdir, check=False).stdout
    return sum(1 for s in out.splitlines()
               if s and not s.startswith(("import:", "init:")))

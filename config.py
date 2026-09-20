"""Fixed configuration — plan.md is the source of these values."""
import os
import shutil
from pathlib import Path

# ~/library collides with ~/Library (case-insensitive APFS), hence learning-library.
# LIBRARY_HOME overrides it — the Docker image sets /data, a bind mount of ~/learning-library.
LIBRARY = Path(os.environ.get("LIBRARY_HOME") or Path.home() / "learning-library")
DB_PATH = LIBRARY / "library.db"       # the data — SQLite is the source of truth (ADR 0002)
SCRATCH = LIBRARY / "scratch"          # one dir per Claude run; wiped on Accept/Revert/start
EXPORT_DIR = LIBRARY / "export"        # default root for ./run.sh export

AREAS = ["research", "painting", "teach", "misc"]  # defaults; more can be named in-app

HOST, PORT = "127.0.0.1", 8900

CLAUDE_MODEL = "sonnet"
CLAUDE_TIMEOUT = 600
CLAUDE_TOOLS = "Read,Edit,Write,Glob,Grep"  # no Bash, no web

# A Finder-launched .app inherits a minimal PATH without ~/.local/bin, so the
# bare name only resolves when the server was started from a shell.
CLAUDE_BIN = shutil.which("claude") or str(Path.home() / ".local/bin/claude")

"""Fixed configuration — plan.md is the source of these values."""
import os
import shutil
from pathlib import Path

# Amendment in plan.md: ~/library collides with ~/Library (case-insensitive APFS).
# LIBRARY_HOME overrides it — the Docker image sets /data, a bind mount of ~/learning-library.
LIBRARY = Path(os.environ.get("LIBRARY_HOME") or Path.home() / "learning-library")
ITEMS = LIBRARY / "items"
DB_PATH = LIBRARY / "library.db"

# Registered sources (import review panel scans these on demand)
SOURCES = [
    {"root": Path.home() / "research", "area": "research"},
    {"root": Path.home() / "Documents" / "painting", "area": "painting"},
]
BUNDLE_AREA = "teach"  # MISSION.md + lessons/ signature ⇒ teach workspace
AREAS = ["research", "painting", "teach", "misc"]

HOST, PORT = "127.0.0.1", 8900

CLAUDE_MODEL = "sonnet"
CLAUDE_TIMEOUT = 600
CLAUDE_TOOLS = "Read,Edit,Write,Glob,Grep"  # no Bash, no web

# A Finder-launched .app inherits a minimal PATH without ~/.local/bin, so the
# bare name only resolves when the server was started from a shell.
CLAUDE_BIN = shutil.which("claude") or str(Path.home() / ".local/bin/claude")

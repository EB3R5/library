"""Fixed configuration — plan.md is the source of these values."""
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

# Secrets live in library/.env (git-ignored, Docker-ignored; the homelab compose mounts it
# as env_file). Real environment variables win over the file.
load_dotenv(Path(__file__).parent / ".env")

# ~/library collides with ~/Library (case-insensitive APFS), hence learning-library.
# LIBRARY_HOME overrides it — the Docker image sets /data, a bind mount of ~/learning-library.
LIBRARY = Path(os.environ.get("LIBRARY_HOME") or Path.home() / "learning-library")
DB_PATH = LIBRARY / "library.db"       # the data — SQLite is the source of truth (ADR 0002)
SCRATCH = LIBRARY / "scratch"          # one dir per Claude run; wiped on Accept/Revert/start
EXPORT_DIR = LIBRARY / "export"        # default root for ./run.sh export

AREAS = ["research", "painting", "teach", "misc"]  # defaults; more can be named in-app

HOST, PORT = "127.0.0.1", 8900

# Where a `tasks:<id>` Source links to (ADR 0004): the Tasks app's base URL.
TASKS_URL = os.environ.get("TASKS_URL", "http://127.0.0.1:8011").rstrip("/")

# Session login (auth.py, ADR 0003). SESSION_SECRET signs the cookie and is required to
# serve — generate one with: python -c "import secrets; print(secrets.token_hex(32))".
# SESSION_MAX_AGE is the cookie lifetime in seconds (default 7 days). SESSION_HTTPS_ONLY
# stays false: localhost is plain http and tailscale terminates TLS in front of the app.
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
SESSION_MAX_AGE = int(os.environ.get("SESSION_MAX_AGE", "604800"))
SESSION_HTTPS_ONLY = os.environ.get("SESSION_HTTPS_ONLY", "false").lower() == "true"

# `Authorization: Bearer <API_TOKEN>` passes the auth gate without a session (the agent
# API, ADR 0005). Separate from SESSION_SECRET on purpose. Empty disables it.
API_TOKEN = os.environ.get("API_TOKEN", "")

CLAUDE_MODEL = "sonnet"
CLAUDE_TIMEOUT = 600
CLAUDE_TOOLS = "Read,Edit,Write,Glob,Grep"  # no Bash, no web

# A Finder-launched .app inherits a minimal PATH without ~/.local/bin, so the
# bare name only resolves when the server was started from a shell.
CLAUDE_BIN = shutil.which("claude") or str(Path.home() / ".local/bin/claude")

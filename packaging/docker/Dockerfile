# Server target. Build from the repo root:
#   docker build -f packaging/docker/Dockerfile -t library .
# No build backend (flat modules run with `uv run app.py`), so the locked dependencies are
# installed with uv and the modules run from /app via `python -m uvicorn` (puts /app on sys.path).
# git is required by gitops (the undo store). The homelab compose mounts ~/learning-library at
# /data (LIBRARY_HOME) and publishes 8900.
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-cache
COPY app.py config.py db.py libfs.py importer.py gitops.py claude_runner.py ./
COPY templates ./templates
# HOME on the data mount: the container may run as the host uid with no passwd entry. Commits in
# the undo store need an identity; safe.directory covers a mount owned by another uid.
ENV HOME=/data LIBRARY_HOME=/data \
    GIT_AUTHOR_NAME=library GIT_AUTHOR_EMAIL=library@localhost \
    GIT_COMMITTER_NAME=library GIT_COMMITTER_EMAIL=library@localhost \
    GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0=*
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"
CMD ["/app/.venv/bin/python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

# Server target. Build from the repo root:
#   docker build -f packaging/docker/Dockerfile -t library .
# No build backend (flat modules run with `uv run app.py`), so the locked dependencies are
# installed with uv and the modules run from /app via `python -m uvicorn` (puts /app on sys.path).
# The homelab compose mounts ~/learning-library at /data (LIBRARY_HOME) and publishes 8900.
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-cache
COPY app.py config.py documents.py export.py claude_runner.py ./
COPY templates ./templates
# HOME on the data mount: the container may run as the host uid with no passwd entry.
ENV HOME=/data LIBRARY_HOME=/data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"
CMD ["/app/.venv/bin/python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

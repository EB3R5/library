#!/bin/sh
# library — run from this checkout. plan.md: no install step, port 8900.
# `./run.sh export [root]` writes the backup tree + a copy of library.db
# (default root: ~/learning-library/export).
cd "$(dirname "$0")" || exit 1
exec uv run app.py "$@"

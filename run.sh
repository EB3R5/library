#!/bin/sh
# library — run from this checkout. plan.md: no install step, port 8900.
# `./run.sh proto` runs the throwaway documents-in-db prototype on 8901.
cd "$(dirname "$0")" || exit 1
if [ "$1" = "proto" ]; then
  exec uv run --with nh3 prototype_documents/app.py
fi
exec uv run app.py "$@"

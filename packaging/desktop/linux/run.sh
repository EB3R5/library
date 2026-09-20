#!/usr/bin/env bash
# Launch library as a native desktop window (pywebview + GTK/WebKit2).
#
# The .venv runs on the distro Python (pinned by install.sh) but still can't see the
# GObject-introspection typelibs unless we point at them. `gi` itself is exposed to the venv
# via .venv/.../site-packages/system-gi.pth (written by install.sh), which *appends* the distro
# site-packages to sys.path so the venv's own packages still win. Only the typelib path is
# needed here. A .desktop launch inherits a minimal PATH: add ~/.local/bin so `claude` resolves.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO"

for d in /usr/lib/girepository-1.0 /usr/lib/x86_64-linux-gnu/girepository-1.0; do
  [ -d "$d" ] && export GI_TYPELIB_PATH="$d${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"
done
export PATH="$HOME/.local/bin:$PATH"

# WebKitGTK's DMA-BUF renderer dies with "Error 71 (Protocol error) dispatching to Wayland
# display" on Hyprland + NVIDIA; the software path is fine for a document reader. Harmless elsewhere.
export WEBKIT_DISABLE_DMABUF_RENDERER=1

exec uv run --extra desktop packaging/desktop/launcher.py

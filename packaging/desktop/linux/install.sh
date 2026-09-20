#!/usr/bin/env bash
# Install the Linux desktop entry for library (Arch/Omarchy or Debian/Ubuntu).
#   1. checks the distro packages pywebview's GTK backend needs
#   2. pins the uv project to the distro Python and syncs the desktop extra
#   3. exposes the system `gi` module to the repo .venv via a .pth file
#   4. renders the .desktop entry with this repo's path and installs it + the icon
# Usage: packaging/desktop/linux/install.sh      (re-runnable)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
APP=library

missing=()
if command -v pacman >/dev/null; then
  for pkg in python-gobject gtk3 webkit2gtk-4.1; do
    pacman -Q "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
  done
  hint="sudo pacman -S ${missing[*]}"
  SYS_SITE="$(python3 -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
else
  for pkg in python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1; do
    dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
  done
  hint="sudo apt install ${missing[*]}"
  SYS_SITE=/usr/lib/python3/dist-packages
fi
if ((${#missing[@]})); then
  echo "missing packages: ${missing[*]}" >&2
  echo "  $hint" >&2
  exit 1
fi
command -v uv >/dev/null || { echo "uv not on PATH — https://docs.astral.sh/uv/" >&2; exit 1; }

# The distro gi is a C extension built for the distro interpreter; a uv-managed Python cannot
# import it. Pin the project to the system python3 (.python-version is gitignored, per machine)
# and sync: uv recreates .venv once if it was on another interpreter, otherwise reuses it.
SYS_PY="$(command -v python3)"
(
  cd "$REPO"
  uv python pin --resolved "$SYS_PY" >/dev/null 2>&1 || printf '%s\n' "$SYS_PY" > .python-version
  uv sync --extra desktop
)
SITE="$("$REPO/.venv/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
echo "$SYS_SITE" > "$SITE/system-gi.pth"

mkdir -p ~/.local/share/applications ~/.local/share/icons/hicolor/256x256/apps
sed "s|@@REPO@@|$REPO|g" "$HERE/$APP.desktop" > ~/.local/share/applications/$APP.desktop
cp "$HERE/$APP.png" ~/.local/share/icons/hicolor/256x256/apps/$APP.png
command -v update-desktop-database >/dev/null && update-desktop-database ~/.local/share/applications || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q ~/.local/share/icons/hicolor || true
echo "installed ~/.local/share/applications/$APP.desktop -> $REPO"

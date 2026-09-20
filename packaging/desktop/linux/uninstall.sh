#!/usr/bin/env bash
# Remove the desktop entry + icon installed by install.sh (leaves the venv alone).
set -euo pipefail
APP=library
rm -f ~/.local/share/applications/$APP.desktop ~/.local/share/icons/hicolor/256x256/apps/$APP.png
command -v update-desktop-database >/dev/null && update-desktop-database ~/.local/share/applications || true
echo "removed $APP desktop entry"

#!/bin/zsh
# Build /Applications/library.app from scratch.
# Usage: packaging/desktop/macos/build.sh
# Requires: Xcode CLT (clang), uv at /opt/homebrew/bin/uv (the launcher execs it).
# The .icns is committed, so Pillow is only needed to regenerate the artwork.
set -euo pipefail

HERE="${0:A:h}"
REPO="${HERE:h:h:h}"
APP="/Applications/library.app"
BUNDLE_ID="com.christian.library.workbench"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "== compile launcher =="
clang -O2 -o "$TMP/library" "$HERE/launcher.c"

echo "== assemble bundle =="
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$TMP/library" "$APP/Contents/MacOS/library"
cp "$HERE/library.icns" "$APP/Contents/Resources/library.icns"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>library</string>
  <key>CFBundleDisplayName</key><string>library</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleVersion</key><string>0.1.0</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>library</string>
  <key>CFBundleIconFile</key><string>library</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

echo "== sign + register =="
codesign --force -s - --identifier "$BUNDLE_ID" "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP"

echo "done: $APP"
echo "First launch: approve the macOS prompt to access the Documents folder."

# Regenerate the icon (only when the artwork changes):
#   uv run --with pillow packaging/desktop/macos/make_icon.py /tmp/icon_1024.png
#   mkdir /tmp/library.iconset
#   for s in 16 32 128 256 512; do
#     sips -z $s $s /tmp/icon_1024.png --out /tmp/library.iconset/icon_${s}x${s}.png
#     sips -z $((s*2)) $((s*2)) /tmp/icon_1024.png --out /tmp/library.iconset/icon_${s}x${s}@2x.png
#   done
#   iconutil -c icns /tmp/library.iconset -o packaging/desktop/macos/library.icns
# The Linux entry's 256px PNG comes from the same artwork:
#   uv run --with pillow packaging/desktop/macos/make_icon.py packaging/desktop/linux/library.png 256

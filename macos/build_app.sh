#!/usr/bin/env bash
# Builds "AI Music Studio.app" for the host architecture and a zip for the release page.
#
#   macos/build_app.sh                    -> dist/AI Music Studio.app + dist/AI-Music-Studio-<ver>-macOS-<arch>.zip
#   macos/build_app.sh --version 1.2.0 --out /tmp/dist
#
# Needs macOS 14+ and Xcode 15+ or just the Command Line Tools (Swift 5.9+). No network access needed.
# The Python engine (studio/ without the PyQt UI) and requirements-engine.txt are copied into
# Contents/Resources/engine; the app finds Python itself or creates its own venv on first launch.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
VERSION="1.2.0"
OUT="$ROOT/dist"
while [ $# -gt 0 ]; do
  case "$1" in
    --version) VERSION="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

APP_NAME="AI Music Studio"
EXE="AIMusicStudio"
ARCH="$(uname -m)"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
APP="$OUT/$APP_NAME.app"
ZIP="$OUT/AI-Music-Studio-$VERSION-macOS-$ARCH.zip"

# Command Line Tools without Xcode: the macOS 27 SDK turns @State into a macro whose plugin ships only
# with Xcode, so fall back to the newest 26.x/15.x SDK that the CLT also installs.
if [ -z "${SDKROOT:-}" ] && ! xcode-select -p 2>/dev/null | grep -q "Xcode"; then
  for sdk in /Library/Developer/CommandLineTools/SDKs/MacOSX15*.sdk /Library/Developer/CommandLineTools/SDKs/MacOSX26*.sdk; do
    if [ -d "$sdk" ]; then SDKROOT="$sdk"; fi
  done
  if [ -n "${SDKROOT:-}" ]; then export SDKROOT; echo "SDKROOT=$SDKROOT"; fi
fi

# keep every cache inside the package: works in CI, sandboxes and read-only home folders
export CLANG_MODULE_CACHE_PATH="$HERE/.mc/clang"
export SWIFTPM_MODULECACHE_OVERRIDE="$HERE/.mc/spm"
SWIFT_FLAGS=(-c release --disable-sandbox
  --package-path "$HERE"
  --scratch-path "$HERE/.build"
  --cache-path "$HERE/.build/cache"
  --config-path "$HERE/.build/config"
  --security-path "$HERE/.build/security"
  -Xswiftc -module-cache-path -Xswiftc "$HERE/.mc/swift")

echo "==> swift build (release, $ARCH)"
swift build "${SWIFT_FLAGS[@]}"
BIN_DIR="$(swift build "${SWIFT_FLAGS[@]}" --show-bin-path)"

echo "==> bundle $APP"
rm -rf "$APP" "$ZIP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/engine"
cp "$BIN_DIR/$EXE" "$APP/Contents/MacOS/$EXE"
cp "$HERE/Resources/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
cp "$ROOT/LICENSE" "$APP/Contents/Resources/LICENSE"

# engine: the Python package without the PyQt UI, no caches
mkdir -p "$APP/Contents/Resources/engine/studio"
# .py plus bundled model data (fakeprint weights, its NOTICE)
( cd "$ROOT/studio" && find . -type f \( -name '*.py' -o -name '*.npz' -o -name 'NOTICE' \) ! -path './ui/*' \
    ! -path '*/__pycache__/*' ) | while read -r f; do
  mkdir -p "$APP/Contents/Resources/engine/studio/$(dirname "$f")"
  cp "$ROOT/studio/$f" "$APP/Contents/Resources/engine/studio/$f"
done
cp "$ROOT/requirements-engine.txt" "$APP/Contents/Resources/engine/requirements-engine.txt"

# CFBundleVersion: BUILD_NUMBER from the environment, else the commit count, else 1
BUILD_NUMBER="${BUILD_NUMBER:-$(git -C "$ROOT" rev-list --count HEAD 2>/dev/null || echo 1)}"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleDisplayName</key><string>$APP_NAME</string>
  <key>CFBundleIdentifier</key><string>io.github.mrx7999.aimusicstudio</string>
  <key>CFBundleExecutable</key><string>$EXE</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$BUILD_NUMBER</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundleDevelopmentRegion</key><string>en</string>
  <key>CFBundleLocalizations</key><array><string>en</string><string>ru</string></array>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.music</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>NSSupportsAutomaticGraphicsSwitching</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>AI Music Studio records live vocals and instruments into your session. / Запись живого вокала и инструментов в сессию.</string>
  <key>NSHumanReadableCopyright</key><string>MIT License, github.com/MRX7999/AI-Music-Studio</string>
</dict>
</plist>
PLIST
printf 'APPL????' > "$APP/Contents/PkgInfo"

echo "==> ad-hoc signature"
xattr -cr "$APP" 2>/dev/null || true      # extended attributes from copied files break the signature
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

echo "==> zip"
# no resource forks or extended attributes (no __MACOSX folder); the signature does not need them
( cd "$OUT" && ditto -c -k --norsrc --noextattr --keepParent "$APP_NAME.app" "$ZIP" )
( cd "$OUT" && shasum -a 256 "$(basename "$ZIP")" | tee "$(basename "$ZIP").sha256" )
echo "done: $APP"

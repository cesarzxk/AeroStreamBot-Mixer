#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

PACKAGE_NAME="aerostream-mixer"
VERSION="1.0.4"
ARCH="amd64"
BUILD_DIR="$PROJECT_DIR/build-deb"
ROOT="$BUILD_DIR/${PACKAGE_NAME}_${VERSION}_${ARCH}"
OPT_DIR="$ROOT/opt/$PACKAGE_NAME"

if [[ ! -x .venv/bin/python ]]; then
    echo "Erro: execute ./install-dependencies.sh primeiro." >&2
    exit 1
fi

.venv/bin/python -m pip install pyinstaller
rm -rf "$ROOT" "$BUILD_DIR/pyinstaller"
mkdir -p "$OPT_DIR" "$ROOT/usr/bin" "$ROOT/usr/share/applications" "$ROOT/usr/share/icons/hicolor/256x256/apps" "$BUILD_DIR/pyinstaller"

.venv/bin/pyinstaller --noconfirm --clean --onedir \
    --name stream-audio-mixer \
    --distpath "$BUILD_DIR/pyinstaller/dist" \
    --workpath "$BUILD_DIR/pyinstaller/work-mixer" \
    --specpath "$BUILD_DIR/pyinstaller" \
    --hidden-import=PyQt5.sip \
    stream-audio-mixer.py

.venv/bin/pyinstaller --noconfirm --clean --onedir \
    --name discord_bot_runner \
    --distpath "$BUILD_DIR/pyinstaller/dist" \
    --workpath "$BUILD_DIR/pyinstaller/work-bot" \
    --specpath "$BUILD_DIR/pyinstaller" \
    --hidden-import=davey \
    --hidden-import=nacl \
    --hidden-import=nacl.secret \
    --hidden-import=nacl.utils \
    --hidden-import=cffi \
    --hidden-import=_cffi_backend \
    --collect-submodules=nacl \
    --collect-binaries=nacl \
    --collect-data=nacl \
    --collect-binaries=cffi \
    --collect-data=cffi \
    discord_bot_runner.py

cp -a "$BUILD_DIR/pyinstaller/dist/stream-audio-mixer/." "$OPT_DIR/"
cp -a "$BUILD_DIR/pyinstaller/dist/discord_bot_runner/." "$OPT_DIR/"

if command -v ffmpeg >/dev/null 2>&1; then
    cp "$(command -v ffmpeg)" "$OPT_DIR/ffmpeg"
fi

if command -v pactl >/dev/null 2>&1; then
    cp "$(command -v pactl)" "$OPT_DIR/pactl"
fi

cat > "$ROOT/usr/bin/aerostream-mixer" <<EOF
#!/usr/bin/env bash
export PATH="/opt/$PACKAGE_NAME:\$PATH"
exec /opt/$PACKAGE_NAME/stream-audio-mixer "\$@"
EOF
chmod 755 "$ROOT/usr/bin/aerostream-mixer"

cp assets/screenshot.png "$ROOT/usr/share/icons/hicolor/256x256/apps/aerostream-mixer.png"
cat > "$ROOT/usr/share/applications/aerostream-mixer.desktop" <<EOF
[Desktop Entry]
Name=AeroStream Mixer
Comment=PipeWire desktop audio mixer with Discord bot
Exec=aerostream-mixer
Icon=aerostream-mixer
Type=Application
Categories=AudioVideo;Audio;Mixer;
Terminal=false
EOF

mkdir -p "$ROOT/DEBIAN"
cat > "$ROOT/DEBIAN/control" <<EOF
Package: $PACKAGE_NAME
Version: $VERSION
Section: sound
Priority: optional
Architecture: $ARCH
Maintainer: AeroStream Mixer
Depends: ffmpeg, pulseaudio-utils, pipewire, pipewire-pulse, libglib2.0-0, libx11-6, libxcb1
Description: PipeWire audio mixer with Discord voice bot
 Routes desktop audio or microphone input and can transmit stream-mix.monitor
 to a Discord voice channel.
EOF

cat > "$ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
chmod 755 /opt/aerostream-mixer/stream-audio-mixer /opt/aerostream-mixer/discord_bot_runner 2>/dev/null || true
exit 0
EOF
chmod 755 "$ROOT/DEBIAN/postinst"

dpkg-deb --build --root-owner-group "$ROOT" "$PROJECT_DIR/${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"
echo "Deb gerado em: ${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"

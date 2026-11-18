#!/bin/bash
# Build Video-to-SRT per macOS Apple Silicon (arm64) — wrapper di build_mac.py.
# Eseguire da qualsiasi cartella:  bash packaging/macos/apple-silicon/build.sh [opzioni di build_mac.py]
#   opzioni: --no-dmg, --sign "Developer ID Application: …"
#
# Layout: lo script sta in <root>/packaging/macos/apple-silicon/. Il venv (.venv),
# il modello (_build_model/), build/ e dist/ vivono nella root del repository.
# Per preparare tutto da zero (Homebrew, ffmpeg, venv, modello): packaging/macos/install.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MACOS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
VENV="$REPO_ROOT/.venv"
cd "$REPO_ROOT"

echo "=== Build Video-to-SRT Apple Silicon (arm64) ==="

if [ "$(uname -m)" != "arm64" ]; then
    echo "ERRORE: questo Mac non è Apple Silicon. Per Intel usa packaging/macos/intel/build.sh"
    exit 1
fi

if [ ! -f "$VENV/bin/python" ]; then
    echo "ERRORE: .venv non trovato. Esegui prima: packaging/macos/install.sh --run"
    exit 1
fi

if ! "$VENV/bin/python" -c "import PyInstaller" 2>/dev/null; then
    echo "Installo PyInstaller nel venv..."
    "$VENV/bin/pip" install --quiet pyinstaller
fi

"$VENV/bin/python" "$MACOS_DIR/build_mac.py" --clean "$@"

echo ""
echo "=== Build completata ==="
echo "App: $REPO_ROOT/dist/Video-to-SRT.app (Apple Silicon arm64)"

#!/bin/bash
# Build Video-to-SRT per macOS Intel (x86_64) — wrapper di build_mac.py sotto Rosetta.
# Eseguire da qualsiasi cartella:  bash packaging/macos/intel/build.sh [opzioni di build_mac.py]
#
# Layout: lo script sta in <root>/packaging/macos/intel/. Il venv Intel (.venv-intel),
# build/ e dist/ (e _build_model/ per --with-model) vivono nella root del repository;
# l'ffmpeg statico x86_64 va in packaging/macos/intel/bin/ffmpeg.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MACOS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
VENV="$REPO_ROOT/.venv-intel"
cd "$REPO_ROOT"

echo "=== Build Video-to-SRT Intel (x86_64) ==="

# Verifica venv Intel
if [ ! -f "$VENV/bin/python" ]; then
    echo "ERRORE: .venv-intel non trovato. Esegui prima (dalla root del repo):"
    echo "  arch -x86_64 /usr/bin/python3 -m venv .venv-intel"
    echo "  arch -x86_64 .venv-intel/bin/pip install -r app/requirements.txt pyinstaller"
    exit 1
fi

# Verifica ffmpeg x86_64
if [ ! -f "$SCRIPT_DIR/bin/ffmpeg" ]; then
    echo "ERRORE: packaging/macos/intel/bin/ffmpeg non trovato."
    echo "Scarica ffmpeg x86_64 statico da https://evermeet.cx/ffmpeg/ e mettilo in packaging/macos/intel/bin/ffmpeg"
    exit 1
fi

# build_mac.py rileva x86_64 da platform.machine() e usa bin/ffmpeg; --clean pulisce build/ e dist/
echo "Avvio PyInstaller..."
arch -x86_64 "$VENV/bin/python" "$MACOS_DIR/build_mac.py" --clean "$@"

echo ""
echo "=== Build completata ==="
echo "App: $REPO_ROOT/dist/Video-to-SRT.app (Intel x86_64)"
file "$REPO_ROOT/dist/Video-to-SRT.app/Contents/MacOS/Video-to-SRT"

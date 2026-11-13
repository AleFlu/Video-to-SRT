#!/bin/bash
# Build Video-to-SRT per macOS Intel (x86_64) — wrapper di build_mac.py sotto Rosetta.
# Eseguire da qualsiasi cartella:  bash packaging/macos/build_intel.sh [opzioni di build_mac.py]
#
# Layout: lo script sta in <root>/packaging/macos/. Il venv Intel (.venv-intel),
# il modello (_build_model/), build/ e dist/ vivono nella root del repository;
# l'ffmpeg statico x86_64 va in packaging/macos/bin/ffmpeg.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
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
    echo "ERRORE: packaging/macos/bin/ffmpeg non trovato."
    echo "Scarica ffmpeg x86_64 statico da https://evermeet.cx/ffmpeg/ e mettilo in packaging/macos/bin/ffmpeg"
    exit 1
fi

# Verifica modello whisper (cache HuggingFace oppure _build_model/ nella root)
MODEL_PATH="$HOME/.cache/huggingface/hub/models--Systran--faster-whisper-large-v3"
if [ ! -d "$MODEL_PATH" ] && [ -z "$(ls -A "$REPO_ROOT/_build_model" 2>/dev/null)" ]; then
    echo "ERRORE: modello Whisper large-v3 non trovato né in $MODEL_PATH né in $REPO_ROOT/_build_model"
    exit 1
fi

# build_mac.py rileva x86_64 da platform.machine() e usa bin/ffmpeg; --clean pulisce build/ e dist/
echo "Avvio PyInstaller..."
arch -x86_64 "$VENV/bin/python" "$SCRIPT_DIR/build_mac.py" --clean "$@"

echo ""
echo "=== Build completata ==="
echo "App: $REPO_ROOT/dist/Video-to-SRT.app"
file "$REPO_ROOT/dist/Video-to-SRT.app/Contents/MacOS/Video-to-SRT"

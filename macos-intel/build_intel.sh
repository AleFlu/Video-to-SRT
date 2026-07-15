#!/bin/bash
# Build Video-to-SRT per macOS Intel (x86_64)
# Eseguire con: bash build_intel.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Build Video-to-SRT Intel (x86_64) ==="

# Verifica venv_intel
if [ ! -f "venv_intel/bin/python" ]; then
    echo "ERRORE: venv_intel non trovato. Esegui prima:"
    echo "  arch -x86_64 /usr/bin/python3 -m venv venv_intel"
    echo "  arch -x86_64 venv_intel/bin/pip install PySide6 faster-whisper onnxruntime soundfile numpy pyobjc-framework-Cocoa pyinstaller"
    exit 1
fi

# Verifica ffmpeg x86_64
if [ ! -f "bin/ffmpeg" ]; then
    echo "ERRORE: bin/ffmpeg non trovato."
    echo "Scarica ffmpeg x86_64 statico da https://evermeet.cx/ffmpeg/ e mettilo in bin/ffmpeg"
    exit 1
fi

# Verifica modello whisper
MODEL_PATH="/Users/$USER/.cache/huggingface/hub/models--Systran--faster-whisper-large-v3"
if [ ! -d "$MODEL_PATH" ]; then
    echo "ERRORE: modello Whisper large-v3 non trovato in $MODEL_PATH"
    exit 1
fi

# Pulisci build precedenti
rm -rf build dist

# Build
echo "Avvio PyInstaller..."
arch -x86_64 venv_intel/bin/pyinstaller Video-to-SRT-intel.spec

echo ""
echo "=== Build completata ==="
echo "App: dist/Video-to-SRT.app"
file dist/Video-to-SRT.app/Contents/MacOS/Video-to-SRT

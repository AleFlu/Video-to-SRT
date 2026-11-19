#!/bin/bash
# ============================================================
# 🍎 Setup — Video → SRT v2 (macOS, PySide6)
# ============================================================
# Uso:
#   chmod +x packaging/macos/setup_mac.sh
#   packaging/macos/setup_mac.sh
# ============================================================

set -e

echo "=================================================="
echo "🍎 Setup Video → SRT v2 per macOS (PySide6)"
echo "=================================================="

# --- 1. Homebrew ---
echo ""
echo "📦 [1/5] Verifica Homebrew..."
if ! command -v brew &> /dev/null; then
  echo "   Installazione Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [[ "$(uname -m)" == "arm64" ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  else
    eval "$(/usr/local/bin/brew shellenv)"
  fi
else
  echo "   ✅ Homebrew presente"
fi

# --- 2. FFmpeg ---
echo ""
echo "🎬 [2/5] Verifica FFmpeg..."
if ! command -v ffmpeg &> /dev/null; then
  brew install ffmpeg
else
  echo "   ✅ FFmpeg presente"
fi

# --- 3. Python 3.10+ ---
echo ""
echo "🐍 [3/5] Verifica Python..."
if ! command -v python3 &> /dev/null; then
  brew install python@3.11
fi
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
if [ "$PY_MINOR" -lt 10 ]; then
  brew install python@3.11
fi
python3 --version

# --- 4. Venv + dipendenze ---
echo ""
echo "📥 [4/5] Ambiente virtuale..."
# Layout: questo script sta in <root>/packaging/macos/; il venv va in <root>/.venv
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_DIR="$REPO_ROOT/.venv"

if [ -d "$VENV_DIR" ]; then
  rm -rf "$VENV_DIR"
fi
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

pip install --upgrade pip --quiet
echo "   📦 PySide6 (Qt for Python)..."
pip install PySide6 --quiet
echo "   📦 faster-whisper..."
pip install faster-whisper --quiet
echo "   📦 onnxruntime (VAD)..."
pip install onnxruntime --quiet
echo "   📦 PyInstaller..."
pip install pyinstaller --quiet

# --- 5. Modello ---
echo ""
echo "🧠 [5/5] Modello Whisper: lo propone e lo scarica l'app alla prima trascrizione."

echo ""
echo "=================================================="
echo "✅ Setup completato!"
echo "=================================================="
echo ""
echo "Per avviare l'app:"
echo "  source .venv/bin/activate   # dalla root del repo"
echo "  python app/main.py"
echo ""

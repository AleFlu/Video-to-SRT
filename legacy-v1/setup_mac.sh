#!/bin/bash
# ============================================================
# 🍎 Setup — Video → SRT (macOS / Apple Silicon + Intel)
# ============================================================
# Stack: faster-whisper + large-v3 + customtkinter
#
# Utilizzo:
#   chmod +x setup_mac.sh
#   ./setup_mac.sh
# ============================================================

set -e

echo "=================================================="
echo "🍎 Setup Video → SRT per macOS"
echo "   Stack: faster-whisper + large-v3 + customtkinter"
echo "=================================================="
echo ""

# ----------------------------------------------------------
# 0. Disattiva Conda se attivo (evita conflitti)
# ----------------------------------------------------------
if [ -n "$CONDA_DEFAULT_ENV" ]; then
  echo "⚠️  Conda rilevato (ambiente: $CONDA_DEFAULT_ENV)"
  echo "   Disattivo Conda per evitare conflitti..."
  # Disattiva tutti gli ambienti conda attivi
  while [ -n "$CONDA_DEFAULT_ENV" ] && [ "$CONDA_DEFAULT_ENV" != "" ]; do
    conda deactivate 2>/dev/null || break
  done
  echo "   ✅ Conda disattivato"
  echo ""
fi

# Rimuovi conda dal PATH temporaneamente per questa sessione
# così python3 punta a Homebrew, non a conda
export PATH=$(echo "$PATH" | tr ':' '\n' | grep -v -i conda | tr '\n' ':' | sed 's/:$//')

# ----------------------------------------------------------
# 1. Homebrew
# ----------------------------------------------------------
echo "📦 [1/7] Verifica Homebrew..."
if ! command -v brew &> /dev/null; then
  echo "   Installazione Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

  if [[ "$(uname -m)" == "arm64" ]]; then
    echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
    eval "$(/opt/homebrew/bin/brew shellenv)"
  else
    echo 'eval "$(/usr/local/bin/brew shellenv)"' >> ~/.zprofile
    eval "$(/usr/local/bin/brew shellenv)"
  fi
else
  echo "   ✅ Homebrew presente"
fi

# Assicura che brew sia nel PATH
if ! command -v brew &> /dev/null; then
  if [[ -x "/opt/homebrew/bin/brew" ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x "/usr/local/bin/brew" ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
fi

# ----------------------------------------------------------
# 2. FFmpeg
# ----------------------------------------------------------
echo ""
echo "🎬 [2/7] Verifica FFmpeg..."
if ! command -v ffmpeg &> /dev/null; then
  echo "   Installazione FFmpeg..."
  brew install ffmpeg
else
  echo "   ✅ FFmpeg presente"
fi

# ----------------------------------------------------------
# 3. Python 3.11 + Tcl/Tk (CRUCIALE: python-tk è separato!)
# ----------------------------------------------------------
echo ""
echo "🐍 [3/7] Installazione Python 3.11 + Tcl/Tk..."

# Installa python@3.11 se non presente
if ! brew list python@3.11 &>/dev/null; then
  echo "   Installazione python@3.11..."
  brew install python@3.11
else
  echo "   ✅ python@3.11 presente"
fi

# CRUCIALE: python-tk è un pacchetto SEPARATO in Homebrew!
# Senza questo, "import tkinter" fallisce con:
#   "your Python may not be configured for Tk"
if ! brew list python-tk@3.11 &>/dev/null; then
  echo "   Installazione python-tk@3.11 (necessario per GUI)..."
  brew install python-tk@3.11
else
  echo "   ✅ python-tk@3.11 presente"
fi

# Determina il path esatto del Python Homebrew
# (NON usare il python di Conda!)
if [[ "$(uname -m)" == "arm64" ]]; then
  BREW_PYTHON="/opt/homebrew/bin/python3.11"
else
  BREW_PYTHON="/usr/local/bin/python3.11"
fi

if [ ! -x "$BREW_PYTHON" ]; then
  # Fallback: cerca con brew
  BREW_PYTHON="$(brew --prefix python@3.11)/bin/python3.11"
fi

if [ ! -x "$BREW_PYTHON" ]; then
  echo "   ❌ Python 3.11 non trovato dopo l'installazione!"
  echo "   Prova: brew reinstall python@3.11 python-tk@3.11"
  exit 1
fi

echo "   ✅ Python: $BREW_PYTHON"
echo "   Versione: $($BREW_PYTHON --version)"

# Verifica che tkinter funzioni PRIMA di continuare
echo "   Verifica tkinter..."
if $BREW_PYTHON -c "import tkinter; print('   ✅ tkinter funziona')" 2>/dev/null; then
  :
else
  echo "   ❌ tkinter non funziona con $BREW_PYTHON"
  echo ""
  echo "   Prova queste soluzioni:"
  echo "     1. brew reinstall python-tk@3.11"
  echo "     2. brew reinstall python@3.11 python-tk@3.11"
  echo "     3. brew uninstall python@3.11 python-tk@3.11 && brew install python@3.11 python-tk@3.11"
  echo ""
  exit 1
fi

# ----------------------------------------------------------
# 4. Venv + dipendenze
# ----------------------------------------------------------
echo ""
echo "📥 [4/7] Ambiente virtuale e dipendenze..."

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

# Ricrea la venv da zero con il Python Homebrew (non conda!)
if [ -d "$VENV_DIR" ]; then
  echo "   Ricreo ambiente virtuale (pulizia)..."
  rm -rf "$VENV_DIR"
fi

echo "   Creo venv con: $BREW_PYTHON"
$BREW_PYTHON -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

# Verifica che dentro la venv tkinter funzioni
python3 -c "import tkinter" 2>/dev/null || {
  echo "   ❌ tkinter non funziona nella venv!"
  echo "   Questo può succedere se python-tk@3.11 è stato installato DOPO python@3.11"
  echo "   Prova: brew reinstall python@3.11 python-tk@3.11"
  exit 1
}
echo "   ✅ tkinter funziona nella venv"

pip install --upgrade pip --quiet

echo "   📦 faster-whisper (include CTranslate2)..."
pip install faster-whisper --quiet

echo "   📦 onnxruntime (per filtro VAD Silero)..."
pip install onnxruntime --quiet

echo "   📦 whisperx (alta precisione — allineamento fonetico)..."
pip install whisperx --quiet 2>/dev/null && {
  echo "   ✅ whisperx installato (modalità alta precisione disponibile)"
} || {
  echo "   ⚠️ whisperx non installato (funziona comunque con faster-whisper)"
}

# ----------------------------------------------------------
# 5. GUI: customtkinter + drag & drop
# ----------------------------------------------------------
echo ""
echo "🎨 [5/7] Installazione GUI (customtkinter + drag & drop)..."
pip install customtkinter --quiet
pip install tkinterdnd2 --quiet

echo "   📦 PyInstaller (per build .app)..."
pip install pyinstaller --quiet

# ----------------------------------------------------------
# 6. Download modello large-v3
# ----------------------------------------------------------
echo ""
echo "🧠 [6/7] Download modello large-v3 (~1.5 GB, solo prima volta)..."
echo "   Questo è il modello con la massima qualità per l'italiano."

python3 -c "
from faster_whisper import WhisperModel
print('   Scaricamento e conversione in corso...')
model = WhisperModel('large-v3', device='cpu', compute_type='int8')
del model
print('   ✅ Modello large-v3 pronto')
"

# Pre-download modello Silero VAD
echo "   Verifica modello VAD (Silero)..."
python3 -c "
try:
    from faster_whisper import WhisperModel
    model = WhisperModel('large-v3', device='cpu', compute_type='int8')
    from faster_whisper.vad import get_vad_model
    get_vad_model()
    print('   ✅ Modello VAD (Silero) pronto')
    del model
except Exception as e:
    print(f'   ⚠️ VAD non disponibile: {e}')
    print('   (la trascrizione funzionerà comunque, senza filtro silenzi)')
"

# ----------------------------------------------------------
# 7. Verifica finale
# ----------------------------------------------------------
echo ""
echo "🔍 [7/7] Verifica finale..."

python3 -c "
import faster_whisper
import ctranslate2
import customtkinter
import tkinter
import sys
import platform

print(f'   Python: {sys.version.split()[0]}')
print(f'   Python path: {sys.executable}')
print(f'   Arch: {platform.machine()}')
print(f'   CTranslate2: {ctranslate2.__version__}')
print(f'   customtkinter: {customtkinter.__version__}')
print(f'   tkinter: ✅ funzionante')
print(f'   faster-whisper: installato')

try:
    import tkinterdnd2
    print(f'   Drag & Drop: ✅ disponibile')
except ImportError:
    print(f'   Drag & Drop: ⚠️ non disponibile (fallback a file dialog)')

try:
    import whisperx
    print(f'   WhisperX: ✅ alta precisione disponibile')
except ImportError:
    print(f'   WhisperX: ⚠️ non disponibile (usa faster-whisper standard)')

from faster_whisper import WhisperModel
model = WhisperModel('large-v3', device='cpu', compute_type='int8')
del model
print('   Modello: ✅ large-v3 pronto')
"

echo ""
echo "=================================================="
echo "✅ Setup completato!"
echo "=================================================="
echo ""
echo "⚠️  IMPORTANTE: Se usi Conda, disattivalo prima di lanciare l'app:"
echo "     conda deactivate"
echo ""
echo "Comandi disponibili:"
echo ""
echo "  source venv/bin/activate"
echo ""
echo "  # GUI (con drag & drop)"
echo "  python app.py"
echo ""
echo "  # CLI (massima qualità)"
echo "  python transcribe.py video.mp4"
echo ""
echo "  # Crea .app bundle"
echo "  python build_mac.py"
echo ""
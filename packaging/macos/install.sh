#!/usr/bin/env bash
# =============================================================================
#  install.sh — Installer professionale per Video → SRT v2
#  Scarica dipendenze, prepara il modello e costruisce il file .app / .dmg.
#
#  Uso rapido:
#      chmod +x install.sh
#      ./install.sh          # setup completo + build .app
#      ./install.sh --run    # setup + avvia in modalità sviluppo (no .app)
#      ./install.sh --dmg    # setup + build .app + .dmg distribuibile
#      ./install.sh --help   # mostra questa guida
#
#  Richiede: macOS 12+, Python 3.10+, Homebrew
# =============================================================================

set -euo pipefail

# ── Colori ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}✅  $*${RESET}"; }
warn() { echo -e "${YELLOW}⚠️   $*${RESET}"; }
err()  { echo -e "${RED}❌  $*${RESET}"; exit 1; }
step() { echo -e "\n${BLUE}${BOLD}▶ $*${RESET}"; }
info() { echo -e "   $*"; }

# ── Costanti ─────────────────────────────────────────────────────────────────
# Layout: questo script sta in <root>/packaging/macos/; l'app in <root>/app/.
# venv (.venv), modello (_build_model/), build/ e dist/ vivono nella root del repo.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
APP_DIR="$REPO_ROOT/app"
VENV_DIR="$REPO_ROOT/.venv"
MODEL_DIR="$REPO_ROOT/_build_model"
APP_NAME="Video-to-SRT"
PYTHON_MIN="3.10"
MODEL_SIZE="large-v3"

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║          Video → SRT v2  •  Installer macOS             ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${RESET}"
echo ""

# ── Argomenti ─────────────────────────────────────────────────────────────────
BUILD_APP=false
BUILD_DMG=false
RUN_DEV=false

for arg in "$@"; do
    case $arg in
        --dmg)    BUILD_DMG=true; BUILD_APP=true ;;
        --app)    BUILD_APP=true ;;
        --run)    RUN_DEV=true ;;
        --help|-h)
            echo "Uso: ./install.sh [--run] [--app] [--dmg] [--help]"
            echo ""
            echo "  (nessun flag)   Setup venv + dipendenze + modello"
            echo "  --run           Setup + avvia l'app in modalità sviluppo"
            echo "  --app           Setup + costruisci Video-to-SRT.app"
            echo "  --dmg           Setup + costruisci .app + .dmg distribuibile"
            echo "  --help          Mostra questo messaggio"
            exit 0
            ;;
        *) warn "Flag sconosciuto: $arg (ignorato)" ;;
    esac
done

# ── 1. Verifica macOS ─────────────────────────────────────────────────────────
step "Verifica sistema operativo"
if [[ "$(uname)" != "Darwin" ]]; then
    err "Questo script è solo per macOS."
fi
MACOS_VER="$(sw_vers -productVersion)"
ok "macOS $MACOS_VER"

# ── 2. Verifica Python ────────────────────────────────────────────────────────
step "Verifica Python $PYTHON_MIN+"

PYTHON=""
for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" &>/dev/null; then
        VER="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
        if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    err "Python $PYTHON_MIN+ non trovato.\nInstalla con: brew install python@3.12"
fi
ok "Python $("$PYTHON" --version)"

# ── 3. Verifica / installa Homebrew ──────────────────────────────────────────
step "Verifica Homebrew"
if ! command -v brew &>/dev/null; then
    warn "Homebrew non trovato. Installazione in corso…"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Aggiunge brew al PATH per questa sessione (Apple Silicon)
    eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null || true
fi
ok "Homebrew $(brew --version | head -1)"

# ── 4. Verifica / installa FFmpeg ─────────────────────────────────────────────
step "Verifica FFmpeg"
if ! command -v ffmpeg &>/dev/null; then
    warn "FFmpeg non trovato — installazione con Homebrew…"
    brew install ffmpeg
fi
ok "FFmpeg $(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')"

# ── 5. Ambiente virtuale ──────────────────────────────────────────────────────
step "Configurazione ambiente virtuale Python"
if [[ ! -d "$VENV_DIR" ]]; then
    info "Creazione venv in $VENV_DIR …"
    "$PYTHON" -m venv "$VENV_DIR"
fi
# Attiva venv
source "$VENV_DIR/bin/activate"
ok "venv attivato: $VENV_DIR"

# ── 6. Dipendenze Python ──────────────────────────────────────────────────────
step "Installazione dipendenze Python"
pip install --quiet --upgrade pip wheel setuptools

REQUIREMENTS="$APP_DIR/requirements.txt"
if [[ -f "$REQUIREMENTS" ]]; then
    pip install --quiet -r "$REQUIREMENTS"
    ok "Dipendenze installate da requirements.txt"
else
    warn "requirements.txt non trovato — installazione manuale delle dipendenze core"
    pip install --quiet \
        "PySide6>=6.6" \
        "faster-whisper>=1.0" \
        "onnxruntime>=1.17" \
        "soundfile>=0.12" \
        "numpy>=1.24"
fi

# ── 7. Modello Whisper ────────────────────────────────────────────────────────
step "Verifica modello Whisper ($MODEL_SIZE)"

if [[ -d "$MODEL_DIR" ]] && [[ -n "$(ls -A "$MODEL_DIR" 2>/dev/null)" ]]; then
    ok "Modello trovato in $MODEL_DIR"
else
    info "Modello non trovato — download in corso (≈ 3 GB, potrebbe richiedere diversi minuti)…"
    mkdir -p "$MODEL_DIR"
    python3 - "$MODEL_DIR" <<'PYEOF'
import sys
from pathlib import Path
model_dir = Path(sys.argv[1])

try:
    from faster_whisper import WhisperModel
    print(f"   Download modello large-v3 in {model_dir} ...")
    WhisperModel("large-v3", device="cpu", download_root=str(model_dir))
    print("   Download completato.")
except Exception as e:
    print(f"   Errore durante il download: {e}")
    print("   Puoi scaricare il modello manualmente più tardi.")
    sys.exit(0)
PYEOF
    if [[ -n "$(ls -A "$MODEL_DIR" 2>/dev/null)" ]]; then
        ok "Modello scaricato in $MODEL_DIR"
    else
        warn "Download modello fallito — l'app funzionerà ma non potrà trascrivere."
    fi
fi

# ── 8. Test rapido ────────────────────────────────────────────────────────────
step "Verifica importazioni Python"
python3 -c "
import PySide6
import faster_whisper
try:
    import soundfile
    print('   soundfile: OK')
except ImportError:
    print('   soundfile: non disponibile (waveform disabilitata)')
print('   PySide6:', PySide6.__version__)
print('   All good.')
" || warn "Alcune importazioni hanno fallito — controlla i log sopra."
ok "Importazioni verificate"

# ── 9. Modalità build / run ───────────────────────────────────────────────────

if $RUN_DEV; then
    step "Avvio in modalità sviluppo"
    ok "Avvio Video → SRT..."
    cd "$REPO_ROOT"
    exec python "$APP_DIR/main.py"
fi

if $BUILD_APP; then
    step "Build applicazione (.app)"

    # PyInstaller richiesto
    pip install --quiet pyinstaller

    if $BUILD_DMG; then
        info "Creazione .dmg richiesta."
        if ! command -v create-dmg &>/dev/null; then
            warn "create-dmg non trovato — installazione con Homebrew…"
            brew install create-dmg
        fi
        python "$SCRIPT_DIR/build_mac.py" --clean
    else
        python "$SCRIPT_DIR/build_mac.py" --clean --no-dmg
    fi

    APP_PATH="$REPO_ROOT/dist/$APP_NAME.app"
    if [[ -d "$APP_PATH" ]]; then
        echo ""
        ok "Build completata!"
        info "App:  $APP_PATH"
        if $BUILD_DMG; then
            DMG_PATH="$(ls "$REPO_ROOT/dist/"*.dmg 2>/dev/null | head -1)"
            [[ -n "$DMG_PATH" ]] && info "DMG:  $DMG_PATH"
        fi
        echo ""
        info "Per installare: trascina $APP_NAME.app nella cartella Applicazioni."
        info "Oppure: open \"$APP_PATH\""
    else
        err "Build fallita — il file .app non è stato creato."
    fi
else
    # Solo setup, nessun build
    echo ""
    echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════════${RESET}"
    echo -e "${GREEN}${BOLD}  Setup completato con successo!${RESET}"
    echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════════${RESET}"
    echo ""
    info "Per avviare l'app in modalità sviluppo:"
    info "  source .venv/bin/activate && python app/main.py"
    echo ""
    info "Per costruire il file .app distribuibile:"
    info "  packaging/macos/install.sh --app"
    echo ""
    info "Per costruire .app + .dmg:"
    info "  packaging/macos/install.sh --dmg"
    echo ""
fi

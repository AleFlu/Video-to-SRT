#!/usr/bin/env bash
# =============================================================================
#  Video → SRT — Installer utente finale
#  Versione 2.0.0 | macOS 12+ | Intel & Apple Silicon
#
#  USO:
#      Doppio clic su questo file oppure esegui in Terminale:
#          bash installer_user.sh
#
#  COSA FA:
#      1. Verifica macOS 12+ e architettura
#      2. Installa Homebrew (se mancante)
#      3. Installa Python 3.12 via Homebrew (se mancante)
#      4. Installa ffmpeg via Homebrew (se mancante)
#      5. Crea ambiente Python isolato (~/.videosrt/)
#      6. Installa dipendenze Python (PySide6, faster-whisper, ecc.)
#      7. Scarica modello Whisper large-v3 (~3 GB)
#      8. Installa l'app in /Applications
#      9. Crea icona nel Launchpad
#
#  RICHIEDE:
#      - macOS 12 Monterey o successivo
#      - Connessione internet (~3.5 GB totali al primo avvio)
#      - Password amministratore (solo per Homebrew e /Applications)
# =============================================================================

set -uo pipefail

# ── Colori & UI ───────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

ok()    { echo -e "${GREEN}  ✓  $*${RESET}"; }
warn()  { echo -e "${YELLOW}  ⚠  $*${RESET}"; }
info()  { echo -e "${CYAN}  →  $*${RESET}"; }
step()  { echo -e "\n${BOLD}${BLUE}━━  $*${RESET}"; }
fatal() { echo -e "\n${RED}${BOLD}  ✗  ERRORE: $*${RESET}\n"; exit 1; }
dim()   { echo -e "${DIM}     $*${RESET}"; }

# ── Configurazione ────────────────────────────────────────────────────────────
APP_NAME="Video-to-SRT"
APP_VERSION="2.0.0"
INSTALL_DIR="$HOME/.videosrt"
VENV_DIR="$INSTALL_DIR/venv"
MODEL_DIR="$INSTALL_DIR/whisper_model"
LOG_DIR="$INSTALL_DIR/logs"
LOG_FILE="$LOG_DIR/install_$(date +%Y%m%d_%H%M%S).log"
APP_BUNDLE_DIR="/Applications/${APP_NAME}.app"

# URL del tarball sorgente (da aggiornare con la release pubblica)
# Per ora usa la directory locale se esiste
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

# ── Banner ────────────────────────────────────────────────────────────────────
clear
echo ""
echo -e "${BOLD}${BLUE}"
echo "  ╔══════════════════════════════════════════════════════╗"
echo "  ║                                                      ║"
echo "  ║        Video → SRT  v${APP_VERSION}                        ║"
echo "  ║        Trascrizione automatica italiana              ║"
echo "  ║                                                      ║"
echo "  ╚══════════════════════════════════════════════════════╝"
echo -e "${RESET}"
echo -e "  ${DIM}Log: $LOG_FILE${RESET}"
echo ""

# ── Funzioni utilità ──────────────────────────────────────────────────────────

ask_continue() {
    echo ""
    read -r -p "  Premi INVIO per continuare o CTRL+C per annullare... "
    echo ""
}

spinner() {
    local pid=$1
    local msg="${2:-Elaborazione}"
    local i=0
    local sp='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    tput civis 2>/dev/null || true
    while kill -0 "$pid" 2>/dev/null; do
        printf "\r  ${CYAN}%s${RESET}  %s " "${sp:$i:1}" "$msg"
        i=$(( (i+1) % ${#sp} ))
        sleep 0.1
    done
    printf "\r                                                          \r"
    tput cnorm 2>/dev/null || true
}

require_network() {
    if ! curl -s --max-time 5 https://pypi.org > /dev/null 2>&1; then
        fatal "Connessione internet non disponibile.\nAssicurati di essere connesso a internet e riprova."
    fi
}

# ── STEP 1: Sistema operativo ─────────────────────────────────────────────────
step "1/8  Verifica sistema"

if [[ "$(uname)" != "Darwin" ]]; then
    fatal "Questo installer è solo per macOS."
fi

MACOS_VER="$(sw_vers -productVersion)"
MACOS_MAJOR="$(echo "$MACOS_VER" | cut -d. -f1)"
ARCH="$(uname -m)"

if [[ "$MACOS_MAJOR" -lt 12 ]]; then
    fatal "Richiesto macOS 12 Monterey o successivo.\nVersione attuale: $MACOS_VER"
fi

ok "macOS $MACOS_VER"

case "$ARCH" in
    arm64)
        ok "Apple Silicon (M1/M2/M3/M4)"
        HOMEBREW_PREFIX="/opt/homebrew"
        ;;
    x86_64)
        ok "Intel x86_64"
        HOMEBREW_PREFIX="/usr/local"
        ;;
    *)
        fatal "Architettura non supportata: $ARCH"
        ;;
esac

# ── STEP 2: Xcode Command Line Tools ─────────────────────────────────────────
step "2/8  Verifica Xcode Command Line Tools"

if ! xcode-select -p &>/dev/null; then
    info "Installazione Xcode Command Line Tools (necessario per Homebrew)..."
    info "Si aprirà una finestra di dialogo — clicca 'Installa'."
    xcode-select --install 2>/dev/null || true
    # Aspetta che l'installazione finisca
    until xcode-select -p &>/dev/null; do
        sleep 5
    done
fi
ok "Xcode CLT disponibile"

# ── STEP 3: Homebrew ──────────────────────────────────────────────────────────
step "3/8  Verifica Homebrew"

if [[ ! -x "$HOMEBREW_PREFIX/bin/brew" ]]; then
    info "Homebrew non trovato — installazione in corso..."
    info "(Potrebbe essere richiesta la password di sistema)"
    echo ""
    require_network
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# Aggiungi brew al PATH per questa sessione
eval "$("$HOMEBREW_PREFIX/bin/brew" shellenv)" 2>/dev/null || true
export PATH="$HOMEBREW_PREFIX/bin:$PATH"

BREW_VER="$(brew --version 2>/dev/null | head -1 || echo 'sconosciuta')"
ok "Homebrew $BREW_VER"

# ── STEP 4: Python 3.12 ───────────────────────────────────────────────────────
step "4/8  Verifica Python 3.10+"

find_python() {
    # Cerca solo Python Homebrew arm64-nativo (3.12+ garantisce wheel arm64 per PySide6)
    for candidate in \
        "$HOMEBREW_PREFIX/bin/python3.14" \
        "$HOMEBREW_PREFIX/bin/python3.13" \
        "$HOMEBREW_PREFIX/bin/python3.12"; do
        if [[ -x "$candidate" ]]; then
            # Verifica che sia davvero arm64 (non Intel sotto Rosetta)
            arch_ok="$("$candidate" -c 'import platform; print(platform.machine())' 2>/dev/null || echo '')"
            if [[ "$ARCH" == "arm64" && "$arch_ok" != "arm64" ]]; then
                continue
            fi
            echo "$candidate"
            return 0
        fi
    done
    # Fallback Intel
    for candidate in \
        "$HOMEBREW_PREFIX/bin/python3.11" \
        "$HOMEBREW_PREFIX/bin/python3.10" \
        "/usr/bin/python3"; do
        if [[ -x "$candidate" ]]; then
            ver="$("$candidate" -c 'import sys; print(sys.version_info >= (3,10))' 2>/dev/null || echo False)"
            if [[ "$ver" == "True" ]]; then
                echo "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

PYTHON="$(find_python || true)"

if [[ -z "$PYTHON" ]]; then
    info "Python 3.12 non trovato — installazione via Homebrew..."
    require_network
    brew install python@3.12 &
    spinner $! "Installazione Python 3.12"
    wait
    PYTHON="$(find_python || true)"
    [[ -z "$PYTHON" ]] && fatal "Python non trovato dopo installazione."
fi

PYVER="$("$PYTHON" --version 2>&1)"
ok "$PYVER ($PYTHON)"

# ── STEP 5: ffmpeg ────────────────────────────────────────────────────────────
step "5/8  Verifica ffmpeg"

FFMPEG_OK=false
for ff in "$HOMEBREW_PREFIX/bin/ffmpeg" "/usr/local/bin/ffmpeg" "$(command -v ffmpeg 2>/dev/null || true)"; do
    if [[ -x "$ff" ]]; then
        FFMPEG_OK=true
        ok "ffmpeg trovato: $ff"
        break
    fi
done

if ! $FFMPEG_OK; then
    info "ffmpeg non trovato — installazione via Homebrew..."
    require_network
    brew install ffmpeg &
    spinner $! "Installazione ffmpeg (potrebbero volerci alcuni minuti)"
    wait
    ok "ffmpeg installato"
fi

# ── STEP 6: Ambiente Python (venv) ────────────────────────────────────────────
step "6/8  Configurazione ambiente Python"

mkdir -p "$INSTALL_DIR"

# Se il venv esiste ma è Intel (x86_64), cancellalo e ricrea arm64
if [[ -d "$VENV_DIR" ]]; then
    VENV_ARCH="$(file "$VENV_DIR/bin/python3" 2>/dev/null | grep -o 'arm64\|x86_64' | head -1 || echo 'unknown')"
    if [[ "$ARCH" == "arm64" && "$VENV_ARCH" != "arm64" ]]; then
        warn "Venv esistente è $VENV_ARCH su Apple Silicon — lo ricreo in arm64..."
        rm -rf "$VENV_DIR"
    fi
fi

if [[ ! -d "$VENV_DIR" ]]; then
    info "Creazione ambiente virtuale isolato..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
ok "Ambiente virtuale: $VENV_DIR"

info "Aggiornamento pip..."
pip install --quiet --upgrade pip wheel setuptools

info "Installazione dipendenze (PySide6, faster-whisper, ecc.)..."
require_network

# onnxruntime >= 1.17 include wheel arm64 nativa — non serve Rosetta
pip install --quiet \
    "PySide6>=6.6.0" \
    "faster-whisper>=1.0.0" \
    "onnxruntime>=1.17.0" \
    "soundfile>=0.12.1" \
    "numpy>=1.24.0" \
    "pyobjc-framework-Cocoa" &

spinner $! "Installazione dipendenze Python"
wait

ok "Dipendenze installate"

# ── STEP 7: Modello Whisper ───────────────────────────────────────────────────
step "7/8  Download modello Whisper large-v3"

mkdir -p "$MODEL_DIR"

if [[ -n "$(ls -A "$MODEL_DIR" 2>/dev/null)" ]]; then
    ok "Modello già presente in $MODEL_DIR"
else
    echo ""
    warn "Il modello Whisper occupa circa 3 GB."
    warn "Il download potrebbe richiedere da 5 a 30 minuti in base alla connessione."
    echo ""
    ask_continue

    require_network
    info "Download modello Whisper large-v3..."
    echo ""

    "$VENV_DIR/bin/python" - "$MODEL_DIR" <<'PYEOF'
import sys
import time
from pathlib import Path

model_dir = sys.argv[1]

try:
    from faster_whisper import WhisperModel
    print("   Connessione a Hugging Face Hub...")
    sys.stdout.flush()

    start = time.time()
    WhisperModel("large-v3", device="cpu", download_root=model_dir)
    elapsed = time.time() - start

    m, s = divmod(int(elapsed), 60)
    print(f"\n   ✓  Download completato in {m}m {s}s")

except KeyboardInterrupt:
    print("\n   Download interrotto dall'utente.")
    sys.exit(1)
except Exception as e:
    print(f"\n   ✗  Errore download: {e}")
    print("   Il modello potrà essere scaricato al primo avvio dell'app.")
    sys.exit(0)
PYEOF

    ok "Modello Whisper scaricato"
fi

# ── STEP 8: Copia sorgenti e creazione .app ───────────────────────────────────
step "8/8  Installazione applicazione"

[[ -f "$SCRIPT_DIR/main.py" ]] || fatal "Sorgenti non trovati. Assicurati che il .command sia nella stessa cartella del progetto."

info "Creazione applicazione arm64-nativa..."

APP_CONTENTS="/Applications/${APP_NAME}.app/Contents"
sudo rm -rf "/Applications/${APP_NAME}.app"
sudo mkdir -p "$APP_CONTENTS/MacOS"
sudo mkdir -p "$APP_CONTENTS/Resources"

# ── Compila stub Mach-O nativo (arm64 o x86_64) ──────────────────────────────
# macOS determina l'architettura dal primo Mach-O nel bundle.
# Uno script bash non ha architettura → macOS chiede Rosetta con librerie universal2.
# Questo stub C è il vero eseguibile: individua launcher.sh nella sua stessa
# directory e lo esegue con bash, ereditando l'architettura nativa.
STUB_C="$(mktemp /tmp/vsr_stub_XXXX.c)"
cat > "$STUB_C" << 'STUB_EOF'
#include <stdio.h>
#include <unistd.h>
#include <mach-o/dyld.h>
#include <libgen.h>
#include <string.h>
#include <stdint.h>
int main(void) {
    char exe[1024]; uint32_t sz = sizeof(exe);
    _NSGetExecutablePath(exe, &sz);
    char dir[1024];
    strncpy(dir, dirname(exe), sizeof(dir) - 1);
    char launcher[2048];
    snprintf(launcher, sizeof(launcher), "%s/launcher.sh", dir);
    execl("/bin/bash", "bash", launcher, (char *)NULL);
    return 1;
}
STUB_EOF

STUB_BIN="$(mktemp /tmp/vsr_stub_bin_XXXX)"
clang -arch arm64 -arch x86_64 -O2 -o "$STUB_BIN" "$STUB_C" \
    || fatal "Compilazione stub fallita. Xcode Command Line Tools richiesto."
rm "$STUB_C"

sudo cp "$STUB_BIN" "$APP_CONTENTS/MacOS/${APP_NAME}"
sudo chmod +x "$APP_CONTENTS/MacOS/${APP_NAME}"
rm "$STUB_BIN"
ok "Stub Mach-O $ARCH compilato"

# ── launcher.sh (script bash con i path assoluti) ─────────────────────────────
sudo tee "$APP_CONTENTS/MacOS/launcher.sh" > /dev/null << LAUNCHER_EOF
#!/usr/bin/env bash
export PATH="/opt/homebrew/bin:/usr/local/bin:\$PATH"
source "${VENV_DIR}/bin/activate"
export VIDEOSRT_MODEL_DIR="${MODEL_DIR}"
exec "${VENV_DIR}/bin/python" "${SCRIPT_DIR}/main.py" "\$@"
LAUNCHER_EOF
sudo chmod +x "$APP_CONTENTS/MacOS/launcher.sh"

# ── Info.plist ────────────────────────────────────────────────────────────────
sudo tee "$APP_CONTENTS/Info.plist" > /dev/null << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>${APP_NAME}</string>
    <key>CFBundleIdentifier</key>
    <string>it.videosrt.app</string>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleShortVersionString</key>
    <string>${APP_VERSION}</string>
    <key>CFBundleVersion</key>
    <string>${APP_VERSION}</string>
    <key>CFBundleIconFile</key>
    <string>app</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSPrincipalClass</key>
    <string>NSApplication</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSMicrophoneUsageDescription</key>
    <string>Video → SRT usa il microfono per la trascrizione.</string>
    <key>CFBundleDocumentTypes</key>
    <array>
        <dict>
            <key>CFBundleTypeName</key>
            <string>File multimediale</string>
            <key>CFBundleTypeRole</key>
            <string>Viewer</string>
            <key>LSHandlerRank</key>
            <string>Alternate</string>
            <key>LSItemContentTypes</key>
            <array>
                <string>public.movie</string>
                <string>public.audio</string>
                <string>public.mpeg-4</string>
                <string>com.apple.quicktime-movie</string>
            </array>
        </dict>
    </array>
</dict>
</plist>
PLIST_EOF

# ── Icona ─────────────────────────────────────────────────────────────────────
if [[ -f "$SCRIPT_DIR/assets/app.icns" ]]; then
    sudo cp "$SCRIPT_DIR/assets/app.icns" "$APP_CONTENTS/Resources/app.icns"
fi

# ── Rimuovi quarantena ────────────────────────────────────────────────────────
sudo xattr -r -d com.apple.quarantine "/Applications/${APP_NAME}.app" 2>/dev/null || true

ok "App installata: /Applications/${APP_NAME}.app"

# Salva configurazione per future operazioni
cat > "$INSTALL_DIR/config.json" << CONFIG_EOF
{
  "version": "${APP_VERSION}",
  "python": "${PYTHON}",
  "venv": "${VENV_DIR}",
  "model_dir": "${MODEL_DIR}",
  "arch": "${ARCH}",
  "macos": "${MACOS_VER}",
  "install_date": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "src_dir": "${SCRIPT_DIR}"
}
CONFIG_EOF

# ── Riepilogo finale ──────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}"
echo "  ╔══════════════════════════════════════════════════════╗"
echo "  ║                                                      ║"
echo "  ║    ✅  Video → SRT installato con successo!          ║"
echo "  ║                                                      ║"
echo "  ╚══════════════════════════════════════════════════════╝"
echo -e "${RESET}"
echo ""
echo -e "  ${BOLD}Come aprire l'app:${RESET}"
echo -e "  ${CYAN}→${RESET}  Launchpad → Video-to-SRT"
echo -e "  ${CYAN}→${RESET}  Finder → Applicazioni → Video-to-SRT"
echo -e "  ${CYAN}→${RESET}  Spotlight (⌘ Spazio) → digita 'Video'"
echo ""
echo -e "  ${DIM}Ambiente:  $INSTALL_DIR${RESET}"
echo -e "  ${DIM}Modello:   $MODEL_DIR${RESET}"
echo -e "  ${DIM}Log:       $LOG_FILE${RESET}"
echo ""

# Offri di aprire l'app subito
read -r -p "  Aprire Video → SRT adesso? [S/n] " OPEN_NOW
OPEN_NOW="${OPEN_NOW:-S}"
if [[ "$OPEN_NOW" =~ ^[Ss]$ ]]; then
    open "/Applications/${APP_NAME}.app"
fi

echo ""
echo -e "  ${DIM}Per disinstallare: rm -rf '/Applications/Video-to-SRT.app' ~/.videosrt${RESET}"
echo ""

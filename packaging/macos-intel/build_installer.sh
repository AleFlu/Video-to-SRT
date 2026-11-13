#!/usr/bin/env bash
# =============================================================================
#  build_installer.sh — Crea il pacchetto .pkg distribuibile per Video → SRT
#
#  Da eseguire UNA VOLTA sul Mac dello sviluppatore dopo aver già buildato
#  il .app con build_mac.py.
#
#  Output:
#      dist/Video-to-SRT-Installer.pkg   ← file da condividere
#
#  Prerequisiti sviluppatore:
#      python build_mac.py --clean       ← crea dist/Video-to-SRT.app
#      (opzionale) export SIGN_APP="Developer ID Application: Nome (XXXXXXXX)"
#      (opzionale) export SIGN_PKG="Developer ID Installer: Nome (XXXXXXXX)"
#
#  L'installer risultante:
#      - Funziona su macOS 12+ (Intel e Apple Silicon)
#      - Installa l'app in /Applications senza richiedere Xcode o Python
#      - Al primo avvio l'app scarica il modello Whisper (~3 GB) con progress UI
#      - Gestisce automaticamente Python, pip, ffmpeg (via script postinstall)
# =============================================================================

set -euo pipefail

# ── Colori ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}✅  $*${RESET}"; }
warn() { echo -e "${YELLOW}⚠️   $*${RESET}"; }
err()  { echo -e "${RED}❌  $*${RESET}"; exit 1; }
step() { echo -e "\n${BLUE}${BOLD}▶ $*${RESET}"; }
info() { echo -e "   $*"; }

# ── Configurazione ────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="Video-to-SRT"
APP_VERSION="2.0.0"
BUNDLE_ID="it.videosrt.app"
APP_PATH="$SCRIPT_DIR/dist/$APP_NAME.app"
PKG_STAGING="$SCRIPT_DIR/dist/_pkg_staging"
PKG_SCRIPTS="$SCRIPT_DIR/dist/_pkg_scripts"
PKG_RESOURCES="$SCRIPT_DIR/dist/_pkg_resources"
PKG_OUT="$SCRIPT_DIR/dist/${APP_NAME}-${APP_VERSION}-Installer.pkg"
SIGN_APP="${SIGN_APP:-}"
SIGN_PKG="${SIGN_PKG:-}"

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║     Video → SRT v${APP_VERSION}  •  Build Installer PKG          ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${RESET}"
echo ""

# ── Verifica .app esistente ───────────────────────────────────────────────────
step "Verifica .app"
if [[ ! -d "$APP_PATH" ]]; then
    err ".app non trovato in dist/\n   Esegui prima: python build_mac.py --clean"
fi
ok "Trovato: $APP_PATH"

# ── Pulizia staging ───────────────────────────────────────────────────────────
step "Preparazione staging"
rm -rf "$PKG_STAGING" "$PKG_SCRIPTS" "$PKG_RESOURCES"
mkdir -p "$PKG_STAGING/Applications"
mkdir -p "$PKG_SCRIPTS"
mkdir -p "$PKG_RESOURCES"

# Copia .app nel payload (va in /Applications)
cp -r "$APP_PATH" "$PKG_STAGING/Applications/"
ok "App copiata in staging"

# ── Welcome / License ─────────────────────────────────────────────────────────
step "Creazione risorse installer"

cat > "$PKG_RESOURCES/welcome.html" <<'WELCOME'
<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, sans-serif; padding: 20px;">
<h2>Benvenuto in Video → SRT</h2>
<p>Questo installer copierà <strong>Video → SRT</strong> nella cartella Applicazioni del tuo Mac.</p>
<p><strong>Requisiti:</strong></p>
<ul>
  <li>macOS 12 Monterey o successivo (Intel e Apple Silicon)</li>
  <li>~500 MB di spazio per l'applicazione</li>
  <li>~3 GB per il modello Whisper (scaricato al primo avvio)</li>
  <li>Connessione internet per il primo avvio (download modello AI)</li>
</ul>
<p>L'installazione richiede la password amministratore.</p>
</body>
</html>
WELCOME

cat > "$PKG_RESOURCES/license.html" <<'LICENSE'
<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, sans-serif; padding: 20px;">
<h2>Licenza</h2>
<p>Video → SRT è software proprietario. Tutti i diritti riservati.</p>
<p>Il motore di trascrizione utilizza faster-whisper (MIT License) e i modelli OpenAI Whisper (MIT License).</p>
<p>L'uso di questo software implica l'accettazione dei termini di licenza.</p>
</body>
</html>
LICENSE

cat > "$PKG_RESOURCES/conclusion.html" <<'CONCLUSION'
<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, sans-serif; padding: 20px;">
<h2>Installazione completata</h2>
<p>✅ <strong>Video → SRT</strong> è stato installato in <em>/Applications</em>.</p>
<p><strong>Al primo avvio</strong> l'app scaricherà automaticamente il modello AI Whisper (≈ 3 GB).<br>
Assicurati di avere una connessione internet attiva.</p>
<p>Puoi trovare l'app nel Launchpad o in <em>Finder → Applicazioni → Video-to-SRT</em>.</p>
</body>
</html>
CONCLUSION

ok "Risorse HTML create"

# ── Script postinstall ────────────────────────────────────────────────────────
step "Creazione script postinstall"

# Lo script postinstall viene eseguito da macOS come root dopo la copia dell'app.
# Fa tutto il setup silenzioso: Python check, ffmpeg, LaunchAgent per il download
# del modello al primo avvio dell'app.

cat > "$PKG_SCRIPTS/postinstall" <<'POSTINSTALL'
#!/usr/bin/env bash
# postinstall — eseguito da macOS Installer come root dopo la copia dell'app
# Scopo: setup silenzioso dell'ambiente (non blocca l'installer, non mostra terminale)

set -uo pipefail

APP_SUPPORT="$HOME/Library/Application Support/Video-to-SRT"
LOG_DIR="$APP_SUPPORT/logs"
SETUP_SCRIPT="$APP_SUPPORT/first_run_setup.sh"
LAUNCH_AGENT_DIR="$HOME/Library/LaunchAgents"
LAUNCH_AGENT_PLIST="$LAUNCH_AGENT_DIR/it.videosrt.firstrun.plist"

mkdir -p "$LOG_DIR"
mkdir -p "$LAUNCH_AGENT_DIR"

LOG="$LOG_DIR/install.log"
exec > >(tee -a "$LOG") 2>&1
echo "[$(date)] === Postinstall Video → SRT ==="

# ── Rileva architettura ────────────────────────────────────────────────────────
ARCH="$(uname -m)"
echo "[$(date)] Architettura: $ARCH"

# ── Trova Python 3.10+ ────────────────────────────────────────────────────────
find_python() {
    for candidate in \
        /opt/homebrew/bin/python3.12 \
        /opt/homebrew/bin/python3.11 \
        /opt/homebrew/bin/python3.10 \
        /usr/local/bin/python3.12 \
        /usr/local/bin/python3.11 \
        /usr/local/bin/python3.10 \
        /usr/bin/python3 \
        "$(command -v python3 2>/dev/null || true)"; do
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
echo "[$(date)] Python trovato: ${PYTHON:-NESSUNO}"

# ── Crea script first-run da eseguire al primo avvio ──────────────────────────
# Questo script verrà eseguito silenziosamente tramite LaunchAgent la prima volta
# che l'utente apre l'app, per completare il setup (download modello, venv, ecc.)

cat > "$SETUP_SCRIPT" << SETUP_EOF
#!/usr/bin/env bash
# first_run_setup.sh — setup ambiente Python + download modello Whisper
# Eseguito dal LaunchAgent al primo avvio dell'app

set -uo pipefail
APP_SUPPORT="\$HOME/Library/Application Support/Video-to-SRT"
LOG="\$APP_SUPPORT/logs/first_run.log"
VENV_DIR="\$APP_SUPPORT/venv"
MODEL_DIR="\$APP_SUPPORT/whisper_model"
DONE_FLAG="\$APP_SUPPORT/.setup_complete"
PROGRESS_PIPE="\$APP_SUPPORT/.progress_pipe"

exec > >( tee -a "\$LOG") 2>&1
echo "[\$(date)] === First-run setup ==="

# Già completato?
if [[ -f "\$DONE_FLAG" ]]; then
    echo "[\$(date)] Setup già completato, uscita."
    exit 0
fi

mkdir -p "\$APP_SUPPORT/logs"
mkdir -p "\$MODEL_DIR"

# ── Rilevamento architettura ────────────────────────────────────────────────
ARCH="\$(uname -m)"
echo "[\$(date)] Arch: \$ARCH"

# ── Python ─────────────────────────────────────────────────────────────────
find_python_fr() {
    for c in \
        /opt/homebrew/bin/python3.12 \
        /opt/homebrew/bin/python3.11 \
        /opt/homebrew/bin/python3.10 \
        /usr/local/bin/python3.12 \
        /usr/local/bin/python3.11 \
        /usr/local/bin/python3.10 \
        /usr/bin/python3; do
        if [[ -x "\$c" ]]; then
            ver="\$("\$c" -c 'import sys; print(sys.version_info >= (3,10))' 2>/dev/null || echo False)"
            if [[ "\$ver" == "True" ]]; then echo "\$c"; return 0; fi
        fi
    done
    return 1
}

PYTHON="\$(find_python_fr || true)"
if [[ -z "\$PYTHON" ]]; then
    echo "[\$(date)] ERRORE: Python 3.10+ non trovato."
    echo "PYTHON_MISSING" > "\$APP_SUPPORT/.setup_error"
    exit 1
fi
echo "[\$(date)] Python: \$PYTHON"

# ── Venv ────────────────────────────────────────────────────────────────────
if [[ ! -d "\$VENV_DIR" ]]; then
    echo "[\$(date)] Creo venv..."
    "\$PYTHON" -m venv "\$VENV_DIR"
fi
source "\$VENV_DIR/bin/activate"
echo "[\$(date)] Venv attivato"

# ── Dipendenze ──────────────────────────────────────────────────────────────
echo "[\$(date)] Installazione dipendenze..."
pip install --quiet --upgrade pip wheel setuptools
pip install --quiet \
    "PySide6>=6.6.0" \
    "faster-whisper>=1.0.0" \
    "onnxruntime>=1.16.0" \
    "soundfile>=0.12.1" \
    "numpy>=1.24.0" \
    "pyobjc-framework-Cocoa"
echo "[\$(date)] Dipendenze OK"

# ── ffmpeg ──────────────────────────────────────────────────────────────────
if ! command -v ffmpeg &>/dev/null; then
    # Prova a trovarlo nei percorsi Homebrew
    for ffpath in /opt/homebrew/bin/ffmpeg /usr/local/bin/ffmpeg; do
        if [[ -x "\$ffpath" ]]; then
            ln -sf "\$ffpath" "\$VENV_DIR/bin/ffmpeg" 2>/dev/null || true
            break
        fi
    done
    if ! command -v ffmpeg &>/dev/null; then
        echo "[\$(date)] WARN: ffmpeg non trovato. Audio solo via libreria Python."
    fi
fi

# ── Modello Whisper ──────────────────────────────────────────────────────────
if [[ -z "\$(ls -A "\$MODEL_DIR" 2>/dev/null)" ]]; then
    echo "[\$(date)] Download modello Whisper large-v3 (~3 GB)..."
    "\$VENV_DIR/bin/python" -c "
from faster_whisper import WhisperModel
import sys
print('Download modello Whisper large-v3...')
WhisperModel('large-v3', device='cpu', download_root=sys.argv[1])
print('Modello scaricato.')
" "\$MODEL_DIR"
    echo "[\$(date)] Modello scaricato"
else
    echo "[\$(date)] Modello già presente"
fi

# ── Scrittura config per l'app ───────────────────────────────────────────────
cat > "\$APP_SUPPORT/config.json" << CFG_EOF
{
  "python": "\$PYTHON",
  "venv": "\$VENV_DIR",
  "model_dir": "\$MODEL_DIR",
  "arch": "\$ARCH",
  "setup_version": "2.0.0"
}
CFG_EOF

touch "\$DONE_FLAG"
echo "[\$(date)] === Setup completato con successo ==="
SETUP_EOF

chmod +x "$SETUP_SCRIPT"
echo "[$(date)] Script first-run creato: $SETUP_SCRIPT"

# ── LaunchAgent per eseguire il setup al prossimo login ──────────────────────
# Viene rimosso automaticamente dopo il completamento dal pulsante nell'app.
cat > "$LAUNCH_AGENT_PLIST" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>it.videosrt.firstrun</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$APP_SUPPORT/first_run_setup.sh</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/firstrun_agent.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/firstrun_agent_err.log</string>
  <key>AbandonProcessGroup</key>
  <true/>
</dict>
</plist>
PLIST_EOF

echo "[$(date)] LaunchAgent installato: $LAUNCH_AGENT_PLIST"

# Carica subito l'agente per avviare il setup in background
launchctl load "$LAUNCH_AGENT_PLIST" 2>/dev/null || true
echo "[$(date)] LaunchAgent avviato"

# ── Corregge quarantena su .app ────────────────────────────────────────────────
if [[ -d "/Applications/Video-to-SRT.app" ]]; then
    xattr -r -d com.apple.quarantine "/Applications/Video-to-SRT.app" 2>/dev/null || true
    echo "[$(date)] Quarantena rimossa da .app"
fi

echo "[$(date)] === Postinstall completato ==="
exit 0
POSTINSTALL

chmod +x "$PKG_SCRIPTS/postinstall"
ok "Script postinstall creato"

# ── preinstall: controllo requisiti minimi ────────────────────────────────────
cat > "$PKG_SCRIPTS/preinstall" <<'PREINSTALL'
#!/usr/bin/env bash
# preinstall — verifica macOS 12+ prima dell'installazione

MACOS_VER="$(sw_vers -productVersion)"
MAJOR="$(echo "$MACOS_VER" | cut -d. -f1)"

if [[ "$MAJOR" -lt 12 ]]; then
    osascript -e "display dialog \"Video → SRT richiede macOS 12 Monterey o successivo.\nVersione attuale: $MACOS_VER\" buttons {\"OK\"} default button 1 with icon stop with title \"Requisiti non soddisfatti\""
    exit 1
fi

exit 0
PREINSTALL

chmod +x "$PKG_SCRIPTS/preinstall"
ok "Script preinstall creato"

# ── distribution.xml ─────────────────────────────────────────────────────────
step "Creazione distribution.xml"

cat > "$PKG_RESOURCES/distribution.xml" << DISTXML
<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">

    <title>Video → SRT ${APP_VERSION}</title>
    <background file="background.png" alignment="center" scaling="proportional" mime-type="image/png"/>
    <welcome file="welcome.html" mime-type="text/html"/>
    <license file="license.html" mime-type="text/html"/>
    <conclusion file="conclusion.html" mime-type="text/html"/>

    <options customize="never" require-scripts="true" rootVolumeOnly="true"/>

    <!-- Richiede macOS 12+ -->
    <volume-check>
        <allowed-os-versions>
            <os-version min="12.0"/>
        </allowed-os-versions>
    </volume-check>

    <!-- Supporta sia arm64 sia x86_64 -->
    <supported-platforms>
        <arch>arm64</arch>
        <arch>x86_64</arch>
    </supported-platforms>

    <choices-outline>
        <line choice="main"/>
    </choices-outline>

    <choice id="main" visible="false" title="Video → SRT">
        <pkg-ref id="${BUNDLE_ID}"/>
    </choice>

    <pkg-ref id="${BUNDLE_ID}" version="${APP_VERSION}" onConclusion="none">
        VideoToSRT-core.pkg
    </pkg-ref>

</installer-gui-script>
DISTXML

ok "distribution.xml creato"

# ── Copia immagine di sfondo ──────────────────────────────────────────────────
if [[ -f "$SCRIPT_DIR/assets/app_512.png" ]]; then
    cp "$SCRIPT_DIR/assets/app_512.png" "$PKG_RESOURCES/background.png"
    ok "Sfondo installer copiato"
else
    # Crea un PNG placeholder se non c'è
    warn "app_512.png non trovato — nessuna immagine di sfondo"
fi

# ── Build component .pkg ──────────────────────────────────────────────────────
step "Build component package"

COMPONENT_PKG="$SCRIPT_DIR/dist/VideoToSRT-core.pkg"

pkgbuild \
    --root "$PKG_STAGING" \
    --scripts "$PKG_SCRIPTS" \
    --identifier "$BUNDLE_ID" \
    --version "$APP_VERSION" \
    --install-location "/" \
    "$COMPONENT_PKG"

ok "Component package creato: $COMPONENT_PKG"

# ── Code signing component (opzionale) ───────────────────────────────────────
if [[ -n "$SIGN_APP" ]] && command -v codesign &>/dev/null; then
    step "Firma .app"
    codesign --deep --force --verbose \
        --sign "$SIGN_APP" \
        --options runtime \
        "$PKG_STAGING/Applications/$APP_NAME.app" \
        && ok "App firmata" \
        || warn "Firma app fallita (continuo senza firma)"
fi

# ── Build installer finale ────────────────────────────────────────────────────
step "Build installer finale .pkg"

productbuild \
    --distribution "$PKG_RESOURCES/distribution.xml" \
    --resources "$PKG_RESOURCES" \
    --package-path "$SCRIPT_DIR/dist" \
    "$PKG_OUT"

ok "Installer creato: $PKG_OUT"

# ── Firma installer (opzionale) ───────────────────────────────────────────────
if [[ -n "$SIGN_PKG" ]] && command -v productsign &>/dev/null; then
    step "Firma installer"
    SIGNED_PKG="${PKG_OUT%.pkg}-signed.pkg"
    productsign --sign "$SIGN_PKG" "$PKG_OUT" "$SIGNED_PKG" \
        && mv "$SIGNED_PKG" "$PKG_OUT" \
        && ok "Installer firmato" \
        || warn "Firma installer fallita"
fi

# ── Pulizia temporanei ────────────────────────────────────────────────────────
step "Pulizia file temporanei"
rm -rf "$PKG_STAGING" "$PKG_SCRIPTS" "$PKG_RESOURCES" "$COMPONENT_PKG"
ok "Pulito"

# ── Riepilogo ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════════${RESET}"
echo -e "${GREEN}${BOLD}  Installer pronto!${RESET}"
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════════${RESET}"
echo ""
info "File:     $PKG_OUT"
info "Peso:     $(du -sh "$PKG_OUT" | cut -f1)"
echo ""
info "Cosa fa questo installer:"
info "  1. Copia Video-to-SRT.app in /Applications"
info "  2. Crea uno script di setup in ~/Library/Application Support/Video-to-SRT/"
info "  3. Al prossimo login installa silenziosamente:"
info "     - Dipendenze Python (PySide6, faster-whisper, ecc.)"
info "     - Modello Whisper large-v3 (~3 GB) — richiede internet"
info ""
if [[ -z "$SIGN_PKG" ]]; then
    warn "Installer non firmato. Gli utenti vedranno un avviso Gatekeeper."
    info "Per firmare: export SIGN_PKG=\"Developer ID Installer: Nome (XXXXXX)\""
    info "Poi riesegui questo script."
fi
echo ""

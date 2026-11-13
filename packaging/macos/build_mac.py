#!/usr/bin/env python3
"""
build_mac.py — Build script professionale per Video → SRT v2 (macOS, ARM e Intel).

Va eseguito con il Python del venv della root del repository; la cartella di
lavoro non conta (i percorsi sono risolti a partire dalla posizione di questo file).

Uso (dalla root del repo):
    .venv/bin/python packaging/macos/build_mac.py [--clean] [--no-dmg] [--sign "Developer ID"]

Architettura: rilevata con platform.machine() (arm64 / x86_64) e usata per
scegliere l'ffmpeg da includere. Per la build Intel su un Mac ARM usa
packaging/macos/build_intel.sh (esegue questo script sotto Rosetta).

Output (nella root del repository):
    dist/Video-to-SRT.app             — applicazione standalone
    dist/Video-to-SRT-<versione>.dmg  — installer drag-to-Applications (se create-dmg è disponibile)

Requisiti:
    pip install pyinstaller
    brew install ffmpeg create-dmg   # opzionale: create-dmg solo per il .dmg

Il modello Whisper viene copiato da <root>/_build_model/ (deve essere già scaricato
tramite install.sh oppure manualmente con faster-whisper / huggingface-cli).

Struttura file risultante nell'app:
    Video-to-SRT.app/Contents/
        MacOS/Video-to-SRT          — eseguibile principale
        Resources/
            whisper_model/          — modello Whisper (large-v3)
            ffmpeg                  — binario ffmpeg bundled
        Frameworks/                 — librerie Qt/PySide6
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


# ============================================================
# Configurazione build
# ============================================================

APP_NAME        = "Video-to-SRT"
APP_VERSION     = "2.0.0"
BUNDLE_ID       = "it.videoSRT.app"

# Percorsi: tutto è risolto dalla posizione di questo file, quindi lo script
# funziona da qualsiasi cartella di lavoro.
HERE            = Path(__file__).resolve().parent        # packaging/macos/
REPO_ROOT       = HERE.parent.parent
APP_DIR         = REPO_ROOT / "app"                      # sorgenti dell'app
ENTRY_POINT     = APP_DIR / "main.py"
ASSETS_DIR      = APP_DIR / "assets"
ICON_FILE       = ASSETS_DIR / "app.icns"
RUNTIME_HOOK    = APP_DIR / "pyi_rth_threads.py"
ENTITLEMENTS    = ASSETS_DIR / "entitlements.plist"      # opzionale
MODEL_SRC_DIR   = REPO_ROOT / "_build_model"             # modello scaricato (ignorato da git)
BUNDLED_FFMPEG  = HERE / "bin" / "ffmpeg"                # ffmpeg statico x86_64 (build Intel)
DIST_DIR        = REPO_ROOT / "dist"
BUILD_DIR       = REPO_ROOT / "build"


def find_ffmpeg() -> str | None:
    """Cerca ffmpeg: prima quello statico in packaging/macos/bin/ (solo x86_64), poi PATH/Homebrew."""
    if platform.machine() == "x86_64" and BUNDLED_FFMPEG.exists():
        return str(BUNDLED_FFMPEG)
    for candidate in (
        shutil.which("ffmpeg"),
        "/opt/homebrew/bin/ffmpeg",  # Apple Silicon
        "/usr/local/bin/ffmpeg",     # Intel
    ):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def find_model() -> Path | None:
    """Cerca il modello Whisper in _build_model/ oppure nella cache HuggingFace."""
    local = MODEL_SRC_DIR
    if local.exists() and any(local.iterdir()):
        return local

    # Cache HuggingFace standard
    hf_cache = Path.home() / ".cache" / "huggingface" / "hub"
    for candidate in hf_cache.glob("models--Systran--faster-whisper-large*"):
        snapshots = candidate / "snapshots"
        if snapshots.exists():
            snaps = sorted(snapshots.iterdir())
            if snaps:
                return snaps[-1]  # ultima snapshot

    return None


def run(cmd: list[str], **kwargs):
    """Esegue un comando e rilancia l'eccezione se fallisce."""
    print(f"\n→ {' '.join(str(c) for c in cmd)}\n")
    subprocess.run(cmd, check=True, **kwargs)


def clean():
    for d in (BUILD_DIR, DIST_DIR):
        if d.exists():
            print(f"  Rimozione {d}/ ...")
            shutil.rmtree(d)


def build(sign_id: str | None = None):
    # Lavoriamo dalla root del repo (il .spec generato finisce in build/).
    os.chdir(REPO_ROOT)
    print(f"Architettura: {platform.machine()}  |  root: {REPO_ROOT}")

    # ---- Verifica prerequisiti ----
    if not shutil.which("pyinstaller"):
        sys.exit("❌  PyInstaller non trovato. Installa con: pip install pyinstaller")

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print("⚠️   ffmpeg non trovato — l'app funzionerà solo con file già pre-elaborati.")

    model_dir = find_model()
    if not model_dir:
        print(
            f"⚠️   Modello Whisper non trovato in '{MODEL_SRC_DIR}'.\n"
            "    Esegui: python -c \"from faster_whisper import WhisperModel; "
            f"WhisperModel('large-v3', download_root='{MODEL_SRC_DIR}')\"\n"
            "    oppure packaging/macos/install.sh per scaricarlo automaticamente.\n"
            "    Il build continua, ma l'app non potrà trascrivere."
        )

    # ---- Costruzione comando PyInstaller ----
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--windowed",               # no terminale visibile
        "--noconfirm",
        "--clean",
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        # app/ nel path di analisi: main.py importa engine, platform_support, core, ui
        # (platform_support.py viene quindi incluso dall'analisi degli import).
        "--paths", str(APP_DIR),
        "--specpath", str(BUILD_DIR),
        "--runtime-hook", str(RUNTIME_HOOK),
        "--add-data", f"{APP_DIR / 'engine.py'}{os.pathsep}.",
        "--add-data", f"{APP_DIR / 'ui'}{os.pathsep}ui",
        "--add-data", f"{APP_DIR / 'core'}{os.pathsep}core",
        "--add-data", f"{ASSETS_DIR}{os.pathsep}assets",
        "--collect-all", "PySide6",
        "--collect-all", "shiboken6",
        "--collect-all", "onnxruntime",
        "--collect-all", "ctranslate2",
        "--collect-data", "faster_whisper",
        "--collect-data", "tokenizers",
        "--hidden-import", "soundfile",
        "--hidden-import", "numpy",
        "--hidden-import", "av",
        "--hidden-import", "encodings",
        "--hidden-import", "pkg_resources",
        # Esclude moduli pesanti inutili
        "--exclude-module", "matplotlib",
        "--exclude-module", "IPython",
        "--exclude-module", "notebook",
        "--exclude-module", "PIL",
        "--exclude-module", "scipy",
        "--exclude-module", "sklearn",
        "--exclude-module", "pandas",
        "--exclude-module", "tensorflow",
        "--exclude-module", "torch",
    ]

    # Icona
    if ICON_FILE.exists():
        cmd += ["--icon", str(ICON_FILE)]
    else:
        print(f"⚠️   Icona non trovata ({ICON_FILE}) — verrà usata l'icona di default.")

    # ffmpeg bundled
    if ffmpeg:
        cmd += ["--add-binary", f"{ffmpeg}{os.pathsep}."]

    # Modello Whisper bundled
    if model_dir:
        cmd += ["--add-data", f"{model_dir}{os.pathsep}whisper_model"]

    cmd.append(str(ENTRY_POINT))

    run(cmd)

    app_path = DIST_DIR / f"{APP_NAME}.app"
    if not app_path.exists():
        sys.exit(f"❌  Build fallita: {app_path} non trovato.")

    print(f"\n✅  App costruita: {app_path}")

    # ---- Info.plist ----
    _patch_info_plist(app_path)

    # ---- Code signing ----
    if sign_id:
        _sign(app_path, sign_id)
    else:
        print("ℹ️   Code signing saltato (usa --sign per firmare).")

    return app_path


def _patch_info_plist(app_path: Path):
    """Aggiunge/corregge chiavi Info.plist per comportamento macOS corretto."""
    plist = app_path / "Contents" / "Info.plist"
    if not plist.exists():
        return

    import plistlib
    with open(plist, "rb") as f:
        data = plistlib.load(f)

    data.setdefault("CFBundleIdentifier",       BUNDLE_ID)
    data.setdefault("CFBundleShortVersionString", APP_VERSION)
    data.setdefault("CFBundleVersion",           APP_VERSION)
    data["NSHighResolutionCapable"]      = True
    data["NSMicrophoneUsageDescription"] = "Video → SRT utilizza il microfono per la trascrizione audio."
    data["NSAppleEventsUsageDescription"] = "Automazione per apertura file."
    # Autorizza file apertura (drag onto dock icon)
    data["CFBundleDocumentTypes"] = [
        {
            "CFBundleTypeName":       "File multimediale",
            "CFBundleTypeRole":       "Viewer",
            "LSHandlerRank":          "Alternate",
            "LSItemContentTypes":     [
                "public.movie", "public.audio", "public.mpeg-4",
                "com.apple.quicktime-movie",
            ],
        }
    ]

    with open(plist, "wb") as f:
        plistlib.dump(data, f)

    print("✅  Info.plist aggiornato.")


def _sign(app_path: Path, sign_id: str):
    """Firma l'app con codesign (richiede Developer ID)."""
    if not shutil.which("codesign"):
        print("⚠️   codesign non trovato — firma saltata.")
        return

    entitlements = ENTITLEMENTS
    sign_cmd = [
        "codesign", "--deep", "--force", "--verbose",
        "--sign", sign_id,
    ]
    if entitlements.exists():
        sign_cmd += ["--entitlements", str(entitlements)]
    sign_cmd.append(str(app_path))

    run(sign_cmd)
    print(f"✅  App firmata con: {sign_id}")


def make_dmg(app_path: Path):
    """Crea un DMG drag-to-Applications usando create-dmg (brew install create-dmg)."""
    if not shutil.which("create-dmg"):
        print("⚠️   create-dmg non trovato (brew install create-dmg) — DMG saltato.")
        return

    dmg_path = DIST_DIR / f"{APP_NAME}-{APP_VERSION}.dmg"
    if dmg_path.exists():
        dmg_path.unlink()

    cmd = [
        "create-dmg",
        "--volname",           f"{APP_NAME} {APP_VERSION}",
        "--volicon",           str(ICON_FILE) if ICON_FILE.exists() else str(app_path),
        "--window-pos",        "200", "120",
        "--window-size",       "660", "400",
        "--icon-size",         "128",
        "--icon",              f"{APP_NAME}.app", "160", "185",
        "--hide-extension",    f"{APP_NAME}.app",
        "--app-drop-link",     "500", "185",
        "--no-internet-enable",
        str(dmg_path),
        str(app_path.parent),  # cartella sorgente = dist/
    ]

    try:
        run(cmd)
        print(f"\n✅  DMG creato: {dmg_path}")
    except subprocess.CalledProcessError:
        print("⚠️   Creazione DMG fallita — verifica i log sopra.")


# ============================================================
# Entrypoint
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Build Video → SRT v2 per macOS")
    parser.add_argument("--clean",   action="store_true",
                        help="Rimuovi build/ e dist/ prima di compilare")
    parser.add_argument("--no-dmg",  action="store_true",
                        help="Salta la creazione del DMG")
    parser.add_argument("--sign",    metavar="DEVELOPER_ID", default=None,
                        help='Firma con: "Developer ID Application: Nome (XXXXXXXXXX)"')
    args = parser.parse_args()

    print("=" * 60)
    print(f"  Video → SRT v{APP_VERSION} — Build macOS")
    print("=" * 60)

    if args.clean:
        print("\n🧹  Pulizia...")
        clean()

    app_path = build(sign_id=args.sign)

    if not args.no_dmg:
        print("\n📦  Creazione DMG...")
        make_dmg(app_path)

    print("\n" + "=" * 60)
    print(f"  Build completata → {DIST_DIR}/")
    print("=" * 60)


if __name__ == "__main__":
    main()

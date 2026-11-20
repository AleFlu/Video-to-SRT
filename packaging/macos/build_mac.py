#!/usr/bin/env python3
"""
build_mac.py — Build script professionale per Video → SRT v2 (macOS, ARM e Intel).

Va eseguito con il Python del venv della root del repository; la cartella di
lavoro non conta (i percorsi sono risolti a partire dalla posizione di questo file).

Uso (dalla root del repo):
    .venv/bin/python packaging/macos/build_mac.py [--clean] [--no-dmg] [--with-model]
                                                  [--sign "Developer ID"]

Architettura: rilevata con platform.machine() (arm64 / x86_64) e usata per
scegliere l'ffmpeg da includere. Per la build Intel su un Mac ARM usa
packaging/macos/intel/build.sh (esegue questo script sotto Rosetta); per Apple
Silicon packaging/macos/apple-silicon/build.sh.

Output (nella root del repository):
    dist/Video-to-SRT.app             — applicazione standalone
    dist/Video-to-SRT-<versione>-macOS-<arm64|intel>.dmg  — installer drag-to-Applications (se create-dmg è disponibile)

Requisiti:
    pip install pyinstaller
    brew install ffmpeg create-dmg   # opzionale: create-dmg solo per il .dmg

Il modello Whisper NON è incluso di norma: l'app propone quello adatto al computer e lo
scarica alla prima trascrizione. Con --with-model viene copiato large-v3 da
<root>/_build_model/ (o dalla cache di Hugging Face) per l'uso senza internet.

Struttura file risultante nell'app:
    Video-to-SRT.app/Contents/
        MacOS/Video-to-SRT          — eseguibile principale
        Resources/
            whisper_model/          — modello Whisper (solo con --with-model)
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
ENTITLEMENTS    = HERE / "entitlements.plist"            # hardened runtime
MODEL_SRC_DIR   = REPO_ROOT / "_build_model"             # modello scaricato (ignorato da git)
BUNDLED_FFMPEG  = HERE / "intel" / "bin" / "ffmpeg"                # ffmpeg statico x86_64 (build Intel)
DIST_DIR        = REPO_ROOT / "dist"
BUILD_DIR       = REPO_ROOT / "build"


def find_ffmpeg() -> str | None:
    """Cerca ffmpeg: prima quello statico in packaging/macos/intel/bin/ (solo x86_64), poi PATH/Homebrew."""
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


def build(sign_id: str | None = None, with_model: bool = False):
    # Lavoriamo dalla root del repo (il .spec generato finisce in build/).
    os.chdir(REPO_ROOT)
    print(f"Architettura: {platform.machine()}  |  root: {REPO_ROOT}")

    # ---- Verifica prerequisiti ----
    # Si usa `python -m PyInstaller` del venv: basta che il modulo ci sia (il venv può non
    # essere attivato, quindi lo script `pyinstaller` può non essere nel PATH).
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("❌  PyInstaller non trovato. Installa con: pip install pyinstaller")

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print("⚠️   ffmpeg non trovato — l'app funzionerà solo con file già pre-elaborati.")

    # Modello: di norma NON incluso (l'app propone quello adatto al computer e lo scarica
    # alla prima trascrizione, con l'avanzamento). --with-model include large-v3 (~3 GB)
    # per chi deve installare su computer senza internet.
    model_dir = find_model() if with_model else None
    if with_model and not model_dir:
        sys.exit(
            f"❌  --with-model: modello large-v3 non trovato in '{MODEL_SRC_DIR}' né nella "
            "cache di Hugging Face.\n    Esegui: python -c \"from faster_whisper import "
            f"WhisperModel; WhisperModel('large-v3', download_root='{MODEL_SRC_DIR}')\""
        )
    if not with_model:
        print("ℹ️   Modello non incluso: l'app lo scarica alla prima trascrizione "
              "(--with-model per includere large-v3).")

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
        # Solo i moduli Qt che l'app usa (gli hook di PyInstaller aggiungono i plugin:
        # piattaforma, stili, multimedia, svg). Con --collect-all PySide6 entravano anche
        # WebEngine (~650 MB), QML/Quick, 3D, PDF... mai usati.
        "--hidden-import", "PySide6.QtCore",
        "--hidden-import", "PySide6.QtGui",
        "--hidden-import", "PySide6.QtWidgets",
        "--hidden-import", "PySide6.QtSvg",
        "--hidden-import", "PySide6.QtMultimedia",
        "--hidden-import", "PySide6.QtMultimediaWidgets",
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtWebEngineWidgets",
        "--exclude-module", "PySide6.QtWebEngineQuick",
        "--exclude-module", "PySide6.QtQml",
        "--exclude-module", "PySide6.QtQuick",
        "--exclude-module", "PySide6.QtPdf",
        "--collect-all", "onnxruntime",
        "--collect-all", "ctranslate2",
        "--collect-data", "faster_whisper",
        "--collect-data", "tokenizers",
        "--hidden-import", "soundfile",
        "--hidden-import", "numpy",
        "--hidden-import", "av",
        "--hidden-import", "encodings",
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


def _macho_files(app_path: Path) -> list[Path]:
    """File Mach-O dentro l'app (librerie, plugin, eseguibili), escluso l'eseguibile
    principale: vanno firmati uno per uno, dall'interno verso l'esterno."""
    sys.path.insert(0, str(HERE))
    from check_bundle import is_macho
    main_exe = app_path / "Contents" / "MacOS" / APP_NAME
    files = [f for f in app_path.rglob("*")
             if f.is_file() and not f.is_symlink() and f != main_exe and is_macho(f)]
    # prima i più annidati
    return sorted(files, key=lambda f: len(f.parts), reverse=True)


def _sign(app_path: Path, sign_id: str):
    """Firma l'app per la distribuzione: ogni libreria, poi il bundle, con hardened
    runtime, marca temporale ed entitlements (requisiti della notarizzazione Apple).

    ``sign_id`` = "Developer ID Application: Nome (TEAMID)"; "-" = firma ad-hoc (solo per
    provare in locale che l'app firmata così parta ancora: Apple non la accetta).
    """
    if not shutil.which("codesign"):
        sys.exit("❌  codesign non trovato (installa gli strumenti da riga di comando di Xcode).")
    base = ["codesign", "--force", "--options", "runtime", "--sign", sign_id]
    if sign_id != "-":
        base.insert(2, "--timestamp")
    files = _macho_files(app_path)
    print(f"🔏  Firma di {len(files)} librerie ed eseguibili...")
    for f in files:
        # Gli eseguibili di supporto (ffmpeg) girano in un processo loro: senza gli
        # entitlements l'hardened runtime gli vieta di caricare le librerie del bundle.
        extra = [] if f.suffix in (".dylib", ".so") or not os.access(f, os.X_OK) else [
            "--entitlements", str(ENTITLEMENTS)]
        subprocess.run(base + extra + [str(f)], check=True, capture_output=True)
    run(base + ["--entitlements", str(ENTITLEMENTS), str(app_path)])
    run(["codesign", "--verify", "--strict", "--verbose=2", str(app_path)])
    print(f"✅  App firmata con: {sign_id}")


def notarize(path: Path, profile: str):
    """Invia ``path`` (.app o .dmg) alla notarizzazione Apple e ci "pinza" il risultato.

    ``profile`` è un profilo del portachiavi creato una volta sola dall'utente con
    ``xcrun notarytool store-credentials <profilo>`` (Apple ID, team e password per app):
    le credenziali non passano mai da questo script.
    """
    target = path
    if path.suffix == ".app":
        target = path.with_suffix(".zip")
        if target.exists():
            target.unlink()
        run(["ditto", "-c", "-k", "--keepParent", str(path), str(target)])
    print(f"📨  Notarizzazione di {target.name} (alcuni minuti)...")
    run(["xcrun", "notarytool", "submit", str(target), "--keychain-profile", profile,
         "--wait"])
    run(["xcrun", "stapler", "staple", str(path)])
    if target != path:
        target.unlink()
    print(f"✅  Notarizzata: {path.name}")


def verify(app_path: Path) -> None:
    """Controlli dopo la build: nessuna libreria fuori dal bundle e autotest dell'app
    compilata (ffmpeg, encoder, VAD, Qt, una piccola esportazione video)."""
    sys.path.insert(0, str(HERE))
    from check_bundle import scan
    problems = scan(app_path)
    if problems:
        for name, deps in problems.items():
            print(f"   {name} → {', '.join(deps)}")
        sys.exit("❌  L'app usa librerie fuori dal bundle: su un Mac pulito non partirebbe.")
    print("✅  Nessuna libreria fuori dal bundle.")
    exe = app_path / "Contents" / "MacOS" / APP_NAME
    # PATH minimo: l'app deve usare il suo ffmpeg, non quello di Homebrew
    env = {"HOME": os.environ.get("HOME", ""), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
           "TMPDIR": os.environ.get("TMPDIR", "/tmp")}
    print("🩺  Autotest dell'app compilata...")
    result = subprocess.run([str(exe), "--self-test"], env=env, capture_output=True,
                            text=True, timeout=600)
    print(result.stdout.rstrip())
    if result.returncode != 0:
        print(result.stderr[-2000:])
        sys.exit("❌  Autotest dell'app compilata non superato.")


def make_dmg(app_path: Path):
    """Crea un DMG drag-to-Applications usando create-dmg (brew install create-dmg)."""
    if not shutil.which("create-dmg"):
        print("⚠️   create-dmg non trovato (brew install create-dmg) — DMG saltato.")
        return None

    arch = "intel" if platform.machine() == "x86_64" else "arm64"
    dmg_path = DIST_DIR / f"{APP_NAME}-{APP_VERSION}-macOS-{arch}.dmg"
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
        return dmg_path
    except subprocess.CalledProcessError:
        print("⚠️   Creazione DMG fallita — verifica i log sopra.")
        return None


# ============================================================
# Entrypoint
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Build Video → SRT v2 per macOS")
    parser.add_argument("--clean",   action="store_true",
                        help="Rimuovi build/ e dist/ prima di compilare")
    parser.add_argument("--no-dmg",  action="store_true",
                        help="Salta la creazione del DMG")
    parser.add_argument("--with-model", action="store_true",
                        help="Includi il modello large-v3 (~3 GB) per l'uso senza internet")
    parser.add_argument("--sign",    metavar="DEVELOPER_ID", default=None,
                        help='Firma con: "Developer ID Application: Nome (XXXXXXXXXX)" '
                             '("-" = ad-hoc, solo per prove locali)')
    parser.add_argument("--notarize", metavar="PROFILO", default=None,
                        help="Notarizza con il profilo creato da "
                             "'xcrun notarytool store-credentials PROFILO' (serve --sign)")
    parser.add_argument("--skip-checks", action="store_true",
                        help="Salta i controlli dopo la build (librerie e autotest)")
    args = parser.parse_args()
    if args.notarize and (not args.sign or args.sign == "-"):
        parser.error("--notarize richiede --sign con un certificato Developer ID")

    print("=" * 60)
    print(f"  Video → SRT v{APP_VERSION} — Build macOS")
    print("=" * 60)

    if args.clean:
        print("\n🧹  Pulizia...")
        clean()

    app_path = build(sign_id=args.sign, with_model=args.with_model)

    if not args.skip_checks:
        verify(app_path)

    dmg = None
    if not args.no_dmg:
        print("\n📦  Creazione DMG...")
        dmg = make_dmg(app_path)
        if dmg and args.sign:
            run(["codesign", "--force", "--sign", args.sign]
                + (["--timestamp"] if args.sign != "-" else []) + [str(dmg)])

    if args.notarize:
        notarize(dmg or app_path, args.notarize)
        if dmg:
            subprocess.run(["xcrun", "stapler", "staple", str(app_path)])

    print("\n" + "=" * 60)
    print(f"  Build completata → {DIST_DIR}/")
    print("=" * 60)


if __name__ == "__main__":
    main()

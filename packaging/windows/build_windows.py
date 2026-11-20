"""
build_windows.py — Build PyInstaller per Windows (.exe + cartella dist/).

Uso (da qualsiasi cartella; i percorsi sono risolti dalla posizione dello script):
    python packaging\\windows\\build_windows.py [--onefile] [--clean] [--skip-checks]

Output (nella root del repository):
    dist/VideoSRT/VideoSRT.exe         (default: cartella)
    dist/VideoSRT.exe                  (con --onefile, più lento all'avvio)

Requisiti:
    pip install pyinstaller
    ffmpeg.exe nel PATH oppure in packaging/windows/
    (opzionale) app/assets/app.ico — se manca la build usa l'icona di default

Note Windows specifiche:
    - UPX disabilitato (causa falsi positivi antivirus)
    - Console nascosta (--noconsole / --windowed)
    - File .spec generato per personalizzazione futura
"""

from __future__ import annotations

import os
import subprocess
import sys
import shutil
from pathlib import Path

script_dir = Path(__file__).resolve().parent      # packaging/windows/
repo_root = script_dir.parent.parent
app_dir = repo_root / "app"                       # sorgenti dell'app
assets_dir = app_dir / "assets"
dist_dir = repo_root / "dist"
build_dir = repo_root / "build"


def find_ffmpeg() -> str | None:
    """Cerca ffmpeg.exe: prima accanto a questo script (packaging/windows/, un build statico
    scelto apposta), poi nel PATH (attenzione ai "shim" di Chocolatey/Scoop: sono piccoli
    lanciatori, non ffmpeg vero, e nell'app non funzionerebbero)."""
    local = script_dir / "ffmpeg.exe"
    if local.exists():
        print(f"[build] ffmpeg locale trovato: {local}")
        return str(local)
    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(path_dir) / "ffmpeg.exe"
        if candidate.exists():
            print(f"[build] ffmpeg trovato: {candidate}")
            return str(candidate)
    print("[build] AVVISO: ffmpeg.exe non trovato. "
          "L'app richiederà ffmpeg installato separatamente dall'utente.")
    return None


def build(onefile: bool = False, clean: bool = False):
    if clean:
        for d in (build_dir, dist_dir):
            shutil.rmtree(d, ignore_errors=True)
        print("[build] cartelle build/ e dist/ pulite")

    pyinstaller = shutil.which("pyinstaller")
    if not pyinstaller:
        print("[ERRORE] PyInstaller non trovato. Installa con: pip install pyinstaller")
        sys.exit(1)

    ffmpeg_path = find_ffmpeg()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "VideoSRT",
        "--windowed",               # nessuna finestra console su Windows
        "--noconfirm",
        "--clean",
        "--distpath", str(dist_dir),
        "--workpath", str(build_dir),
        "--specpath", str(build_dir),
        # app/ nel path di analisi: main.py importa engine, platform_support, core, ui
        "--paths", str(app_dir),
        # Raccogli tutti i moduli necessari
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
        "--collect-all", "ctranslate2",
        "--collect-all", "faster_whisper",
        "--collect-all", "onnxruntime",
        "--hidden-import", "soundfile",
        "--hidden-import", "numpy",
        "--hidden-import", "numba",
        "--hidden-import", "tqdm",
        "--hidden-import", "huggingface_hub",
        "--hidden-import", "tokenizers",
        # Runtime hook threading
        "--runtime-hook", str(app_dir / "pyi_rth_threads.py"),
        # Assets
        "--add-data", f"{assets_dir}{os.pathsep}assets",
    ]

    if ffmpeg_path:
        cmd += ["--add-binary", f"{ffmpeg_path}{os.pathsep}."]

    if onefile:
        cmd += ["--onefile"]

    # Icona .ico per Windows
    ico_path = assets_dir / "app.ico"
    if ico_path.exists():
        cmd += ["--icon", str(ico_path)]
    else:
        print(f"[build] AVVISO: {ico_path} non trovato — verrà usata l'icona di default.")

    cmd += [str(app_dir / "main.py")]

    print(f"[build] esecuzione: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(repo_root))
    if result.returncode != 0:
        print(f"[build] ERRORE: PyInstaller ha restituito codice {result.returncode}")
        sys.exit(result.returncode)

    print("\n[build] Build completata.")
    if onefile:
        exe = dist_dir / "VideoSRT.exe"
        print(f"[build] Eseguibile: {exe}")
    else:
        exe_dir = dist_dir / "VideoSRT"
        exe = exe_dir / "VideoSRT.exe"
        print(f"[build] Cartella output: {exe_dir}")
        print(f"[build] Eseguibile:      {exe}")
    return exe


def self_test(exe: Path) -> None:
    """Autotest dell'app compilata (ffmpeg, encoder, VAD, Qt, piccola esportazione video).

    L'eseguibile non ha console: l'esito arriva da un file di report e dal codice di uscita.
    """
    report = dist_dir / "autotest.txt"
    report.unlink(missing_ok=True)
    print("[build] autotest dell'app compilata...")
    result = subprocess.run([str(exe), "--self-test", "--self-test-report", str(report)],
                            timeout=600)
    if report.exists():
        print(report.read_text(encoding="utf-8"))
    if result.returncode != 0 or not report.exists():
        print(f"[build] ERRORE: autotest non superato (codice {result.returncode})")
        sys.exit(1)


if __name__ == "__main__":
    onefile = "--onefile" in sys.argv
    clean   = "--clean" in sys.argv
    exe = build(onefile=onefile, clean=clean)
    if "--skip-checks" not in sys.argv:
        self_test(exe)

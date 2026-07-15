"""
build_windows.py — Build PyInstaller per Windows (.exe + cartella dist/).

Uso:
    python build_windows.py [--onefile] [--clean]

Output:
    dist/VideoSRT/VideoSRT.exe         (default: cartella)
    dist/VideoSRT.exe                  (con --onefile, più lento all'avvio)

Requisiti:
    pip install pyinstaller
    ffmpeg.exe nel PATH o nella stessa cartella

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

script_dir = Path(__file__).resolve().parent


def find_ffmpeg() -> str | None:
    """Cerca ffmpeg.exe sul sistema."""
    # Cerca nel PATH
    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(path_dir) / "ffmpeg.exe"
        if candidate.exists():
            print(f"[build] ffmpeg trovato: {candidate}")
            return str(candidate)
    # Cerca nella cartella dell'app
    local = script_dir / "ffmpeg.exe"
    if local.exists():
        print(f"[build] ffmpeg locale trovato: {local}")
        return str(local)
    print("[build] AVVISO: ffmpeg.exe non trovato. "
          "L'app richiederà ffmpeg installato separatamente dall'utente.")
    return None


def build(onefile: bool = False, clean: bool = False):
    if clean:
        for d in ("build", "dist"):
            shutil.rmtree(script_dir / d, ignore_errors=True)
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
        # Raccogli tutti i moduli necessari
        "--collect-all", "PySide6",
        "--collect-all", "shiboken6",
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
        "--runtime-hook", "pyi_rth_threads.py",
        # Assets
        "--add-data", f"assets{os.pathsep}assets",
    ]

    if ffmpeg_path:
        cmd += ["--add-binary", f"{ffmpeg_path}{os.pathsep}."]

    if onefile:
        cmd += ["--onefile"]

    # Icona .ico per Windows
    ico_path = script_dir / "assets" / "app.ico"
    if ico_path.exists():
        cmd += ["--icon", str(ico_path)]
    else:
        print("[build] AVVISO: assets/app.ico non trovato. "
              "Usa assets/make_icon_windows.py per generarlo.")

    cmd += ["main.py"]

    print(f"[build] esecuzione: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(script_dir))
    if result.returncode != 0:
        print(f"[build] ERRORE: PyInstaller ha restituito codice {result.returncode}")
        sys.exit(result.returncode)

    print("\n[build] Build completata.")
    if onefile:
        exe = script_dir / "dist" / "VideoSRT.exe"
        print(f"[build] Eseguibile: {exe}")
    else:
        exe_dir = script_dir / "dist" / "VideoSRT"
        print(f"[build] Cartella output: {exe_dir}")
        print(f"[build] Eseguibile:      {exe_dir / 'VideoSRT.exe'}")


if __name__ == "__main__":
    onefile = "--onefile" in sys.argv
    clean   = "--clean" in sys.argv
    build(onefile=onefile, clean=clean)

#!/usr/bin/env python3
"""
build_mac.py — Crea il bundle Video-to-SRT.app per macOS
Include: modello Whisper large-v3, modello Silero VAD, FFmpeg.

Utilizzo:
  python build_mac.py
  python build_mac.py --model large-v3-turbo
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def abort(msg: str):
    print(f"\n❌ {msg}")
    sys.exit(1)


def status(msg: str):
    print(f"\n{'='*55}")
    print(f"  {msg}")
    print(f"{'='*55}")


def find_ffmpeg() -> str:
    result = shutil.which("ffmpeg")
    if not result:
        abort("FFmpeg non trovato. Installalo con: brew install ffmpeg")
    return result


def ensure_whisper_model(model_name: str) -> str:
    """
    Scarica il modello faster-whisper e restituisce il path della cartella
    snapshot con i file reali (risolve la struttura cache huggingface).
    """
    from faster_whisper import WhisperModel
    from huggingface_hub import scan_cache_dir

    status(f"Preparazione modello Whisper '{model_name}'")

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    del model

    repo_name = f"Systran/faster-whisper-{model_name}"
    try:
        cache_info = scan_cache_dir()
        for repo in cache_info.repos:
            if repo.repo_id == repo_name:
                for revision in repo.revisions:
                    snapshot_dir = revision.snapshot_path
                    if snapshot_dir.exists():
                        size_mb = sum(
                            f.stat().st_size for f in snapshot_dir.rglob("*") if f.is_file()
                        ) / 1e6
                        print(f"   ✅ Modello trovato ({size_mb:.0f} MB)")
                        return str(snapshot_dir)
    except Exception as e:
        print(f"   ⚠️  scan_cache_dir fallito: {e}")

    # Fallback manuale
    cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
    model_dir_name = f"models--Systran--faster-whisper-{model_name}"
    snapshots_dir = cache_dir / model_dir_name / "snapshots"

    if snapshots_dir.exists():
        for snap in sorted(snapshots_dir.iterdir()):
            if snap.is_dir() and list(snap.glob("*")):
                size_mb = sum(f.stat().st_size for f in snap.rglob("*") if f.is_file()) / 1e6
                print(f"   ✅ Modello trovato via fallback ({size_mb:.0f} MB)")
                return str(snap)

    abort(f"Modello '{model_name}' non trovato nella cache.")


def find_silero_vad_model() -> str | None:
    """
    Cerca il modello Silero VAD (silero_vad.onnx).
    faster-whisper lo scarica/include in vari posti possibili.
    """
    status("Preparazione modello VAD (Silero)")

    # Prova a far scaricare il modello se non presente
    try:
        from faster_whisper.vad import get_vad_model
        get_vad_model()
        print("   ✅ Modello VAD inizializzato")
    except Exception as e:
        print(f"   ⚠️  Inizializzazione VAD fallita: {e}")

    # Cerca il file .onnx — prima nel pacchetto faster_whisper (più affidabile)
    try:
        import faster_whisper
        pkg_dir = Path(faster_whisper.__file__).parent
        for onnx_file in pkg_dir.rglob("silero_vad.onnx"):
            size_kb = onnx_file.stat().st_size / 1024
            print(f"   ✅ Silero VAD nel pacchetto ({size_kb:.0f} KB): {onnx_file}")
            return str(onnx_file)
    except Exception:
        pass

    # Poi nelle cache di sistema
    search_paths = [
        Path.home() / ".cache" / "silero-vad",
        Path.home() / ".cache" / "torch" / "hub",
        Path.home() / ".cache" / "huggingface",
    ]

    for base in search_paths:
        if base.exists():
            for onnx_file in base.rglob("silero_vad.onnx"):
                size_kb = onnx_file.stat().st_size / 1024
                print(f"   ✅ Silero VAD trovato ({size_kb:.0f} KB): {onnx_file}")
                return str(onnx_file)

    print("   ⚠️  Silero VAD non trovato (VAD non sarà disponibile nella .app)")
    return None


def build(model_name: str = "large-v3"):
    if platform.system() != "Darwin":
        abort("Questo script è solo per macOS.")

    status(f"🍎 Build Video-to-SRT.app (modello: {model_name})")
    print(f"   Architettura: {platform.machine()}")
    print(f"   Python: {sys.version.split()[0]}")

    # --- 1/6: Verifica dipendenze ---
    status("1/6 — Verifica dipendenze")

    try:
        import faster_whisper
        print(f"   ✅ faster-whisper")
    except ImportError:
        abort("faster-whisper non installato.")

    try:
        import onnxruntime
        print(f"   ✅ onnxruntime {onnxruntime.__version__}")
    except ImportError:
        print("   ⚠️  onnxruntime non installato (VAD non funzionerà)")

    try:
        import customtkinter
        print(f"   ✅ customtkinter {customtkinter.__version__}")
    except ImportError:
        abort("customtkinter non installato.")

    try:
        import PyInstaller
        print(f"   ✅ PyInstaller {PyInstaller.__version__}")
    except ImportError:
        abort("PyInstaller non installato.")

    ffmpeg_path = find_ffmpeg()
    print(f"   ✅ FFmpeg: {ffmpeg_path}")

    # --- 2/6: Modello Whisper ---
    model_dir = ensure_whisper_model(model_name)

    # --- 3/6: Modello VAD ---
    vad_onnx_path = find_silero_vad_model()

    # --- 4/6: Raccolta risorse ---
    status("4/6 — Raccolta risorse")

    script_dir = Path(__file__).resolve().parent
    app_py = script_dir / "app.py"
    engine_py = script_dir / "engine.py"

    if not app_py.exists() or not engine_py.exists():
        abort("File app.py o engine.py non trovati.")

    # Copia il modello risolvendo i symlink di huggingface
    temp_model_dir = script_dir / "_build_model"
    if temp_model_dir.exists():
        shutil.rmtree(temp_model_dir)
    print(f"   📋 Copia modello Whisper risolvendo symlink...")
    shutil.copytree(model_dir, temp_model_dir, symlinks=False)
    model_build_dir = str(temp_model_dir)
    size_mb = sum(f.stat().st_size for f in temp_model_dir.rglob("*") if f.is_file()) / 1e6
    print(f"   ✅ Modello copiato ({size_mb:.0f} MB)")

    # customtkinter assets
    import customtkinter
    ctk_dir = Path(customtkinter.__file__).parent
    print(f"   ✅ customtkinter assets")

    # Icona (opzionale)
    icon_path = script_dir / "icon.icns"
    has_icon = icon_path.exists()
    if has_icon:
        print(f"   ✅ Icona: {icon_path}")
    else:
        print(f"   ℹ️  Nessuna icona (metti icon.icns nella cartella per usarla)")

    # --- 5/6: Build PyInstaller ---
    status("5/6 — Build .app bundle (può richiedere diversi minuti)")

    # Runtime hook: path
    rth_path = script_dir / "pyi_rth_threads.py"
    if not rth_path.exists():
        abort("File pyi_rth_threads.py non trovato nella cartella del progetto.")
    print(f"   ✅ Runtime hook: {rth_path.name}")

    sep = os.pathsep

    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(app_py),
        "--name", "Video-to-SRT",
        "--windowed",
        "--noconfirm",
        "--clean",
        # --- Runtime hook: setta OMP_NUM_THREADS PRIMA di tutto ---
        "--runtime-hook", str(rth_path),
        # --- Dati ---
        "--add-data", f"{engine_py}{sep}.",
        "--add-data", f"{model_build_dir}{sep}whisper_model",
        "--add-data", f"{ctk_dir}{sep}customtkinter",
        "--add-binary", f"{ffmpeg_path}{sep}.",
        # --- Hidden imports ---
        "--hidden-import", "faster_whisper",
        "--hidden-import", "ctranslate2",
        "--hidden-import", "huggingface_hub",
        "--hidden-import", "tokenizers",
        "--hidden-import", "numpy",
        "--hidden-import", "av",
        "--hidden-import", "customtkinter",
        # --- Collect completo: include TUTTE le librerie ottimizzate ---
        "--collect-all", "onnxruntime",
        "--collect-all", "ctranslate2",
        "--collect-data", "faster_whisper",
    ]

    if has_icon:
        cmd.extend(["--icon", str(icon_path)])

    # LICENSE.txt
    license_path = script_dir / "LICENSE.txt"
    if license_path.exists():
        cmd.extend(["--add-data", f"{license_path}{sep}."])
        print(f"   ✅ LICENSE.txt incluso")

    # Silero VAD onnx model
    if vad_onnx_path:
        cmd.extend(["--add-data", f"{vad_onnx_path}{sep}silero_vad"])
        print(f"   ✅ Silero VAD incluso")

    # tkinterdnd2 (drag & drop) — opzionale
    try:
        import tkinterdnd2
        dnd_dir = Path(tkinterdnd2.__file__).parent
        cmd.extend(["--add-data", f"{dnd_dir}{sep}tkinterdnd2"])
        cmd.extend(["--hidden-import", "tkinterdnd2"])
        print("   ✅ tkinterdnd2 incluso (drag & drop)")
    except ImportError:
        print("   ⚠️  tkinterdnd2 non trovato (drag & drop non incluso)")

    result = subprocess.run(cmd, cwd=str(script_dir))

    # Cleanup
    if temp_model_dir.exists():
        print("   🧹 Pulizia file temporanei...")
        shutil.rmtree(temp_model_dir)

    if result.returncode != 0:
        abort("Build fallito.")

    # --- 6/6: Verifica output ---
    status("6/6 — Verifica output")

    app_path = script_dir / "dist" / "Video-to-SRT.app"
    if not app_path.exists():
        abort(f".app non trovato: {app_path}")

    total_size = sum(f.stat().st_size for f in app_path.rglob("*") if f.is_file())
    size_gb = total_size / (1024 ** 3)

    print(f"\n   📦 {app_path}")
    print(f"   📐 Dimensione: {size_gb:.1f} GB")

    status("✅ Build completato!")
    print(f"""
   Il bundle .app è pronto in:
   {app_path}

   Per testarlo:
     open dist/Video-to-SRT.app

   Per distribuirlo:
     zip -r Video-to-SRT.zip dist/Video-to-SRT.app

   ⚠️  macOS potrebbe bloccare l'app al primo avvio:
      Preferenze di Sistema → Privacy e Sicurezza → "Apri comunque"
""")


def main():
    parser = argparse.ArgumentParser(description="Build Video-to-SRT.app")
    parser.add_argument(
        "--model", default="large-v3",
        choices=["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"],
        help="Modello da includere (default: large-v3)",
    )
    args = parser.parse_args()
    build(model_name=args.model)


if __name__ == "__main__":
    main()
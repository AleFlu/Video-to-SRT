#!/usr/bin/env python3
"""
transcribe.py — CLI per Video → SRT (ottimizzata per italiano)
"""

import argparse
import os
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

from engine import run_pipeline, check_ffmpeg, check_whisper, MODELS, DEFAULT_MODEL


def main():
    parser = argparse.ArgumentParser(
        description="Trascrizione automatica video/audio → SRT (italiano)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  python transcribe.py video.mp4
  python transcribe.py video.mp4 -m large-v3-turbo
  python transcribe.py video.mp4 -m small
  python transcribe.py video.mp4 --beam 10
  python transcribe.py video.mp4 --no-vad
        """,
    )
    parser.add_argument("input", help="File video o audio da trascrivere")
    parser.add_argument("-m", "--model", default=DEFAULT_MODEL,
                        choices=list(MODELS.keys()),
                        help=f"Modello Whisper (default: {DEFAULT_MODEL})")
    parser.add_argument("-o", "--output", default=None,
                        help="Percorso file SRT di output")
    parser.add_argument("--beam", type=int, default=5,
                        help="Beam size (default: 5)")
    parser.add_argument("--no-vad", action="store_true",
                        help="Disattiva il filtro VAD")
    args = parser.parse_args()

    input_path = os.path.abspath(args.input)
    if not os.path.isfile(input_path):
        sys.exit(f"❌ File non trovato: {input_path}")
    if not check_ffmpeg():
        sys.exit("❌ FFmpeg non trovato. Installalo: brew install ffmpeg")
    if not check_whisper():
        sys.exit("❌ faster-whisper non installato. Esegui: pip install faster-whisper")

    output_path = args.output or str(Path(input_path).with_suffix(".srt"))
    info = MODELS.get(args.model, {})

    print("=" * 55)
    print("🎬 Video/Audio → SRT  (Ottimizzato per italiano)")
    print("=" * 55)
    print(f"   Input:     {Path(input_path).name}")
    print(f"   Modello:   {args.model} {info.get('quality', '')}")
    print(f"   Beam size: {args.beam}")
    print(f"   VAD:       {'Attivo' if not args.no_vad else 'Off'}")
    print(f"   Output:    {Path(output_path).name}")
    print("=" * 55)

    try:
        result = run_pipeline(
            input_path=input_path, output_path=output_path,
            model_size=args.model, beam_size=args.beam,
            vad_filter=not args.no_vad,
            on_status=lambda msg: print(f"   {msg}"),
        )
        print(f"\n🎉 File SRT generato: {result}")
    except KeyboardInterrupt:
        print("\n\n⏹  Interrotto dall'utente.")
        sys.exit(130)
    except RuntimeError as e:
        sys.exit(f"❌ {e}")


if __name__ == "__main__":
    main()
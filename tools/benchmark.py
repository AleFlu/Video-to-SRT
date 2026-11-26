"""Benchmark della trascrizione su clip corte: tempi, testo e (dove c'è) errore sulle parole.

Trascrive ogni video di una cartella con le impostazioni predefinite dell'app e salva un
JSON. Con ``--confronta`` lo paragona a un'esecuzione precedente: serve a controllare,
prima e dopo una modifica, che il testo resti identico e i tempi non peggiorino.

Riferimenti facoltativi in ``<cartella>/riferimenti/`` (vedi il LEGGIMI lì):
``<clip>.srt`` testo corretto a mano, ``<clip>.ignora.txt`` tratti "inizio-fine" da non
contare. Con un riferimento si calcola il WER (parole sbagliate, mancanti o in più sul
totale delle parole giuste).

Uso, dalla cartella ``app``:
    ../.venv/bin/python ../tools/benchmark.py <cartella clip> prima.json
    ../.venv/bin/python ../tools/benchmark.py <cartella clip> dopo.json --confronta prima.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".mp3", ".wav", ".m4a"}


def words(text: str) -> list:
    """Parole minuscole senza punteggiatura (l'apostrofo separa: "l'altra" → l, altra)."""
    return re.findall(r"\w+", text.lower())


def wer(ref: list, hyp: list) -> float:
    """Distanza di modifica tra liste di parole, sul numero di parole del riferimento."""
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / len(ref)


def ignored_ranges(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*([\d.]+)\s*-\s*([\d.]+)", line)
        if m:
            out.append((float(m.group(1)), float(m.group(2))))
    return out


def counted_text(subs, ranges) -> list:
    """Parole dei sottotitoli il cui centro non cade in un tratto da ignorare."""
    kept = []
    for start, end, text in subs:
        mid = (start + end) / 2
        if not any(a <= mid <= b for a, b in ranges):
            kept.extend(words(text))
    return kept


def run(folder: Path, model: str) -> dict:
    import engine
    from core.srt_io import parse_srt
    from core.transcription_config import TranscriptionConfig

    config = TranscriptionConfig(model_size=model)
    t0 = time.perf_counter()
    engine._get_or_load_model(model)
    result = {"model": model, "load_s": round(time.perf_counter() - t0, 1), "clips": {}}
    refs = folder / "riferimenti"
    for clip in sorted(p for p in folder.iterdir() if p.suffix.lower() in VIDEO_EXTS):
        t = time.perf_counter()
        subs = engine.transcribe(
            str(clip), model_size=model, beam_size=config.beam_size,
            vad_filter=config.vad_filter, denoise=config.denoise, language=config.language,
            config=config)
        secs = time.perf_counter() - t
        rows = [(s["start"], s["end"], s["text"]) for s in subs]
        entry = {"secs": round(secs, 1), "n_subs": len(rows),
                 "subs": [[round(a, 3), round(b, 3), x] for a, b, x in rows]}
        ref = refs / f"{clip.stem}.srt"
        if ref.exists():
            ranges = ignored_ranges(refs / f"{clip.stem}.ignora.txt")
            good = [(s.start, s.end, s.text) for s in parse_srt(str(ref))]
            entry["wer"] = round(wer(counted_text(good, ranges), counted_text(rows, ranges)), 4)
        result["clips"][clip.name] = entry
        extra = f"  WER {entry['wer']:.1%}" if "wer" in entry else ""
        print(f"{secs:7.1f} s  {len(rows):3d} sottotitoli  {clip.name}{extra}", flush=True)
    result["total_s"] = round(sum(c["secs"] for c in result["clips"].values()), 1)
    print(f"Totale {result['total_s']} s (caricamento modello {result['load_s']} s)")
    return result


def compare(before: dict, after: dict) -> bool:
    """Stampa il confronto; False se un testo è cambiato."""
    same_all = True
    print(f"\n{'clip':40s} {'prima':>8s} {'dopo':>8s} {'diff':>7s}  testo")
    for name, b in before["clips"].items():
        a = after["clips"].get(name)
        if a is None:
            print(f"{name:40s} mancante nell'esecuzione nuova")
            same_all = False
            continue
        same = b["subs"] == a["subs"]
        same_all &= same
        diff = (a["secs"] - b["secs"]) / b["secs"] if b["secs"] else 0.0
        note = "identico" if same else "CAMBIATO"
        if "wer" in a:
            note += f" (WER {b.get('wer', 0):.1%} → {a['wer']:.1%})"
        print(f"{name[:40]:40s} {b['secs']:7.1f}s {a['secs']:7.1f}s {diff:+7.1%}  {note}")
    tb, ta = before["total_s"], after["total_s"]
    print(f"{'Totale':40s} {tb:7.1f}s {ta:7.1f}s {(ta - tb) / tb:+7.1%}")
    return same_all


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cartella", type=Path)
    ap.add_argument("uscita", type=Path)
    ap.add_argument("--modello", default="large-v3")
    ap.add_argument("--confronta", type=Path, help="JSON di un'esecuzione precedente")
    args = ap.parse_args()
    args.cartella, args.uscita = args.cartella.resolve(), args.uscita.resolve()
    if args.confronta:
        args.confronta = args.confronta.resolve()
    os.chdir(Path(__file__).resolve().parent.parent / "app")
    result = run(args.cartella, args.modello)
    args.uscita.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.confronta:
        return 0 if compare(json.loads(args.confronta.read_text(encoding="utf-8")), result) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
self_test.py — Autotest dell'app (``Video-to-SRT --self-test``).

Serve a verificare un'app compilata su un computer diverso da quello della build (o in
CI): controlla che ci siano davvero tutti i pezzi che a sorgente si danno per scontati —
ffmpeg con i filtri e gli encoder usati, CTranslate2, faster-whisper e il VAD Silero, i
plugin Qt (multimedia, SVG), i font — e fa una piccola esportazione video vera.

Non scarica il modello Whisper: se manca lo segnala come informazione, non come errore.
Esito: codice di uscita 0 (tutto bene) o 1; righe "OK"/"ERRORE"/"INFO" su stdout (se c'è)
e, con ``--self-test-report PERCORSO``, anche in un file (le app per Windows senza console
non hanno stdout).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

Result = Tuple[str, str, str]      # (esito, controllo, dettaglio)


def _ffmpeg() -> str:
    from core.burn_in import ffmpeg_path
    path = ffmpeg_path()
    if not path:
        raise RuntimeError("ffmpeg non trovato (né nell'app né nel PATH)")
    return path


def _run(cmd: List[str]) -> subprocess.CompletedProcess:
    import platform_support
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=120,
                          **platform_support.subprocess_kwargs())


def check_ffmpeg() -> str:
    ff = _ffmpeg()
    out = _run([ff, "-hide_banner", "-version"])
    if out.returncode != 0:
        raise RuntimeError(f"ffmpeg non si avvia: {out.stderr.strip()[-200:]}")
    filters = _run([ff, "-hide_banner", "-filters"]).stdout
    missing = [f for f in ("overlay", "afftdn", "loudnorm", "highpass") if f" {f} " not in filters]
    if missing:
        raise RuntimeError(f"filtri ffmpeg mancanti: {', '.join(missing)}")
    return f"{ff} — {out.stdout.splitlines()[0]}"


def check_encoders() -> str:
    from core.burn_in import VideoInfo, video_encoders
    encs = video_encoders(_ffmpeg(), VideoInfo(64, 64, 1.0, True))
    return "encoder video: " + ", ".join(e[1] for e in encs)


def check_ctranslate2() -> str:
    import ctranslate2
    types = sorted(ctranslate2.get_supported_compute_types("cpu"))
    if "int8" not in types and "int8_float32" not in types:
        raise RuntimeError(f"CTranslate2 senza int8: {types}")
    return f"CTranslate2 {ctranslate2.__version__}, cpu: {', '.join(types)}"


def check_vad() -> str:
    import numpy as np

    import engine
    engine._setup_environment()
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    get_speech_timestamps(np.zeros(16000, dtype=np.float32), VadOptions())
    return "VAD Silero caricato"


def check_qt() -> str:
    from PySide6.QtCore import QByteArray
    from PySide6.QtMultimedia import QMediaFormat
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import QApplication

    from ui import icons
    from ui.fonts import load_app_fonts

    QApplication.instance() or QApplication([sys.argv[0]])
    families = load_app_fonts()
    if not families:
        raise RuntimeError("font IBM Plex non caricati")
    svg = icons.svg_markup("search", icons.theme.qcolor("text"))
    if not QSvgRenderer(QByteArray(svg.encode("utf-8"))).isValid():
        raise RuntimeError("plugin SVG mancante")
    decoders = QMediaFormat().supportedFileFormats(QMediaFormat.Decode)
    if not decoders:
        raise RuntimeError("Qt Multimedia senza backend (anteprima video non funzionerebbe)")
    return f"font {', '.join(families)}; Qt Multimedia: {len(decoders)} formati"


def check_export_and_preprocess() -> str:
    """Mini video vero: pre-elaborazione dell'audio come per la trascrizione e
    esportazione con i sottotitoli impressi."""
    import engine
    from core.burn_in import burn_in, probe
    ff = _ffmpeg()
    with tempfile.TemporaryDirectory(prefix="videosrt_selftest_") as tmp:
        src = Path(tmp) / "prova.mp4"
        made = _run([ff, "-hide_banner", "-loglevel", "error",
                     "-f", "lavfi", "-i", "color=c=gray:size=320x240:rate=25",
                     "-f", "lavfi", "-i", "sine=frequency=440", "-t", "1",
                     "-c:v", "mpeg4", "-c:a", "aac", "-y", str(src)])
        if made.returncode != 0:
            raise RuntimeError(f"video di prova non creato: {made.stderr.strip()[-200:]}")
        wav = engine.preprocess_audio(str(src))
        if not wav or not os.path.getsize(wav):
            raise RuntimeError("pre-elaborazione dell'audio non riuscita")
        os.unlink(wav)
        out = Path(tmp) / "con sottotitoli.mp4"
        t = time.time()
        burn_in(str(src), [(0.1, 0.9, "Prova")], str(out))
        info = probe(ff, str(out))
        if (info.width, info.height) != (320, 240) or not info.has_audio:
            raise RuntimeError(f"video esportato inatteso: {info}")
        return f"audio pre-elaborato; video esportato in {time.time() - t:.1f} s"


def check_spelling() -> str:
    from core.spelling import Speller
    sp = Speller(user_words=[])
    if not sp.available:
        raise RuntimeError("dizionario italiano non caricato")
    if not sp.is_known("cittadino") or sp.is_known("cittadinno"):
        raise RuntimeError("il dizionario italiano non riconosce le parole")
    return "dizionario italiano"


def check_model() -> Optional[str]:
    """Solo informativo: il modello si scarica alla prima trascrizione."""
    import engine
    size = engine.recommended_model()
    state = "presente" if engine.is_model_available(size) else "da scaricare alla prima trascrizione"
    return f"modello consigliato {size}: {state}"


CHECKS: List[Tuple[str, Callable[[], Optional[str]], bool]] = [
    # (nome, funzione, obbligatorio)
    ("ffmpeg", check_ffmpeg, True),
    ("encoder", check_encoders, True),
    ("CTranslate2", check_ctranslate2, True),
    ("VAD", check_vad, True),
    ("Qt", check_qt, True),
    ("esportazione", check_export_and_preprocess, True),
    ("ortografia", check_spelling, True),
    ("modello", check_model, False),
]


def run_checks(checks=None) -> List[Result]:
    results: List[Result] = []
    for name, fn, required in (CHECKS if checks is None else checks):
        try:
            detail = fn() or ""
            results.append(("OK" if required else "INFO", name, detail))
        except Exception as e:  # noqa: BLE001 — ogni guasto va riportato, non sollevato
            logger.debug("Autotest %s:\n%s", name, traceback.format_exc())
            results.append(("ERRORE" if required else "INFO", name, f"{type(e).__name__}: {e}"))
    return results


def report_text(results: List[Result]) -> str:
    lines = [f"{state:<6} {name}: {detail}" for state, name, detail in results]
    ok = all(state != "ERRORE" for state, _n, _d in results)
    lines.append("Autotest superato" if ok else "Autotest NON superato")
    return "\n".join(lines) + "\n"


def main(argv: List[str]) -> int:
    """Esegue l'autotest; ``--self-test-report PERCORSO`` scrive anche un file."""
    report_path = None
    if "--self-test-report" in argv:
        i = argv.index("--self-test-report")
        if i + 1 < len(argv):
            report_path = argv[i + 1]
    results = run_checks()
    text = report_text(results)
    if sys.stdout is not None:
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except (OSError, ValueError):
            pass
    if report_path:
        Path(report_path).write_text(text, encoding="utf-8")
    return 0 if all(state != "ERRORE" for state, _n, _d in results) else 1

"""
burn_in.py — Video con i sottotitoli impressi nell'immagine ("burn-in").

I sottotitoli sono disegnati con Qt (riquadro scuro e testo bianco, come nell'anteprima)
in PNG trasparenti grandi quanto il fotogramma; ffmpeg li sovrappone al video con il filtro
``overlay``, leggendoli come una sequenza di immagini con le loro durate (concat demuxer).
Così non serve un ffmpeg con libass o freetype: quello di Homebrew non li ha.

L'uscita è sempre MP4 (H.264 + AAC), adatta a reel e social.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from PySide6.QtCore import QRectF, QThread, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter

import platform_support

logger = logging.getLogger(__name__)

_POLL_S = 0.2
_BOX_ALPHA = 170            # riquadro dietro il testo: nero semitrasparente
_MIN_SEGMENT_S = 0.001      # le durate più brevi vengono saltate (concat non le accetta)


class BurnInError(RuntimeError):
    """Esportazione del video non riuscita (messaggio in italiano)."""


class BurnInCancelled(Exception):
    """Esportazione annullata dall'utente."""


# ── Informazioni sul video ───────────────────────────────────────────────────

@dataclass(frozen=True)
class VideoInfo:
    width: int           # dimensioni come si vede il video (rotazione già applicata)
    height: int
    duration: float      # secondi
    has_audio: bool
    bitrate_kbps: int = 0   # bitrate complessivo dichiarato dal file (0 = sconosciuto)


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_VIDEO_RE = re.compile(r"Stream #\S+.*?: Video: .*?(\d{2,5})x(\d{2,5})")
_ROTATION_RE = re.compile(r"rotation of (-?\d+(?:\.\d+)?) degrees")
_BITRATE_RE = re.compile(r"Duration:.*?bitrate:\s*(\d+)\s*kb/s")


def parse_probe(stderr: str) -> Optional[VideoInfo]:
    """VideoInfo dall'output di ``ffmpeg -i`` (None se non c'è una traccia video)."""
    video = _VIDEO_RE.search(stderr)
    if not video:
        return None
    width, height = int(video.group(1)), int(video.group(2))
    rotation = _ROTATION_RE.search(stderr[video.start():])
    if rotation and round(abs(float(rotation.group(1)))) % 180 == 90:
        width, height = height, width          # video del telefono girato di 90°
    duration = 0.0
    m = _DURATION_RE.search(stderr)
    if m:
        duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    has_audio = re.search(r"Stream #\S+.*?: Audio:", stderr) is not None
    rate = _BITRATE_RE.search(stderr)
    return VideoInfo(width, height, duration, has_audio, int(rate.group(1)) if rate else 0)


def ffmpeg_path() -> Optional[str]:
    """ffmpeg incluso nell'app o nel PATH (None se manca)."""
    try:
        from engine import get_bundled_ffmpeg
        bundled = get_bundled_ffmpeg()
    except Exception:  # noqa: BLE001 — motore non importabile: si cerca nel PATH
        bundled = None
    return bundled or shutil.which(platform_support.ffmpeg_executable_name())


def probe(ffmpeg: str, path: str) -> VideoInfo:
    """Dimensioni, durata e audio del video ``path``."""
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-i", path],
                             capture_output=True, text=True, errors="replace", timeout=60,
                             **platform_support.subprocess_kwargs())
    except (OSError, subprocess.SubprocessError) as e:
        raise BurnInError(f"Impossibile leggere il video ({e}).") from e
    info = parse_probe(out.stderr)
    if info is None:
        raise BurnInError("Il file non contiene una traccia video.")
    return info


# ── Disegno dei sottotitoli ──────────────────────────────────────────────────

@dataclass(frozen=True)
class SubtitleStyle:
    font_px: int
    bottom_margin: int    # dal fondo dell'immagine al riquadro
    max_text_w: int       # larghezza massima di una riga
    pad_h: int
    pad_v: int


def style_for(width: int, height: int) -> SubtitleStyle:
    """Stile in proporzione al fotogramma. Nei video verticali (reel) i sottotitoli stanno
    più in alto, sopra i pulsanti e le didascalie dei social."""
    short = min(width, height)
    font_px = max(14, round(short * 0.05))
    vertical = height > width
    bottom = round(height * (0.20 if vertical else 0.07))
    return SubtitleStyle(font_px=font_px, bottom_margin=bottom,
                         max_text_w=round(width * (0.84 if vertical else 0.80)),
                         pad_h=max(6, round(font_px * 0.4)),
                         pad_v=max(3, round(font_px * 0.18)))


def _wrap(text: str, fm: QFontMetricsF, max_w: float) -> List[str]:
    """Righe del sottotitolo (gli a capo del testo restano; le righe troppo lunghe vanno a
    capo tra le parole)."""
    lines: List[str] = []
    for raw in text.splitlines():
        current = ""
        for word in raw.split():
            test = f"{current} {word}".strip()
            if not current or fm.horizontalAdvance(test) <= max_w:
                current = test
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines


def render_subtitle(text: str, width: int, height: int) -> QImage:
    """Fotogramma trasparente ``width``×``height`` con il sottotitolo in basso al centro."""
    img = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    style = style_for(width, height)
    font = QFont(platform_support.ui_font_family())
    font.setPixelSize(style.font_px)
    font.setWeight(QFont.DemiBold)
    fm = QFontMetricsF(font)
    lines = _wrap(text, fm, style.max_text_w - 2 * style.pad_h)
    if not lines:
        return img
    line_h = fm.height()
    box_w = max(fm.horizontalAdvance(line) for line in lines) + 2 * style.pad_h
    box_h = line_h * len(lines) + 2 * style.pad_v
    box = QRectF((width - box_w) / 2, height - style.bottom_margin - box_h, box_w, box_h)

    p = QPainter(img)
    try:
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, _BOX_ALPHA))
        p.drawRoundedRect(box, style.pad_v, style.pad_v)
        p.setFont(font)
        p.setPen(QColor(Qt.white))
        for i, line in enumerate(lines):
            x = (width - fm.horizontalAdvance(line)) / 2
            y = box.top() + style.pad_v + fm.ascent() + i * line_h
            p.drawText(round(x), round(y), line)
    finally:
        p.end()
    return img


# ── Sequenza delle immagini ──────────────────────────────────────────────────

Cue = Tuple[float, float, str]


def overlay_timeline(cues: Sequence[Cue], duration: float) -> List[Tuple[Optional[int], float]]:
    """Sequenza ``(indice del sottotitolo o None = vuoto, durata)`` che copre 0–``duration``.

    I sottotitoli sono in ordine di inizio; uno che si sovrappone al precedente comincia
    dove l'altro finisce, e niente va oltre la fine del video.
    """
    order = sorted(range(len(cues)), key=lambda i: cues[i][0])
    out: List[Tuple[Optional[int], float]] = []
    t = 0.0
    for i in order:
        start, end, text = cues[i]
        start = max(t, float(start))
        end = min(float(end), duration) if duration > 0 else float(end)
        if not text.strip() or end - start < _MIN_SEGMENT_S:
            continue
        if start - t >= _MIN_SEGMENT_S:
            out.append((None, start - t))
        out.append((i, end - start))
        t = end
    tail = (duration - t) if duration > 0 else 0.0
    out.append((None, max(tail, 0.04)))
    return out


def _concat_quote(path: Path) -> str:
    # barre in avanti anche su Windows: ffmpeg le accetta e non vanno interpretate
    return "'" + path.as_posix().replace("'", "'\\''") + "'"


def write_overlay_sequence(cues: Sequence[Cue], info: VideoInfo, folder: Path,
                           cancel_event: Optional[threading.Event] = None) -> Path:
    """Disegna i sottotitoli in ``folder`` e scrive l'elenco per il concat demuxer."""
    blank = folder / "vuoto.png"
    render_subtitle("", info.width, info.height).save(str(blank), "PNG")
    lines = ["ffconcat version 1.0"]
    last = blank
    for idx, dur in overlay_timeline(cues, info.duration):
        if cancel_event is not None and cancel_event.is_set():
            raise BurnInCancelled()
        if idx is None:
            path = blank
        else:
            path = folder / f"sub_{idx:05d}.png"
            if not path.exists():
                img = render_subtitle(cues[idx][2], info.width, info.height)
                if not img.save(str(path), "PNG"):
                    raise BurnInError("Impossibile preparare le immagini dei sottotitoli.")
        lines += [f"file {_concat_quote(path)}", f"duration {dur:.3f}"]
        last = path
    lines.append(f"file {_concat_quote(last)}")   # l'ultima durata vale solo se si ripete
    listing = folder / "sottotitoli.ffconcat"
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return listing


# ── Comando ffmpeg ───────────────────────────────────────────────────────────

_HW_MIN_KBPS = 4000
_HW_MAX_KBPS = 20000


def video_encoders(ffmpeg: str, info: VideoInfo) -> List[List[str]]:
    """Encoder H.264 da provare in ordine, tra quelli dell'ffmpeg disponibile.

    Prima quello hardware del Mac (VideoToolbox: ~6 volte più veloce; bitrate pari a quello
    della sorgente, così il file non pesa più dell'originale), poi libx264, poi quello di
    Windows; mpeg4 come ultima risorsa. Se uno fallisce si passa al successivo.
    """
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-encoders"],
                             capture_output=True, text=True, errors="replace", timeout=30,
                             **platform_support.subprocess_kwargs()).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    names = set(re.findall(r"^\s*V\S*\s+(\S+)", out, re.MULTILINE))
    kbps = min(_HW_MAX_KBPS, max(_HW_MIN_KBPS, info.bitrate_kbps or 10000))
    candidates: List[List[str]] = []
    if "h264_videotoolbox" in names:
        candidates.append(["-c:v", "h264_videotoolbox", "-b:v", f"{kbps}k"])
    if "libx264" in names:
        candidates.append(["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"])
    if "h264_mf" in names:
        candidates.append(["-c:v", "h264_mf", "-b:v", f"{kbps}k"])
    candidates.append(["-c:v", "mpeg4", "-q:v", "2"])
    return candidates


def build_command(ffmpeg: str, source: str, listing: Path, output: str, info: VideoInfo,
                  encoder_args: Sequence[str]) -> List[str]:
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y",
           "-i", source,
           "-f", "concat", "-safe", "0", "-i", str(listing),
           "-filter_complex",
           "[1:v]format=rgba[sub];"
           "[0:v][sub]overlay=0:0:eof_action=pass:format=auto,format=yuv420p[v]",
           "-map", "[v]"]
    if info.has_audio:
        cmd += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "192k"]
    cmd += list(encoder_args)
    cmd += ["-movflags", "+faststart", "-progress", "pipe:1", "-nostats", output]
    return cmd


def _stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def burn_in(source: str, cues: Sequence[Cue], output: str, *,
            ffmpeg: Optional[str] = None,
            on_progress: Optional[Callable[[float], None]] = None,
            cancel_event: Optional[threading.Event] = None) -> None:
    """Scrive in ``output`` (MP4) il video ``source`` con i sottotitoli ``cues`` impressi.

    ``cues`` = ``(inizio, fine, testo)`` in secondi. ``on_progress`` riceve 0–1.
    Annullabile con ``cancel_event`` (BurnInCancelled; il file parziale viene rimosso).
    """
    ffmpeg = ffmpeg or ffmpeg_path()
    if not ffmpeg:
        raise BurnInError("ffmpeg non trovato: serve per esportare il video.")
    if os.path.abspath(source) == os.path.abspath(output):
        raise BurnInError("Il video esportato non può sostituire quello originale.")
    info = probe(ffmpeg, source)

    shown = [0.0]

    def progress(value: float) -> None:
        value = max(shown[0], min(1.0, value))     # mai all'indietro
        shown[0] = value
        if on_progress:
            on_progress(value)

    progress(0.0)
    with tempfile.TemporaryDirectory(prefix="videosrt_burn_") as tmp:
        tmp_dir = Path(tmp)
        listing = write_overlay_sequence(cues, info, tmp_dir, cancel_event)
        progress(0.02)
        encoders = video_encoders(ffmpeg, info)
        for n, encoder in enumerate(encoders):
            cmd = build_command(ffmpeg, source, listing, output, info, encoder)
            try:
                _run_ffmpeg(cmd, info.duration, tmp_dir / f"ffmpeg_{n}.log", output,
                            progress, cancel_event)
                break
            except BurnInError as e:
                if n == len(encoders) - 1:
                    raise
                logger.warning("Encoder %s non riuscito, provo il successivo: %s",
                               encoder[1], e)
    progress(1.0)


def _run_ffmpeg(cmd: List[str], duration: float, err_path: Path, output: str,
                progress: Callable[[float], None],
                cancel_event: Optional[threading.Event]) -> None:
    """Esegue ffmpeg riportando l'avanzamento; file parziale rimosso se non riesce."""
    logger.info("Esportazione video con sottotitoli: %s", " ".join(cmd))
    ok = False
    with open(err_path, "w", encoding="utf-8", errors="replace") as err:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, text=True,
                                errors="replace", bufsize=1,
                                **platform_support.subprocess_kwargs())
        reader = threading.Thread(target=_read_progress, args=(proc, duration, progress),
                                  daemon=True)
        reader.start()
        try:
            while proc.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    _stop(proc)
                    raise BurnInCancelled()
                time.sleep(_POLL_S)
            reader.join(2)
            ok = proc.returncode == 0
        finally:
            if proc.poll() is None:
                _stop(proc)
            if not ok:
                _remove(output)
    if not ok:
        tail = err_path.read_text(encoding="utf-8", errors="replace").strip()
        tail = "\n".join(tail.splitlines()[-6:])
        logger.warning("ffmpeg (burn-in) fallito, codice %s:\n%s", proc.returncode, tail)
        raise BurnInError(f"ffmpeg non è riuscito a creare il video.\n\n{tail}")


def _read_progress(proc: subprocess.Popen, duration: float,
                   progress: Callable[[float], None]) -> None:
    """Legge ``-progress pipe:1`` (``out_time_us=…``) e riporta l'avanzamento 2–99 %."""
    if proc.stdout is None:
        return
    for line in proc.stdout:
        key, _, value = line.strip().partition("=")
        if key in ("out_time_us", "out_time_ms") and duration > 0:
            try:
                seconds = int(value) / 1e6
            except ValueError:
                continue
            progress(0.02 + 0.97 * min(1.0, seconds / duration))


def _remove(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


# ── Thread per la UI ─────────────────────────────────────────────────────────

class BurnInWorker(QThread):
    """Esegue ``burn_in`` fuori dal thread della UI.

    Segnali: ``progress(float)`` 0–1, ``done(str)`` percorso del video, ``failed(str)``,
    ``cancelled()``.
    """

    progress = Signal(float)
    done = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, source: str, cues: Sequence[Cue], output: str, parent=None):
        super().__init__(parent)
        self.source = source
        self.cues = list(cues)
        self.output = output
        self._cancel = threading.Event()

    def request_cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:  # noqa: D401 — override QThread
        try:
            burn_in(self.source, self.cues, self.output,
                    on_progress=self.progress.emit, cancel_event=self._cancel)
        except BurnInCancelled:
            self.cancelled.emit()
        except BurnInError as e:
            self.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001 — qualsiasi errore va mostrato all'utente
            logger.exception("Esportazione video non riuscita")
            self.failed.emit(str(e) or type(e).__name__)
        else:
            self.done.emit(self.output)

"""
engine.py — Core della trascrizione (ottimizzato per italiano)

Stack: faster-whisper (CTranslate2) + large-v3 + VAD Silero, WhisperX opzionale.
Compatibile: Python 3.9+, macOS (Apple Silicon e Intel), Windows, Linux.
Le differenze tra sistemi operativi passano da ``platform_support``.
"""

from __future__ import annotations

import gc
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from core.constants import MAX_CHARS_PER_LINE  # noqa: F401 — riesportata per compatibilità
from core.constants import normalize_language
from core.subtitle_layout import (
    MAX_WORD_S, LayoutRules, find_uncovered_speech, is_stretched, layout,
    light_punctuation, words_from_segments,
)
from core.transcription_config import ITALIAN_PROMPT  # noqa: F401 — riesportata per compatibilità
from core.transcription_config import TranscriptionConfig, VadOptions
from core import whisper_models
from platform_support import (
    cpu_threads, ffmpeg_executable_name, subprocess_kwargs, total_ram_bytes,
)

logger = logging.getLogger(__name__)


class TranscriptionCancelled(Exception):
    """Eccezione sollevata quando l'utente annulla la trascrizione."""


def _check_cancel(cancel_event: Optional[threading.Event]) -> None:
    """Solleva ``TranscriptionCancelled`` se l'utente ha richiesto l'annullamento."""
    if cancel_event is not None and cancel_event.is_set():
        raise TranscriptionCancelled("Trascrizione annullata dall'utente")


# ============================================================
# Cache e stato globale
# ============================================================
# La cache è condivisa tra il thread di pre-caricamento (main.py) e i QThread
# di trascrizione: ogni accesso passa da _model_lock.
_model_cache: Dict = {"model": None, "model_key": None}
_model_lock = threading.RLock()
_setup_done = False


# ============================================================
# Backend detection
# ============================================================
def _has_whisperx() -> bool:
    """WhisperX: allineamento fonetico wav2vec2 per timestamp precisi."""
    try:
        import whisperx  # noqa: F401
        return True
    except ImportError:
        return False


def high_accuracy_unavailable_reason() -> str:
    """Motivo per cui la modalità "Alta precisione" non è utilizzabile ("" se lo è).

    Non importa WhisperX (trascinerebbe PyTorch all'avvio): controlla solo che il
    pacchetto sia installato.
    """
    if _is_frozen():
        return "Non inclusa in questa versione dell'app"
    import importlib.util
    try:
        found = importlib.util.find_spec("whisperx") is not None
    except (ImportError, ValueError):
        found = False
    return "" if found else "WhisperX non è installato (pip install whisperx)"


def high_accuracy_available() -> bool:
    """True se la modalità "Alta precisione" (WhisperX) può essere usata."""
    return high_accuracy_unavailable_reason() == ""


# ============================================================
# Configurazione
# ============================================================
# I valori predefiniti di prompt iniziale, glossario, decodifica e VAD vivono in
# core.transcription_config e si possono cambiare con un file .vsrtconfig; qui restano
# i nomi storici (ITALIAN_PROMPT è importato da lì).
VAD_PARAMS = VadOptions().as_dict()

# ============================================================
# Post-processing: correzione italianizzazioni Whisper
# ============================================================
# Lista di (pattern_regex, replacement) ordinata dalla più specifica alla più generica.
# Il pattern deve fare match su quello che Whisper produce con language=it e MAI su una
# parola italiana comune ("Le api fanno il miele", "debuggare", "la UIF"): nel dubbio la
# regola non c'è (vedi test_codeswitching_leaves_everyday_italian_unchanged).
_CODESWITCHING_CORRECTIONS: List = [
    # --- ML / AI ---
    (r"\bmacchin(?:a)?\s*l[ae]rning\b",             "machine learning"),
    (r"\bdip\s*l[ae]rning\b",                        "deep learning"),
    (r"\bneur[ao]l\s*n[ae]twork[s]?\b",              "neural network"),
    (r"\bnatural\s*l[ae]nguage\b",                   "natural language"),
    (r"\blarg[e]?\s*l[ae]nguage\s*model[s]?\b",      "large language model"),
    (r"\bl\.?l\.?m\.?\b",                            "LLM"),
    (r"\bfain\s*t[iu]n(?:ing|are|ato|ata|ati|ate)?\b","fine-tuning"),
    (r"\bover\s*fit(?:ting|tare|tato)?\b",            "overfitting"),
    (r"\bdata\s*set[s]?\b",                           "dataset"),
    (r"\bbench\s*mark[s]?\b",                         "benchmark"),

    # --- Infrastruttura / DevOps ---
    (r"\bdeploi\b",                                  "deploy"),
    (r"\bfr[ae]mework[s]?\b",                         "framework"),
    (r"\bb[ae]ck\s*end\b",                            "backend"),
    (r"\bfront\s*end\b",                              "frontend"),
    (r"\bfull\s*stack\b",                             "full stack"),
    (r"\bpip[ae]line[s]?\b",                          "pipeline"),
    (r"\bdoch[ae]r\b",                                "Docker"),
    (r"\bcubernetis\b",                               "Kubernetes"),
    (r"\bcluod\b",                                    "cloud"),
    (r"\bsirver[s]?\b",                               "server"),
    (r"\bsir\s*ver[s]?\b",                            "server"),

    # --- Sviluppo software ---
    (r"\bdabug\b",                                    "debug"),
    (r"\brifactoring\b",                              "refactoring"),
    (r"\bpull\s*r[ae]qu[ae]st[s]?\b",                "pull request"),
    (r"\bcodi[ck]\s*base\b",                          "codebase"),
    (r"\bgit\s*hab\b",                                "GitHub"),
    (r"\bgit\s*lab\b",                                "GitLab"),

    # --- Web / Social media ---
    (r"\bsocial\s*m[ae]dia\b",                        "social media"),
    (r"\bconten[t]?\s*cr[ae]ator[s]?\b",              "content creator"),
    (r"\binfl[iu][ae]nc[ae]r[s]?\b",                  "influencer"),
    (r"\bstr[ae]aming\b",                              "streaming"),
    (r"\bstr[ae]am[s]?\b",                             "stream"),
    (r"\bstor(?:ies|i)\b",                             "stories"),

    # --- Anglicismi tech generici ---
    (r"\bfeat[iu]r[ae][s]?\b",                        "feature"),
    (r"\bscr[ae]enshot[s]?\b",                        "screenshot"),
    (r"\bh[ae]rduer[ae]\b",                            "hardware"),
    (r"\bs[ao]ftuer[ae]\b",                            "software"),
    (r"\bu[ae]ks\b",                                   "UX"),
    # "api" sono anche le api del miele: solo davanti a un termine tecnico
    (r"\bapi(?=\s+(?:rest|restful|key|keys|endpoint|endpoints|gateway)\b)", "API"),
    (r"\bsdk[s]?\b",                                   "SDK"),

    # --- Business / Startup ---
    (r"\bstar[t]?\s*ap[s]?\b",                        "startup"),
    (r"\bsceil[iu]\s*ap\b",                            "scale-up"),
    (r"\bfandr[ae]ising\b",                            "fundraising"),
    (r"\bbrandin[gh]\b",                               "branding"),
    (r"\bmark[ae]ting\b",                              "marketing"),

    # --- Comune / Quotidiano ---
    (r"\bui[ck]\s*end\b",                              "weekend"),
    (r"\bwi[ck]\s*end\b",                              "weekend"),
    (r"\bci[ck]\s*end\b",                              "weekend"),
    (r"\bci\s*end\b",                                  "weekend"),
]


def _postprocess_codeswitching(text: str) -> str:
    """Corregge le italianizzazioni più comuni prodotte da Whisper con language=it.

    Applica sostituzioni regex case-insensitive preservando la capitalizzazione
    originale (tutto-maiuscolo = acronimo, prima-maiuscola = inizio frase/nome).
    """
    for pattern, replacement in _CODESWITCHING_CORRECTIONS:
        def _replace(m: re.Match, repl: str = replacement) -> str:
            original = m.group(0)
            # Acronimi tutto-maiuscolo: API, SDK, LLM, UI, UX
            if original.isupper():
                return repl.upper()
            # Prima lettera maiuscola: inizio frase o nome proprio
            if original and original[0].isupper():
                return repl[0].upper() + repl[1:]
            return repl

        text = re.sub(pattern, _replace, text, flags=re.IGNORECASE)

    return text


# Catalogo, modelli scaricati e download: core.whisper_models (qui riesportati)
MODELS = whisper_models.MODELS
DEFAULT_MODEL = whisper_models.DEFAULT_MODEL


# ============================================================
# Bundle helpers (PyInstaller)
# ============================================================
def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def get_bundled_ffmpeg() -> Optional[str]:
    """Percorso dell'ffmpeg incluso nel bundle PyInstaller, se presente."""
    if _is_frozen():
        p = Path(sys._MEIPASS) / ffmpeg_executable_name()
        return str(p) if p.exists() else None
    return None


def get_bundled_model_dir() -> Optional[str]:
    """Cartella del modello Whisper incluso nel bundle, se presente e non vuota."""
    if _is_frozen():
        d = Path(sys._MEIPASS) / "whisper_model"
        if d.exists() and any(d.iterdir()):
            return str(d)
    return None


def _copy_bundled_vad(bundle_dir: Path) -> None:
    """Copia silero_vad.onnx dal bundle nelle cache attese dalle librerie VAD."""
    vad_onnx = None
    for candidate in (
        bundle_dir / "silero_vad" / "silero_vad.onnx",
        bundle_dir / "faster_whisper" / "assets" / "silero_vad.onnx",
    ):
        if candidate.exists():
            vad_onnx = candidate
            break

    if not vad_onnx:
        for f in bundle_dir.rglob("silero_vad.onnx"):
            vad_onnx = f
            break

    if not vad_onnx:
        logger.debug("silero_vad.onnx non trovato nel bundle")
        return

    for cache_path in (
        Path.home() / ".cache" / "silero-vad",
        Path.home() / ".cache" / "torch" / "hub" / "snakers4_silero-vad_master",
    ):
        try:
            cache_path.mkdir(parents=True, exist_ok=True)
            dst = cache_path / "silero_vad.onnx"
            if not dst.exists():
                shutil.copy2(vad_onnx, dst)
        except OSError as e:
            logger.warning("Copia del modello VAD in %s non riuscita: %s", cache_path, e)


def _setup_environment() -> None:
    """Setup una tantum: thread CPU, PATH di FFmpeg, modello VAD."""
    global _setup_done
    if _setup_done:
        return

    thread_str = str(cpu_threads())
    logger.info("Thread CPU: %s (totale CPU: %s)", thread_str, os.cpu_count())
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "CT2_NUM_THREADS"):
        os.environ.setdefault(var, thread_str)
    os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")

    bundled_ffmpeg = get_bundled_ffmpeg()
    if bundled_ffmpeg:
        ffmpeg_dir = str(Path(bundled_ffmpeg).parent)
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

    if _is_frozen():
        try:
            _copy_bundled_vad(Path(sys._MEIPASS))
        except Exception as e:  # noqa: BLE001 — il VAD ha comunque un fallback
            logger.warning("Preparazione del modello VAD non riuscita: %s", e)

    _setup_done = True


# ============================================================
# Checks
# ============================================================
def check_ffmpeg() -> bool:
    """True se ffmpeg è disponibile (nel bundle o nel PATH)."""
    if get_bundled_ffmpeg():
        return True
    return shutil.which(ffmpeg_executable_name()) is not None


# ============================================================
# Pre-processing audio
# ============================================================
_FFMPEG_TIMEOUT_S = 300.0
_FFMPEG_POLL_S = 0.2


def _stop_process(proc) -> None:
    """Termina un processo figlio (terminate, poi kill se non reagisce)."""
    try:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
    except Exception as e:  # noqa: BLE001 — pulizia best-effort
        logger.debug("Arresto di ffmpeg non riuscito: %s", e)


def preprocess_audio(
    input_path: str,
    on_status: Optional[Callable] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Optional[str]:
    """Estrae l'audio a 16 kHz mono con riduzione rumore. None se non riesce.

    Annullabile: se ``cancel_event`` viene impostato ffmpeg è terminato, il file
    temporaneo rimosso e viene sollevata ``TranscriptionCancelled``.
    """
    _check_cancel(cancel_event)
    if on_status:
        on_status("Pre-elaborazione audio (riduzione rumore)...")

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_path = tmp.name
    tmp.close()

    ffmpeg_cmd = get_bundled_ffmpeg() or ffmpeg_executable_name()

    cmd = [
        ffmpeg_cmd,
        "-i", os.path.abspath(input_path),
        "-vn",
        "-af", ",".join([
            "highpass=f=80",
            "afftdn=nf=-25",
            "loudnorm=I=-16:TP=-1.5:LRA=7",
        ]),
        "-ar", "16000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        "-y",
        tmp_path,
    ]

    def _remove_tmp() -> None:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    ok = False
    proc = None
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            **subprocess_kwargs(),
        )
        deadline = time.monotonic() + _FFMPEG_TIMEOUT_S
        while True:
            if cancel_event is not None and cancel_event.is_set():
                _stop_process(proc)
                _remove_tmp()
                raise TranscriptionCancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(cmd, _FFMPEG_TIMEOUT_S)
            try:
                _out, err = proc.communicate(timeout=min(_FFMPEG_POLL_S, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        if proc.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            ok = True
        else:
            logger.warning("ffmpeg ha restituito %s: %s", proc.returncode, (err or "")[:500])
    except TranscriptionCancelled:
        raise
    except subprocess.TimeoutExpired:
        if proc is not None:
            _stop_process(proc)
        logger.warning("Pre-elaborazione audio interrotta: timeout di ffmpeg")
    except Exception as e:  # noqa: BLE001 — si prosegue con l'audio originale
        if proc is not None and proc.poll() is None:
            _stop_process(proc)
        logger.warning("Pre-elaborazione audio non riuscita: %s", e)

    if ok:
        if on_status:
            on_status("Audio pre-elaborato")
        return tmp_path

    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    if on_status:
        on_status("⚠️ Pre-elaborazione audio non riuscita — uso l'audio originale")
    return None


# ============================================================
# Modello: caricamento e cache
# ============================================================
def get_optimal_device() -> Tuple[str, str]:
    """``("cuda", "float16")`` se CTranslate2 vede una GPU CUDA, altrimenti CPU int8."""
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception as e:  # noqa: BLE001 — in assenza di CUDA si usa la CPU
        logger.debug("Rilevamento CUDA non riuscito: %s", e)
    return "cpu", "int8"


_hardware_cache: Dict[str, Any] = {}


def detect_hardware() -> Tuple[int, bool]:
    """(RAM totale in byte, GPU CUDA presente), letti una volta sola."""
    if "hw" not in _hardware_cache:
        _hardware_cache["hw"] = (total_ram_bytes(), get_optimal_device()[0] == "cuda")
    return _hardware_cache["hw"]


def recommended_model() -> str:
    """Il modello più adatto a questo computer (vedi ``whisper_models.recommend_model``)."""
    return whisper_models.recommend_model(*detect_hardware())


def is_model_available(model_size: str) -> bool:
    """True se il modello si può caricare senza scaricare niente (incluso o in cache)."""
    if model_size == DEFAULT_MODEL and get_bundled_model_dir():
        return True
    return whisper_models.is_downloaded(model_size)


def ensure_model(model_size: str, *, on_status: Optional[Callable] = None,
                 on_progress: Optional[Callable] = None,
                 cancel_event: Optional[threading.Event] = None) -> None:
    """Scarica il modello se manca, con stato e avanzamento (annullabile)."""
    if is_model_available(model_size):
        return
    try:
        whisper_models.download(model_size, on_status=on_status, on_progress=on_progress,
                                cancel_event=cancel_event)
    except whisper_models.DownloadCancelled:
        raise TranscriptionCancelled("Download del modello annullato") from None


def _get_or_load_model(model_size: str = DEFAULT_MODEL,
                       on_status: Optional[Callable] = None):
    """Ritorna il modello faster-whisper, caricandolo una sola volta (thread-safe)."""
    from faster_whisper import WhisperModel

    bundled = get_bundled_model_dir()
    model_path = bundled if (bundled and model_size == DEFAULT_MODEL) else model_size

    device, compute_type = get_optimal_device()
    cache_key = (model_path, device, compute_type)

    with _model_lock:
        if _model_cache["model"] is not None and _model_cache["model_key"] == cache_key:
            if on_status:
                on_status("Modello già pronto")
            return _model_cache["model"]

        # Libera il modello precedente prima di caricarne un altro (memoria)
        if _model_cache["model"] is not None:
            _model_cache["model"] = None
            _model_cache["model_key"] = None
            gc.collect()

        if on_status:
            on_status(f"Caricamento modello '{model_size}'...")

        threads = cpu_threads()
        try:
            import ctranslate2
            logger.info("Tipi di calcolo CTranslate2: %s",
                        ctranslate2.get_supported_compute_types("cpu"))
        except Exception as e:  # noqa: BLE001 — solo diagnostica
            logger.debug("Tipi di calcolo CTranslate2 non disponibili: %s", e)
        logger.info("Modello: %s · device %s · compute %s · %d thread · frozen=%s",
                    model_path, device, compute_type, threads, _is_frozen())

        model = WhisperModel(model_path, device=device, compute_type=compute_type,
                             cpu_threads=threads, num_workers=1)
        _model_cache["model"] = model
        _model_cache["model_key"] = cache_key

    info_str = f"Modello pronto ({device}, {compute_type}, {threads}t)"
    if on_status:
        on_status(info_str)
    logger.info(info_str)
    return model


def preload_model(model_size: str = DEFAULT_MODEL,
                  on_status: Optional[Callable] = None) -> bool:
    """Pre-carica il modello all'avvio se è già sul computer (mai un download allo
    splash: si scarica alla prima trascrizione, con l'avanzamento). False se manca o se
    il caricamento fallisce."""
    if not is_model_available(model_size):
        logger.info("Modello %s non ancora scaricato: niente pre-caricamento", model_size)
        if on_status:
            on_status(f"Modello {model_size} da scaricare alla prima trascrizione")
        return False
    try:
        _setup_environment()
        _get_or_load_model(model_size, on_status=on_status)
        return True
    except Exception as e:  # noqa: BLE001 — l'app parte comunque
        logger.exception("Pre-caricamento del modello fallito")
        if on_status:
            on_status(f"Pre-caricamento fallito: {e}")
        return False


# ============================================================
# Composizione dei sottotitoli
# ============================================================
def _build_subtitles(raw_segments: Sequence[Any], rules: LayoutRules,
                     audio_end: Optional[float], italian: bool,
                     light_punct: bool = False) -> List[Dict]:
    """Segmenti Whisper → sottotitoli definitivi ``{"start", "end", "text", "confidence"}``.

    ``core.subtitle_layout.layout`` decide divisione, testo e tempi (regole Netflix
    italiane); qui si aggiunge solo la correzione del code-switching se la lingua
    effettiva è l'italiano. Il testo non va a capo (lo fa l'esportazione) e i tempi sono
    già quelli finali: nessuno li deve ritoccare dopo. ``light_punct`` (formato reel)
    toglie punto e virgola in fondo a ogni sottotitolo.
    """
    subs = layout(raw_segments, rules, audio_end=audio_end)
    for sub in subs:
        if italian:
            sub["text"] = _postprocess_codeswitching(sub["text"])
        if light_punct:
            sub["text"] = light_punctuation(sub["text"])
    return subs


# ============================================================
# Recupero del parlato saltato con il filtro VAD
# ============================================================
# Whisper a volte non trascrive un tratto che il VAD marca come parlato (caso reale: ~10 s
# in mezzo a un discorso con il filtro VAD; 24 s con il filtro spento, lasciando due sillabe
# stirate su 7 s). Questi tratti vengono ritrascritti da soli, senza filtro VAD, con gli
# stessi parametri di decodifica. Il VAD serve solo a trovarli: si fa anche a filtro spento.
_SAMPLE_RATE = 16000
_RECOVERY_MIN_HOLE_S = 1.5
_RECOVERY_MARGIN_S = 0.3
# Doppioni tra parole ritrascritte e già presenti: stesso testo e tempi che si sovrappongono
# (o si toccano: parola di durata nulla), oppure la parola che segue è già un doppione di
# quella che segue l'altra. Caso reale: " la democrazia" ritrascritta a 59,22–60,12 s,
# " La democrazia" originale a 59,98–60,48 s con " La" di durata nulla.
_DUPLICATE_TOL_S = 0.1
_DUPLICATE_CHAIN_S = 1.0


def _decode_pcm(audio_path: str):
    """Audio a 16 kHz mono (float32) decodificato come lo decodifica faster-whisper."""
    from faster_whisper.audio import decode_audio
    return decode_audio(audio_path, sampling_rate=_SAMPLE_RATE)


def _vad_speech_spans(audio_pcm, vad_options: Dict) -> List[Tuple[float, float]]:
    """Tratti di parlato (secondi) secondo il VAD Silero, con le stesse opzioni usate dal
    filtro VAD di faster-whisper."""
    from faster_whisper.vad import VadOptions as FwVadOptions
    from faster_whisper.vad import get_speech_timestamps
    chunks = get_speech_timestamps(audio_pcm, FwVadOptions(**vad_options),
                                   sampling_rate=_SAMPLE_RATE)
    return [(c["start"] / _SAMPLE_RATE, c["end"] / _SAMPLE_RATE) for c in chunks]


def _field(obj: Any, name: str, default: Any = None) -> Any:
    """Attributo di un oggetto di faster-whisper o chiave di un dict."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _norm_word(text: str) -> str:
    """Parola in minuscolo senza punteggiatura attorno (per confrontare due trascrizioni)."""
    return text.strip().strip(".,;:!?…\"'’«»()[]").lower()


def _transcribe_hole(model, audio_pcm, hole: Tuple[float, float], decode_kwargs: Dict,
                     cancel_event: Optional[threading.Event],
                     existing: Sequence[Any] = ()) -> List[Dict]:
    """Ritrascrive solo ``hole`` (con un margine) e restituisce segmenti-dict con tempi
    assoluti.

    Si tengono le parole con il punto medio dopo l'inizio del tratto e l'inizio prima della
    sua fine: il tratto finisce dove comincia la parola già trascritta dopo, e una parola a
    cavallo della fine ("lusso" in "denim di lusso di altissima…") andrebbe persa con il
    solo criterio del punto medio. Si scartano invece i doppioni di ``existing`` (parole già
    trascritte, con ``text/start/end``): vedi ``_duplicate_flags``.
    """
    hole_start, hole_end = hole
    total_s = len(audio_pcm) / _SAMPLE_RATE
    offset = max(0.0, hole_start - _RECOVERY_MARGIN_S)
    stop = min(total_s, hole_end + _RECOVERY_MARGIN_S)
    chunk = audio_pcm[int(offset * _SAMPLE_RATE):int(stop * _SAMPLE_RATE)]

    kwargs = dict(decode_kwargs)
    kwargs.pop("vad_parameters", None)
    kwargs.update(vad_filter=False, word_timestamps=True)
    segments_iter, _info = model.transcribe(chunk, **kwargs)
    found: List[Tuple[Any, List[Dict]]] = []
    try:
        for seg in segments_iter:
            _check_cancel(cancel_event)
            words = []
            for w in _field(seg, "words", None) or []:
                start = float(_field(w, "start", 0.0)) + offset
                end = float(_field(w, "end", 0.0)) + offset
                text = str(_field(w, "word", "") or "")
                if not ((start + end) / 2 >= hole_start and start < hole_end) or not text.strip():
                    continue
                words.append({"word": text, "start": start, "end": end,
                              "probability": _field(w, "probability", 1.0)})
            found.append((seg, words))
    finally:
        _close_iter(segments_iter)

    flags = iter(_duplicate_flags([w for _seg, ws in found for w in ws], existing))
    out: List[Dict] = []
    for seg, all_words in found:
        words = [w for w in all_words if not next(flags)]
        text = "".join(w["word"] for w in words)
        seg_start = float(_field(seg, "start", 0.0)) + offset
        seg_end = float(_field(seg, "end", 0.0)) + offset
        if not words:
            if all_words:
                continue          # solo doppioni
            # segmento senza parole con tempi: si tiene solo se è dentro il tratto
            text = str(_field(seg, "text", "") or "")
            if not text.strip() or not hole_start <= (seg_start + seg_end) / 2 <= hole_end:
                continue
        else:
            seg_start, seg_end = words[0]["start"], words[-1]["end"]
        out.append({
            "start": seg_start, "end": seg_end, "text": text, "words": words,
            "no_speech_prob": _field(seg, "no_speech_prob", 0.0),
            "avg_logprob": _field(seg, "avg_logprob", 0.0),
        })
    return out


def _duplicate_flags(recovered: Sequence[Dict], existing: Sequence[Any]) -> List[bool]:
    """Per ogni parola ritrascritta (in ordine di tempo): True se ripete una di
    ``existing``.

    Doppione = stesso testo e tempi sovrapposti (con ``_DUPLICATE_TOL_S`` di tolleranza),
    oppure stesso testo della parola esistente subito prima di quella di cui è doppione la
    parola ritrascritta successiva, entro ``_DUPLICATE_CHAIN_S``: i tempi originali sono
    spesso sfasati di qualche decimo ("la democrazia" / "La democrazia"). Due parole uguali
    vicine ma vere ("di lusso di") restano: la catena parte solo da una sovrapposizione.
    """
    ex = sorted(existing, key=lambda x: x.start)
    flags = [False] * len(recovered)
    chained: Optional[int] = None     # indice in ``ex`` del doppione della parola dopo
    for i in range(len(recovered) - 1, -1, -1):
        w = recovered[i]
        text = _norm_word(w["word"])
        match = next((j for j, x in enumerate(ex) if _norm_word(x.text) == text
                      and w["start"] < x.end + _DUPLICATE_TOL_S
                      and x.start - _DUPLICATE_TOL_S < w["end"]), None)
        if match is None and chained:
            prev = ex[chained - 1]
            if (_norm_word(prev.text) == text
                    and abs(prev.start - w["start"]) <= _DUPLICATE_CHAIN_S):
                match = chained - 1
        flags[i] = match is not None
        chained = match
    return flags


def _recover_skipped_speech(
    model,
    audio_pcm,
    raw_segments: Sequence[Any],
    vad_options: Dict,
    decode_kwargs: Dict,
    cancel_event: Optional[threading.Event] = None,
    on_status: Optional[Callable] = None,
) -> List[Any]:
    """Ritrascrive i tratti di parlato (VAD) rimasti senza parole e li unisce ai segmenti.

    I tratti sono quelli di ``find_uncovered_speech`` (≥ 1,5 s di parlato senza parole);
    ognuno è ritrascritto da solo (margine di 0,3 s, ``vad_filter=False``, stessi
    ``decode_kwargs`` di decodifica; parole tenute: vedi ``_transcribe_hole``). Restituisce i segmenti originali più quelli
    recuperati, in ordine di tempo. Un errore qui non interrompe mai la trascrizione
    (si registra e si prosegue); l'annullamento sì.
    """
    segments = list(raw_segments)
    try:
        spans = _vad_speech_spans(audio_pcm, vad_options)
        words, _bounds = words_from_segments(segments, LayoutRules())
        holes = find_uncovered_speech(spans, words, min_len_s=_RECOVERY_MIN_HOLE_S)
    except Exception as e:  # noqa: BLE001 — il recupero è un extra, mai bloccante
        logger.warning("Ricerca del parlato saltato non riuscita: %s", e)
        return segments
    if not holes:
        return segments

    n = len(holes)
    msg = (f"Recupero di {n} tratti di parlato saltati…" if n > 1
           else "Recupero di 1 tratto di parlato saltato…")
    logger.info("%s %s", msg, ", ".join(f"{s:.2f}–{e:.2f} s" for s, e in holes))
    if on_status:
        on_status(msg)

    recovered: List[Dict] = []
    filled: List[Tuple[float, float]] = []
    for hole in holes:
        _check_cancel(cancel_event)
        try:
            near = [w for w in words if not is_stretched(w)
                    and w.end >= hole[0] - 1.0 and w.start <= hole[1] + 1.0]
            found = _transcribe_hole(model, audio_pcm, hole, decode_kwargs, cancel_event, near)
        except TranscriptionCancelled:
            raise
        except Exception as e:  # noqa: BLE001 — si passa al tratto successivo
            logger.warning("Ritrascrizione del tratto %.2f–%.2f s non riuscita: %s",
                           hole[0], hole[1], e)
            continue
        text = " ".join(" ".join(str(seg["text"]).split()) for seg in found)
        if text:
            logger.info("Recuperato %.2f–%.2f s: %s", hole[0], hole[1], text)
            filled.append(hole)
        else:
            logger.info("Nessuna parola recuperata in %.2f–%.2f s", hole[0], hole[1])
        recovered.extend(found)

    if not recovered:
        return segments
    segments = _drop_stretched_words(segments, filled)
    # ordinamento stabile: a parità di inizio restano prima i segmenti originali
    return sorted(segments + recovered, key=lambda seg: float(_field(seg, "start", 0.0)))


def _drop_stretched_words(segments: Sequence[Any],
                          filled: Sequence[Tuple[float, float]]) -> List[Any]:
    """Toglie le parole stirate (più lunghe di ``MAX_WORD_S``) che cadono in un tratto
    ritrascritto: al loro posto ci sono ora le parole vere. Un segmento toccato diventa un
    dict con le parole rimaste; se non ne resta nessuna sparisce."""
    if not filled:
        return list(segments)

    def stretched_in_hole(w) -> bool:
        start = float(_field(w, "start", 0.0))
        end = float(_field(w, "end", 0.0))
        return (end - start > MAX_WORD_S
                and any(start < he and end > hs for hs, he in filled))

    out: List[Any] = []
    for seg in segments:
        seg_words = list(_field(seg, "words", None) or [])
        kept = [w for w in seg_words if not stretched_in_hole(w)]
        if len(kept) == len(seg_words):
            out.append(seg)
            continue
        for w in seg_words:
            if w not in kept:
                logger.info("Parola stirata sostituita: %r %.2f–%.2f s",
                            str(_field(w, "word", "")), float(_field(w, "start", 0.0)),
                            float(_field(w, "end", 0.0)))
        if not kept:
            continue
        words = [{"word": str(_field(w, "word", "") or ""),
                  "start": float(_field(w, "start", 0.0)), "end": float(_field(w, "end", 0.0)),
                  "probability": _field(w, "probability", 1.0)} for w in kept]
        out.append({
            "start": words[0]["start"], "end": words[-1]["end"],
            "text": "".join(w["word"] for w in words), "words": words,
            "no_speech_prob": _field(seg, "no_speech_prob", 0.0),
            "avg_logprob": _field(seg, "avg_logprob", 0.0),
        })
    return out


# ============================================================
# Trascrizione WhisperX
# ============================================================
def _wav_duration(path: str) -> Optional[float]:
    """Durata di un file WAV (l'audio pre-elaborato) in secondi; None se non è un WAV."""
    import wave
    try:
        with wave.open(path, "rb") as f:
            rate = f.getframerate()
            return f.getnframes() / float(rate) if rate else None
    except (OSError, EOFError, wave.Error):
        return None


def _transcribe_whisperx(
    audio_path: str,
    *,
    model_size: str = DEFAULT_MODEL,
    beam_size: int = 5,
    language: Optional[str] = "it",
    config: Optional[TranscriptionConfig] = None,
    cancel_event: Optional[threading.Event] = None,
    on_status: Optional[Callable] = None,
    on_progress: Optional[Callable] = None,
) -> List[Dict]:
    import whisperx

    language = normalize_language(language)
    config = config or TranscriptionConfig()

    def status(msg):
        if on_status:
            on_status(msg)

    def progress(pct):
        if on_progress:
            on_progress(pct)

    device, compute_type = get_optimal_device()
    logger.info("Backend WhisperX: %s, %s, %s", model_size, device, compute_type)

    status("WhisperX · Caricamento modello...")
    progress(0.10)
    _check_cancel(cancel_event)

    asr_options = {"beam_size": beam_size, "word_timestamps": True}
    prompt = config.decoding.prompt_for(language)
    if prompt:
        asr_options["initial_prompt"] = prompt

    wx_model = whisperx.load_model(
        model_size, device=device, compute_type=compute_type,
        language=language, asr_options=asr_options,
    )
    try:
        progress(0.20)
        status("WhisperX · Trascrizione in corso...")
        _check_cancel(cancel_event)
        result = wx_model.transcribe(audio_path, batch_size=8)
    finally:
        del wx_model
        gc.collect()

    detected_lang = result.get("language") or language
    logger.info("WhisperX: lingua rilevata = %s, %d segmenti grezzi",
                detected_lang, len(result.get("segments", [])))

    progress(0.50)
    _check_cancel(cancel_event)

    status("WhisperX · Allineamento fonetico (wav2vec2)...")

    try:
        align_model, align_metadata = whisperx.load_align_model(
            language_code=detected_lang, device=device,
        )
        try:
            _check_cancel(cancel_event)
            aligned = whisperx.align(
                result["segments"], align_model, align_metadata,
                audio_path, device=device,
                return_char_alignments=False,
            )
        finally:
            del align_model
            gc.collect()

        segments = aligned.get("segments", result.get("segments", []))
        logger.info("WhisperX: %d segmenti allineati", len(segments))
    except TranscriptionCancelled:
        raise
    except Exception as align_err:  # noqa: BLE001 — si usano i timestamp Whisper
        logger.warning("Allineamento WhisperX fallito: %s", align_err)
        status("⚠️ Allineamento non riuscito — uso timestamp Whisper")
        segments = result.get("segments", [])

    progress(0.75)
    _check_cancel(cancel_event)

    # Stessa composizione di faster-whisper (le parole di WhisperX sono dict con "score")
    status("WhisperX · Segmentazione sottotitoli...")
    italian = language == "it" or (language is None and detected_lang == "it")
    collected = _build_subtitles(segments, config.readability.layout_rules(),
                                 _wav_duration(audio_path), italian,
                                 config.readability.light_punctuation)

    status(f"Trascrizione completata: {len(collected)} sottotitoli (WhisperX)")
    progress(1.0)
    return collected


# ============================================================
# Trascrizione (dispatcher)
# ============================================================
def _is_vad_unavailable_error(err: BaseException) -> bool:
    """True se l'errore indica che il VAD (Silero/ONNX) non è disponibile."""
    msg = str(err).lower()
    relates_to_vad = any(k in msg for k in ("onnx", "vad", "silero"))
    if isinstance(err, (ImportError, FileNotFoundError)):
        return relates_to_vad
    return "onnx" in msg


def _accepts_kwarg(fn, name: str) -> bool:
    """True se ``fn`` accetta l'argomento ``name`` (es. ``hotwords``, assente nelle
    versioni più vecchie di faster-whisper)."""
    import inspect
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return name in params or any(p.kind is inspect.Parameter.VAR_KEYWORD
                                 for p in params.values())


def _close_iter(it) -> None:
    """Chiude un generatore di segmenti, se possibile."""
    close = getattr(it, "close", None)
    if close is not None:
        try:
            close()
        except Exception as e:  # noqa: BLE001 — solo pulizia
            logger.debug("Chiusura del generatore non riuscita: %s", e)


def transcribe(
    input_path: str,
    *,
    model_size: str = DEFAULT_MODEL,
    beam_size: int = 5,
    vad_filter: bool = True,
    denoise: bool = True,
    high_accuracy: bool = False,
    language: Optional[str] = "it",
    config: Optional[TranscriptionConfig] = None,
    cancel_event: Optional[threading.Event] = None,
    on_status: Optional[Callable] = None,
    on_progress: Optional[Callable] = None,
) -> List[Dict]:
    """Trascrive ``input_path`` e restituisce i sottotitoli come dict start/end/text.

    ``language`` None (o "auto") = rilevamento automatico della lingua.
    ``config`` fornisce i parametri avanzati: decodifica (prompt, glossario come
    ``hotwords``, temperature, soglie) e VAD Silero (None = predefiniti). Modello,
    lingua, beam, filtro VAD, riduzione rumore e alta precisione restano gli argomenti
    espliciti.
    """
    language = normalize_language(language)
    config = config or TranscriptionConfig()

    def status(msg):
        if on_status:
            on_status(msg)

    def progress(pct):
        if on_progress:
            on_progress(pct)

    _setup_environment()

    # Modello mancante: lo si scarica prima di tutto (avanzamento 0–5 %, stato in GB)
    if not (high_accuracy and _has_whisperx() and not _is_frozen()):
        ensure_model(model_size, on_status=on_status,
                     on_progress=lambda p: progress(0.05 * p), cancel_event=cancel_event)
    progress(0.05)

    _check_cancel(cancel_event)
    preprocessed_path = None
    if denoise:
        preprocessed_path = preprocess_audio(
            input_path, on_status=on_status, cancel_event=cancel_event,
        )
    audio_path = preprocessed_path if preprocessed_path else input_path
    if preprocessed_path:
        status("Audio ripulito")
    progress(0.10)

    segments_iter = None
    try:
        if high_accuracy and not (_has_whisperx() and not _is_frozen()):
            # Mai un ripiego silenzioso: l'utente ha chiesto una modalità che non c'è.
            reason = high_accuracy_unavailable_reason() or "WhisperX non utilizzabile"
            logger.warning("Alta precisione richiesta ma non disponibile: %s", reason)
            status(f"⚠️ Alta precisione non disponibile ({reason}) — uso la modalità standard")

        if high_accuracy and _has_whisperx() and not _is_frozen():
            try:
                status("Backend: WhisperX (alta precisione)")
                logger.info("Uso il backend WhisperX (allineamento wav2vec2)")
                return _transcribe_whisperx(
                    audio_path, model_size=model_size, beam_size=beam_size,
                    language=language, config=config, cancel_event=cancel_event,
                    on_status=on_status, on_progress=on_progress,
                )
            except TranscriptionCancelled:
                raise
            except Exception as wx_err:  # noqa: BLE001 — fallback a faster-whisper
                logger.warning("WhisperX fallito: %s", wx_err)
                status("⚠️ WhisperX non riuscito — fallback a faster-whisper...")

        logger.info("Uso il backend faster-whisper")
        model = _get_or_load_model(model_size, on_status=on_status)
        progress(0.15)

        # Parametri di decodifica (predefiniti in core.transcription_config)
        dec = config.decoding
        transcribe_params = dict(
            language=language,
            task="transcribe",
            beam_size=beam_size,
            patience=dec.patience,
            initial_prompt=dec.prompt_for(language),
            word_timestamps=True,
            condition_on_previous_text=dec.condition_on_previous_text,
            no_speech_threshold=dec.no_speech_threshold,
            log_prob_threshold=dec.log_prob_threshold,
            compression_ratio_threshold=dec.compression_ratio_threshold,
            temperature=list(dec.temperature),
        )
        # Glossario: a differenza di initial_prompt (solo la prima finestra di 30 s con
        # condition_on_previous_text=False), hotwords vale per ogni finestra.
        hotwords = dec.hotwords()
        if hotwords:
            if _accepts_kwarg(model.transcribe, "hotwords"):
                transcribe_params["hotwords"] = hotwords
            else:
                logger.warning("Glossario ignorato: questa versione di faster-whisper "
                               "non supporta hotwords")

        vad_active = False
        first_seg = None
        info = None
        _check_cancel(cancel_event)
        status("Elaborazione audio in corso...")

        if vad_filter:
            try:
                segments_iter, info = model.transcribe(
                    audio_path, **transcribe_params,
                    vad_filter=True,
                    vad_parameters=config.vad.as_dict(),
                )
                _check_cancel(cancel_event)
                first_seg = next(segments_iter, None)
                vad_active = True
            except TranscriptionCancelled:
                raise
            except Exception as vad_err:
                if not _is_vad_unavailable_error(vad_err):
                    raise
                logger.warning("VAD non disponibile: %s", vad_err)
                status("⚠️ VAD non disponibile — proseguo senza filtro silenzi...")
                _close_iter(segments_iter)
                segments_iter = None
                first_seg = None

        if not vad_active:
            _check_cancel(cancel_event)
            segments_iter, info = model.transcribe(audio_path, **transcribe_params,
                                                   vad_filter=False)
            _check_cancel(cancel_event)
            first_seg = next(segments_iter, None)

        _check_cancel(cancel_event)

        duration = info.duration or 0
        vad_label = " · VAD attivo" if vad_active else (" · VAD off" if vad_filter else "")
        status(f"Lingua: {info.language} ({info.language_probability:.0%}){vad_label}")

        # Raccoglie tutti i segmenti grezzi
        raw_segments = []

        def collect_segment(seg):
            _check_cancel(cancel_event)
            raw_segments.append(seg)
            if duration > 0:
                progress(min(0.15 + (seg.end / duration) * 0.75, 0.90))
                status(f"Trascrizione in corso... {int(seg.end / duration * 100)}%")

        if first_seg is not None:
            collect_segment(first_seg)
        for seg in segments_iter:
            collect_segment(seg)

        _close_iter(segments_iter)
        segments_iter = None

        # Tratti di parlato che Whisper ha saltato (con o senza filtro VAD): ritrascritti
        _check_cancel(cancel_event)
        try:
            audio_pcm = _decode_pcm(audio_path)
        except Exception as e:  # noqa: BLE001 — il recupero è un extra, mai bloccante
            logger.warning("Audio per il recupero del parlato saltato non disponibile: %s",
                           e)
            audio_pcm = None
        if audio_pcm is not None:
            decode_kwargs = dict(transcribe_params, language=language or info.language)
            raw_segments = _recover_skipped_speech(
                model, audio_pcm, raw_segments, config.vad.as_dict(), decode_kwargs,
                cancel_event=cancel_event, on_status=on_status,
            )
            del audio_pcm

        # Composizione dei sottotitoli: divisione, testo e tempi definitivi
        _check_cancel(cancel_event)
        status("Segmentazione sottotitoli...")
        italian = language == "it" or (language is None and info.language == "it")
        collected = _build_subtitles(raw_segments, config.readability.layout_rules(),
                                     info.duration or None, italian,
                                     config.readability.light_punctuation)

        status(f"Trascrizione completata: {len(collected)} sottotitoli")
        progress(1.0)
        return collected

    finally:
        if segments_iter is not None:
            _close_iter(segments_iter)
        if preprocessed_path:
            try:
                os.unlink(preprocessed_path)
            except OSError:
                pass


# ============================================================
# Pipeline completa (mantenuta per CLI e compatibilità)
# ============================================================
def run_pipeline(
    input_path: str,
    output_path: Optional[str] = None,
    model_size: str = DEFAULT_MODEL,
    beam_size: int = 5,
    vad_filter: bool = True,
    denoise: bool = True,
    high_accuracy: bool = False,
    cancel_event: Optional[threading.Event] = None,
    on_status: Optional[Callable] = None,
    on_progress: Optional[Callable] = None,
    language: Optional[str] = "it",
    config: Optional[TranscriptionConfig] = None,
) -> str:
    """Trascrive e scrive direttamente un file SRT. Ritorna il percorso scritto.

    ``config``: parametri avanzati e limiti di leggibilità, anche per l'a capo dell'SRT
    (None = predefiniti).
    """
    from core.srt_io import unique_output_path, write_srt
    from core.subtitle_model import Subtitle

    def status(msg):
        if on_status:
            on_status(msg)

    language = normalize_language(language)
    if not output_path:
        output_path = str(Path(input_path).with_suffix(".srt"))
    output_path = unique_output_path(output_path)

    segments = transcribe(
        input_path, model_size=model_size, beam_size=beam_size,
        vad_filter=vad_filter, denoise=denoise, high_accuracy=high_accuracy,
        language=language, config=config, cancel_event=cancel_event,
        on_status=on_status, on_progress=on_progress,
    )

    if not segments:
        raise RuntimeError("Nessun segmento trovato nella trascrizione.")

    # I tempi sono già definitivi (core.subtitle_layout): si scrive e basta
    status("Generazione file SRT...")
    subtitles = [Subtitle.from_dict(s) for s in segments]
    r = config.readability if config is not None else None
    write_srt(subtitles, output_path, max_chars=r.max_chars_per_line if r else None,
              max_lines=r.max_lines if r else None)
    status(f"Salvato: {Path(output_path).name} ({len(subtitles)} sottotitoli)")
    return output_path

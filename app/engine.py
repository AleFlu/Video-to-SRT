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
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from core.constants import MAX_CHARS_PER_LINE  # noqa: F401 — riesportata per compatibilità
from core.constants import MAX_SUBTITLE_DURATION, MIN_SUBTITLE_DURATION
from platform_support import cpu_threads, ffmpeg_executable_name, subprocess_kwargs

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


# ============================================================
# Configurazione
# ============================================================
ITALIAN_PROMPT = (
    "Trascrizione fedele in italiano. Mantieni invariate le parole straniere "
    "pronunciate dallo speaker: termini tecnici inglesi, brand, comandi, anglicismi. "
    "Esempi: machine learning, deploy, framework, backend, feature, ok, trend, "
    "social media, iPhone, Google, npm, git. "
    "Punteggiatura italiana: punto, virgola, punto interrogativo, punto esclamativo, due punti. "
    "Apostrofi: c'è, dell', un'altra, l'uomo. Accenti: è, à, ì, ò, ù. "
    "Sì (affermazione). Nomi propri con maiuscola."
)

# Parametri VAD Silero (tuning invariato)
VAD_PARAMS = dict(min_silence_duration_ms=150, speech_pad_ms=100, threshold=0.50)

# ============================================================
# Post-processing: correzione italianizzazioni Whisper
# ============================================================
# Lista di (pattern_regex, replacement) ordinata dalla più specifica alla più generica.
# Il pattern deve fare match su quello che Whisper produce con language=it.
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
    (r"\bdeploi(?:are|ato|ata|ati|ate|ment|mento)?\b","deploy"),
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
    (r"\bd[ae]bug(?:ging|gare|gato)?\b",              "debug"),
    (r"\brifact(?:oring|orare|orato)?\b",             "refactoring"),
    (r"\bpull\s*r[ae]qu[ae]st[s]?\b",                "pull request"),
    (r"\bcodi[ck](?:\s*base)?\b",                     "codebase"),
    (r"\bgit\s*hab\b",                                "GitHub"),
    (r"\bgit\s*lab\b",                                "GitLab"),

    # --- Web / Social media ---
    (r"\bsocial\s*m[ae]dia\b",                        "social media"),
    (r"\bconten[t]?\s*cr[ae]ator[s]?\b",              "content creator"),
    (r"\binfl[iu][ae]nc[ae]r[s]?\b",                  "influencer"),
    (r"\bstr[ae]aming\b",                              "streaming"),
    (r"\bstr[ae]am[s]?\b",                             "stream"),
    (r"\breel[s]?\b",                                  "reel"),
    (r"\bstor(?:ies|i)\b",                             "stories"),

    # --- Anglicismi tech generici ---
    (r"\bfeat[iu]r[ae][s]?\b",                        "feature"),
    (r"\bscr[ae]enshot[s]?\b",                        "screenshot"),
    (r"\bh[ae]rduer[ae]\b",                            "hardware"),
    (r"\bs[ao]ftuer[ae]\b",                            "software"),
    (r"\bu[ai]f\b",                                    "UI"),
    (r"\bu[ae]ks\b",                                   "UX"),
    (r"\bapi[s]?\b",                                   "API"),
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
    (r"\bweb[s]?\b",                                   "web"),
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


MODELS = {
    "tiny":           {"label": "tiny — Test rapidi",              "ram": "~1 GB",  "quality": "★☆☆☆☆"},
    "base":           {"label": "base — Qualità base",             "ram": "~1 GB",  "quality": "★★☆☆☆"},
    "small":          {"label": "small — Discreta per italiano",   "ram": "~2 GB",  "quality": "★★★☆☆"},
    "medium":         {"label": "medium — Buona qualità",          "ram": "~5 GB",  "quality": "★★★★☆"},
    "large-v3":       {"label": "large-v3 — Massima qualità ★",   "ram": "~6 GB",  "quality": "★★★★★"},
    "large-v3-turbo": {"label": "large-v3-turbo — Ottima + veloce","ram": "~4 GB",  "quality": "★★★★½"},
}
DEFAULT_MODEL = "large-v3"

# Timing sottotitoli (MAX_SUBTITLE_DURATION / MIN_SUBTITLE_DURATION da core.constants)
MIN_GAP_BETWEEN_SUBS = 0.08


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
def preprocess_audio(input_path: str, on_status: Optional[Callable] = None) -> Optional[str]:
    """Estrae l'audio a 16 kHz mono con riduzione rumore. None se non riesce."""
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

    ok = False
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300, **subprocess_kwargs(),
        )
        if result.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            ok = True
        else:
            logger.warning(
                "ffmpeg ha restituito %s: %s", result.returncode, (result.stderr or "")[:500],
            )
    except subprocess.TimeoutExpired:
        logger.warning("Pre-elaborazione audio interrotta: timeout di ffmpeg")
    except Exception as e:  # noqa: BLE001 — si prosegue con l'audio originale
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
    """Pre-carica il modello all'avvio. False (con messaggio) se fallisce."""
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
# Segmentazione sottotitoli — architettura globale
# ============================================================
SENTENCE_ENDINGS = {".", "!", "?", "…"}
CLAUSE_BREAKS    = {",", ";", ":", "–", "—"}
MIN_WORD_PROB    = 0.35

# Soglie acustiche
GAP_FORCE   = 0.40   # gap >= questo → split sempre (silenzio reale)
GAP_CLAUSE  = 0.25   # gap dopo ,;: con blocco >= 20 char
GAP_SOFT    = 0.10   # gap minimo al soft limit

# Limiti caratteri (due righe × 42 = 84 max assoluto)
SOFT_LIMIT  = 42     # preferisci splittare al prossimo gap disponibile
HARD_LIMIT  = 84     # split forzato — mai blocchi più lunghi di così

# Merge: frammenti sotto questa soglia vengono assorbiti dal successivo
MERGE_MIN_CHARS = 25

_IT_FIXES = [
    (re.compile(r'\s+([.,;:!?])'),                       r'\1'),
    (re.compile(r'  +'),                                  ' '),
    (re.compile(r"([a-zA-ZÀ-ù]') ([a-zA-ZÀ-ù])"),       r"\1\2"),
    (re.compile(r'\bun po\b(?=\s|$)'),                   "un po'"),
    (re.compile(
        r'\bce\b(?=\s+(?:un|una|il|lo|la|stato|stata|bisogno|qualcosa|'
        r'niente|ancora|già|sempre|molto|troppo|poco|bene|male|più|meno)\b)',
        re.IGNORECASE
    ), "c'è"),
]


def _postprocess_typography(text: str) -> str:
    """Correzioni tipografiche per sottotitoli (spazi prima di punteggiatura, apostrofi, ecc.)."""
    for pattern, replacement in _IT_FIXES:
        text = pattern.sub(replacement, text)
    return text.strip()


class _FakeWord:
    """Parola sintetica che rappresenta l'intero testo di un segmento senza
    parole affidabili (nessun timestamp per parola utilizzabile)."""

    __slots__ = ("word", "start", "end", "probability", "_is_synthetic")

    def __init__(self, word: str, start: float, end: float):
        self.word = word
        self.start = start
        self.end = end
        self.probability = 1.0
        self._is_synthetic = True


def _is_synthetic(word) -> bool:
    return getattr(word, "_is_synthetic", False)


def collect_all_words(segments_iter, min_word_prob: float = MIN_WORD_PROB) -> Tuple[List, Set[int]]:
    """Raccoglie tutte le parole da tutti i segmenti in una lista flat globale.

    Ignora segmenti con no_speech_prob alto o avg_logprob troppo basso.
    Restituisce ``(parole, boundary)``: le parole hanno .start .end .word .probability;
    ``boundary`` contiene gli indici in cui inizia un nuovo segmento Whisper
    (hard break impliciti). Un segmento senza parole affidabili diventa un
    unico ``_FakeWord`` con il testo del segmento.
    """
    all_words: List = []
    seg_boundaries: Set[int] = set()

    for seg in segments_iter:
        no_speech  = getattr(seg, "no_speech_prob", 0.0)
        avg_logprob = getattr(seg, "avg_logprob", 0.0)
        if no_speech > 0.9 or avg_logprob < -1.8:
            continue

        words = getattr(seg, "words", None) or []
        valid = [w for w in words
                 if w.word.strip() and getattr(w, "probability", 1.0) >= min_word_prob]

        if not valid:
            # Nessuna parola affidabile: usa il testo grezzo del segmento come blocco unico
            text = (getattr(seg, "text", "") or "").strip()
            if text:
                if all_words:
                    seg_boundaries.add(len(all_words))
                all_words.append(_FakeWord(text, seg.start, seg.end))
            continue

        if all_words:
            seg_boundaries.add(len(all_words))
        all_words.extend(valid)

    return all_words, seg_boundaries


def _find_best_split(words: List) -> int:
    """Trova l'indice migliore dove splittare una lista di parole già accumulata.

    Strategia: cerca il gap acustico più grande tra le parole, con preferenza
    per i confini dopo punteggiatura debole. Restituisce l'indice DOPO cui
    splittare (0 = non splittare, len-1 = dopo l'ultima — non usare).
    Considera solo posizioni che lasciano almeno 15 char per parte.
    """
    if len(words) < 2:
        return 0

    best_idx  = 0
    best_score = -1.0

    for j in range(len(words) - 1):
        left_text  = " ".join(w.word.strip() for w in words[:j + 1])
        right_text = " ".join(w.word.strip() for w in words[j + 1:])
        # Entrambe le parti devono avere un minimo di contenuto
        if len(left_text) < 15 or len(right_text) < 10:
            continue

        gap = words[j + 1].start - words[j].end
        w_text = words[j].word.strip()
        ends_clause = any(w_text.endswith(p) for p in CLAUSE_BREAKS)

        # Score: gap acustico + bonus punteggiatura + bonus bilanciamento lunghezze
        balance = 1.0 - abs(len(left_text) - len(right_text)) / max(len(left_text) + len(right_text), 1)
        score = gap + (0.15 if ends_clause else 0.0) + balance * 0.05

        if score > best_score:
            best_score = score
            best_idx   = j + 1  # split DOPO words[j]

    return best_idx


def _merge_short_fragments(subtitles: List[Dict]) -> List[Dict]:
    """Unisce i frammenti corti al sottotitolo SUCCESSIVO, solo se il risultato
    resta entro HARD_LIMIT caratteri e MAX_SUBTITLE_DURATION secondi."""
    if len(subtitles) < 2:
        return subtitles
    merged: List[Dict] = []
    i = 0
    while i < len(subtitles):
        sub = subtitles[i]
        if (len(sub["text"]) < MERGE_MIN_CHARS
                and i + 1 < len(subtitles)
                and (subtitles[i + 1]["start"] - sub["end"]) < 0.5):
            nxt = subtitles[i + 1]
            text = sub["text"] + " " + nxt["text"]
            if len(text) <= HARD_LIMIT and (nxt["end"] - sub["start"]) <= MAX_SUBTITLE_DURATION:
                merged.append({"start": sub["start"], "end": nxt["end"], "text": text})
                i += 2
                continue
        merged.append(sub)
        i += 1
    return merged


def segment_words_semantic(all_words: List, seg_boundaries: Set[int]) -> List[Dict]:
    """Segmentazione semantica globale su stream di parole.

    Priorità di split forward (per ogni parola appena accumulata):
      P1  boundary di segmento Whisper (VAD hard break)
      P2  gap acustico >= GAP_FORCE (silenzio reale)
      P3  punteggiatura forte (.!?…) — SEMPRE, senza condizione sul gap
      P4  punteggiatura debole (,;:–—) + gap >= GAP_CLAUSE + blocco >= 20 char
      P5  blocco >= SOFT_LIMIT + gap >= GAP_SOFT (split opportunistico)
      P6  blocco >= HARD_LIMIT → best-gap-split retroattivo sul blocco accumulato
    Una parola sintetica (segmento senza parole affidabili) forma sempre un
    blocco a sé: split prima e dopo di essa.
    """
    if not all_words:
        return []

    subtitles: List[Dict] = []
    current: List        = []

    def _flush_words(words: List):
        if not words:
            return
        text = _postprocess_typography(" ".join(w.word.strip() for w in words))
        if text:
            subtitles.append({
                "start": words[0].start,
                "end":   words[-1].end,
                "text":  text,
            })

    n = len(all_words)
    for i, word in enumerate(all_words):
        synthetic = _is_synthetic(word)
        if synthetic and current:
            # Split PRIMA della parola sintetica
            _flush_words(current)
            current = []

        current.append(word)
        is_last = (i == n - 1)

        if is_last:
            break

        if synthetic:
            # Split DOPO la parola sintetica
            _flush_words(current)
            current = []
            continue

        word_text   = word.word.strip()
        next_word   = all_words[i + 1]
        gap         = next_word.start - word.end
        block_len   = len(" ".join(w.word.strip() for w in current))
        ends_sent   = any(word_text.endswith(p) for p in SENTENCE_ENDINGS)
        ends_clause = any(word_text.endswith(p) for p in CLAUSE_BREAKS)
        is_boundary = (i + 1) in seg_boundaries

        should_split = False

        # P1 — boundary Whisper: split solo se c'è già contenuto significativo
        # (evita di spezzare frasi lunghe in mini-blocchi per ogni segmento Whisper)
        if is_boundary and (block_len >= MERGE_MIN_CHARS or ends_sent or gap >= GAP_CLAUSE):
            should_split = True

        # P2 — silenzio acustico reale
        elif gap >= GAP_FORCE:
            should_split = True

        # P3 — punteggiatura forte: split SEMPRE
        elif ends_sent:
            # Se il blocco è già lungo, prima di splittare qui cerca se c'è
            # un punto migliore interno (best-gap retroattivo)
            if block_len > SOFT_LIMIT and len(current) > 2:
                split_at = _find_best_split(current)
                if 0 < split_at < len(current):
                    _flush_words(current[:split_at])
                    current = current[split_at:]
                    # il residuo (con la parola col punto) viene flushato sotto
            should_split = True

        # P4 — punteggiatura debole con pausa
        elif ends_clause and gap >= GAP_CLAUSE and block_len >= 20:
            should_split = True

        # P5 — soft limit raggiunto: aspetta il primo gap disponibile
        elif block_len >= SOFT_LIMIT and gap >= GAP_SOFT:
            should_split = True

        # P6 — hard limit: best-gap-split retroattivo, poi flush
        elif block_len >= HARD_LIMIT:
            split_at = _find_best_split(current)
            if 0 < split_at < len(current):
                _flush_words(current[:split_at])
                current = current[split_at:]
            else:
                # Nessun punto decente trovato: flush tutto e ricomincia
                _flush_words(current)
                current = []
            continue  # non fare should_split, current è già aggiornato

        if should_split:
            _flush_words(current)
            current = []

    _flush_words(current)

    return _merge_short_fragments(subtitles)


# ============================================================
# Post-processing timing
# ============================================================
def post_process_timing(segments: List[Dict]) -> List[Dict]:
    """Aggiusta i tempi rispettando le pause reali del parlato.

    Filosofia speech-synchronized:
    - Pausa reale (gap > 0.3s): subtitle finisce entro 200ms dall'ultima parola.
      Lo schermo resta NERO durante la pausa — non si estende il subtitle.
    - Parlato continuo (gap <= 0.3s): piccolo pad di 150ms per confort visivo.
    - Mai estendere nella pausa per ragioni di "tempo di lettura".
    Garanzie finali: ``end <= next.start - MIN_GAP_BETWEEN_SUBS`` quando possibile
    ed ``end > start`` sempre.
    """
    if not segments:
        return segments

    HOLD_AFTER_SPEECH = 0.20   # max estensione dopo ultima parola in caso di pausa reale
    PAD_CONTINUOUS    = 0.15   # estensione in parlato continuo
    PAUSE_THRESHOLD   = 0.30   # gap > questo = silenzio reale

    processed = []
    n = len(segments)

    for i, seg in enumerate(segments):
        start = seg["start"]
        end   = seg["end"]
        text  = seg["text"].strip()
        if not text:
            continue

        next_start = segments[i + 1]["start"] if i < n - 1 else None
        gap_to_next = (next_start - end) if next_start is not None else float("inf")
        followed_by_silence = gap_to_next > PAUSE_THRESHOLD

        if followed_by_silence:
            new_end = end + HOLD_AFTER_SPEECH
        else:
            new_end = end + PAD_CONTINUOUS

        # Mai superare MAX_SUBTITLE_DURATION
        if (new_end - start) > MAX_SUBTITLE_DURATION:
            new_end = start + MAX_SUBTITLE_DURATION

        # Mai sconfinare nel subtitle successivo
        if next_start is not None:
            max_allowed = next_start - MIN_GAP_BETWEEN_SUBS
            if new_end > max_allowed:
                new_end = max_allowed

        # Floor: almeno MIN_SUBTITLE_DURATION visibile
        if (new_end - start) < MIN_SUBTITLE_DURATION:
            candidate = start + MIN_SUBTITLE_DURATION
            if next_start is not None:
                candidate = min(candidate, next_start - MIN_GAP_BETWEEN_SUBS)
            new_end = max(new_end, candidate)

        if new_end <= start:
            new_end = start + 0.1

        processed.append({"start": round(start, 3), "end": round(new_end, 3), "text": text})

    # Pass finale sui valori arrotondati: niente sovrapposizioni quando possibile,
    # mai durata nulla o negativa.
    for i, cur in enumerate(processed):
        nxt = processed[i + 1] if i + 1 < len(processed) else None
        if nxt is not None:
            limit = round(nxt["start"] - MIN_GAP_BETWEEN_SUBS, 3)
            if cur["end"] > limit > cur["start"]:
                cur["end"] = limit
        if cur["end"] <= cur["start"]:
            fallback = cur["start"] + 0.1
            if nxt is not None and nxt["start"] > cur["start"]:
                fallback = min(fallback, nxt["start"])
            cur["end"] = round(fallback, 3)
            if cur["end"] <= cur["start"]:
                cur["end"] = cur["start"] + 0.001
    return processed


# ============================================================
# Trascrizione WhisperX
# ============================================================
class _WhisperXWordAdapter:
    __slots__ = ("word", "start", "end", "probability")

    def __init__(self, d: Dict):
        self.word = d.get("word", "")
        self.start = d.get("start", 0.0)
        self.end = d.get("end", 0.0)
        self.probability = d.get("score", 1.0)


class _WhisperXSegmentAdapter:
    __slots__ = ("start", "end", "text", "words", "no_speech_prob", "avg_logprob")

    def __init__(self, d: Dict):
        self.start = d.get("start", 0.0)
        self.end = d.get("end", 0.0)
        self.text = d.get("text", "")
        self.no_speech_prob = 0.0
        self.avg_logprob = 0.0
        raw_words = d.get("words") or []
        self.words = [
            _WhisperXWordAdapter(w) for w in raw_words
            if w.get("start") is not None and w.get("end") is not None
        ]


def _transcribe_whisperx(
    audio_path: str,
    *,
    model_size: str = DEFAULT_MODEL,
    beam_size: int = 5,
    language: str = "it",
    cancel_event: Optional[threading.Event] = None,
    on_status: Optional[Callable] = None,
    on_progress: Optional[Callable] = None,
) -> List[Dict]:
    import whisperx

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
    if language == "it":
        asr_options["initial_prompt"] = ITALIAN_PROMPT

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

    detected_lang = result.get("language", language)
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

    # Stessa pipeline globale di faster-whisper
    status("WhisperX · Segmentazione sottotitoli...")
    adapted = [_WhisperXSegmentAdapter(seg) for seg in segments
               if (seg.get("text") or "").strip()]
    all_words, seg_boundaries = collect_all_words(adapted)
    collected = segment_words_semantic(all_words, seg_boundaries)

    if language == "it":
        for seg in collected:
            seg["text"] = _postprocess_codeswitching(seg["text"])

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
    language: str = "it",
    cancel_event: Optional[threading.Event] = None,
    on_status: Optional[Callable] = None,
    on_progress: Optional[Callable] = None,
) -> List[Dict]:
    """Trascrive ``input_path`` e restituisce i sottotitoli come dict start/end/text."""

    def status(msg):
        if on_status:
            on_status(msg)

    def progress(pct):
        if on_progress:
            on_progress(pct)

    _setup_environment()

    progress(0.05)

    _check_cancel(cancel_event)
    preprocessed_path = None
    if denoise:
        preprocessed_path = preprocess_audio(input_path, on_status=on_status)
    audio_path = preprocessed_path if preprocessed_path else input_path
    if preprocessed_path:
        status("Audio ripulito")
    progress(0.10)

    segments_iter = None
    try:
        if high_accuracy and _has_whisperx() and not _is_frozen():
            try:
                status("Backend: WhisperX (alta precisione)")
                logger.info("Uso il backend WhisperX (allineamento wav2vec2)")
                return _transcribe_whisperx(
                    audio_path, model_size=model_size, beam_size=beam_size,
                    language=language, cancel_event=cancel_event,
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

        # Parametri di decodifica (tuning invariato)
        transcribe_params = dict(
            language=language,
            task="transcribe",
            beam_size=beam_size,
            patience=1.0,
            initial_prompt=ITALIAN_PROMPT if language == "it" else None,
            word_timestamps=True,
            condition_on_previous_text=False,
            no_speech_threshold=0.5,
            log_prob_threshold=-1.2,
            compression_ratio_threshold=2.4,
            temperature=[0.0, 0.2, 0.4, 0.6],
        )

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
                    vad_parameters=dict(VAD_PARAMS),
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

        # Raccoglie tutti i segmenti grezzi per la pipeline globale
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

        # Pipeline globale: raccoglie tutte le parole e segmenta semanticamente
        status("Segmentazione sottotitoli...")
        all_words, seg_boundaries = collect_all_words(raw_segments)
        collected = segment_words_semantic(all_words, seg_boundaries)

        # Post-processing code-switching: corregge italianizzazioni Whisper
        if language == "it":
            for seg in collected:
                seg["text"] = _postprocess_codeswitching(seg["text"])

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
    language: str = "it",
) -> str:
    """Trascrive e scrive direttamente un file SRT. Ritorna il percorso scritto."""
    from core.srt_io import unique_output_path, write_srt
    from core.subtitle_model import Subtitle

    def status(msg):
        if on_status:
            on_status(msg)

    if not output_path:
        output_path = str(Path(input_path).with_suffix(".srt"))
    output_path = unique_output_path(output_path)

    segments = transcribe(
        input_path, model_size=model_size, beam_size=beam_size,
        vad_filter=vad_filter, denoise=denoise, high_accuracy=high_accuracy,
        language=language, cancel_event=cancel_event,
        on_status=on_status, on_progress=on_progress,
    )

    if not segments:
        raise RuntimeError("Nessun segmento trovato nella trascrizione.")

    status("Ottimizzazione timing sottotitoli...")
    segments = post_process_timing(segments)

    status("Generazione file SRT...")
    subtitles = [Subtitle(start=s["start"], end=s["end"], text=s["text"]) for s in segments]
    write_srt(subtitles, output_path)
    status(f"Salvato: {Path(output_path).name} ({len(subtitles)} sottotitoli)")
    return output_path

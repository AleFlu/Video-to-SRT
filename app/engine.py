"""
engine.py — Core della trascrizione (ottimizzato per italiano)

Stack: faster-whisper (CTranslate2) + large-v3 + VAD Silero
Compatibile: Python 3.9+, macOS 12+ (M1/M2/M3/M4).
"""

from __future__ import annotations  # Abilita str | None su Python 3.9

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Optional, Tuple, List, Dict
import re


class TranscriptionCancelled(Exception):
    """Eccezione sollevata quando l'utente annulla la trascrizione."""
    pass


# ============================================================
# Cache e stato globale
# ============================================================
_model_cache: Dict = {"model": None, "model_key": None}
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


def _postprocess_italian(text: str) -> str:
    """Corregge le italianizzazioni più comuni prodotte da Whisper con language=it.

    Applica sostituzioni regex case-insensitive preservando la capitalizzazione
    originale (tutto-maiuscolo = acronimo, prima-maiuscola = inizio frase/nome).
    Compatibile Python 3.9+, zero dipendenze esterne.
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

# Sottotitoli
MAX_CHARS_PER_LINE = 42

# Timing sottotitoli
MAX_SUBTITLE_DURATION = 7.0
MIN_GAP_BETWEEN_SUBS = 0.08
MIN_SUBTITLE_DURATION = 0.5
READING_SPEED_CPS = 17.0
SILENCE_THRESHOLD = 0.4
END_PAD_SPEECH = 0.15
END_PAD_SILENCE = 0.05


# ============================================================
# Bundle helpers (PyInstaller .app)
# ============================================================
def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def get_bundled_ffmpeg() -> Optional[str]:
    if _is_frozen():
        p = Path(sys._MEIPASS) / "ffmpeg"
        return str(p) if p.exists() else None
    return None


def get_bundled_model_dir() -> Optional[str]:
    if _is_frozen():
        d = Path(sys._MEIPASS) / "whisper_model"
        if d.exists() and any(d.iterdir()):
            return str(d)
    return None


def _get_p_core_count() -> int:
    try:
        result = subprocess.run(
            ["sysctl", "-n", "hw.perflevel0.logicalcpu"],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            count = int(result.stdout.strip())
            if count > 0:
                return count
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError, OSError):
        pass
    total = os.cpu_count() or 8
    return max(4, total // 2)


def _get_optimal_cpu_threads() -> int:
    count = _get_p_core_count()
    print(f"[engine] P-cores: {count} (totale CPU: {os.cpu_count()})")
    return count


def _setup_environment():
    """Setup una tantum: CPU threads, FFmpeg PATH, VAD model."""
    global _setup_done
    if _setup_done:
        return
    _setup_done = True

    thread_str = str(_get_optimal_cpu_threads())
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "CT2_NUM_THREADS",
                "OMP_WAIT_POLICY"):
        if var not in os.environ:
            if var == "OMP_WAIT_POLICY":
                os.environ[var] = "PASSIVE"
            else:
                os.environ[var] = thread_str

    bundled_ffmpeg = get_bundled_ffmpeg()
    if bundled_ffmpeg:
        ffmpeg_dir = str(Path(bundled_ffmpeg).parent)
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

    if not _is_frozen():
        return

    bundle_dir = Path(sys._MEIPASS)

    vad_onnx = None
    for candidate in [
        bundle_dir / "silero_vad" / "silero_vad.onnx",
        bundle_dir / "faster_whisper" / "assets" / "silero_vad.onnx",
    ]:
        if candidate.exists():
            vad_onnx = candidate
            break

    if not vad_onnx:
        for f in bundle_dir.rglob("silero_vad.onnx"):
            vad_onnx = f
            break

    if vad_onnx:
        import shutil
        for cache_path in [
            Path.home() / ".cache" / "silero-vad",
            Path.home() / ".cache" / "torch" / "hub" / "snakers4_silero-vad_master",
        ]:
            cache_path.mkdir(parents=True, exist_ok=True)
            dst = cache_path / "silero_vad.onnx"
            if not dst.exists():
                shutil.copy2(vad_onnx, dst)


# ============================================================
# Checks
# ============================================================
def check_ffmpeg() -> bool:
    if get_bundled_ffmpeg():
        return True
    try:
        subprocess.run(["ffmpeg", "-version"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


# ============================================================
# Pre-processing audio
# ============================================================
def preprocess_audio(input_path: str, on_status: Optional[Callable] = None) -> Optional[str]:
    import tempfile

    if on_status:
        on_status("Pre-elaborazione audio (riduzione rumore)...")

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_path = tmp.name
    tmp.close()

    ffmpeg_cmd = "ffmpeg"
    bundled = get_bundled_ffmpeg()
    if bundled:
        ffmpeg_cmd = bundled

    cmd = [
        ffmpeg_cmd,
        "-i", input_path,
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

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            if on_status:
                on_status("Audio pre-elaborato")
            return tmp_path
        else:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return None
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return None


# ============================================================
# Modello: caricamento e cache
# ============================================================
def get_optimal_device() -> Tuple[str, str]:
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda", "float16"
        if torch.backends.mps.is_available():
            if os.environ.get("VSRT_FORCE_MPS") == "1":
                return "mps", "float32"
            print("[engine] Apple Silicon: CPU int8 > MPS float32 per CT2 4.x")
    except ImportError:
        pass
    return "cpu", "int8"


def _get_or_load_model(model_size: str = DEFAULT_MODEL,
                        on_status: Optional[Callable] = None):
    from faster_whisper import WhisperModel
    import ctranslate2

    bundled = get_bundled_model_dir()
    if bundled and model_size == DEFAULT_MODEL:
        model_path = bundled
    else:
        model_path = model_size

    device, compute_type = get_optimal_device()
    cache_key = (model_path, device, compute_type)

    if _model_cache["model"] is not None and _model_cache["model_key"] == cache_key:
        if on_status:
            on_status("Modello già pronto")
        return _model_cache["model"], device, compute_type

    if on_status:
        on_status(f"Caricamento modello '{model_size}'...")

    cpu_threads = _get_optimal_cpu_threads()
    ct2_types = ctranslate2.get_supported_compute_types("cpu")
    print(f"[engine] CTranslate2 compute types: {ct2_types}")
    print(f"[engine] CPU threads: {cpu_threads}")
    print(f"[engine] OMP_NUM_THREADS: {os.environ.get('OMP_NUM_THREADS', 'NOT SET')}")
    print(f"[engine] Device: {device}, Compute: {compute_type}")
    print(f"[engine] Model path: {model_path}")
    print(f"[engine] Frozen: {_is_frozen()}")

    model = WhisperModel(model_path, device=device, compute_type=compute_type,
                          cpu_threads=cpu_threads)
    _model_cache["model"] = model
    _model_cache["model_key"] = cache_key

    info_str = f"Modello pronto ({device}, {compute_type}, {cpu_threads}t)"
    if on_status:
        on_status(info_str)
    print(f"[engine] {info_str}")
    return model, device, compute_type


def preload_model(model_size: str = DEFAULT_MODEL,
                  on_status: Optional[Callable] = None) -> bool:
    try:
        _setup_environment()
        _get_or_load_model(model_size, on_status=on_status)
        return True
    except Exception as e:
        if on_status:
            on_status(f"Pre-caricamento fallito: {e}")
        return False


# ============================================================
# Timestamp e formattazione SRT
# ============================================================
def format_timestamp_srt(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total_ms = round(seconds * 1000)
    ms = total_ms % 1000
    total_secs = total_ms // 1000
    secs = total_secs % 60
    total_mins = total_secs // 60
    mins = total_mins % 60
    hrs = total_mins // 60
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"


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


def _postprocess_italian_subs(text: str) -> str:
    """Correzioni tipografiche per sottotitoli (spazi prima di punteggiatura, apostrofi, ecc.)."""
    for pattern, replacement in _IT_FIXES:
        text = pattern.sub(replacement, text)
    return text.strip()


def collect_all_words(segments_iter, min_word_prob: float = MIN_WORD_PROB) -> List:
    """Raccoglie tutte le parole da tutti i segmenti in una lista flat globale.

    Ignora segmenti con no_speech_prob alto o avg_logprob troppo basso.
    Restituisce la lista di word objects con .start .end .word .probability.
    Tiene anche traccia dei boundary di segmento Whisper come hard break impliciti.
    """
    all_words = []
    seg_boundaries: set = set()  # indici in all_words dove inizia un nuovo segmento

    for seg in segments_iter:
        no_speech  = getattr(seg, "no_speech_prob", 0.0)
        avg_logprob = getattr(seg, "avg_logprob", 0.0)
        if no_speech > 0.9 or avg_logprob < -1.8:
            continue

        words = getattr(seg, "words", None) or []
        valid = [w for w in words
                 if w.word.strip() and getattr(w, "probability", 1.0) >= min_word_prob]

        if not valid:
            # Nessuna parola con timestamp: usa testo grezzo del segmento come blocco unico
            text = getattr(seg, "text", "").strip()
            if text:
                # Crea un word-like object sintetico
                class _FakeWord:
                    def __init__(self, word, start, end):
                        self.word  = word
                        self.start = start
                        self.end   = end
                        self.probability = 1.0
                        self._is_synthetic = True
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


def segment_words_semantic(all_words: List, seg_boundaries: set) -> List[Dict]:
    """Segmentazione semantica globale su stream di parole.

    Priorità di split forward (per ogni parola appena accumulata):
      P1  boundary di segmento Whisper (VAD hard break)
      P2  gap acustico >= GAP_FORCE (silenzio reale)
      P3  punteggiatura forte (.!?…) — SEMPRE, senza condizione sul gap
      P4  punteggiatura debole (,;:–—) + gap >= GAP_CLAUSE + blocco >= 20 char
      P5  blocco >= SOFT_LIMIT + gap >= GAP_SOFT (split opportunistico)
      P6  blocco >= HARD_LIMIT → best-gap-split retroattivo sul blocco accumulato
    """
    if not all_words:
        return []

    subtitles: List[Dict] = []
    current: List        = []

    def _flush_words(words: List):
        if not words:
            return
        if getattr(words[0], "_is_synthetic", False):
            text = words[0].word
        else:
            text = " ".join(w.word.strip() for w in words)
        text = _postprocess_italian_subs(text)
        if text:
            subtitles.append({
                "start": words[0].start,
                "end":   words[-1].end,
                "text":  text,
            })

    n = len(all_words)
    for i, word in enumerate(all_words):
        current.append(word)
        is_last = (i == n - 1)

        if is_last:
            break

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
                if split_at > 0 and split_at < len(current):
                    _flush_words(current[:split_at])
                    current = current[split_at:]
                    # flush il residuo (include la parola col punto)
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
            if split_at > 0 and split_at < len(current):
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

    # Merge frammenti corti verso il subtitle SUCCESSIVO
    if len(subtitles) >= 2:
        merged: List[Dict] = []
        i = 0
        while i < len(subtitles):
            sub = subtitles[i]
            if (len(sub["text"]) < MERGE_MIN_CHARS
                    and i + 1 < len(subtitles)
                    and (subtitles[i + 1]["start"] - sub["end"]) < 0.5):
                nxt = subtitles[i + 1]
                merged.append({
                    "start": sub["start"],
                    "end":   nxt["end"],
                    "text":  sub["text"] + " " + nxt["text"],
                })
                i += 2
            else:
                merged.append(sub)
                i += 1
        subtitles = merged

    return subtitles


# Mantenuto per compatibilità con path WhisperX che passa segmenti singoli
def split_segment_by_words(segment) -> List[Dict]:
    """Wrapper legacy: usa la nuova pipeline globale su un singolo segmento."""
    words, boundaries = collect_all_words([segment])
    return segment_words_semantic(words, boundaries)


def wrap_subtitle_text(text: str) -> str:
    if len(text) <= MAX_CHARS_PER_LINE:
        return text
    mid = len(text) // 2
    for offset in range(0, mid):
        for pos in [mid + offset, mid - offset]:
            if 0 <= pos < len(text) and text[pos] == " ":
                return text[:pos] + "\n" + text[pos + 1:]
    return text


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
    return processed


def generate_srt(segments: List[Dict]) -> str:
    srt_lines = []
    index = 1
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        start = format_timestamp_srt(seg["start"])
        end = format_timestamp_srt(seg["end"])
        srt_lines.append(f"{index}\n{start} --> {end}\n{wrap_subtitle_text(text)}\n")
        index += 1
    return "\n".join(srt_lines)


# ============================================================
# Trascrizione WhisperX
# ============================================================
def _transcribe_whisperx(
    audio_path: str,
    model_size: str = DEFAULT_MODEL,
    beam_size: int = 5,
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

    def _check_cancel():
        if cancel_event and cancel_event.is_set():
            raise TranscriptionCancelled("Trascrizione annullata dall'utente")

    device, compute_type = get_optimal_device()
    # WhisperX wav2vec2 alignment doesn't support MPS — fall back to CPU for full pipeline
    if device == "mps":
        device, compute_type = "cpu", "int8"
    print(f"[engine] WhisperX backend: {model_size}, {device}, {compute_type}")

    status("WhisperX · Caricamento modello...")
    progress(0.10)
    _check_cancel()

    wx_model = whisperx.load_model(
        model_size, device=device, compute_type=compute_type,
        language="it",
        asr_options={
            "initial_prompt": ITALIAN_PROMPT,
            "beam_size": beam_size,
            "word_timestamps": True,
        },
    )

    progress(0.20)
    status("WhisperX · Trascrizione in corso...")
    _check_cancel()

    result = wx_model.transcribe(audio_path, batch_size=8)
    detected_lang = result.get("language", "it")
    print(f"[engine] WhisperX: lingua rilevata = {detected_lang}")
    print(f"[engine] WhisperX: {len(result.get('segments', []))} segmenti raw")

    progress(0.50)
    _check_cancel()

    del wx_model
    import gc
    gc.collect()

    status("WhisperX · Allineamento fonetico (wav2vec2)...")

    try:
        align_model, align_metadata = whisperx.load_align_model(
            language_code=detected_lang, device=device,
        )
        _check_cancel()

        aligned = whisperx.align(
            result["segments"], align_model, align_metadata,
            audio_path, device=device,
            return_char_alignments=False,
        )

        del align_model
        gc.collect()

        segments = aligned.get("segments", result.get("segments", []))
        print(f"[engine] WhisperX: {len(segments)} segmenti allineati")
    except Exception as align_err:
        print(f"[engine] WhisperX alignment fallito: {align_err}")
        status("⚠️ Allineamento non riuscito — uso timestamp Whisper")
        segments = result.get("segments", [])

    progress(0.75)
    _check_cancel()

    status("WhisperX · Segmentazione sottotitoli...")

    collected = []
    total = len(segments)

    for i, seg in enumerate(segments):
        _check_cancel()

        text = seg.get("text", "").strip()
        if not text:
            continue

        words = seg.get("words", [])

        if words:
            adapter = _WhisperXSegmentAdapter(seg)
            subs = split_segment_by_words(adapter)
            collected.extend(subs)
        else:
            start = seg.get("start", 0)
            end = seg.get("end", 0)
            if start is not None and end is not None:
                collected.append({"start": start, "end": end, "text": text})

        if total > 0:
            progress(0.75 + (i / total) * 0.20)
            status(f"Segmentazione... {int((i + 1) / total * 100)}%")

    # Post-processing code-switching: corregge italianizzazioni Whisper
    for seg in collected:
        seg["text"] = _postprocess_italian(seg["text"])

    status(f"Trascrizione completata: {len(collected)} sottotitoli (WhisperX)")
    progress(1.0)
    return collected


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


# ============================================================
# Trascrizione (dispatcher)
# ============================================================
def transcribe(
    input_path: str,
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

    def status(msg):
        if on_status:
            on_status(msg)

    def progress(pct):
        if on_progress:
            on_progress(pct)

    def _check_cancel():
        if cancel_event and cancel_event.is_set():
            raise TranscriptionCancelled("Trascrizione annullata dall'utente")

    _setup_environment()

    progress(0.05)

    _check_cancel()
    preprocessed_path = None
    if denoise:
        preprocessed_path = preprocess_audio(input_path, on_status=on_status)
    audio_path = preprocessed_path if preprocessed_path else input_path
    if preprocessed_path:
        status("Audio ripulito")
    progress(0.10)

    try:
        if high_accuracy and _has_whisperx() and not _is_frozen():
            try:
                status("Backend: WhisperX (alta precisione)")
                print("[engine] Usando WhisperX backend (wav2vec2 alignment)")
                return _transcribe_whisperx(
                    audio_path, model_size=model_size, beam_size=beam_size,
                    cancel_event=cancel_event, on_status=on_status, on_progress=on_progress,
                )
            except TranscriptionCancelled:
                raise
            except Exception as wx_err:
                print(f"[engine] WhisperX fallito: {wx_err}")
                status("⚠️ WhisperX non riuscito — fallback a faster-whisper...")

        print("[engine] Usando faster-whisper backend (CPU)")
        model, device, compute_type = _get_or_load_model(model_size, on_status=on_status)
        progress(0.15)

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
        _check_cancel()
        status("Elaborazione audio in corso...")

        if vad_filter:
            try:
                segments_iter, info = model.transcribe(
                    audio_path, **transcribe_params,
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=150, speech_pad_ms=100, threshold=0.50),
                )
                _check_cancel()
                first_seg = next(segments_iter, None)
                vad_active = True
            except TranscriptionCancelled:
                raise
            except Exception as vad_err:
                err_str = str(vad_err)
                if any(k in err_str for k in ("ONNX", "onnx", "NO_SUCHFILE")):
                    status("⚠️ VAD non disponibile — proseguo senza filtro silenzi...")
                    first_seg = None
                else:
                    raise

        if not vad_active:
            _check_cancel()
            segments_iter, info = model.transcribe(audio_path, **transcribe_params, vad_filter=False)
            _check_cancel()
            first_seg = next(segments_iter, None)

        _check_cancel()

        duration = info.duration or 0
        vad_label = " · VAD attivo" if vad_active else (" · VAD off" if vad_filter else "")
        status(f"Lingua: {info.language} ({info.language_probability:.0%}){vad_label}")

        # Raccoglie tutti i segmenti raw per la pipeline globale
        raw_segments = []

        def collect_segment(seg):
            _check_cancel()
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
        all_words, seg_boundaries = collect_all_words(iter(raw_segments))
        collected = segment_words_semantic(all_words, seg_boundaries)

        # Post-processing code-switching: corregge italianizzazioni Whisper
        if language == "it":
            for seg in collected:
                seg["text"] = _postprocess_italian(seg["text"])

        status(f"Trascrizione completata: {len(collected)} sottotitoli")
        progress(1.0)
        return collected

    finally:
        if preprocessed_path:
            try:
                os.unlink(preprocessed_path)
            except OSError:
                pass


# ============================================================
# Output
# ============================================================
def write_srt(segments: List[Dict], output_path: str):
    os.makedirs(str(Path(output_path).parent), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(generate_srt(segments))


def _unique_output_path(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return path
    counter = 2
    while True:
        new_path = p.parent / f"{p.stem}_{counter}{p.suffix}"
        if not new_path.exists():
            return str(new_path)
        counter += 1


# ============================================================
# Pipeline completa (mantenuta per CLI e compat)
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
) -> str:

    def status(msg):
        if on_status:
            on_status(msg)

    if not output_path:
        output_path = str(Path(input_path).with_suffix(".srt"))
    output_path = _unique_output_path(output_path)

    segments = transcribe(
        input_path, model_size=model_size, beam_size=beam_size,
        vad_filter=vad_filter, denoise=denoise, high_accuracy=high_accuracy,
        cancel_event=cancel_event,
        on_status=on_status, on_progress=on_progress,
    )

    if not segments:
        raise RuntimeError("Nessun segmento trovato nella trascrizione.")

    status("Ottimizzazione timing sottotitoli...")
    segments = post_process_timing(segments)

    status("Generazione file SRT...")
    write_srt(segments, output_path)
    status(f"Salvato: {Path(output_path).name} ({len(segments)} sottotitoli)")
    return output_path

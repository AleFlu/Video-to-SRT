"""
engine.py — Core della trascrizione (ottimizzato per italiano)

Stack: faster-whisper (CTranslate2) + large-v3 + VAD Silero
Compatibile: Python 3.9+, macOS 12+ (M1/M2/M3/M4)
"""

from __future__ import annotations  # Abilita str | None su Python 3.9

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Optional, Tuple, List, Dict


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
# Memory helpers
# ============================================================
def _get_available_memory_gb() -> float:
    """Restituisce la RAM disponibile in GB. Fallback conservativo."""
    try:
        import platform as _plat
        if _plat.system() == "Darwin":
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=5,
            )
            total_bytes = int(result.stdout.strip())
            result2 = subprocess.run(
                ["vm_stat"], capture_output=True, text=True, timeout=5,
            )
            lines = result2.stdout.split("\n")
            page_size = 16384
            free_pages = inactive_pages = 0
            for line in lines:
                if "page size of" in line:
                    page_size = int(line.split()[-2])
                elif "Pages free" in line:
                    free_pages = int(line.split()[-1].rstrip("."))
                elif "Pages inactive" in line:
                    inactive_pages = int(line.split()[-1].rstrip("."))
            return (free_pages + inactive_pages) * page_size / (1024 ** 3)
        else:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable"):
                        return int(line.split()[1]) / (1024 ** 2)
    except Exception:
        pass
    return 4.0


def _release_cached_model():
    """Libera il modello faster-whisper dalla cache per fare spazio in RAM."""
    import gc
    if _model_cache["model"] is not None:
        print("[engine] Rilascio modello faster-whisper dalla cache per liberare RAM...")
        _model_cache["model"] = None
        _model_cache["model_key"] = None
        gc.collect()

# ============================================================
# Configurazione
# ============================================================
ITALIAN_PROMPT = (
    "Questa è una trascrizione in lingua italiana con punteggiatura corretta, "
    "inclusi punti, virgole, punti interrogativi e punti esclamativi. "
    "I nomi propri hanno la lettera maiuscola."
)

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
MAX_LINES_PER_SUB = 2
MAX_CHARS_PER_SUB = MAX_CHARS_PER_LINE * MAX_LINES_PER_SUB

# Timing sottotitoli
MAX_SUBTITLE_DURATION = 7.0
MIN_GAP_BETWEEN_SUBS = 0.08
MIN_SUBTITLE_DURATION = 0.5
READING_SPEED_CPS = 17.0
SILENCE_THRESHOLD = 0.8
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


def _get_optimal_cpu_threads() -> int:
    """
    Determina il numero ottimale di thread per CTranslate2.
    Su Apple Silicon usa tutti i core disponibili.
    os.cpu_count() restituisce il totale (performance + efficiency).
    """
    count = os.cpu_count()
    if count is None:
        return 4
    return count


def _setup_environment():
    """Setup una tantum: CPU threads, FFmpeg PATH, VAD model."""
    global _setup_done
    if _setup_done:
        return
    _setup_done = True

    # --- CPU threading: fondamentale per le performance nel bundle ---
    # DEVE essere settato PRIMA di qualsiasi import di ctranslate2/onnxruntime
    thread_str = str(_get_optimal_cpu_threads())
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "CT2_NUM_THREADS",
                "OMP_WAIT_POLICY"):
        if var not in os.environ:
            if var == "OMP_WAIT_POLICY":
                os.environ[var] = "PASSIVE"  # Riduce consumo CPU in idle
            else:
                os.environ[var] = thread_str

    # FFmpeg bundlato → aggiungi al PATH
    bundled_ffmpeg = get_bundled_ffmpeg()
    if bundled_ffmpeg:
        ffmpeg_dir = str(Path(bundled_ffmpeg).parent)
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

    if not _is_frozen():
        return

    # Nel bundle: assicura che il modello Silero VAD sia trovabile
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


def check_whisper() -> bool:
    try:
        from faster_whisper import WhisperModel  # noqa: F401
        return True
    except ImportError:
        return False


# ============================================================
# Pre-processing audio (riduzione rumore per audio scadente)
# ============================================================
def preprocess_audio(input_path: str, on_status: Optional[Callable] = None) -> Optional[str]:
    """
    Pre-processa l'audio con FFmpeg per migliorare la qualità della trascrizione.

    Applica in sequenza:
    1. Highpass a 100Hz — rimuove rumble e ronzii bassi
    2. afftdn — riduzione rumore adattiva FFT
    3. loudnorm — normalizzazione volume EBU R128
    4. Conversione a 16kHz mono WAV (formato ottimale per Whisper)

    Restituisce il path del file temporaneo, o None se fallisce.
    Il chiamante è responsabile di cancellare il file temporaneo.
    """
    import tempfile

    if on_status:
        on_status("Pre-elaborazione audio (riduzione rumore)...")

    # Crea file temporaneo
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_path = tmp.name
    tmp.close()

    # Determina il path di FFmpeg (bundlato o di sistema)
    ffmpeg_cmd = "ffmpeg"
    bundled = get_bundled_ffmpeg()
    if bundled:
        ffmpeg_cmd = bundled

    cmd = [
        ffmpeg_cmd,
        "-i", input_path,
        "-vn",                          # Scarta video
        "-af", ",".join([
            "highpass=f=100",            # Rimuovi sotto 100Hz
            "afftdn=nf=-20",            # Riduzione rumore FFT (-20dB noise floor)
            "loudnorm=I=-16:TP=-1.5",   # Normalizzazione volume broadcast standard
        ]),
        "-ar", "16000",                 # 16kHz (ottimale per Whisper)
        "-ac", "1",                     # Mono
        "-c:a", "pcm_s16le",           # WAV 16-bit
        "-y",                           # Sovrascrivi
        tmp_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            if on_status:
                on_status("Audio pre-elaborato")
            return tmp_path
        else:
            # FFmpeg fallito — elimina il file e torna None
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
    except ImportError:
        pass
    return "cpu", "int8"


def _get_or_load_model(model_size: str = DEFAULT_MODEL,
                        on_status: Optional[Callable] = None):
    from faster_whisper import WhisperModel
    import ctranslate2

    # Usa il modello bundlato SOLO se corrisponde a quello richiesto
    bundled = get_bundled_model_dir()
    if bundled and model_size == DEFAULT_MODEL:
        model_path = bundled
    else:
        model_path = model_size  # Scarica da HuggingFace cache

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
# Segmentazione sottotitoli
# ============================================================
SENTENCE_ENDINGS = {".", "!", "?", "…"}
SENTENCE_SPLIT = 0.03  # Dopo . ! ? basta 30ms — Whisper comprime i gap tra frasi
WORD_GAP_SPLIT = 0.4   # Se la pausa tra due parole è > 400ms, forza split
MIN_WORD_PROB = 0.35   # Parole con probabilità sotto questa soglia vengono scartate
                       # (probabili allucinazioni da rumore di fondo)


def split_segment_by_words(segment) -> List[Dict]:
    """
    Spezza un segmento in sotto-segmenti usando i word timestamps.

    Criteri di split (in ordine di priorità):
    1. Silenzio lungo (≥ 0.8s) → split sempre
    2. Fine frase (. ! ?) + micro-gap (≥ 30ms) → split
    3. Parola successiva maiuscola + micro-gap → nuova frase
    4. Pausa media (> 400ms) tra parole → split
    5. Superamento limite caratteri (84)

    Anti-orfano: parole corte (A, E, Il, La...) a fine blocco vengono
    spostate al blocco successivo con timing corretto.
    """
    if not hasattr(segment, "words") or not segment.words:
        return [{"start": segment.start, "end": segment.end, "text": segment.text.strip()}]

    # Filtra parole con probabilità troppo bassa
    words = []
    for w in segment.words:
        text = w.word.strip()
        if not text:
            continue
        prob = getattr(w, "probability", 1.0)
        if prob < MIN_WORD_PROB:
            continue
        words.append(w)

    if not words:
        return []

    # --- Fase 1: raccogli blocchi di words ---
    blocks = []  # Ogni blocco è una lista di word objects
    current_block = []

    for i, word in enumerate(words):
        word_text = word.word.strip()
        current_text = " ".join(w.word.strip() for w in current_block) if current_block else ""
        test_text = (current_text + " " + word_text).strip() if current_text else word_text

        # Limite caratteri → split PRIMA di questa parola
        if len(test_text) > MAX_CHARS_PER_SUB and current_block:
            remaining = sum(len(w.word.strip()) + 1 for w in words[i:])
            if remaining >= 20:
                blocks.append(current_block)
                current_block = []

        current_block.append(word)

        # Check split DOPO questa parola
        if i < len(words) - 1:
            next_word = words[i + 1]
            next_text = next_word.word.strip()
            gap = next_word.start - word.end
            ends_sentence = any(word_text.endswith(p) for p in SENTENCE_ENDINGS)
            current_len = len(" ".join(w.word.strip() for w in current_block))
            next_is_upper = len(next_text) > 0 and next_text[0].isupper()

            should_split = False

            # 1. Silenzio lungo → split SEMPRE (era il bug: prima richiedeva
            #    anche current_len >= 20, lasciando parole orfane nel blocco)
            if gap > SILENCE_THRESHOLD:
                should_split = True

            # 2. Fine frase (. ! ?) + micro-gap (30ms) per evitare split
            #    su timestamp sovrapposti di Whisper
            if not should_split and ends_sentence and gap >= SENTENCE_SPLIT and current_len >= 10:
                should_split = True

            # 3. Prossima parola maiuscola = nuova frase (anche senza punto)
            #    Es: "casa Il giorno dopo" → split prima di "Il"
            if not should_split and next_is_upper and gap >= SENTENCE_SPLIT and current_len >= 8:
                should_split = True

            # 4. Pausa media tra parole
            remaining = sum(len(w.word.strip()) + 1 for w in words[i + 1:])
            if not should_split and gap > WORD_GAP_SPLIT and current_len > 10 and remaining >= 20:
                should_split = True

            if should_split:
                blocks.append(current_block)
                current_block = []

    if current_block:
        blocks.append(current_block)

    if not blocks:
        return [{"start": segment.start, "end": segment.end, "text": segment.text.strip()}]

    # --- Fase 2: anti-orfano ---
    # Sposta parole corte (≤3 chars, senza punteggiatura) dalla fine
    # di un blocco all'inizio del blocco successivo.
    for b in range(len(blocks) - 1):
        block = blocks[b]
        if len(block) <= 1:
            continue
        last_word = block[-1].word.strip()
        if len(last_word) <= 3 and not any(last_word.endswith(p) for p in SENTENCE_ENDINGS):
            orphan = block.pop()
            blocks[b + 1].insert(0, orphan)

    # --- Fase 3: converti blocchi → sottotitoli con timing corretto ---
    subtitles = []
    for b_idx, block in enumerate(blocks):
        if not block:
            continue
        text = " ".join(w.word.strip() for w in block)
        if not text.strip():
            continue

        # Start time: normalmente è il primo word del blocco.
        # MA se il primo word è un orfano spostato dal blocco precedente
        # (pronunciato prima del silenzio), usiamo il SECONDO word come start
        # (quello pronunciato dopo il silenzio).
        start_time = block[0].start
        end_time = block[-1].end

        if len(block) >= 2 and b_idx > 0:
            prev_block = blocks[b_idx - 1]
            if prev_block:
                prev_end = prev_block[-1].end
                gap_before_orphan = block[0].start - prev_end
                gap_after_orphan = block[1].start - block[0].end
                # Se c'è un silenzio significativo tra la prima e la seconda parola
                # del blocco, la prima è un orfano → start dalla seconda
                if gap_after_orphan > 0.3:
                    start_time = block[1].start

        subtitles.append({
            "start": start_time,
            "end": end_time,
            "text": text.strip(),
        })

    # --- Fase 4: unisci sottotitoli troppo corti ---
    if len(subtitles) >= 2:
        cleaned = []
        i = 0
        while i < len(subtitles):
            sub = subtitles[i]
            if len(sub["text"]) <= 4 and i < len(subtitles) - 1:
                nxt = subtitles[i + 1]
                cleaned.append({
                    "start": nxt["start"],  # Usa lo start del blocco principale
                    "end": nxt["end"],
                    "text": sub["text"] + " " + nxt["text"],
                })
                i += 2
            else:
                cleaned.append(sub)
                i += 1
        subtitles = cleaned

    if not subtitles:
        return [{"start": segment.start, "end": segment.end, "text": segment.text.strip()}]
    return subtitles


def wrap_subtitle_text(text: str) -> str:
    """Spezza il testo su max 2 righe da ~42 caratteri."""
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
    """Elimina i sottotitoli che restano visibili durante i silenzi."""
    if not segments:
        return segments

    processed = []
    n = len(segments)

    for i, seg in enumerate(segments):
        start = seg["start"]
        end = seg["end"]
        text = seg["text"].strip()
        if not text:
            continue

        min_reading_time = max(MIN_SUBTITLE_DURATION, len(text) / READING_SPEED_CPS)

        if i < n - 1:
            next_start = segments[i + 1]["start"]
            is_followed_by_silence = (next_start - end) > SILENCE_THRESHOLD
        else:
            is_followed_by_silence = True

        if is_followed_by_silence:
            ideal_end = start + min_reading_time
            new_end = min(ideal_end, end + END_PAD_SILENCE)
            new_end = max(new_end, start + min_reading_time)
        else:
            new_end = end + END_PAD_SPEECH

        if (new_end - start) > MAX_SUBTITLE_DURATION:
            new_end = start + MAX_SUBTITLE_DURATION

        if i < n - 1:
            max_allowed = segments[i + 1]["start"] - MIN_GAP_BETWEEN_SUBS
            if new_end > max_allowed:
                new_end = max_allowed

        if new_end <= start:
            new_end = start + MIN_SUBTITLE_DURATION

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
# WhisperX: alta precisione con allineamento fonetico
# ============================================================
def _get_whisperx_batch_size() -> int:
    """Batch_size ottimale per WhisperX in base alla RAM disponibile."""
    available_gb = _get_available_memory_gb()
    print(f"[engine] RAM disponibile: {available_gb:.1f} GB")
    if available_gb > 10:
        return 4
    elif available_gb > 6:
        return 2
    else:
        return 1  # Minimo — lento ma non crasha


class _WhisperXWordAdapter:
    """Adatta un word dict di WhisperX all'interfaccia di split_segment_by_words."""
    __slots__ = ("word", "start", "end", "probability")

    def __init__(self, d: Dict):
        self.word = d.get("word", "")
        self.start = d.get("start", 0.0)
        self.end = d.get("end", 0.0)
        self.probability = d.get("score", 1.0)


class _WhisperXSegmentAdapter:
    """Adatta un segment dict di WhisperX all'interfaccia di split_segment_by_words."""
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
    model_size: str = DEFAULT_MODEL,
    beam_size: int = 5,
    cancel_event: Optional[threading.Event] = None,
    on_status: Optional[Callable] = None,
    on_progress: Optional[Callable] = None,
) -> List[Dict]:
    """
    WhisperX pipeline:
    1. Whisper → testo accurato
    2. wav2vec2 italiano → word timestamps ±20ms
    3. Stessa segmentazione a 4 fasi di faster-whisper
    """
    import gc
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

    device = "cpu"
    compute_type = "int8"

    # Libera il modello faster-whisper dalla cache (splash screen lo precarica)
    _release_cached_model()
    status("WhisperX · Liberata memoria dal modello precedente")

    available_gb = _get_available_memory_gb()
    print(f"[engine] WhisperX: {model_size}, {device}, RAM disponibile: {available_gb:.1f} GB")

    # Check memoria minima — downgrade se necessario
    min_ram = 5.0 if model_size in ("large-v3", "large-v3-turbo") else 3.0
    if available_gb < min_ram:
        fallback = "small" if available_gb < 3.0 else "medium"
        status(f"⚠️ RAM insufficiente ({available_gb:.1f} GB) per {model_size}, uso '{fallback}'")
        model_size = fallback

    # --- Step 1: Trascrizione ---
    status("WhisperX · Caricamento modello...")
    progress(0.10)
    _check_cancel()

    batch_size = _get_whisperx_batch_size()
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
    status(f"WhisperX · Trascrizione (batch={batch_size})...")
    _check_cancel()

    result = wx_model.transcribe(audio_path, batch_size=batch_size)
    detected_lang = result.get("language", "it")
    print(f"[engine] WhisperX: lingua={detected_lang}, "
          f"{len(result.get('segments', []))} segmenti raw")

    progress(0.50)
    _check_cancel()

    # Libera modello Whisper prima di caricare wav2vec2
    del wx_model
    gc.collect()

    import time
    time.sleep(0.5)

    # --- Step 2: Allineamento fonetico ---
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

        del align_model, align_metadata
        gc.collect()

        segments = aligned.get("segments", result.get("segments", []))
        print(f"[engine] WhisperX: {len(segments)} segmenti allineati")
    except Exception as align_err:
        print(f"[engine] WhisperX alignment fallito: {align_err}")
        status("⚠️ Allineamento non riuscito — uso timestamp Whisper")
        segments = result.get("segments", [])

    del result
    gc.collect()

    progress(0.75)
    _check_cancel()

    # --- Step 3: Segmentazione (stessa pipeline a 4 fasi) ---
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

    status(f"Trascrizione completata: {len(collected)} sottotitoli (WhisperX)")
    progress(1.0)
    return collected


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

    # --- Pre-processing audio (opzionale) ---
    _check_cancel()
    preprocessed_path = None
    if denoise:
        preprocessed_path = preprocess_audio(input_path, on_status=on_status)
    audio_path = preprocessed_path if preprocessed_path else input_path
    if preprocessed_path:
        status("Audio ripulito")
    progress(0.10)

    try:
        # --- Backend WhisperX (alta precisione) ---
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
            except MemoryError:
                import gc
                gc.collect()
                status("⚠️ Memoria esaurita con WhisperX — fallback a faster-whisper...")
                print("[engine] MemoryError con WhisperX, fallback")
            except Exception as wx_err:
                print(f"[engine] WhisperX fallito: {wx_err}")
                status("⚠️ WhisperX non riuscito — fallback a faster-whisper...")

        # --- Backend faster-whisper (standard) ---
        print("[engine] Usando faster-whisper backend (CPU)")
        model, device, compute_type = _get_or_load_model(model_size, on_status=on_status)
        progress(0.15)

        transcribe_params = dict(
            language="it",
            task="transcribe",
            beam_size=beam_size,
            patience=1.0,
            initial_prompt=ITALIAN_PROMPT,
            word_timestamps=True,
            condition_on_previous_text=True,
            no_speech_threshold=0.6,
            log_prob_threshold=-1.0,
            compression_ratio_threshold=2.4,
            temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
        )

        vad_active = False
        _check_cancel()
        status("Elaborazione audio in corso...")

        if vad_filter:
            try:
                segments_iter, info = model.transcribe(
                    audio_path, **transcribe_params,
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=500, speech_pad_ms=300, threshold=0.5),
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

        collected = []

        def process_segment(seg):
            _check_cancel()
            no_speech = getattr(seg, "no_speech_prob", 0)
            avg_logprob = getattr(seg, "avg_logprob", 0)
            if no_speech > 0.8:
                if duration > 0:
                    progress(min(0.15 + (seg.end / duration) * 0.8, 0.95))
                return
            if avg_logprob < -1.5:
                if duration > 0:
                    progress(min(0.15 + (seg.end / duration) * 0.8, 0.95))
                return
            subs = split_segment_by_words(seg)
            collected.extend(subs)
            if duration > 0:
                progress(min(0.15 + (seg.end / duration) * 0.8, 0.95))
                status(f"Trascrizione in corso... {int(seg.end / duration * 100)}%")

        if first_seg is not None:
            process_segment(first_seg)
        for seg in segments_iter:
            process_segment(seg)

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
# Pipeline completa
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
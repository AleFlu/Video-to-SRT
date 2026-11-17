"""
transcription_config.py — Configurazione dei parametri di trascrizione (file .vsrtconfig).

Raccoglie in un unico oggetto immutabile tutto ciò che decide il risultato di una
trascrizione:
  - le scelte della schermata iniziale (modello, lingua, filtro VAD, alta precisione,
    beam, riduzione rumore);
  - i parametri di decodifica di faster-whisper (prompt iniziale, temperature, soglie);
  - i parametri del VAD Silero;
  - i limiti di leggibilità dei sottotitoli (caratteri per riga, CPS, durate).

I valori predefiniti di decodifica e VAD sono quelli storici dell'app: una configurazione
predefinita produce esattamente gli stessi parametri di prima. ``engine`` riprende da qui
``ITALIAN_PROMPT`` e ``VAD_PARAMS``; i limiti di leggibilità predefiniti (guida Netflix
italiana) restano in ``core.constants``.

Formato del file (JSON UTF-8):

    {
      "format": "videosrt-config",
      "version": 1,
      "transcription": {"model_size": "large-v3", "language": "it", "vad_filter": true,
                        "high_accuracy": false, "beam_size": 5, "denoise": true},
      "decoding": {"initial_prompts": {"it": "..."}, "glossary": ["machine learning", ...],
                   "temperature": [0.0, 0.2, 0.4, 0.6], "patience": 1.0,
                   "no_speech_threshold": 0.5, "log_prob_threshold": -1.2,
                   "compression_ratio_threshold": 2.4, "condition_on_previous_text": false},
      "vad": {"threshold": 0.5, "min_silence_duration_ms": 150, "speech_pad_ms": 100},
      "readability": {"max_chars_per_line": 42, "max_lines": 2, "max_cps": 20.0,
                      "warn_cps": 17.0, "min_duration_s": 0.833, "max_duration_s": 7.0,
                      "min_gap_s": 0.083, "keep_low_confidence_words": true}
    }

Lettura tollerante: campi sconosciuti ignorati, campi mancanti = valori predefiniti.
Un file con ``version`` più recente di quella supportata viene rifiutato. Ogni errore
(file illeggibile, JSON malformato, valore fuori intervallo) è un ``ValueError`` con
messaggio in italiano.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from dataclasses import dataclass, field, fields
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from core.constants import (
    MAX_CHARS_PER_LINE, MAX_CPS, MAX_SUBTITLE_DURATION, MIN_GAP_BETWEEN_SUBS,
    MIN_SUBTITLE_DURATION, WARN_CPS, normalize_language,
)
from core.subtitle_layout import LayoutRules

log = logging.getLogger(__name__)

CONFIG_FORMAT = "videosrt-config"
CONFIG_VERSION = 1
EXTENSION = ".vsrtconfig"
FILE_FILTER = f"Configurazione Video → SRT (*{EXTENSION});;Tutti i file (*.*)"

# Un file di configurazione è piccolo: oltre questa soglia non lo si legge nemmeno
# (evita di caricare in memoria un video scelto per sbaglio).
MAX_FILE_BYTES = 1024 * 1024
MAX_PROMPT_CHARS = 2000
MAX_GLOSSARY_TERMS = 100
MAX_GLOSSARY_TERM_CHARS = 100
AUTO_LANGUAGE = "auto"

# Prompt iniziale per l'italiano (tuning invariato): orienta Whisper su punteggiatura,
# apostrofi, accenti e parole straniere lasciate in lingua originale.
ITALIAN_PROMPT = (
    "Trascrizione fedele in italiano. Mantieni invariate le parole straniere "
    "pronunciate dallo speaker: termini tecnici inglesi, brand, comandi, anglicismi. "
    "Esempi: machine learning, deploy, framework, backend, feature, ok, trend, "
    "social media, iPhone, Google, npm, git. "
    "Punteggiatura italiana: punto, virgola, punto interrogativo, punto esclamativo, due punti. "
    "Apostrofi: c'è, dell', un'altra, l'uomo. Accenti: è, à, ì, ò, ù. "
    "Sì (affermazione). Nomi propri con maiuscola."
)

# Glossario predefinito: gli anglicismi e i marchi già citati in ITALIAN_PROMPT. Passato a
# faster-whisper come ``hotwords``, che (a differenza di initial_prompt) vale per ogni
# finestra di 30 s e non solo per la prima.
DEFAULT_GLOSSARY = (
    "machine learning", "deploy", "framework", "backend", "feature", "ok", "trend",
    "social media", "iPhone", "Google", "npm", "git",
)

# Distanza minima tra due sottotitoli (secondi)
DEFAULT_MIN_GAP_S = MIN_GAP_BETWEEN_SUBS

_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}$")
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


# ── Validazione dei singoli valori ────────────────────────────────────────────

def _show(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


def _invalid(path: str, expected: str, value: Any) -> ValueError:
    return ValueError(f"Valore non valido per '{path}': {expected} (trovato: {_show(value)})")


def _num(x: float) -> str:
    return f"{x:g}"


def _check_bool(path: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise _invalid(path, "deve essere true o false", value)
    return value


def _check_int(path: str, value: Any, lo: int, hi: int) -> int:
    expected = f"deve essere un numero intero tra {lo} e {hi}"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(path, expected, value)
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise _invalid(path, expected, value)
        value = int(value)
    if not lo <= value <= hi:
        raise _invalid(path, expected, value)
    return value


def _check_float(path: str, value: Any, lo: float, hi: float) -> float:
    expected = f"deve essere un numero tra {_num(lo)} e {_num(hi)}"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(path, expected, value)
    try:
        value = float(value)
    except OverflowError:
        raise _invalid(path, expected, value) from None
    if not math.isfinite(value) or not lo <= value <= hi:
        raise _invalid(path, expected, value)
    return value


def _check_language_code(path: str, value: Any) -> str:
    if not isinstance(value, str) or not _LANGUAGE_RE.match(value.strip().lower()):
        raise _invalid(path, "deve essere un codice lingua di 2-3 lettere (es. \"it\")", value)
    return value.strip().lower()


def _check_prompts(path: str, value: Any) -> Tuple[Tuple[str, str], ...]:
    """Prompt per lingua: oggetto {codice: testo} → coppie ordinate per codice."""
    if isinstance(value, Mapping):
        items: Iterable = value.items()
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        raise _invalid(path, "deve essere un oggetto {codice lingua: testo}", value)
    prompts: Dict[str, str] = {}
    for item in items:
        if not (isinstance(item, (list, tuple)) and len(item) == 2):
            raise _invalid(path, "deve essere un oggetto {codice lingua: testo}", value)
        code = _check_language_code(f"{path} (chiave)", item[0])
        text = item[1]
        if not isinstance(text, str) or len(text) > MAX_PROMPT_CHARS:
            raise _invalid(f"{path}.{code}",
                           f"deve essere un testo di al massimo {MAX_PROMPT_CHARS} caratteri",
                           text)
        prompts[code] = text
    return tuple(sorted(prompts.items()))


def glossary_sentence(terms) -> Optional[str]:
    """Frase con punteggiatura che contiene i termini del glossario (None se vuoto)."""
    terms = [t for t in terms if t]
    if not terms:
        return None
    body = terms[0] if len(terms) == 1 else ", ".join(terms[:-1]) + " e " + terms[-1]
    return f"Parliamo di {body}. Sì, è così."


def parse_glossary(text: str) -> Tuple[str, ...]:
    """Termini separati da virgola (o a capo) → tupla senza vuoti né duplicati."""
    terms = []
    for raw in str(text).replace("\n", ",").split(","):
        term = " ".join(raw.split())
        if term and term not in terms:
            terms.append(term)
    return tuple(terms)


def _check_glossary(path: str, value: Any) -> Tuple[str, ...]:
    expected = (f"deve essere un elenco di al massimo {MAX_GLOSSARY_TERMS} termini "
                f"(testi di al massimo {MAX_GLOSSARY_TERM_CHARS} caratteri)")
    if not isinstance(value, (list, tuple)) or len(value) > MAX_GLOSSARY_TERMS:
        raise _invalid(path, expected, value)
    terms = []
    for i, term in enumerate(value):
        if not isinstance(term, str):
            raise _invalid(f"{path}[{i}]", expected, term)
        term = " ".join(term.split())
        if len(term) > MAX_GLOSSARY_TERM_CHARS or "," in term:
            raise _invalid(f"{path}[{i}]", "deve essere un termine senza virgole di al "
                           f"massimo {MAX_GLOSSARY_TERM_CHARS} caratteri", term)
        if term and term not in terms:
            terms.append(term)
    return tuple(terms)


def _check_temperature(path: str, value: Any) -> Tuple[float, ...]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = [value]
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= 10:
        raise _invalid(path, "deve essere un elenco da 1 a 10 numeri tra 0 e 1", value)
    return tuple(_check_float(f"{path}[{i}]", v, 0.0, 1.0) for i, v in enumerate(value))


def _set(obj: Any, name: str, value: Any) -> None:
    """Normalizza un campo di una dataclass immutabile (solo dentro __post_init__)."""
    object.__setattr__(obj, name, value)


# ── Sezioni della configurazione ──────────────────────────────────────────────

@dataclass(frozen=True)
class DecodingOptions:
    """Parametri di decodifica di faster-whisper (backend standard).

    ``glossary`` (termini inglesi, marchi, nomi propri) arriva a faster-whisper come
    ``hotwords``. Con "Alta precisione" (WhisperX) si applica solo il prompt iniziale:
    WhisperX usa i propri valori per glossario, temperature e soglie.
    """

    initial_prompts: Tuple[Tuple[str, str], ...] = (("it", ITALIAN_PROMPT),)
    glossary: Tuple[str, ...] = DEFAULT_GLOSSARY
    temperature: Tuple[float, ...] = (0.0, 0.2, 0.4, 0.6)
    patience: float = 1.0
    no_speech_threshold: float = 0.5
    log_prob_threshold: float = -1.2
    compression_ratio_threshold: float = 2.4
    condition_on_previous_text: bool = False

    SECTION = "decoding"

    def __post_init__(self) -> None:
        p = self.SECTION
        _set(self, "initial_prompts", _check_prompts(f"{p}.initial_prompts", self.initial_prompts))
        _set(self, "glossary", _check_glossary(f"{p}.glossary", self.glossary))
        _set(self, "temperature", _check_temperature(f"{p}.temperature", self.temperature))
        _set(self, "patience", _check_float(f"{p}.patience", self.patience, 0.1, 10.0))
        _set(self, "no_speech_threshold",
             _check_float(f"{p}.no_speech_threshold", self.no_speech_threshold, 0.0, 1.0))
        _set(self, "log_prob_threshold",
             _check_float(f"{p}.log_prob_threshold", self.log_prob_threshold, -20.0, 0.0))
        _set(self, "compression_ratio_threshold",
             _check_float(f"{p}.compression_ratio_threshold",
                          self.compression_ratio_threshold, 1.0, 10.0))
        _check_bool(f"{p}.condition_on_previous_text", self.condition_on_previous_text)

    def prompt_for(self, language: Optional[str]) -> Optional[str]:
        """Prompt iniziale per la lingua richiesta; None con il rilevamento automatico
        (``language`` None) o se per quella lingua non c'è un prompt."""
        if not language:
            return None
        return dict(self.initial_prompts).get(language) or None

    def hotwords(self) -> Optional[str]:
        """Glossario nel formato di ``hotwords`` di faster-whisper (None se vuoto).

        Gli hotwords vengono ripassati al modello a ogni finestra di 30 s e Whisper ne
        imita lo stile: un semplice elenco separato da virgole gli fa perdere la
        punteggiatura nelle finestre successive alla prima (verificato su audio reale).
        Per questo il glossario diventa una frase italiana con punteggiatura.
        """
        return glossary_sentence(self.glossary)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "initial_prompts": dict(self.initial_prompts),
            "glossary": list(self.glossary),
            "temperature": list(self.temperature),
            "patience": self.patience,
            "no_speech_threshold": self.no_speech_threshold,
            "log_prob_threshold": self.log_prob_threshold,
            "compression_ratio_threshold": self.compression_ratio_threshold,
            "condition_on_previous_text": self.condition_on_previous_text,
        }


@dataclass(frozen=True)
class VadOptions:
    """Parametri del VAD Silero (stessi nomi di ``vad_parameters`` di faster-whisper)."""

    threshold: float = 0.50
    min_silence_duration_ms: int = 150
    speech_pad_ms: int = 100

    SECTION = "vad"

    def __post_init__(self) -> None:
        p = self.SECTION
        _set(self, "threshold", _check_float(f"{p}.threshold", self.threshold, 0.01, 0.99))
        _set(self, "min_silence_duration_ms",
             _check_int(f"{p}.min_silence_duration_ms", self.min_silence_duration_ms, 0, 10000))
        _set(self, "speech_pad_ms", _check_int(f"{p}.speech_pad_ms", self.speech_pad_ms, 0, 5000))

    def as_dict(self) -> Dict[str, Any]:
        """Dict pronto per ``vad_parameters`` di faster-whisper."""
        return dict(min_silence_duration_ms=self.min_silence_duration_ms,
                    speech_pad_ms=self.speech_pad_ms, threshold=self.threshold)

    def to_dict(self) -> Dict[str, Any]:
        return {"threshold": self.threshold,
                "min_silence_duration_ms": self.min_silence_duration_ms,
                "speech_pad_ms": self.speech_pad_ms}


@dataclass(frozen=True)
class ReadabilityLimits:
    """Limiti di leggibilità e opzioni di segmentazione dei sottotitoli.

    Li usano la composizione dei sottotitoli nel motore (``layout_rules``), i controlli
    dell'editor (``max_cps``, ``warn_cps``, ``min_duration_s``) e l'a capo in
    esportazione (``max_chars_per_line``, ``max_lines``). ``max_cps`` è la soglia di errore
    dell'editor; ``warn_cps`` è l'obiettivo di lettura che il motore cerca di rispettare.
    """

    max_chars_per_line: int = MAX_CHARS_PER_LINE
    max_lines: int = 2
    max_cps: float = MAX_CPS
    warn_cps: float = WARN_CPS
    min_duration_s: float = MIN_SUBTITLE_DURATION
    max_duration_s: float = MAX_SUBTITLE_DURATION
    min_gap_s: float = DEFAULT_MIN_GAP_S
    keep_low_confidence_words: bool = True

    SECTION = "readability"

    def __post_init__(self) -> None:
        p = self.SECTION
        _set(self, "max_chars_per_line",
             _check_int(f"{p}.max_chars_per_line", self.max_chars_per_line, 10, 100))
        _set(self, "max_lines", _check_int(f"{p}.max_lines", self.max_lines, 1, 3))
        _set(self, "max_cps", _check_float(f"{p}.max_cps", self.max_cps, 5.0, 60.0))
        _set(self, "warn_cps", _check_float(f"{p}.warn_cps", self.warn_cps, 5.0, 60.0))
        _set(self, "min_duration_s",
             _check_float(f"{p}.min_duration_s", self.min_duration_s, 0.1, 10.0))
        _set(self, "max_duration_s",
             _check_float(f"{p}.max_duration_s", self.max_duration_s, 1.0, 60.0))
        _set(self, "min_gap_s", _check_float(f"{p}.min_gap_s", self.min_gap_s, 0.0, 2.0))
        _check_bool(f"{p}.keep_low_confidence_words", self.keep_low_confidence_words)
        if self.warn_cps > self.max_cps:
            raise ValueError(f"Valore non valido per '{p}.warn_cps': non può superare "
                             f"'{p}.max_cps' ({_num(self.warn_cps)} > {_num(self.max_cps)})")
        if self.min_duration_s >= self.max_duration_s:
            raise ValueError(f"Valore non valido per '{p}.min_duration_s': deve essere minore "
                             f"di '{p}.max_duration_s' ({_num(self.min_duration_s)} ≥ "
                             f"{_num(self.max_duration_s)})")

    def to_dict(self) -> Dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def layout_rules(self) -> LayoutRules:
        """Regole per ``core.subtitle_layout``: i tempi puntano a ``warn_cps`` (obiettivo
        di lettura), non a ``max_cps`` (soglia d'errore dell'editor)."""
        return LayoutRules(
            max_chars_per_line=self.max_chars_per_line, max_lines=self.max_lines,
            max_cps=self.warn_cps, min_duration_s=self.min_duration_s,
            max_duration_s=self.max_duration_s, min_gap_s=self.min_gap_s,
            keep_low_confidence_words=self.keep_low_confidence_words,
        )


_SECTIONS = {
    DecodingOptions.SECTION: DecodingOptions,
    VadOptions.SECTION: VadOptions,
    ReadabilityLimits.SECTION: ReadabilityLimits,
}
_BASIC_SECTION = "transcription"


# ── Configurazione completa ───────────────────────────────────────────────────

@dataclass(frozen=True)
class TranscriptionConfig:
    """Configurazione completa di una trascrizione (immutabile, sempre valida).

    ``language`` è un codice ISO ("it") o "auto" per il rilevamento automatico.
    """

    model_size: str = "large-v3"
    language: str = "it"
    vad_filter: bool = True
    high_accuracy: bool = False
    beam_size: int = 5
    denoise: bool = True
    decoding: DecodingOptions = field(default_factory=DecodingOptions)
    vad: VadOptions = field(default_factory=VadOptions)
    readability: ReadabilityLimits = field(default_factory=ReadabilityLimits)

    def __post_init__(self) -> None:
        p = _BASIC_SECTION
        if not isinstance(self.model_size, str) or not _MODEL_RE.match(self.model_size):
            raise _invalid(f"{p}.model_size", "deve essere il nome di un modello Whisper "
                           "(es. \"large-v3\")", self.model_size)
        language = AUTO_LANGUAGE if self.language is None else self.language
        if isinstance(language, str) and language.strip().lower() in ("", AUTO_LANGUAGE):
            language = AUTO_LANGUAGE
        else:
            language = _check_language_code(f"{p}.language", language)
        _set(self, "language", language)
        for name in ("vad_filter", "high_accuracy", "denoise"):
            _check_bool(f"{p}.{name}", getattr(self, name))
        _set(self, "beam_size", _check_int(f"{p}.beam_size", self.beam_size, 1, 15))
        for name, klass in _SECTIONS.items():
            if not isinstance(getattr(self, name), klass):
                raise _invalid(name, f"deve essere un {klass.__name__}", getattr(self, name))

    @property
    def whisper_language(self) -> Optional[str]:
        """Codice lingua per Whisper: None = rilevamento automatico."""
        return normalize_language(self.language)

    def is_default(self) -> bool:
        return self == TranscriptionConfig()

    # ── Serializzazione ──────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "format": CONFIG_FORMAT,
            "version": CONFIG_VERSION,
            _BASIC_SECTION: {
                "model_size": self.model_size,
                "language": self.language,
                "vad_filter": self.vad_filter,
                "high_accuracy": self.high_accuracy,
                "beam_size": self.beam_size,
                "denoise": self.denoise,
            },
        }
        for name in _SECTIONS:
            data[name] = getattr(self, name).to_dict()
        return data

    @classmethod
    def from_dict(cls, data: Any) -> "TranscriptionConfig":
        """Crea la configurazione da un dict letto dal file (vedi docstring del modulo)."""
        if not isinstance(data, dict):
            raise ValueError("Il file non contiene una configurazione (atteso un oggetto JSON)")
        if data.get("format") != CONFIG_FORMAT:
            raise ValueError("Il file non è una configurazione di Video → SRT "
                             f"(campo \"format\" diverso da \"{CONFIG_FORMAT}\")")
        version = data.get("version")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValueError("Configurazione non valida: campo \"version\" mancante o non valido")
        if version > CONFIG_VERSION:
            raise ValueError(
                f"Configurazione creata da una versione più recente dell'app (formato {version}, "
                f"questa versione legge fino al {CONFIG_VERSION}): aggiorna l'applicazione "
                "per importarla"
            )
        kwargs = _known_fields(cls, _section(data, _BASIC_SECTION), _BASIC_SECTION,
                               exclude=_SECTIONS)
        for name, klass in _SECTIONS.items():
            kwargs[name] = klass(**_known_fields(klass, _section(data, name), name))
        ignored = sorted(set(data) - {"format", "version", _BASIC_SECTION, *_SECTIONS})
        if ignored:
            log.info("Configurazione: sezioni sconosciute ignorate: %s", ", ".join(ignored))
        return cls(**kwargs)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str) -> "TranscriptionConfig":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"File di configurazione non valido: JSON malformato "
                             f"(riga {e.lineno}, colonna {e.colno})") from e
        except RecursionError as e:
            raise ValueError("File di configurazione non valido: struttura troppo annidata") from e
        return cls.from_dict(data)


def _section(data: Dict[str, Any], name: str) -> Dict[str, Any]:
    value = data.get(name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Configurazione non valida: la sezione \"{name}\" deve essere un "
                         "oggetto JSON")
    return value


def _known_fields(klass, values: Dict[str, Any], section: str,
                  exclude: Iterable[str] = ()) -> Dict[str, Any]:
    """Solo i campi della dataclass: quelli sconosciuti vengono ignorati (e annotati)."""
    names = {f.name for f in fields(klass)} - set(exclude)
    ignored = sorted(set(values) - names)
    if ignored:
        log.info("Configurazione: campi sconosciuti ignorati in \"%s\": %s",
                 section, ", ".join(ignored))
    return {k: v for k, v in values.items() if k in names}


# ── File ──────────────────────────────────────────────────────────────────────

def load_config(path: str) -> TranscriptionConfig:
    """Legge un file .vsrtconfig. ``ValueError`` (in italiano) se non è utilizzabile."""
    try:
        size = os.path.getsize(path)
        if size > MAX_FILE_BYTES:
            raise ValueError("Il file è troppo grande per essere una configurazione "
                             f"(massimo {MAX_FILE_BYTES // 1024} KB)")
        with open(path, "rb") as f:
            raw = f.read(MAX_FILE_BYTES + 1)
    except OSError as e:
        raise ValueError(f"Impossibile leggere il file: {e.strerror or e}") from e
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ValueError("Il file non è un testo UTF-8: non è una configurazione valida") from e
    return TranscriptionConfig.from_json(text)


def save_config(config: TranscriptionConfig, path: str) -> None:
    """Scrive la configurazione in ``path`` (scrittura atomica; ``OSError`` se fallisce)."""
    # Import locale: srt_io legge i limiti attivi da questo modulo.
    from core.srt_io import _write_text
    _write_text(path, config.to_json())


# ── Limiti di leggibilità attivi nell'editor ──────────────────────────────────
# I controlli dell'editor (CPS, durata minima) e l'a capo in esportazione leggono i
# limiti della configurazione corrente da qui. La trascrizione invece riceve i limiti
# esplicitamente con la configurazione (il worker gira in un altro thread).

_active_readability = ReadabilityLimits()


def active_readability() -> ReadabilityLimits:
    """Limiti di leggibilità della configurazione corrente."""
    return _active_readability


def set_active_readability(limits: Optional[ReadabilityLimits]) -> None:
    """Imposta i limiti correnti (None = predefiniti)."""
    global _active_readability
    _active_readability = limits if limits is not None else ReadabilityLimits()


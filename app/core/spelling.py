"""
spelling.py — Controllo ortografico italiano e parole incerte per l'editor.

Due aiuti alla revisione, che non toccano la trascrizione:

- **Parole incerte**: le parole che Whisper ha scritto con probabilità bassa (salvate nel
  sottotitolo in ``Subtitle.uncertain``). Si evidenziano solo finché il testo è quello
  della trascrizione (``Subtitle.asr_text``): appena lo si modifica il sottotitolo conta
  come rivisto, e l'annullamento le fa tornare senza stato da ripristinare.
- **Ortografia**: dizionario italiano di ``pyspellchecker`` (una lista di frequenze senza
  morfologia: da solo segnava ~4% di parole giuste come "civica" o "potenziare"). Per
  questo le parole della trascrizione originale del sottotitolo sono considerate giuste
  (Whisper non sbaglia l'ortografia: sbaglia parole vere, e per quelle ci sono le parole
  incerte); il controllo trova quindi soprattutto i refusi scritti a mano. Un SRT
  importato (senza trascrizione) è controllato tutto. Si ignorano i nomi propri
  (maiuscola fuori da inizio frase), le sigle, le parole elise ("cos'", "l'") e quelle di
  una lettera. Le parole aggiunte dall'utente stanno in QSettings (``USER_WORDS_KEY``).

Se ``pyspellchecker`` manca (ambiente vecchio) il controllo ortografico è spento e le
parole incerte funzionano lo stesso.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

from PySide6.QtCore import QObject, QSettings, Signal

from core.subtitle_layout import fold_word, uncertain_tokens  # noqa: F401 (riesportata)
from core.subtitle_model import is_unedited

logger = logging.getLogger(__name__)

Span = Tuple[int, int]

USER_WORDS_KEY = "spelling/user_words"
_WORD_RE = re.compile(r"[^\W\d_]+")
_APOSTROPHES = "'’"
_SENTENCE_END = ".!?…"
# Parole tronche con l'apostrofo finale ("un po'", "mo'", "di'")
_TRUNCATED = frozenset({"po", "mo", "di", "fa", "sta", "va", "da", "be", "to", "pie"})
# Parole comuni che il dizionario di frequenze non ha
_EXTRA_WORDS = frozenset({
    "online", "offline", "ok", "okay", "smartphone", "social", "web", "email", "mail",
    "app", "chat", "post", "link", "video", "podcast", "reel", "reels", "streaming",
    "ricarica", "ricariche", "preavviso", "civica", "civico", "civiche", "civici",
})
_CACHE_MAX = 4096


def word_spans(text: str) -> List[Span]:
    """Posizioni delle parole (solo lettere) nel testo."""
    return [m.span() for m in _WORD_RE.finditer(text)]


def uncertain_spans(text: str, uncertain: Sequence[str], asr_text: str) -> List[Span]:
    """Posizioni delle parole incerte, solo finché il testo non è stato modificato."""
    if not uncertain or not is_unedited(text, asr_text):
        return []
    wanted = set(uncertain)
    return [(s, e) for s, e in word_spans(text) if fold_word(text[s:e]) in wanted]


def _sentence_start(text: str, pos: int) -> bool:
    """True se la parola in ``pos`` apre il testo o una frase."""
    i = pos - 1
    while i >= 0 and (text[i].isspace() or text[i] in "\"«“'’(-—"):
        i -= 1
    return i < 0 or text[i] in _SENTENCE_END


def _candidates(text: str) -> List[Tuple[int, int, str]]:
    """Parole da controllare: ``(inizio, fine, forma minuscola)``."""
    out = []
    for s, e in word_spans(text):
        word = text[s:e]
        nxt = text[e] if e < len(text) else ""
        if nxt in _APOSTROPHES:
            after = text[e + 1] if e + 1 < len(text) else ""
            if after.isalpha() or word.lower() in _TRUNCATED:
                continue                       # "cos'è", "l'orecchio", "un po'"
        if len(word) < 2 or any(c.isupper() for c in word[1:]):
            continue                           # "è", "LLM", "iPhone"
        if word[0].isupper() and not _sentence_start(text, s):
            continue                           # nome proprio
        out.append((s, e, word.lower()))
    return out


class _Notifier(QObject):
    changed = Signal()        # parole dell'utente cambiate: ridisegnare gli evidenziatori


class Speller:
    """Dizionario italiano (caricato alla prima richiesta) + parole dell'utente."""

    def __init__(self, user_words: Optional[Iterable[str]] = None):
        self.notifier = _Notifier()
        self._checker = None
        self._loaded = False
        self._user: Optional[Set[str]] = (
            {w.lower() for w in user_words} if user_words is not None else None)
        self._cache: Dict[Tuple[str, str], Tuple[Span, ...]] = {}

    # ---- Dizionario ----
    def _load(self):
        if self._loaded:
            return self._checker
        self._loaded = True
        try:
            from spellchecker import SpellChecker
            self._checker = SpellChecker(language="it", distance=1)
        except Exception as e:   # libreria o dizionario mancanti: controllo spento
            logger.warning("Controllo ortografico non disponibile: %s", e)
            self._checker = None
        return self._checker

    @property
    def available(self) -> bool:
        return self._load() is not None

    def user_words(self) -> Set[str]:
        if self._user is None:
            raw = QSettings("VideoSRT", "v2").value(USER_WORDS_KEY, [])
            if isinstance(raw, str):
                raw = [raw]
            self._user = {str(w).lower() for w in (raw or [])}
        return self._user

    def add_user_word(self, word: str) -> None:
        """Aggiunge la parola al dizionario dell'utente (ricordata tra le sessioni)."""
        words = self.user_words()
        w = word.strip().lower()
        if not w or w in words:
            return
        words.add(w)
        QSettings("VideoSRT", "v2").setValue(USER_WORDS_KEY, sorted(words))
        self._cache.clear()
        self.notifier.changed.emit()

    def is_known(self, word: str) -> bool:
        w = word.lower()
        checker = self._load()
        if checker is None:
            return True
        return w in _EXTRA_WORDS or w in self.user_words() or w in checker

    # ---- Controllo ----
    def misspelled_spans(self, text: str, asr_text: str = "") -> Tuple[Span, ...]:
        """Parole sconosciute del testo; quelle della trascrizione originale sono buone."""
        key = (text, asr_text)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        if self._load() is None or not text.strip():
            spans: Tuple[Span, ...] = ()
        else:
            trusted: FrozenSet[str] = frozenset(
                m.group().lower() for m in _WORD_RE.finditer(asr_text))
            spans = tuple((s, e) for s, e, w in _candidates(text)
                          if w not in trusted and not self.is_known(w))
        if len(self._cache) >= _CACHE_MAX:
            self._cache.clear()
        self._cache[key] = spans
        return spans

    def suggestions(self, word: str, limit: int = 5) -> List[str]:
        """Correzioni possibili, le più frequenti prima, con la maiuscola dell'originale."""
        checker = self._load()
        if checker is None or not word:
            return []
        low = word.lower()
        found = checker.candidates(low) or set()
        found.discard(low)
        if not found and len(low) > 5:
            found = set(checker.edit_distance_2(low)) - {low}
        ranked = sorted(found, key=lambda w: (-checker.word_usage_frequency(w), w))[:limit]
        if word[0].isupper():
            ranked = [w[:1].upper() + w[1:] for w in ranked]
        return ranked


SPELLER = Speller()

"""
subtitle_layout.py — Dai timestamp per parola di Whisper a sottotitoli italiani ben formati.

Modulo puro (niente Qt, niente ``engine``), deterministico. Regole di riferimento: Netflix
Italian Timed Text Style Guide (42 caratteri per riga, 2 righe, 17 CPS, durata 5/6 s – 7 s,
pausa tra sottotitoli di 2 fotogrammi oppure ≥ 0,5 s, piramide con la riga in basso più lunga).

Pipeline (``layout``)::

    segmenti Whisper ──words_from_segments──▶ parole (+ confini di segmento)
                     ──segment──────────────▶ sottotitoli (testo corretto, non a capo)
                     ──time_subtitles───────▶ tempi definitivi

``wrap_lines`` va applicata al testo solo alla fine (dopo eventuali altre correzioni);
``find_uncovered_speech`` segnala i tratti di parlato (VAD) rimasti senza parole, da
ritrascrivere.

Scelte principali:
- Nessuna parola viene scartata per bassa probabilità (``keep_low_confidence_words``):
  la confidenza minima finisce in ``confidence`` e l'editor la può evidenziare.
- Il testo nasce concatenando le parole così come le scrive Whisper (spazio iniziale
  compreso): "l" + "'industria" → "l'industria", "Est" + "-ce" → "Est-ce".
- La divisione in sottotitoli è una programmazione dinamica su ogni blocco di parlato
  (blocchi separati da silenzi ≥ 1,5 s o da segmenti senza timestamp per parola): ogni
  candidato deve stare in 2 righe da 42 caratteri e in 7 s di parlato; il costo premia i
  tagli a fine frase, sulla punteggiatura, sulle pause e prima di congiunzioni/preposizioni,
  e penalizza fortemente i sottotitoli che finiscono con articolo/preposizione/clitico/
  congiunzione o che lasciano in coda la prima parola di una nuova frase, quelli che
  mescolano frasi diverse, e quelli di 1–2 parole o con meno di 0,8 s di parlato.
- Unica eccezione al silenzio di 1,5 s: se la parola prima del silenzio non può chiudere un
  sottotitolo ("Per [2 s] noi, …", "…eh? È [1,9 s] vestito…") e il silenzio è ≤ 3 s, il
  blocco continua: un "Per" isolato è peggio di un sottotitolo che attraversa la pausa.
- Euristiche lasciate fuori perché non sicure: "e'" minuscolo → "è" (raro, ambiguo con
  l'apocope poetica); "ce la/ce lo" → "c'è" (sono quasi sempre "ce la faccio", "ce lo dice").
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "FUNCTION_WORDS", "LayoutRules", "Word", "find_uncovered_speech", "fix_typography",
    "join_words", "layout", "segment", "time_subtitles", "words_from_segments", "wrap_lines",
]


# ── Regole ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LayoutRules:
    """Limiti di impaginazione e di tempo (valori predefiniti: guida Netflix italiana)."""

    max_chars_per_line: int = 42
    max_lines: int = 2
    max_cps: float = 17.0
    min_duration_s: float = 0.833
    max_duration_s: float = 7.0
    min_gap_s: float = 0.083
    snap_gap_s: float = 0.5
    end_pad_s: float = 0.2          # coda dopo l'ultima parola quando nient'altro serve
    keep_low_confidence_words: bool = True
    min_word_prob: float = 0.35     # usata solo se keep_low_confidence_words è False


@dataclass
class Word:
    """Parola con tempi. ``text`` è come lo produce Whisper, con lo spazio iniziale."""

    text: str
    start: float
    end: float
    probability: float = 1.0
    synthetic: bool = False   # intero testo di un segmento senza timestamp per parola usabili


# Scarto dei segmenti inaffidabili (stessa regola della pipeline storica)
_MAX_NO_SPEECH_PROB = 0.9
_MIN_AVG_LOGPROB = -1.8

# Segmentazione
_HARD_SILENCE_S = 1.5      # un sottotitolo non attraversa un silenzio così lungo…
_MAX_BRIDGE_S = 3.0        # …salvo dopo una parola che non può chiuderlo (fino a 3 s)
_STRONG_PAUSE_S = 0.4      # pausa "forte" tra due parole
_SHORT_SPEECH_S = 0.8      # sotto questa durata di parlato un sottotitolo è troppo breve
_MIN_START_STEP_S = 0.01   # distanza minima imposta tra inizi coincidenti (dati degeneri)

# Unione degli span VAD in find_uncovered_speech
_SPEECH_MERGE_GAP_S = 0.3


# ── Lessico ───────────────────────────────────────────────────────────────────

_ARTICLES = {"il", "lo", "la", "i", "gli", "le", "un", "uno", "una"}
_PREPOSITIONS = {"di", "a", "da", "in", "con", "su", "per", "tra", "fra"}
_ARTICULATED = {
    "del", "dello", "della", "dei", "degli", "delle",
    "al", "allo", "alla", "ai", "agli", "alle",
    "dal", "dallo", "dalla", "dai", "dagli", "dalle",
    "nel", "nello", "nella", "nei", "negli", "nelle",
    "sul", "sullo", "sulla", "sui", "sugli", "sulle",
    "col", "coi", "pel", "pei",
}
_CLITICS = {"mi", "ti", "si", "ci", "vi", "ne", "li", "gli", "ce", "ve"}
_CONJUNCTIONS = {"e", "ed", "o", "od", "ma", "che", "se", "non", "né", "cui"}
# Determinanti e aggettivi troncati che stanno sempre davanti al nome ("maggior cura").
_PRENOMINAL = {"ogni", "qualche", "quel", "quei", "quegli", "maggior", "miglior", "minor",
               "peggior", "gran", "bel", "buon", "qual", "tal"}

#: Parole con cui un sottotitolo o la riga superiore non devono mai finire.
FUNCTION_WORDS: frozenset = frozenset(
    _ARTICLES | _PREPOSITIONS | _ARTICULATED | _CLITICS | _CONJUNCTIONS | _PRENOMINAL)

# Finali solo sconsigliati: ausiliari (separano dal participio), possessivi (dal nome),
# subordinanti e avverbi che reggono quello che segue.
_WEAK_END_WORDS = frozenset({
    "perché", "quando", "come", "dove", "mentre", "anche", "molto", "più", "meno",
    "mio", "mia", "miei", "mie", "tuo", "tua", "tuoi", "tue", "suo", "sua", "suoi", "sue",
    "nostro", "nostra", "nostri", "nostre", "vostro", "vostra", "vostri", "vostre",
    "è", "ho", "hai", "ha", "abbiamo", "avete", "hanno", "sono", "sei", "siamo", "siete",
    "era", "erano", "essere", "avere", "stato", "stata", "stati", "state",
    "sta", "sto", "stai", "stiamo", "stanno",
    # pronomi soggetto (solo soggetto: "se tu / devi")
    "io", "tu",
    # connettivi: aprono ciò che segue ("…possibile, quindi" / "seguendo…")
    "quindi", "cioè", "però", "poi", "allora", "infatti", "ovvero", "oppure", "invece",
    "dunque",
    # avverbi che reggono una preposizione ("dietro / a un prodotto")
    "dietro", "davanti", "dentro", "fino", "verso", "senza", "contro", "oltre", "accanto",
    "insieme", "rispetto", "grazie",
})

# Congiunzioni e relativi davanti ai quali si va a capo volentieri…
_CONJ_BREAK_BEFORE = frozenset({
    "e", "ed", "o", "oppure", "ma", "però", "perché", "quindi", "che", "se", "quando",
    "come", "mentre", "dove", "cioè", "poi", "infatti", "invece", "allora", "ovvero",
    "dunque", "poiché", "siccome", "sebbene", "benché", "finché", "affinché", "né",
})
# …e preposizioni, con un vantaggio minore (non deve prevalere sull'equilibrio delle righe).
_PREP_BREAK_BEFORE = frozenset(_PREPOSITIONS | _ARTICULATED)
_BREAK_BEFORE_WORDS = _CONJ_BREAK_BEFORE | _PREP_BREAK_BEFORE

# Coppie da non separare con un a capo o un cambio di sottotitolo.
_LOCKED_PAIRS = frozenset({
    ("così", "come"), ("tanto", "quanto"), ("prima", "che"), ("prima", "di"),
    ("dopo", "che"), ("dato", "che"), ("visto", "che"), ("anche", "se"), ("come", "se"),
    ("fino", "a"), ("fino", "al"), ("fino", "alla"), ("oltre", "a"), ("rispetto", "a"),
    ("rispetto", "al"), ("rispetto", "alla"), ("grazie", "a"), ("grazie", "al"),
    ("grazie", "alla"), ("insieme", "a"), ("insieme", "con"), ("davanti", "a"),
    ("dietro", "a"), ("dietro", "al"), ("dietro", "alla"), ("accanto", "a"),
    ("invece", "di"), ("senza", "che"), ("ogni", "volta"), ("un", "po'"),
    ("tutti", "i"), ("tutti", "gli"), ("tutte", "le"), ("tutto", "il"), ("tutto", "lo"),
    ("tutta", "la"),
})
_COST_LOCKED = 40.0

_SENTENCE_END_CHARS = ".!?…"
_CLAUSE_END_CHARS = ",;:–—"
_CLOSING_QUOTES = "\"'’»”)]"
_OPENING_QUOTES = "\"'‘«“(["

# Abbreviazioni dopo cui il punto non chiude la frase (niente maiuscola dopo).
_ABBREVIATIONS = frozenset({
    "ecc", "etc", "dott", "dr", "sig", "sigg", "sigra", "prof", "ing", "avv", "arch", "geom",
    "es", "pag", "pagg", "n", "nr", "art", "cap", "vol", "tel", "fig", "vs", "ca", "cfr",
    "rag", "mr", "mrs", "ms", "st", "pp",
})


def _core(token: str) -> str:
    """Parola in minuscolo senza virgolette/parentesi attorno."""
    return token.strip().strip(_OPENING_QUOTES + _CLOSING_QUOTES).lower()


def _trailing(token: str) -> str:
    """Ultimo carattere significativo (ignora virgolette e parentesi di chiusura)."""
    t = token.strip().rstrip(_CLOSING_QUOTES.replace("'", "").replace("’", ""))
    return t[-1:] if t else ""


def _ends_sentence(token: str) -> bool:
    last = _trailing(token)
    if last not in _SENTENCE_END_CHARS or not last:
        return False
    if last == ".":
        body = token.strip().rstrip(_CLOSING_QUOTES).rstrip(".")
        body = body.lstrip(_OPENING_QUOTES)
        if body.lower() in _ABBREVIATIONS or "." in body or (len(body) == 1 and body.isalpha()):
            return False
    return True


def _ends_clause(token: str) -> bool:
    last = _trailing(token)
    return bool(last) and last in _CLAUSE_END_CHARS


def _is_dangling(token: str) -> bool:
    """True se il sottotitolo/la riga non può finire con questa parola."""
    t = token.strip()
    if not t or _trailing(t) in _SENTENCE_END_CHARS + _CLAUSE_END_CHARS:
        return False
    low = _core(t)
    if t.endswith(("'", "’")):
        # elisione staccata ("dell'", "l'"): regge la parola seguente; "po'" no
        return low.rstrip("'’") not in {"po", "mo", "be", "e"}
    return low in FUNCTION_WORDS


def _is_weak_end(token: str) -> bool:
    t = token.strip()
    if not t or _trailing(t) in _SENTENCE_END_CHARS + _CLAUSE_END_CHARS:
        return False
    return _core(t) in _WEAK_END_WORDS


def _is_locked(last: str, first: str, before: str = "") -> bool:
    """True se ``last`` + ``first`` non vanno separati: locuzioni ("così come",
    "tutti i") e numeri. Un numero va con il nome proprio che lo precede ("AirPods Pro 3",
    ``before`` è la parola prima di ``last``), altrimenti con la parola dopo ("30 giorni")."""
    if not last or not first or _trailing(last) in _SENTENCE_END_CHARS + _CLAUSE_END_CHARS:
        return False
    if first[0].isdigit():
        return last[:1].isupper()
    if last[-1].isdigit():
        return not before[:1].isupper()
    return (_core(last), _core(first)) in _LOCKED_PAIRS


def _first_token(text: str) -> str:
    parts = text.split()
    return parts[0] if parts else ""


def _last_token(text: str) -> str:
    parts = text.split()
    return parts[-1] if parts else ""


# ── Tipografia ────────────────────────────────────────────────────────────────

_LETTER = r"[^\W\d_]"
_APOS = "['’]"

# Forme elise che si attaccano alla parola seguente: "l 'industria", "dell' amore", "Cos 'è".
_ELIDABLE = (
    "l", "dell", "nell", "all", "dall", "sull", "coll", "pell", "un", "quest", "quell",
    "bell", "sant", "buon", "nessun", "ciascun", "qualcun", "alcun", "tutt", "senz", "mezz",
    "anch", "neanch", "nemmen", "c", "d", "m", "t", "s", "v", "n", "ch", "cos", "dov", "com",
    "quand", "ov", "dev", "quant", "tant", "grand", "cent", "qu",
)
_ELISION_RE = re.compile(
    r"\b(" + "|".join(sorted(_ELIDABLE, key=len, reverse=True)) + r")"
    r"(?:[ \t]+(" + _APOS + r")[ \t]*|(" + _APOS + r")[ \t]+)(?=" + _LETTER + ")",
    re.IGNORECASE,
)
_PO_RE = re.compile(r"\b([Pp]o)(" + _APOS + r")(?=" + _LETTER + ")")
_E_ACCENT_GLUED_RE = re.compile(r"(?<![\w'’])E" + _APOS + r"(?=" + _LETTER + ")")
_E_ACCENT_RE = re.compile(r"(?<![\w'’])E" + _APOS + r"(?![\w'’])")
_UN_PO_RE = re.compile(r"\b([Uu]n) po\b(?![\w'’])")
# "ce" seguito da parole che non possono seguire il clitico "ce" (che vuole lo/la/li/le/ne
# o un verbo): "ce un problema" → "c'è un problema". "ce la/lo" restano ("ce la faccio").
_CE_RE = re.compile(
    r"\b([Cc])e\b(?=[ \t]+(?:un|una|uno|il|stato|stata|stati|state|bisogno|qualcosa|"
    r"qualcuno|niente|nessuno|nulla|ancora|già|sempre|molto|troppo|poco|più|meno|"
    r"bene|male)\b)"
)
_ELLIPSIS_RE = re.compile(r"\.{3,}")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"[ \t]+([.,;:!?…])")
_OK_RE = re.compile(r"\bOK\b")
_CAPITALIZE_RE = re.compile(r"([.!?…])([ \t]+)([" + _OPENING_QUOTES + r"]?)(" + _LETTER + ")")
_SPACES_RE = re.compile(r"[ \t ]+")


def _elision_sub(m: re.Match) -> str:
    return m.group(1) + (m.group(2) or m.group(3))


def _capitalize_sub(m: re.Match) -> str:
    punct, space, quote, letter = m.group(1), m.group(2), m.group(3), m.group(4)
    if not letter.islower():
        return m.group(0)
    if punct == ".":
        before = m.string[:m.start(1)]
        prev = re.split(r"[\s" + re.escape(_OPENING_QUOTES) + "]", before)[-1]
        if prev.lower() in _ABBREVIATIONS or "." in prev or (len(prev) == 1 and prev.isalpha()):
            return m.group(0)
    return punct + space + quote + letter.upper()


def _normalize_spaces(text: str) -> str:
    lines = [_SPACES_RE.sub(" ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


_TRAILING_SOFT_PUNCT_RE = re.compile(r"[.,;:]+$")


def light_punctuation(text: str) -> str:
    """Punteggiatura leggera dei reel: toglie punto, virgola, punto e virgola e due punti
    in fondo al sottotitolo (il taglio fa già da pausa); restano ? ! e …, che danno il
    tono. Il resto del testo non cambia."""
    return _TRAILING_SOFT_PUNCT_RE.sub("", text.rstrip())


def fix_typography(text: str) -> str:
    """Correzioni tipografiche italiane, idempotenti (``fix(fix(x)) == fix(x)``).

    - spazi multipli compressi, nessuno spazio prima di . , ; : ! ? …;
    - "..." → "…";
    - elisioni staccate riattaccate solo dopo forme che si elidono davvero
      ("l 'industria", "dell' amore", "Cos 'è", "un 'altra", "c 'è");
      "po' potremmo" resta staccato e "po'potremmo" diventa "po' potremmo";
    - "E'" a inizio parola → "È" ("E'la" → "È la"); il minuscolo "e'" non si tocca;
    - "un po" → "un po'";
    - "ce" → "c'è" solo davanti a parole che non possono seguire il clitico "ce"
      (un, una, stato, bisogno, niente, già, sempre…): "ce la faccio" resta com'è;
    - "OK" → "Ok";
    - maiuscola dopo . ! ? … seguiti da spazio (non dopo abbreviazioni come "ecc.").

    Nessun'altra parola viene modificata; numeri e trattini restano come sono.
    """
    if not text:
        return ""
    text = _normalize_spaces(text)
    text = _ELLIPSIS_RE.sub("…", text)
    text = _ELISION_RE.sub(_elision_sub, text)
    text = _PO_RE.sub(r"\1\2 ", text)
    text = _E_ACCENT_GLUED_RE.sub("È ", text)
    text = _E_ACCENT_RE.sub("È", text)
    text = _UN_PO_RE.sub(r"\1 po'", text)
    text = _CE_RE.sub(r"\1'è", text)
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    text = _OK_RE.sub("Ok", text)
    text = _CAPITALIZE_RE.sub(_capitalize_sub, text)
    return _normalize_spaces(text)


def join_words(words: Sequence[Word]) -> str:
    """Testo delle parole con la spaziatura di Whisper (concatenazione, poi spazi
    normalizzati). Nessuna correzione tipografica: vedi ``fix_typography``."""
    return " ".join("".join(w.text for w in words).split())


# ── A capo ────────────────────────────────────────────────────────────────────

_BAD_BREAK = 1000.0   # penalità di un a capo dopo una parola funzionale


def _break_penalty(top: str, bottom: str) -> float:
    """Penalità di un a capo tra ``top`` e ``bottom`` (più bassa = migliore)."""
    last, first = _last_token(top), _first_token(bottom)
    pen = 0.0
    punct_end = _ends_sentence(last) or _ends_clause(last)
    if _ends_sentence(last):
        pen -= 40.0
    elif _ends_clause(last):
        pen -= 30.0
    elif _core(first) in _CONJ_BREAK_BEFORE:
        pen -= 12.0
    elif _core(first) in _PREP_BREAK_BEFORE:
        pen -= 6.0
    if _is_dangling(last):
        pen += _BAD_BREAK
    elif _is_weak_end(last):
        pen += 15.0
    top_words = top.split()
    if _is_locked(last, first, top_words[-2] if len(top_words) >= 2 else ""):
        pen += _COST_LOCKED
    # nome proprio su due parole ("Apple / Intelligence")
    if last[:1].isupper() and first[:1].isupper() and not punct_end:
        pen += 10.0
    # niente righe di 1–2 parole corte (soprattutto in alto); più tollerabile se la riga
    # è un inciso chiuso dalla punteggiatura ("Quindi io, / così come…")
    if len(top.split()) <= 2 and len(top) < 15:
        pen += 20.0 if punct_end else 45.0
    if len(bottom.split()) <= 2 and len(bottom) < 15:
        pen += 25.0
    # equilibrio, con preferenza per la riga in basso più lunga (piramide)
    diff = len(top) - len(bottom)
    pen += 0.3 * abs(diff) + (0.3 * diff if diff > 0 else 0.0)
    return pen


def _best_two_lines(flat: str, max_chars: int) -> Tuple[Optional[int], float, bool]:
    """Miglior spazio in cui andare a capo: ``(posizione, penalità, entrambe_le_righe_ok)``.

    Se nessuno spazio lascia due righe entro ``max_chars``, ripiega sullo spazio più
    bilanciato (``ok=False``); ``posizione`` è None se il testo non ha spazi.
    """
    spaces = [i for i, ch in enumerate(flat) if ch == " "]
    best: Optional[Tuple[float, int]] = None
    for pos in spaces:
        top, bottom = flat[:pos], flat[pos + 1:]
        if len(top) > max_chars or len(bottom) > max_chars:
            continue
        key = (_break_penalty(top, bottom), pos)
        if best is None or key < best:
            best = key
    if best is not None:
        return best[1], best[0], True
    if not spaces:
        return None, 0.0, False
    pos = min(spaces, key=lambda p: (abs(p - (len(flat) - p - 1)), p))
    return pos, _BAD_BREAK, False


def _wrap(flat: str, max_chars: int, max_lines: int) -> Tuple[List[str], float, bool]:
    """Righe, penalità complessiva e validità (tutte le righe entro il limite)."""
    if len(flat) <= max_chars:
        return [flat], 0.0, True
    if max_lines <= 1:
        return [flat], _BAD_BREAK, False
    pos, pen, ok = _best_two_lines(flat, max_chars)
    if ok or max_lines == 2:
        if pos is None:
            return [flat], pen, False
        return [flat[:pos], flat[pos + 1:]], pen, ok
    # più di due righe: la prima riga è la più lunga che sta nel limite senza finire
    # con una parola funzionale; il resto si impagina ricorsivamente
    spaces = [i for i, ch in enumerate(flat) if ch == " " and i <= max_chars]
    good = [i for i in spaces if not _is_dangling(_last_token(flat[:i]))]
    cut = (good or spaces or [None])[-1]
    if cut is None:
        return [flat], _BAD_BREAK, False
    rest, rest_pen, rest_ok = _wrap(flat[cut + 1:], max_chars, max_lines - 1)
    return [flat[:cut]] + rest, rest_pen, rest_ok


def wrap_lines(text: str, rules: LayoutRules = LayoutRules()) -> str:
    """Va a capo con criterio linguistico; righe separate da ``"\\n"``.

    Una riga sola se ci sta. Altrimenti, tra tutti gli spazi che lasciano righe entro
    ``max_chars_per_line``, sceglie quello con la penalità più bassa: preferisce dopo
    , ; : . ? ! e prima di congiunzioni/preposizioni/"che"; non lascia mai in fondo
    alla riga superiore articoli, preposizioni (anche articolate), clitici o
    e/o/ma/che/se/non; preferisce la riga inferiore più lunga e righe bilanciate; evita
    righe di 1–2 parole corte. Se nessuno spazio rispetta il limite, usa lo spazio più
    bilanciato. Non spezza mai una parola. Gli a capo già presenti vengono rifatti.
    """
    flat = " ".join(text.split())
    if not flat:
        return ""
    lines, _, _ = _wrap(flat, rules.max_chars_per_line, rules.max_lines)
    return "\n".join(lines)


def _wrap_check(text: str, rules: LayoutRules) -> Tuple[bool, float]:
    """``(entra_nei_limiti, penalità dell'a capo)`` per il testo di un sottotitolo."""
    lines, pen, ok = _wrap(" ".join(text.split()), rules.max_chars_per_line, rules.max_lines)
    return ok and len(lines) <= rules.max_lines, pen


# ── Parole dai segmenti ───────────────────────────────────────────────────────

def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _segment_words(seg: Any, rules: LayoutRules) -> List[Word]:
    """Parole usabili di un segmento (testo non vuoto, tempi numerici)."""
    out: List[Word] = []
    for w in _get(seg, "words", None) or []:
        text = _get(w, "word", None)
        if text is None:
            text = _get(w, "text", "")
        text = str(text or "")
        start, end = _num(_get(w, "start")), _num(_get(w, "end"))
        if not text.strip() or start is None or end is None:
            continue
        prob = _num(_get(w, "probability"))
        if prob is None:
            prob = _num(_get(w, "score"), 1.0)   # WhisperX
        if not rules.keep_low_confidence_words and prob < rules.min_word_prob:
            continue
        out.append(Word(text, start, end, prob))
    if not out:
        return out
    if len(out) > 1 and not any(w.text[:1].isspace() for w in out):
        # parole senza la convenzione dello spazio iniziale (es. WhisperX): separale
        for w in out:
            w.text = " " + w.text.strip()
    elif not out[0].text[:1].isspace():
        out[0].text = " " + out[0].text   # un confine di segmento è sempre un confine di parola
    return out


def words_from_segments(segments: Iterable[Any],
                        rules: LayoutRules = LayoutRules()) -> Tuple[List[Word], Set[int]]:
    """Parole di tutti i segmenti in un'unica lista, con gli indici in cui inizia un nuovo
    segmento Whisper (indice 0 escluso).

    Accetta oggetti ``Segment`` di faster-whisper o dict con le stesse chiavi (``words``
    come dict ``word/start/end/probability``). Scarta i segmenti con ``no_speech_prob`` >
    0,9 o ``avg_logprob`` < −1,8; tiene tutte le parole, anche poco probabili, salvo
    ``keep_low_confidence_words=False``. Un segmento senza parole usabili diventa una sola
    parola sintetica con il testo del segmento e confidenza ``exp(avg_logprob)``.
    """
    words: List[Word] = []
    boundaries: Set[int] = set()
    for seg in segments or []:
        no_speech = _num(_get(seg, "no_speech_prob", 0.0), 0.0)
        avg_logprob = _num(_get(seg, "avg_logprob", 0.0), 0.0)
        if no_speech > _MAX_NO_SPEECH_PROB or avg_logprob < _MIN_AVG_LOGPROB:
            logger.debug("Segmento scartato (no_speech=%.2f, avg_logprob=%.2f)",
                         no_speech, avg_logprob)
            continue
        seg_words = _segment_words(seg, rules)
        if not seg_words:
            text = " ".join(str(_get(seg, "text", "") or "").split())
            if not text:
                continue
            start = _num(_get(seg, "start"), 0.0)
            end = max(start, _num(_get(seg, "end"), start))
            prob = min(1.0, math.exp(avg_logprob))
            seg_words = [Word(" " + text, start, end, prob, synthetic=True)]
        if words:
            boundaries.add(len(words))
        words.extend(seg_words)
    return words, boundaries


# ── Segmentazione ─────────────────────────────────────────────────────────────

# Costi della programmazione dinamica (unità arbitrarie, più basso = meglio)
_COST_SUBTITLE = 12.0         # costo fisso per sottotitolo: evita la frammentazione
_COST_FEW_WORDS = 80.0        # sottotitolo di 1–2 parole
_COST_SHORT_SPEECH = 40.0     # meno di 0,8 s di parlato
_COST_PAUSE_PER_S = 25.0      # per secondo di pausa interna oltre 0,3 s
_COST_FEW_WORDS_COMPLETE = 20.0  # …ma è una battuta completa ("Ehm, via.")
_COST_SENTENCE_INSIDE = 14.0  # per ogni fine frase interna (> costo di un sottotitolo:
#                               due frasi medie si separano, due battute brevi restano unite)
_COST_STRADDLE_START = 15.0   # comincia a metà frase e poi ne apre un'altra
_COST_SENTENCE_TAIL = 25.0    # fine frase interna + inizio della successiva lasciato a metà
_COST_SHORT_TAIL = 40.0       # …e quell'inizio è di sole 1–2 parole
_COST_DANGLING = 400.0        # finisce con parola funzionale
_COST_ORPHAN = 400.0          # finisce con la prima parola di una nuova frase
_COST_WEAK_END = 15.0
_COST_WRAP_FACTOR = 0.25      # peso della penalità di a capo


def _sanitize(words: Sequence[Word], boundaries: Set[int]) -> Tuple[List[Word], Set[int]]:
    """Copia delle parole con tempi coerenti (inizi e fini non decrescenti, fine ≥ inizio),
    senza parole vuote; i confini vengono rimappati sui nuovi indici."""
    out: List[Word] = []
    new_bounds: Set[int] = set()
    pending = False
    prev_start = prev_end = None
    for i, w in enumerate(words):
        if i in boundaries:
            pending = True
        if not (w.text or "").strip():
            continue
        start = _num(w.start, prev_start if prev_start is not None else 0.0)
        end = _num(w.end, start)
        if prev_start is not None:
            start = max(start, prev_start)
        end = max(end, start, prev_end if prev_end is not None else start)
        if pending and out:
            new_bounds.add(len(out))
        pending = False
        out.append(Word(w.text, start, end, _num(w.probability, 1.0), bool(w.synthetic)))
        prev_start, prev_end = start, end
    return out, new_bounds


def _gap(block: Sequence[Word], k: int) -> float:
    """Pausa tra la parola ``k`` e la successiva."""
    return max(0.0, block[k + 1].start - block[k].end)


def _expand_synthetic(w: Word) -> List[Word]:
    """Divide una parola sintetica in parole con tempi proporzionali ai caratteri."""
    text = " ".join(w.text.split())
    total = max(len(text), 1)
    dur = max(0.0, w.end - w.start)
    out: List[Word] = []
    pos = 0
    for tok in text.split(" "):
        s = w.start + dur * pos / total
        e = w.start + dur * (pos + len(tok)) / total
        out.append(Word(" " + tok, s, e, w.probability, synthetic=True))
        pos += len(tok) + 1
    return out


def _break_cost(block: Sequence[Word], j: int, bounds: Set[int]) -> float:
    """Costo di chiudere un sottotitolo dopo ``block[j - 1]`` (``j < len(block)``)."""
    tok = block[j - 1].text.strip()
    nxt = _core(block[j].text)
    g = _gap(block, j - 1)
    if _ends_sentence(tok):
        cost = 0.0
    elif _ends_clause(tok):
        cost = 3.0 if g >= 0.2 else 5.0
    elif g >= _STRONG_PAUSE_S:
        cost = 8.0
    elif nxt in _BREAK_BEFORE_WORDS:
        cost = 20.0 if g >= 0.15 else 28.0
    else:
        cost = 40.0 - 30.0 * min(g, _STRONG_PAUSE_S)
    if j in bounds:
        cost -= 3.0     # confine di segmento Whisper: solo un indizio
    if _is_dangling(tok):
        cost += _COST_DANGLING
    elif _is_weak_end(tok):
        cost += _COST_WEAK_END
    if _is_locked(tok, block[j].text, block[j - 2].text.strip() if j >= 2 else ""):
        cost += _COST_LOCKED
    return cost


def _starts_sentence(block: Sequence[Word], i: int, prev_word: Optional[Word]) -> bool:
    """True se ``block[i]`` apre una frase (la parola prima chiude una frase).

    L'inizio assoluto del parlato non conta come inizio di frase: non si sa cosa c'era prima.
    """
    before = block[i - 1] if i > 0 else prev_word
    return before is not None and _ends_sentence(before.text)


def _orphan_cost(block: Sequence[Word], j: int, prev_word: Optional[Word]) -> float:
    """Penalità se ``block[j - 1]`` è la prima parola di una frase lasciata in coda."""
    if _ends_sentence(block[j - 1].text):
        return 0.0
    return _COST_ORPHAN if _starts_sentence(block, j - 1, prev_word) else 0.0


def _subtitle_cost(block: Sequence[Word], i: int, j: int, text: str, wrap_pen: float,
                   prev_word: Optional[Word]) -> float:
    """Costo intrinseco del sottotitolo ``block[i:j]``.

    Oltre ai sottotitoli troppo corti e alle pause interne, penalizza i sottotitoli che
    mescolano frasi: ogni fine frase interna costa un po' (molto se seguita da una pausa,
    cioè probabilmente da un cambio di battuta), e di più se il sottotitolo comincia a metà
    di una frase o lascia a metà quella che apre ("…abbigliamento. Valore che è…,").
    """
    n = len(block)
    starts = _starts_sentence(block, i, prev_word) or (i == 0 and prev_word is None)
    ends = _ends_sentence(block[j - 1].text)
    cost = _COST_SUBTITLE
    if len(text.split()) <= 2 and n > 2:
        # una battuta completa ("Ehm, via.") può stare da sola; un frammento no
        cost += _COST_FEW_WORDS_COMPLETE if (starts and ends) else _COST_FEW_WORDS
    if block[j - 1].end - block[i].start < _SHORT_SPEECH_S and (j - i) < n:
        cost += _COST_SHORT_SPEECH
    last_end = -1
    inside = 0
    for k in range(i, j - 1):
        g = _gap(block, k)
        is_end = _ends_sentence(block[k].text)
        if g > 0.3:
            cost += _COST_PAUSE_PER_S * (g - 0.3) * (2.0 if is_end else 1.0)
        if is_end:
            last_end = k
            inside += 1
    if inside:
        cost += _COST_SENTENCE_INSIDE * inside
        if not starts:
            cost += _COST_STRADDLE_START
        if not ends:
            cost += _COST_SENTENCE_TAIL
            if j - 1 - last_end <= 2:
                cost += _COST_SHORT_TAIL
    return cost + _COST_WRAP_FACTOR * max(0.0, wrap_pen)


def _plan_block(block: Sequence[Word], bounds: Set[int], prev_word: Optional[Word],
                rules: LayoutRules) -> List[Tuple[int, int]]:
    """Divisione ottima (costo minimo) di un blocco di parole in sottotitoli.

    Programmazione dinamica: ``best[j]`` = costo minimo per impaginare ``block[:j]``.
    Un candidato ``block[i:j]`` è ammesso se il testo sta in ``max_lines`` righe da
    ``max_chars_per_line`` e il parlato dura al massimo ``max_duration_s`` (una parola
    singola è sempre ammessa, così una soluzione esiste sempre).
    """
    n = len(block)
    max_len = rules.max_chars_per_line * rules.max_lines + rules.max_lines - 1
    best = [math.inf] * (n + 1)
    back = [0] * (n + 1)
    best[0] = 0.0
    for i in range(n):
        if best[i] == math.inf:
            continue
        for j in range(i + 1, n + 1):
            single = j == i + 1
            text = fix_typography(join_words(block[i:j]))
            if not single and (len(text) > max_len
                               or block[j - 1].end - block[i].start > rules.max_duration_s):
                break
            fits, wrap_pen = _wrap_check(text, rules)
            if not fits and not single:
                continue
            cost = best[i] + _subtitle_cost(block, i, j, text, wrap_pen if fits else 0.0,
                                            prev_word)
            if j < n:
                cost += _break_cost(block, j, bounds)
            cost += _orphan_cost(block, j, prev_word)
            if cost < best[j]:
                best[j] = cost
                back[j] = i
    ranges: List[Tuple[int, int]] = []
    j = n
    while j > 0:
        ranges.append((back[j], j))
        j = back[j]
    ranges.reverse()
    return ranges


def _split_blocks(words: Sequence[Word], bounds: Set[int]
                  ) -> List[Tuple[List[Word], Set[int]]]:
    """Blocchi indipendenti: si separa sui silenzi ≥ 1,5 s e attorno alle parole
    sintetiche (che vengono espanse in parole con tempi proporzionali).

    Eccezione: un silenzio fino a 3 s si attraversa se la parola prima non può chiudere
    un sottotitolo (parola funzionale, o prima parola di una nuova frase): "Per [2 s] noi,
    l'innovazione…" resta un sottotitolo solo invece di lasciare "Per" da solo.
    """
    blocks: List[Tuple[List[Word], Set[int]]] = []
    current: List[Word] = []
    current_bounds: Set[int] = set()

    def stuck(block: List[Word]) -> bool:
        last = block[-1]
        if _is_dangling(last.text):
            return True
        if _ends_sentence(last.text):
            return False
        before = block[-2] if len(block) >= 2 else (blocks[-1][0][-1] if blocks else None)
        return before is not None and _ends_sentence(before.text)

    for idx, w in enumerate(words):
        if w.synthetic:
            if current:
                blocks.append((current, current_bounds))
            blocks.append((_expand_synthetic(w), set()))
            current, current_bounds = [], set()
            continue
        silence = w.start - current[-1].end if current else 0.0
        if silence >= _HARD_SILENCE_S and not (silence <= _MAX_BRIDGE_S and stuck(current)):
            blocks.append((current, current_bounds))
            current, current_bounds = [], set()
        if current and idx in bounds:
            current_bounds.add(len(current))
        current.append(w)
    if current:
        blocks.append((current, current_bounds))
    return blocks


def _capitalize_first(text: str) -> str:
    for k, ch in enumerate(text):
        if ch.isalpha():
            return text[:k] + ch.upper() + text[k + 1:] if ch.islower() else text
        if ch not in _OPENING_QUOTES:
            return text
    return text


def segment(words: Sequence[Word], boundaries: Set[int],
            rules: LayoutRules = LayoutRules()) -> List[Dict]:
    """Divide le parole in sottotitoli ``{"start", "end", "text", "confidence"}``.

    ``start``/``end`` sono inizio della prima parola e fine dell'ultima (i tempi
    definitivi li calcola ``time_subtitles``); ``text`` è già corretto con
    ``fix_typography`` ma non va a capo; ``confidence`` è la probabilità minima delle
    parole. Ogni testo sta in ``max_lines`` righe da ``max_chars_per_line`` dopo
    ``wrap_lines`` (salvo una singola parola più lunga del limite).

    Priorità dei tagli: fine frase, punteggiatura di proposizione, pausa ≥ 0,4 s, prima di
    congiunzione/preposizione (meglio se su una pausa); i confini dei segmenti Whisper sono
    solo un indizio. Mai finire con una parola funzionale (``FUNCTION_WORDS``) né con la
    prima parola di una nuova frase, né separare locuzioni ("così come", "dietro a") o un
    numero dalla sua parola; si evitano sottotitoli che mescolano frasi diverse e quelli di
    ≤ 2 parole o < 0,8 s di parlato (unendoli al vicino con la pausa più breve, se i limiti
    lo consentono; una battuta completa come "Ehm, via." può restare da sola). Nessun
    sottotitolo attraversa un silenzio ≥ 1,5 s, salvo un silenzio ≤ 3 s dopo una parola
    che non può chiudere il sottotitolo; le parole sintetiche formano sottotitoli propri
    (divisi a parole se troppo lunghi, tempo ripartito in proporzione). Se la parola
    precedente chiude una frase, la prima lettera del sottotitolo diventa maiuscola.
    """
    clean, bounds = _sanitize(words, set(boundaries or ()))
    subs: List[Dict] = []
    prev_word: Optional[Word] = None
    for block, block_bounds in _split_blocks(clean, bounds):
        for i, j in _plan_block(block, block_bounds, prev_word, rules):
            part = block[i:j]
            text = fix_typography(join_words(part))
            if not text:
                continue
            if prev_word is not None and _ends_sentence(prev_word.text):
                text = _capitalize_first(text)
            subs.append({
                "start": part[0].start,
                "end": max(w.end for w in part),
                "text": text,
                "confidence": min(w.probability for w in part),
            })
            prev_word = part[-1]
    return subs


# ── Tempi ─────────────────────────────────────────────────────────────────────

def _flat_len(text: str) -> int:
    return len(" ".join(str(text).split()))


def time_subtitles(subs: Sequence[Dict], rules: LayoutRules = LayoutRules(),
                   audio_end: Optional[float] = None) -> List[Dict]:
    """Tempi definitivi dei sottotitoli (copie dei dict, altre chiavi conservate).

    - inizio = inizio della prima parola;
    - fine = fine dell'ultima parola + ``end_pad_s``, poi estesa nel silenzio seguente
      finché i CPS (testo senza a capo) scendono a ``max_cps`` e almeno fino a
      ``min_duration_s``; mai oltre ``inizio successivo − min_gap_s``, ``inizio +
      max_duration_s`` né ``audio_end``. Se i CPS non si raggiungono restano così
      (li segnala l'editor);
    - pause tra ``min_gap_s`` e ``snap_gap_s`` chiuse a esattamente ``min_gap_s``
      allungando il sottotitolo precedente (se resta entro ``max_duration_s``);
    - mai sovrapposizioni, sempre fine > inizio: se le parole si sovrappongono la fine
      diventa ``inizio successivo − min_gap_s`` o, se non c'è spazio, l'inizio successivo.
    """
    items = [dict(s) for s in subs if str(s.get("text", "")).strip()]
    n = len(items)
    if not n:
        return []
    starts: List[float] = []
    for it in items:
        s = max(0.0, _num(it.get("start"), 0.0))
        if starts and s < starts[-1] + _MIN_START_STEP_S:
            s = starts[-1] + _MIN_START_STEP_S
        starts.append(round(s, 3))

    ends: List[float] = []
    for i, it in enumerate(items):
        s = starts[i]
        speech_end = max(_num(it.get("end"), s), s)
        desired = max(speech_end + rules.end_pad_s,
                      s + _flat_len(it["text"]) / rules.max_cps,
                      s + rules.min_duration_s)
        limit = s + rules.max_duration_s
        if audio_end is not None and audio_end > s:
            limit = min(limit, audio_end)
        nxt = starts[i + 1] if i + 1 < n else None
        if nxt is not None:
            limit = min(limit, nxt - rules.min_gap_s)
        end = min(desired, limit)
        if end <= s:
            # nessuno spazio per la pausa minima: si arriva al più all'inizio successivo
            hard = nxt if nxt is not None else s + rules.min_duration_s
            end = min(desired, hard) if hard > s else s + 0.001
        ends.append(round(end, 3))

    for i in range(n - 1):
        gap = starts[i + 1] - ends[i]
        if rules.min_gap_s + 1e-6 < gap < rules.snap_gap_s:
            new_end = round(starts[i + 1] - rules.min_gap_s, 3)
            if new_end - starts[i] <= rules.max_duration_s + 1e-6:
                ends[i] = new_end

    for i, it in enumerate(items):
        it["start"], it["end"] = starts[i], ends[i]
        if it["end"] <= it["start"]:
            it["end"] = round(it["start"] + 0.001, 3)
    return items


def layout(segments: Iterable[Any], rules: LayoutRules = LayoutRules(),
           audio_end: Optional[float] = None) -> List[Dict]:
    """Pipeline completa: ``words_from_segments`` → ``segment`` → ``time_subtitles``.

    Il testo restituito non va a capo: applicare ``wrap_lines`` dopo le altre correzioni.
    """
    words, boundaries = words_from_segments(segments, rules)
    return time_subtitles(segment(words, boundaries, rules), rules, audio_end)


# ── Parlato senza parole ──────────────────────────────────────────────────────

def find_uncovered_speech(speech: Sequence[Tuple[float, float]], words: Sequence[Word],
                          min_len_s: float = 1.5) -> List[Tuple[float, float]]:
    """Tratti di parlato (VAD) lunghi almeno ``min_len_s`` in cui non cade nessuna parola.

    Gli span VAD vengono prima uniti quando li separa una pausa < 0,3 s. Dentro ogni span
    si tolgono gli intervalli coperti dalle parole (sovrapposizione, parole di durata nulla
    comprese): restano i buchi, cioè lo span intero se non contiene parole oppure il tratto
    scoperto di uno span lungo (caso reale: Whisper salta ~10 s in mezzo a 40 s di
    parlato). Sono i tratti da ritrascrivere.
    """
    spans = sorted((float(s), float(e)) for s, e in speech if float(e) > float(s))
    merged: List[List[float]] = []
    for s, e in spans:
        if merged and s - merged[-1][1] < _SPEECH_MERGE_GAP_S:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    covered = sorted((min(w.start, w.end), max(w.start, w.end)) for w in words)
    found: List[Tuple[float, float]] = []
    for s, e in merged:
        if e - s < min_len_s:
            continue
        cursor = s
        for ws, we in covered:
            if we < s or ws > e:
                continue
            if ws > cursor and ws - cursor >= min_len_s:
                found.append((round(cursor, 3), round(ws, 3)))
            cursor = max(cursor, we)
            if cursor >= e:
                break
        if e - cursor >= min_len_s:
            found.append((round(cursor, 3), round(e, 3)))
    return found

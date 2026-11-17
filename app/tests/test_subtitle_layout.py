"""
test_subtitle_layout.py — Impaginazione dei sottotitoli italiani da timestamp per parola.

Nessun modello e nessuna UI: parole e segmenti sono dict o ``SimpleNamespace`` costruiti a
mano, con esempi presi da trascrizioni reali (tempi originali di Whisper).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import List, Optional, Tuple

import pytest

from core import subtitle_layout as sl
from core.subtitle_layout import LayoutRules, Word

RULES = LayoutRules()


# ── Helper ────────────────────────────────────────────────────────────────────

def _words(spec: List[Tuple]) -> List[Word]:
    """Parole da tuple ``(testo, inizio, fine[, probabilità])``."""
    out = []
    for item in spec:
        text, start, end = item[0], item[1], item[2]
        prob = item[3] if len(item) > 3 else 1.0
        out.append(Word(text, start, end, prob))
    return out


def _even_words(text: str, start: float = 0.0, step: float = 0.3,
                gaps: Optional[dict] = None) -> List[Word]:
    """Parole con tempi regolari; ``gaps`` = {indice parola: pausa prima di essa}."""
    out: List[Word] = []
    t = start
    for i, tok in enumerate(text.split()):
        t += (gaps or {}).get(i, 0.0)
        out.append(Word(" " + tok, t, t + step - 0.02))
        t += step
    return out


def _seg_dict(words: List[Tuple], text: Optional[str] = None, **extra) -> dict:
    ws = [{"word": w[0], "start": w[1], "end": w[2],
           "probability": w[3] if len(w) > 3 else 0.99} for w in words]
    seg = {
        "start": ws[0]["start"] if ws else extra.get("start", 0.0),
        "end": ws[-1]["end"] if ws else extra.get("end", 0.0),
        "text": text if text is not None else "".join(w["word"] for w in ws),
        "words": ws, "no_speech_prob": 0.01, "avg_logprob": -0.2,
    }
    seg.update(extra)
    return seg


def _texts(subs: List[dict]) -> List[str]:
    return [s["text"] for s in subs]


def _last_token(text: str) -> str:
    return text.split()[-1]


def _fits(text: str, rules: LayoutRules = RULES) -> bool:
    lines = sl.wrap_lines(text, rules).split("\n")
    return len(lines) <= rules.max_lines and all(len(x) <= rules.max_chars_per_line
                                                 for x in lines)


# Parole reali (nico_ed_ema): "…destinato al macero. Mi permetto di aggiungere…"
NICO = [(" ancora", 44.73, 45.25), (" più", 45.25, 45.45), (" pulita.", 45.45, 45.91),
        (" Rimane", 46.05, 46.61), (" assurdo", 46.63, 47.51), (" pensare", 47.51, 47.97),
        (" che", 47.97, 48.09), (" altrimenti", 48.09, 48.61), (" tutto", 48.61, 48.81),
        (" questo", 48.81, 49.09), (" materiale", 49.09, 49.69), (" sarebbe", 49.69, 49.97),
        (" stato", 49.97, 50.13), (" destinato", 50.13, 50.91), (" al", 50.91, 51.41),
        (" macero.", 51.41, 51.83), (" Mi", 51.91, 52.19), (" permetto", 52.92, 53.36),
        (" di", 53.36, 53.36), (" aggiungere", 53.36, 53.78), (" che", 53.78, 53.92),
        (" questo", 53.92, 54.06), (" è", 54.06, 54.18), (" uno", 54.18, 54.26),
        (" dei", 54.26, 54.34), (" motivi", 54.34, 54.68), (" per", 54.68, 54.74),
        (" cui", 54.74, 54.92), (" spacchiamo", 54.92, 55.34), (" i", 55.34, 55.44),
        (" culi.", 55.44, 55.68)]

# Parole reali (matteo_scpt_final): "…costituisce veramente il valore dietro a un prodotto"
MATTEO = [(" Un", 20.96, 21.12), (" lavoro", 21.12, 21.36), (" fatto", 21.36, 21.68),
          (" di", 21.68, 21.92), (" ricerca", 21.92, 22.34), (" di", 22.34, 22.44),
          (" perfezione", 22.44, 23.3), (" e", 23.3, 23.42), (" artigianalità,", 23.42, 24.32),
          (" e", 24.34, 24.66), (" cura", 24.68, 24.98), (" dei", 24.98, 25.08),
          (" dettagli.", 25.08, 25.74), (" Ed", 25.87, 26.09), (" è", 26.09, 26.15),
          (" questo", 26.15, 26.57), (" quello", 26.57, 26.87), (" che", 26.87, 27.03),
          (" costituisce", 27.03, 27.63), (" veramente", 27.63, 27.99), (" il", 27.99, 28.91),
          (" valore", 29.06, 29.46), (" dietro", 29.46, 29.78), (" a", 29.78, 29.82),
          (" un", 29.82, 29.9), (" prodotto", 29.9, 30.18), (" SCPT.", 30.18, 30.84, 0.85)]

# Parole reali (matteo_scpt_final): prima frase, 5.24–14.68 s
MATTEO_START = [
    (" Modalenta", 5.24, 5.72, 0.75), (" è", 5.72, 6.02), (" il", 6.02, 6.08),
    (" nostro", 6.08, 6.36), (" manifesto,", 6.36, 7.16), (" la", 7.16, 7.4),
    (" visione", 7.43, 7.85), (" di", 7.85, 7.89), (" una", 7.89, 8.03), (" moda", 8.03, 8.33),
    (" basata", 8.33, 8.63), (" su", 8.63, 8.83), (" un", 8.83, 8.93),
    (" concetto", 8.93, 9.29), (" fondamentale,", 9.29, 10.19), (" comprendere", 10.54, 11.2),
    (" e", 11.2, 11.38), (" comunicare", 11.38, 12.0), (" il", 12.0, 12.1),
    (" valore", 12.1, 12.56), (" che", 12.56, 12.66), (" sta", 12.66, 12.82),
    (" dietro", 12.82, 13.1), (" alla", 13.1, 13.2), (" produzione", 13.2, 13.74),
    (" di", 13.74, 13.84), (" un", 13.84, 13.96), (" capo", 13.96, 14.16), (" di", 14.16, 14.22),
    (" abbigliamento.", 14.22, 14.68)]

# Parole reali (Cappato_reels_4): "…il permesso quindi è chiaro che se Se la democrazia…"
CAPPATO = [(" devi", 55.1, 55.22), (" andare", 55.22, 55.5), (" in", 55.5, 55.74),
           (" comune", 55.74, 56.18), (" a", 56.18, 56.34), (" chiedere", 56.34, 56.62),
           (" il", 56.62, 56.76), (" permesso", 56.76, 57.4), (" quindi", 57.4, 57.98, 0.24),
           (" è", 58.22, 58.64), (" chiaro", 58.64, 58.94), (" che", 58.94, 59.02),
           (" se", 59.02, 59.22), (" Se", 59.22, 59.36), (" la", 59.36, 59.66),
           (" democrazia", 59.66, 60.48), (" diventa,", 60.6, 61.66), (" come", 61.66, 61.9),
           (" sta", 61.9, 62.08), (" diventando,", 62.08, 62.78), (" l", 62.8, 63.0),
           ("'unica", 63.0, 63.46), (" attività", 63.46, 64.0), (" umana", 64.0, 64.48),
           (" seria,", 64.48, 64.84)]


# ── words_from_segments ───────────────────────────────────────────────────────

def test_words_from_segments_keeps_all_low_probability_words():
    seg = _seg_dict([(" il", 0.0, 0.2, 0.9), (" permesso", 0.2, 0.6, 0.9),
                     (" quindi", 0.6, 1.0, 0.24), (" bene.", 1.0, 1.3, 0.05)])
    words, _ = sl.words_from_segments([seg])
    assert [w.text for w in words] == [" il", " permesso", " quindi", " bene."]
    assert words[2].probability == pytest.approx(0.24)
    assert not any(w.synthetic for w in words)


def test_words_from_segments_can_still_drop_low_probability_words():
    rules = LayoutRules(keep_low_confidence_words=False)
    seg = _seg_dict([(" il", 0.0, 0.2, 0.9), (" quindi", 0.6, 1.0, 0.24)])
    words, _ = sl.words_from_segments([seg], rules)
    assert [w.text for w in words] == [" il"]


def test_words_from_segments_discards_unreliable_segments():
    good = _seg_dict([(" ciao", 0.0, 0.4)])
    silent = _seg_dict([(" grazie", 1.0, 1.4)], no_speech_prob=0.95)
    garbage = _seg_dict([(" bla", 2.0, 2.4)], avg_logprob=-2.0)
    words, _ = sl.words_from_segments([good, silent, garbage])
    assert [w.text.strip() for w in words] == ["ciao"]


def test_words_from_segments_accepts_faster_whisper_objects():
    w = SimpleNamespace(word=" ciao", start=0.0, end=0.4, probability=0.8)
    seg = SimpleNamespace(start=0.0, end=0.4, text=" ciao", words=[w],
                          no_speech_prob=0.0, avg_logprob=-0.1)
    words, boundaries = sl.words_from_segments([seg])
    assert words == [Word(" ciao", 0.0, 0.4, 0.8)]
    assert boundaries == set()


def test_words_from_segments_synthetic_word_and_boundaries():
    seg1 = _seg_dict([(" uno", 0.0, 0.3), (" due", 0.3, 0.6)])
    seg2 = _seg_dict([], text=" testo senza parole", start=1.0, end=2.0)
    seg3 = _seg_dict([("tre", 2.5, 2.8)])  # senza spazio iniziale: va aggiunto
    words, boundaries = sl.words_from_segments([seg1, seg2, seg3])
    assert [w.synthetic for w in words] == [False, False, True, False]
    assert words[2].text.strip() == "testo senza parole"
    assert (words[2].start, words[2].end) == (1.0, 2.0)
    assert boundaries == {2, 3}
    assert sl.join_words(words) == "uno due testo senza parole tre"


# ── join_words ────────────────────────────────────────────────────────────────

def test_join_words_uses_whisper_spacing_for_elisions():
    words = _words([(" rendere", 0, 1), (" l", 1, 2), ("'industria", 2, 3),
                    (" Cos", 3, 4), ("'è", 4, 5), (" un", 5, 6), ("'illusione", 6, 7)])
    assert sl.join_words(words) == "rendere l'industria Cos'è un'illusione"


def test_join_words_keeps_french_hyphenation():
    words = _words([(" Excuse", 0, 1), ("-moi.", 1, 2), (" Est", 2, 3), ("-ce", 3, 4),
                    (" que", 4, 5), (" tu", 5, 6)])
    assert sl.join_words(words) == "Excuse-moi. Est-ce que tu"


def test_join_words_empty():
    assert sl.join_words([]) == ""


# ── fix_typography ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, fixed", [
    ("per rendere l 'industria della moda", "per rendere l'industria della moda"),
    ("Cos 'è intelligenza artificiale civica?", "Cos'è intelligenza artificiale civica?"),
    ("È un 'illusione pensare", "È un'illusione pensare"),
    ("non c 'è niente", "non c'è niente"),
    ("la lingua dell' amore", "la lingua dell'amore"),
    ("Tra un po'potremmo pagare", "Tra un po' potremmo pagare"),
    ("Tra un po' potremmo pagare", "Tra un po' potremmo pagare"),
    ("E'la democrazia che viene superata.", "È la democrazia che viene superata."),
    ("E' la democrazia che viene superata.", "È la democrazia che viene superata."),
    ("superata. E' un'illusione", "superata. È un'illusione"),
    ("ciao , come stai ? bene !", "ciao, come stai? Bene!"),
    ("e che devi passare...", "e che devi passare…"),
    ("aspetta ... poi", "aspetta… Poi"),
    ("macero.  mi permetto", "macero. Mi permetto"),
    ("Va bene, OK.", "Va bene, Ok."),
    ("costa 1.000 euro, cioè 3,5 al giorno", "costa 1.000 euro, cioè 3,5 al giorno"),
    ("un po bene", "un po' bene"),
    ("ce un problema", "c'è un problema"),
    ("Ce bisogno di tempo", "C'è bisogno di tempo"),
    ("ce la faccio", "ce la faccio"),
    ("ce lo dice sempre", "ce lo dice sempre"),
    ("Est-ce que tu sais où je peux...", "Est-ce que tu sais où je peux…"),
    ("  spazi   multipli  ", "spazi multipli"),
    ("l'occhio, con l'orecchio", "l'occhio, con l'orecchio"),
    ("ha detto 'ciao' a tutti", "ha detto 'ciao' a tutti"),
])
def test_fix_typography(raw, fixed):
    assert sl.fix_typography(raw) == fixed


@pytest.mark.parametrize("raw", [
    "per rendere l 'industria", "Tra un po'potremmo", "E'la democrazia. e poi...",
    "ciao , come stai ?", "un po", "ce un problema", "OK ok", "dell' amore . quindi",
    "E' E' E'", "po'po'po'", "...", "", "l 'l 'l", "a ... b ... c",
])
def test_fix_typography_is_idempotent(raw):
    once = sl.fix_typography(raw)
    assert sl.fix_typography(once) == once


# ── wrap_lines ────────────────────────────────────────────────────────────────

def test_wrap_lines_single_line_when_it_fits():
    assert sl.wrap_lines("Ed è questo quello che costituisce") == \
        "Ed è questo quello che costituisce"


def test_wrap_lines_never_splits_di_una():
    text = "la visione di una moda basata su un concetto fondamentale"
    wrapped = sl.wrap_lines(text)
    top, bottom = wrapped.split("\n")
    assert len(top) <= 42 and len(bottom) <= 42
    assert wrapped in (
        "la visione di una moda basata\nsu un concetto fondamentale",
        "la visione di una moda\nbasata su un concetto fondamentale",
    )


def test_wrap_lines_prefers_after_comma():
    text = "Modalenta è il nostro manifesto, la visione di una moda"
    assert sl.wrap_lines(text) == "Modalenta è il nostro manifesto,\nla visione di una moda"


def test_wrap_lines_never_ends_top_line_on_function_word():
    # Lo spazio più bilanciato è dopo "il": va evitato.
    text = "Ed è questo quello che costituisce veramente il valore dietro a un prodotto."
    top, bottom = sl.wrap_lines(text).split("\n")
    assert _last_token(top).lower() not in {"il", "a", "un", "che", "dietro"}
    assert len(top) <= 42 and len(bottom) <= 42


def test_wrap_lines_avoids_short_top_line():
    # "Sì," da solo in alto sarebbe dopo una virgola, ma è una riga di una parola.
    text = "Sì, devo essere aiutato a votare e a firmare"
    assert sl.wrap_lines(text) == "Sì, devo essere aiutato\na votare e a firmare"


def test_wrap_lines_prefers_bottom_heavy_pyramid():
    text = " ".join(["parola"] * 7)  # 48 caratteri: 20/27 oppure 27/20
    top, bottom = sl.wrap_lines(text).split("\n")
    assert (len(top), len(bottom)) == (20, 27)


def test_wrap_lines_keeps_locked_pairs_together():
    # Caso reale (Cappato): "Quindi io, così / come sono aiutato a pagare,"
    wrapped = sl.wrap_lines("Quindi io, così come sono aiutato a pagare,")
    assert "così\ncome" not in wrapped
    assert wrapped == "Quindi io,\ncosì come sono aiutato a pagare,"


def test_wrap_lines_prefers_balance_over_weak_preposition_bonus():
    # Caso reale (nico): "che acquista e produce materiale partendo / da un design preciso,"
    assert sl.wrap_lines("che acquista e produce materiale partendo da un design preciso,") == \
        "che acquista e produce materiale\npartendo da un design preciso,"


def test_wrap_lines_keeps_numbers_with_their_word():
    # Caso reale (Apple): "Meno male che gli AirPods Pro / 3 utilizzano Apple Intelligence"
    wrapped = sl.wrap_lines("Meno male che gli AirPods Pro 3 utilizzano Apple Intelligence")
    assert wrapped == "Meno male che gli AirPods Pro 3\nutilizzano Apple Intelligence"
    assert "30\ngiorni" not in sl.wrap_lines(
        "certi comuni ti chiedono almeno 30 giorni di preavviso per tutto")


@pytest.mark.parametrize("text, bad", [
    # casi reali (matteo, linda)
    ("e a tutti di iniziare a prendersi maggior cura di ciò che abbiamo", "maggior\n"),
    ("Ottenuto il peso, andiamo a scrivere tutti i dati sulla nostra tabella", "tutti\ni "),
    ("Abbiamo scelto a tal proposito di dare una forma di patchwork", "tal\n"),
])
def test_wrap_lines_keeps_determiners_with_their_noun(text, bad):
    assert bad not in sl.wrap_lines(text)


def test_wrap_lines_fallback_never_cuts_words():
    text = " ".join(["parola"] * 20)  # 139 caratteri: nessuna coppia di righe ≤ 42
    wrapped = sl.wrap_lines(text)
    assert wrapped.replace("\n", " ") == text
    assert wrapped.count("\n") == 1
    top, bottom = wrapped.split("\n")
    assert abs(len(top) - len(bottom)) <= len("parola") + 1


def test_wrap_lines_single_long_word_unchanged():
    word = "x" * 60
    assert sl.wrap_lines(word) == word


def test_wrap_lines_rewraps_existing_newlines():
    assert sl.wrap_lines("ciao\ncome stai") == "ciao come stai"


# ── segment ───────────────────────────────────────────────────────────────────

def test_segment_empty():
    assert sl.segment([], set()) == []


def test_segment_single_word():
    subs = sl.segment(_words([(" ciao.", 1.0, 1.4, 0.7)]), set())
    assert subs == [{"start": 1.0, "end": 1.4, "text": "ciao.", "confidence": 0.7}]


def test_segment_never_ends_on_article():
    subs = sl.segment(_words(MATTEO), set())
    for s in subs:
        assert _last_token(s["text"]).lower() not in sl.FUNCTION_WORDS, _texts(subs)
        assert _fits(s["text"]), s["text"]
    joined = " ".join(_texts(subs))
    assert "il valore dietro" in joined
    assert not any(t.endswith("veramente il") for t in _texts(subs))


def test_segment_prefers_comma_over_preposition():
    # Caso reale (matteo): "…la visione di una moda basata" / "su un concetto fondamentale,
    # comprendere…" taglia una frase a metà ignorando la virgola subito dopo.
    subs = sl.segment(_words(MATTEO_START), set())
    texts = _texts(subs)
    assert not any(t.endswith("basata") for t in texts), texts
    assert any(t.endswith("su un concetto fondamentale,") for t in texts), texts
    assert texts[-1].endswith("di un capo di abbigliamento."), texts
    for t in texts:
        assert _fits(t), t


def test_segment_real_sentence_with_pause_and_comma():
    # Caso reale (matteo, 31.89–42.46 s): pausa di 0,67 s dopo "concetto", virgola dopo
    # "armadi,". Non va spezzato "a tutte / e a tutti" né "maggior / cura".
    words = _words([
        (" Comprendere", 31.89, 32.33), (" e", 32.33, 32.45), (" avere", 32.45, 32.65),
        (" consapevolezza", 32.65, 33.71), (" di", 33.71, 33.81), (" questo", 33.81, 34.03),
        (" concetto", 34.03, 34.61), (" permetterebbe", 35.28, 36.08), (" a", 36.08, 36.22),
        (" tutte", 36.22, 36.6), (" e", 36.6, 36.8), (" a", 36.8, 36.92), (" tutti", 36.92, 37.24),
        (" di", 37.24, 37.46), (" iniziare", 37.46, 37.82), (" a", 37.82, 37.88),
        (" prendersi", 37.88, 38.42), (" maggior", 38.42, 38.8), (" cura", 38.8, 39.2),
        (" di", 39.2, 39.26), (" ciò", 39.26, 39.44), (" che", 39.44, 39.5),
        (" abbiamo", 39.5, 39.78), (" nei", 39.78, 39.96), (" nostri", 39.96, 40.26),
        (" armadi,", 40.26, 40.66), (" allungare", 40.9, 41.56), (" la", 41.56, 41.72),
        (" vita", 41.72, 41.94), (" dei", 41.94, 42.06), (" prodotti.", 42.06, 42.46)])
    texts = _texts(sl.segment(words, set()))
    assert texts[0] == "Comprendere e avere consapevolezza di questo concetto", texts
    assert not any(t.endswith("a tutte") or t.endswith("maggior") for t in texts), texts
    for t in texts:
        assert "maggior\n" not in sl.wrap_lines(t)


def test_segment_keeps_first_word_of_sentence_with_its_sentence():
    subs = sl.segment(_words(NICO), set())
    texts = _texts(subs)
    assert not any(t.endswith(" Mi") for t in texts), texts
    assert any("Mi permetto" in t for t in texts), texts
    assert any(t.endswith("al macero.") for t in texts), texts
    for t in texts:
        assert _fits(t), t


def test_segment_merges_single_word_with_neighbour():
    words = _words(CAPPATO)
    subs = sl.segment(words, set())
    texts = _texts(subs)
    for t in texts:
        assert len(t.split()) > 2, texts
        assert _fits(t), t
    assert " ".join(texts).split() == sl.join_words(words).split()


def test_segment_prefers_following_neighbour_when_pause_is_shorter():
    words = _even_words("Abbiamo parlato a lungo della moda sostenibile.") + \
        _even_words("quindi", start=3.0) + \
        _even_words("adesso vediamo come si realizza il tessuto.", start=3.4)
    texts = _texts(sl.segment(words, set()))
    assert texts == ["Abbiamo parlato a lungo della moda sostenibile.",
                     "Quindi adesso vediamo come si realizza il tessuto."]


def test_segment_retains_low_probability_words_and_reports_confidence():
    words = _words([(" il", 0.0, 0.2, 0.9), (" permesso", 0.2, 0.6, 0.9),
                    (" quindi", 0.6, 1.0, 0.24), (" è", 1.0, 1.2, 0.95),
                    (" chiaro.", 1.2, 1.6, 0.05)])
    subs = sl.segment(words, set())
    assert _texts(subs) == ["il permesso quindi è chiaro."]
    assert subs[0]["confidence"] == pytest.approx(0.05)


def test_segment_every_subtitle_fits_two_lines():
    text = ("Modalenta è il nostro manifesto, la visione di una moda basata su un concetto "
            "fondamentale, comprendere e comunicare il valore che sta dietro alla produzione "
            "di un capo di abbigliamento. Valore che è determinato dalla materia prima, ma "
            "anche e soprattutto dal lavoro delle nostre persone.")
    words = _even_words(text, step=0.25)
    subs = sl.segment(words, set())
    assert " ".join(_texts(subs)).split() == text.split()
    for s in subs:
        assert _fits(s["text"]), s["text"]
        assert _last_token(s["text"]).lower() not in sl.FUNCTION_WORDS


def test_segment_never_spans_long_silence():
    words = _even_words("Questa è una frase che continua", step=0.3) + \
        _even_words("dopo una lunga pausa di silenzio.", start=3.5)
    subs = sl.segment(words, set())
    for s in subs:
        assert not (s["start"] < 2.0 < s["end"]), subs
    assert len(subs) == 2


def test_segment_bridges_long_silence_after_function_word():
    # Caso reale (nico_ed_ema): "Per" [1,98 s di silenzio] "noi, l'innovazione…".
    # "Per" da solo sarebbe peggio che attraversare il silenzio.
    words = _words([(" Per", 2.65, 2.95), (" noi,", 4.93, 5.29), (" l", 5.29, 5.41),
                    ("'innovazione", 5.41, 6.13), (" nasce", 6.13, 6.47),
                    (" dalla", 6.47, 6.67), (" Materia.", 6.67, 7.14)])
    assert _texts(sl.segment(words, set())) == ["Per noi, l'innovazione nasce dalla Materia."]


def test_segment_bridges_long_silence_after_sentence_start():
    # Caso reale (v6): "…eh? È" [1,85 s] "vestito da giocatore di baseball."
    words = _words([(" Oh,", 19.17, 19.65, 0.26), (" bello", 19.65, 20.13),
                    (" fresco", 20.13, 20.53), (" oggi,", 20.53, 20.67), (" eh?", 20.77, 20.87),
                    (" È", 20.91, 21.37, 0.05), (" vestito", 23.22, 23.68), (" da", 23.68, 23.8),
                    (" giocatore", 23.8, 24.24), (" di", 24.24, 24.4),
                    (" baseball.", 24.4, 24.76)])
    texts = _texts(sl.segment(words, set()))
    assert texts == ["Oh, bello fresco oggi, eh?", "È vestito da giocatore di baseball."]


def test_segment_does_not_bridge_very_long_silence():
    words = _even_words("Ecco il") + _even_words("risultato finale del lavoro.", start=5.0)
    texts = _texts(sl.segment(words, set()))
    assert texts == ["Ecco il", "risultato finale del lavoro."]


def test_segment_keeps_sentences_apart_when_a_pause_separates_them():
    # Caso reale (Apple): "…ne fonctionnent plus." [0,5 s] "Ragazzi, il francese…"
    words = _even_words("Le mienes ne fonctionnent plus.") + \
        _even_words("Ragazzi, il francese è la lingua dell'amore.", start=2.0)
    texts = _texts(sl.segment(words, set()))
    assert texts == ["Le mienes ne fonctionnent plus.",
                     "Ragazzi, il francese è la lingua dell'amore."]


def test_segment_does_not_start_new_sentence_after_a_sentence_tail():
    # Caso reale (Apple): "…per tradurre" / "in tempo reale. Così puoi capire…"
    text = ("Meno male che gli AirPods Pro 3 utilizzano Apple Intelligence per tradurre "
            "in tempo reale. Così puoi capire le lingue e anche le intenzioni a quanto pare.")
    subs = sl.segment(_even_words(text, step=0.25), set())
    texts = _texts(subs)
    assert any(t.endswith("in tempo reale.") for t in texts), texts
    assert any(t.startswith("Così puoi capire") for t in texts), texts


def test_segment_avoids_connective_at_end():
    # Caso reale (linda): "…meno tessuto possibile, quindi" [0,6 s] "seguendo tutto il bordo…"
    words = _even_words("Andiamo a tagliare scartando meno tessuto possibile,") + \
        _even_words("quindi", start=2.4) + \
        _even_words("seguendo tutto il bordo e ottenendo la forma di metà gamba.", start=3.0)
    texts = _texts(sl.segment(words, set()))
    assert not any(t.endswith("quindi") for t in texts), texts


def test_segment_keeps_short_complete_sentence_alone():
    # "Ehm, via." è una battuta completa tra due pause: non va incollata alla frase dopo.
    words = _even_words("Ehm, via.", step=0.45) + _even_words(
        "Meno male che gli AirPods utilizzano la traduzione in tempo reale.", start=2.0)
    texts = _texts(sl.segment(words, set()))
    assert texts[0] == "Ehm, via."


def test_segment_splits_long_sentence_at_strong_pause():
    text = ("Comprendere e avere consapevolezza di questo concetto permetterebbe a tutte "
            "e a tutti di iniziare a prendersi cura")
    words = _even_words(text, step=0.3, gaps={7: 0.67})
    subs = sl.segment(words, set())
    assert _texts(subs)[0] == "Comprendere e avere consapevolezza di questo concetto"


def test_segment_whisper_boundaries_are_only_a_hint():
    words = _even_words("Mi piace un sacco questo grandangolo.")
    subs = sl.segment(words, {3})
    assert _texts(subs) == ["Mi piace un sacco questo grandangolo."]


def test_segment_synthetic_word_is_its_own_subtitle():
    words = _even_words("Prima frase completa e chiara.") + [
        Word(" testo senza tempi per parola", 2.0, 3.0, 1.0, synthetic=True)] + \
        _even_words("Dopo il blocco sintetico arriva altro.", start=3.1)
    texts = _texts(sl.segment(words, {5, 6}))
    assert "Testo senza tempi per parola" in texts or "testo senza tempi per parola" in texts


def test_segment_long_synthetic_word_is_split_with_proportional_time():
    long_text = " ".join(["parola"] * 30)  # 209 caratteri
    words = [Word(" " + long_text, 10.0, 30.0, 1.0, synthetic=True)]
    subs = sl.segment(words, set())
    assert len(subs) >= 3
    assert " ".join(_texts(subs)) == long_text
    assert subs[0]["start"] == pytest.approx(10.0)
    assert subs[-1]["end"] == pytest.approx(30.0)
    for a, b in zip(subs, subs[1:]):
        assert a["end"] <= b["start"] + 1e-9
    for s in subs:
        assert _fits(s["text"])
        dur = s["end"] - s["start"]
        assert dur == pytest.approx(20.0 * (len(s["text"]) + 1) / (len(long_text) + 1), abs=1.0)


@pytest.mark.parametrize("spec", [
    [(" a", 1.0, 1.0), (" b.", 1.0, 1.0)],                            # start == end
    [(" uno", 2.0, 2.5), (" due", 1.0, 1.5), (" tre.", 3.0, 3.5)],     # tempi non ordinati
    [(" uno", 0.0, 2.0), (" due", 1.0, 3.0), (" tre.", 2.5, 2.6)],     # parole sovrapposte
    [(" ", 0.0, 1.0), (" ok", 1.0, 1.2)],                              # parola vuota
])
def test_segment_robust_to_bad_word_times(spec):
    subs = sl.segment(_words(spec), set())
    assert subs
    for s in subs:
        assert s["end"] >= s["start"]
    for a, b in zip(subs, subs[1:]):
        assert a["start"] <= b["start"]


# ── time_subtitles ────────────────────────────────────────────────────────────

def _sub(start: float, end: float, text: str) -> dict:
    return {"start": start, "end": end, "text": text, "confidence": 1.0}


def _cps(s: dict) -> float:
    return len(s["text"].replace("\n", " ")) / (s["end"] - s["start"])


def test_time_extends_into_silence_until_17_cps():
    text = "a" * 40
    out = sl.time_subtitles([_sub(10.0, 11.0, text), _sub(20.0, 21.0, "dopo")])
    assert out[0]["start"] == 10.0
    assert out[0]["end"] == pytest.approx(10.0 + 40 / 17.0, abs=0.002)
    assert _cps(out[0]) <= 17.0 + 0.01


def test_time_cps_counts_text_without_line_breaks():
    out = sl.time_subtitles([_sub(0.0, 1.0, "a" * 20 + "\n" + "b" * 19)])
    assert out[0]["end"] == pytest.approx(40 / 17.0, abs=0.002)


def test_time_cps_extension_stops_two_frames_before_next():
    out = sl.time_subtitles([_sub(0.0, 1.0, "a" * 60), _sub(2.0, 3.0, "dopo dopo")])
    assert out[0]["end"] == pytest.approx(2.0 - 0.083, abs=0.001)
    assert out[1]["start"] == 2.0


def test_time_pad_when_cps_already_fine():
    out = sl.time_subtitles([_sub(0.0, 3.0, "breve testo"), _sub(10.0, 11.0, "dopo")])
    assert out[0]["end"] == pytest.approx(3.2)


def test_time_min_duration():
    out = sl.time_subtitles([_sub(5.0, 5.2, "Sì."), _sub(10.0, 11.0, "dopo")])
    assert out[0]["end"] - out[0]["start"] == pytest.approx(0.833, abs=0.001)


def test_time_max_duration():
    out = sl.time_subtitles([_sub(0.0, 6.95, "a" * 84), _sub(30.0, 31.0, "dopo")])
    assert out[0]["end"] == pytest.approx(7.0)


def test_time_max_duration_even_if_speech_is_longer():
    out = sl.time_subtitles([_sub(0.0, 9.0, "testo")])
    assert out[0]["end"] == pytest.approx(7.0)


def test_time_snaps_small_gaps_to_two_frames():
    out = sl.time_subtitles([_sub(0.0, 1.0, "ciao"), _sub(1.4, 2.0, "come stai"),
                             _sub(5.0, 6.0, "bene")])
    assert out[1]["start"] - out[0]["end"] == pytest.approx(0.083, abs=0.001)
    assert out[2]["start"] - out[1]["end"] >= 0.5


def test_time_gaps_are_two_frames_or_at_least_half_second():
    subs = [_sub(0.0, 0.9, "uno due tre"), _sub(1.1, 1.8, "quattro"), _sub(2.3, 2.9, "cinque"),
            _sub(3.0, 3.5, "sei sette"), _sub(4.25, 5.0, "otto")]
    out = sl.time_subtitles(subs)
    for a, b in zip(out, out[1:]):
        gap = b["start"] - a["end"]
        assert gap == pytest.approx(0.083, abs=0.0015) or gap >= 0.5 - 1e-9, (a, b)


def test_time_never_past_audio_end():
    out = sl.time_subtitles([_sub(9.0, 9.5, "a" * 60)], audio_end=10.0)
    assert out[0]["end"] == pytest.approx(10.0)


def test_time_overlapping_words_resolved():
    out = sl.time_subtitles([_sub(0.0, 2.0, "prima"), _sub(1.5, 3.0, "seconda")])
    assert out[0]["end"] == pytest.approx(1.5 - 0.083, abs=0.001)
    assert out[0]["end"] > out[0]["start"]


def test_time_degenerate_inputs_never_overlap():
    subs = [_sub(1.0, 1.0, "a"), _sub(1.0, 1.0, "b"), _sub(1.02, 0.5, "c"), _sub(0.9, 1.1, "d")]
    out = sl.time_subtitles(subs)
    for s in out:
        assert s["end"] > s["start"]
    for a, b in zip(out, out[1:]):
        assert a["end"] <= b["start"]


def test_time_leaves_unreachable_cps():
    out = sl.time_subtitles([_sub(0.0, 1.0, "a" * 80), _sub(1.2, 2.0, "dopo")])
    assert out[0]["end"] == pytest.approx(1.2 - 0.083, abs=0.001)
    assert _cps(out[0]) > 17.0


def test_time_empty():
    assert sl.time_subtitles([]) == []


# ── layout (end-to-end) ───────────────────────────────────────────────────────

def test_layout_end_to_end_real_segment():
    seg = _seg_dict([w + ((0.99,) if len(w) == 3 else ()) for w in MATTEO])
    seg["words"][-1]["probability"] = 0.25  # "SCPT." poco probabile: resta
    subs = sl.layout([seg], audio_end=31.5)
    text = " ".join(s["text"] for s in subs)
    assert text.endswith("prodotto SCPT.")
    for s in subs:
        assert _fits(s["text"])
        assert s["end"] > s["start"]
        assert s["end"] - s["start"] <= 7.0 + 1e-9
    assert subs[-1]["end"] <= 31.5


def test_layout_empty():
    assert sl.layout([]) == []


# ── find_uncovered_speech ─────────────────────────────────────────────────────

def test_uncovered_speech_whole_span_without_words():
    speech = [(0.0, 3.0), (3.1, 4.0), (10.0, 22.0)]
    words = _words([(" ciao", 0.5, 1.0), (" come", 1.8, 2.6), (" va", 3.2, 3.5)])
    assert sl.find_uncovered_speech(speech, words) == [(10.0, 22.0)]


def test_uncovered_speech_hole_inside_long_span():
    # Caso reale (nico_ed_ema): un unico tratto VAD 7.36–46.88 s in cui Whisper non ha
    # prodotto parole tra 24.73 e 34.75 s.
    speech = [(7.36, 46.88)]
    before = _even_words("parola " * 55, start=7.4, step=0.3)      # 7.40 → 23.88
    edges = _words([(" consapevole.", 24.03, 24.73), (" di", 34.75, 35.03)])
    after = _even_words("parola " * 39, start=35.1, step=0.3)      # 35.10 → 46.78
    found = sl.find_uncovered_speech(speech, before + edges + after)
    assert found == [(pytest.approx(24.73), pytest.approx(34.75))]


def test_uncovered_speech_merges_close_spans_and_filters_short():
    speech = [(0.0, 0.8), (0.9, 1.7), (5.0, 6.0)]  # 0–1.7 unito (pausa 0.1 s); 5–6 corto
    assert sl.find_uncovered_speech(speech, []) == [(0.0, 1.7)]
    assert sl.find_uncovered_speech(speech, [], min_len_s=0.5) == [(0.0, 1.7), (5.0, 6.0)]


def test_uncovered_speech_word_overlap_counts():
    speech = [(0.0, 2.0)]
    # parole che coprono abbastanza il tratto: nessun buco ≥ 1.5 s
    assert sl.find_uncovered_speech(speech, _words([(" ehm", 0.6, 1.0)])) == []
    assert sl.find_uncovered_speech(speech, _words([(" ehm", 1.0, 1.0)])) == []
    # una parola solo in coda: i primi 1.9 s restano scoperti
    assert sl.find_uncovered_speech(speech, _words([(" ehm", 1.9, 2.5)])) == [(0.0, 1.9)]
    # parole non ordinate
    words = _words([(" b", 1.2, 2.0), (" a", 0.0, 0.4)])
    assert sl.find_uncovered_speech(speech, words) == []


def test_uncovered_speech_empty():
    assert sl.find_uncovered_speech([], []) == []

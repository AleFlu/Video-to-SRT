"""
test_engine.py — Test del motore di trascrizione senza caricare modelli Whisper.

Usa oggetti finti (SimpleNamespace) per parole e segmenti, e moduli finti
``faster_whisper`` / ``ctranslate2`` iniettati in ``sys.modules``.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import types
from types import SimpleNamespace

import pytest

import engine


# ── Helper ────────────────────────────────────────────────────────────────────

def _w(word: str, start: float, end: float, prob: float = 0.9) -> SimpleNamespace:
    return SimpleNamespace(word=word, start=start, end=end, probability=prob)


def _seg(words, text: str = "", start: float = None, end: float = None) -> SimpleNamespace:
    if start is None:
        start = words[0].start if words else 0.0
    if end is None:
        end = words[-1].end if words else 0.0
    if not text:
        text = " ".join(w.word.strip() for w in words)
    return SimpleNamespace(
        words=words, text=text, start=start, end=end,
        no_speech_prob=0.0, avg_logprob=-0.2,
    )


def _all_text(subs) -> str:
    return " ".join(s["text"] for s in subs)


# ── Composizione dei sottotitoli (core.subtitle_layout) ───────────────────────

def _fw_model(segments, captured=None, detected="it", duration=None):
    """Modello faster-whisper finto: restituisce sempre ``segments``."""
    if duration is None:
        duration = max((s.end for s in segments), default=1.0) + 1.0

    class FakeModel:
        def transcribe(self, audio, **kwargs):
            if captured is not None:
                captured.append((audio, kwargs))
            info = SimpleNamespace(duration=duration, language=detected,
                                   language_probability=0.9)
            return iter(list(segments)), info

    return FakeModel()


def _transcribe_with(monkeypatch, segments, **kwargs):
    monkeypatch.setattr(engine, "_setup_environment", lambda: None)
    monkeypatch.setattr(engine, "_get_or_load_model", lambda *a, **k: _fw_model(segments))
    kwargs.setdefault("vad_filter", False)
    return engine.transcribe("x.wav", denoise=False, **kwargs)


def test_transcribe_keeps_low_confidence_words(monkeypatch):
    """Bug storico: le parole con probabilità < 0,35 sparivano dai sottotitoli."""
    words = [_w(" Oggi", 0.0, 0.4), _w(" parliamo", 0.45, 0.9), _w(" di", 0.95, 1.05),
             _w(" Kubernetes", 1.1, 1.8, prob=0.2), _w(" insieme.", 1.85, 2.4)]
    out = _transcribe_with(monkeypatch, [_seg(words)])
    assert _all_text(out) == "Oggi parliamo di Kubernetes insieme."
    assert out[0]["confidence"] == pytest.approx(0.2)


def test_transcribe_joins_apostrophes(monkeypatch):
    """Bug storico: "l 'industria" / "dell' amore" restavano staccati."""
    words = [_w(" Questa", 0.0, 0.3), _w(" è", 0.32, 0.4), _w(" l", 0.42, 0.5),
             _w("'industria", 0.5, 1.0), _w(" dell'", 1.05, 1.2), _w(" amore.", 1.2, 1.7)]
    out = _transcribe_with(monkeypatch, [_seg(words)])
    assert _all_text(out) == "Questa è l'industria dell'amore."


def test_transcribe_returns_final_timing_and_flat_text(monkeypatch):
    """Il motore restituisce tempi definitivi (nessuno li ritocca dopo) e testo senza a capo."""
    words = [_w(" " + t, 0.1 + i * 0.3, 0.35 + i * 0.3)
             for i, t in enumerate("Questa frase è abbastanza lunga da andare su due righe "
                                   "una volta esportata come file.".split())]
    out = _transcribe_with(monkeypatch, [_seg(words)])
    assert all("\n" not in s["text"] for s in out)
    for cur, nxt in zip(out, out[1:]):
        assert cur["end"] <= nxt["start"] - 0.083 + 1e-9
    assert all(s["end"] - s["start"] >= 0.833 - 1e-9 for s in out)
    assert set(out[0]) >= {"start", "end", "text", "confidence"}


def test_transcribe_layout_follows_config_readability(monkeypatch):
    from dataclasses import replace
    from core.transcription_config import ReadabilityLimits, TranscriptionConfig
    words = [_w(" parola%02d" % i, i * 0.3, i * 0.3 + 0.25) for i in range(8)]
    cfg = replace(TranscriptionConfig(),
                  readability=ReadabilityLimits(max_chars_per_line=20, max_lines=1))
    out = _transcribe_with(monkeypatch, [_seg(words)], config=cfg)
    assert all(len(s["text"]) <= 20 for s in out)
    assert _all_text(out).split() == ["parola%02d" % i for i in range(8)]


def test_layout_rules_from_readability():
    from core.subtitle_layout import LayoutRules
    from core.transcription_config import ReadabilityLimits
    r = ReadabilityLimits(max_chars_per_line=37, max_lines=3, max_cps=25.0, warn_cps=15.0,
                          min_duration_s=1.0, max_duration_s=6.0, min_gap_s=0.1,
                          keep_low_confidence_words=False)
    rules = r.layout_rules()
    assert isinstance(rules, LayoutRules)
    assert (rules.max_chars_per_line, rules.max_lines, rules.max_cps, rules.min_duration_s,
            rules.max_duration_s, rules.min_gap_s, rules.keep_low_confidence_words) == (
        37, 3, 15.0, 1.0, 6.0, 0.1, False)
    # predefiniti = guida Netflix italiana
    assert ReadabilityLimits().layout_rules() == LayoutRules()


def test_old_pipeline_removed():
    for name in ("collect_all_words", "segment_words_semantic", "post_process_timing",
                 "_FakeWord", "_postprocess_typography", "_merge_short_fragments",
                 "_find_best_split", "MIN_GAP_BETWEEN_SUBS", "MIN_WORD_PROB",
                 "_WhisperXSegmentAdapter"):
        assert not hasattr(engine, name), name


# ── Recupero del parlato saltato dal VAD ──────────────────────────────────────

class _SliceModel:
    """Modello finto per la ritrascrizione: parole con tempi relativi all'inizio della
    porzione di audio ricevuta (come faster-whisper con un array numpy)."""

    def __init__(self, words_abs, fail=False):
        self.words_abs = words_abs    # [(testo, inizio assoluto, fine assoluta)]
        self.calls = []
        self.fail = fail

    def transcribe(self, audio, **kwargs):
        self.calls.append((audio, kwargs))
        if self.fail:
            raise RuntimeError("decodifica fallita")
        offset = audio.offset
        ws = [_w(t, s - offset, e - offset) for t, s, e in self.words_abs
              if offset <= s and e <= offset + len(audio) / 16000]
        segs = [_seg(ws)] if ws else []
        return iter(segs), SimpleNamespace(duration=len(audio) / 16000, language="it",
                                           language_probability=0.9)


class _Pcm:
    """Audio finto: basta che si possa affettare e misurare (tiene traccia dell'offset)."""

    def __init__(self, seconds, offset=0.0):
        self.n = int(seconds * 16000)
        self.offset = offset

    def __len__(self):
        return self.n

    def __getitem__(self, sl):
        start = sl.start or 0
        stop = min(self.n, sl.stop if sl.stop is not None else self.n)
        return _Pcm((stop - start) / 16000, self.offset + start / 16000)


def _speech_seg(texts, t0, step=0.4):
    return _seg([_w(" " + t, t0 + i * step, t0 + i * step + step - 0.05)
                 for i, t in enumerate(texts)])


def test_recover_skipped_speech_merges_hole_words_in_time_order(monkeypatch):
    before = _speech_seg(["Prima", "parte", "del", "discorso."], 0.0)
    after = _speech_seg(["Ultima", "parte."], 9.0)
    # parole "vere" nel buco 3–8 s, più una fuori dal buco (deve essere scartata)
    hole_words = [(" In", 3.2, 3.5), (" questo", 3.6, 4.0), (" caso,", 4.1, 4.6),
                  (" per", 4.7, 5.0), (" esempio.", 5.1, 5.8), (" fuori", 8.1, 8.25)]
    model = _SliceModel(hole_words)
    monkeypatch.setattr(engine, "_vad_speech_spans", lambda pcm, opts: [(0.0, 8.0),
                                                                         (9.0, 10.0)])
    statuses = []
    merged = engine._recover_skipped_speech(
        model, _Pcm(12.0), [before, after], {"threshold": 0.5},
        {"language": "it", "hotwords": "deploy", "beam_size": 5, "vad_filter": True,
         "vad_parameters": {"threshold": 0.5}},
        cancel_event=None, on_status=statuses.append)
    assert len(model.calls) == 1
    audio, kw = model.calls[0]
    assert kw["vad_filter"] is False and "vad_parameters" not in kw
    assert kw["language"] == "it" and kw["hotwords"] == "deploy" and kw["word_timestamps"]
    assert audio.offset == pytest.approx(1.55 - 0.3, abs=1e-3)  # buco 1,55–8 s, margine 0,3
    texts = [" ".join(w.word.strip() if hasattr(w, "word") else w["word"].strip()
                      for w in (s.words if hasattr(s, "words") else s["words"]))
             for s in merged]
    assert texts == ["Prima parte del discorso.", "In questo caso, per esempio.",
                     "Ultima parte."]
    starts = [s.start if hasattr(s, "start") else s["start"] for s in merged]
    assert starts == sorted(starts) and starts[1] == pytest.approx(3.2)
    assert any("Recupero di 1 tratto di parlato saltato" in m for m in statuses)


def _merged_words(merged):
    words = []
    for seg in merged:
        for w in (seg.words if hasattr(seg, "words") else seg["words"]):
            words.append(w.word.strip() if hasattr(w, "word") else w["word"].strip())
    return words


def test_recover_skipped_speech_boundary_words(monkeypatch):
    """Caso reale ("nico", buco 24,73–34,75 s): una parola a cavallo della fine del buco
    ("lusso") va tenuta anche se il punto medio cade fuori; una a cavallo dell'inizio ("In")
    va tenuta se il punto medio cade dentro."""
    before = _speech_seg(["Prima."], 0.0)
    after = _seg([_w(" di", 6.75, 7.05), _w(" altissima", 7.05, 7.6),
                  _w(" qualità.", 7.6, 8.1)])
    hole_words = [(" In", 0.3, 0.6), (" del", 2.0, 2.3), (" denim", 2.3, 2.6),
                  (" di", 6.4, 6.62), (" lusso", 6.62, 6.98)]
    monkeypatch.setattr(engine, "_vad_speech_spans", lambda pcm, opts: [(0.0, 8.2)])
    merged = engine._recover_skipped_speech(_SliceModel(hole_words), _Pcm(9.0),
                                            [before, after], {}, {})
    assert _merged_words(merged) == ["Prima.", "In", "del", "denim", "di", "lusso", "di",
                                     "altissima", "qualità."]


def test_recover_skipped_speech_drops_duplicate_of_neighbour(monkeypatch):
    """Una parola ritrascritta che ripete quella già presente subito dopo il buco (stesso
    testo, tempi sovrapposti) non viene duplicata ("denim di di altissima")."""
    before = _speech_seg(["Prima."], 0.0)
    after = _seg([_w(" di", 6.75, 7.05), _w(" altissima", 7.05, 7.6)])
    hole_words = [(" del", 2.0, 2.3), (" denim", 2.3, 2.6), (" Di,", 6.5, 6.85)]
    monkeypatch.setattr(engine, "_vad_speech_spans", lambda pcm, opts: [(0.0, 8.0)])
    merged = engine._recover_skipped_speech(_SliceModel(hole_words), _Pcm(9.0),
                                            [before, after], {}, {})
    assert _merged_words(merged) == ["Prima.", "del", "denim", "di", "altissima"]


def test_recover_skipped_speech_drops_duplicate_touching_zero_length_word(monkeypatch):
    """Caso reale (Cappato reels 4, tempi −54 s): la parola dopo il buco ha durata nulla
    e tempi sfasati (" La" 59,98–59,98), quella ritrascritta è a 59,22–59,64 s: "che se
    la La democrazia"."""
    before = _speech_seg(["Prima."], 0.0)
    after = _seg([_w(" La", 5.98, 5.98, prob=0.014), _w(" democrazia", 5.98, 6.48)])
    hole_words = [(" che", 4.94, 5.02), (" se", 5.02, 5.22), (" la", 5.22, 5.64),
                  (" democrazia", 5.64, 6.12)]
    monkeypatch.setattr(engine, "_vad_speech_spans", lambda pcm, opts: [(0.0, 6.6)])
    merged = engine._recover_skipped_speech(_SliceModel(hole_words), _Pcm(7.0),
                                            [before, after], {}, {})
    assert _merged_words(merged) == ["Prima.", "che", "se", "La", "democrazia"]


def test_recover_skipped_speech_no_holes_returns_input(monkeypatch):
    seg = _speech_seg(["Tutto", "coperto."], 0.0)
    model = _SliceModel([])
    monkeypatch.setattr(engine, "_vad_speech_spans", lambda pcm, opts: [(0.0, 0.8)])
    assert engine._recover_skipped_speech(model, _Pcm(2.0), [seg], {}, {}) == [seg]
    assert model.calls == []


def test_recover_skipped_speech_failure_never_breaks(monkeypatch):
    seg = _speech_seg(["Ciao."], 0.0)
    monkeypatch.setattr(engine, "_vad_speech_spans", lambda pcm, opts: [(0.0, 6.0)])
    model = _SliceModel([], fail=True)
    assert engine._recover_skipped_speech(model, _Pcm(7.0), [seg], {}, {}) == [seg]

    def broken_vad(pcm, opts):
        raise RuntimeError("onnx mancante")
    monkeypatch.setattr(engine, "_vad_speech_spans", broken_vad)
    assert engine._recover_skipped_speech(model, _Pcm(7.0), [seg], {}, {}) == [seg]


def test_recover_skipped_speech_respects_cancel(monkeypatch):
    seg = _speech_seg(["Ciao."], 0.0)
    monkeypatch.setattr(engine, "_vad_speech_spans",
                        lambda pcm, opts: [(0.0, 0.4), (2.0, 5.0), (7.0, 10.0)])
    ev = threading.Event()
    ev.set()
    model = _SliceModel([])
    with pytest.raises(engine.TranscriptionCancelled):
        engine._recover_skipped_speech(model, _Pcm(11.0), [seg], {}, {}, cancel_event=ev)
    assert model.calls == []


def test_transcribe_end_to_end_with_recovered_hole(monkeypatch):
    """Pipeline completa con VAD: apostrofi uniti, parola poco probabile tenuta, buco
    del VAD ritrascritto e inserito al suo posto."""
    first = _seg([_w(" Questa", 0.0, 0.3), _w(" è", 0.32, 0.4), _w(" l", 0.42, 0.5),
                  _w("'idea", 0.5, 0.9), _w(" di", 0.95, 1.05),
                  _w(" Matteo.", 1.1, 1.6, prob=0.1)])
    last = _speech_seg(["Grazie", "a", "tutti."], 12.0)
    hole = [(" In", 4.0, 4.3), (" questo", 4.4, 4.8), (" specifico", 4.9, 5.5),
            (" caso,", 5.6, 6.0), (" per", 6.1, 6.3), (" esempio.", 6.4, 7.0)]
    captured = []

    class Model:
        def transcribe(self, audio, **kwargs):
            captured.append(kwargs)
            if isinstance(audio, _Pcm):
                return _SliceModel(hole).transcribe(audio, **kwargs)
            return iter([first, last]), SimpleNamespace(duration=14.0, language="it",
                                                        language_probability=0.9)

    monkeypatch.setattr(engine, "_setup_environment", lambda: None)
    monkeypatch.setattr(engine, "_get_or_load_model", lambda *a, **k: Model())
    monkeypatch.setattr(engine, "_decode_pcm", lambda path: _Pcm(14.0))
    monkeypatch.setattr(engine, "_vad_speech_spans",
                        lambda pcm, opts: [(0.0, 1.7), (3.8, 7.2), (12.0, 13.2)])
    statuses = []
    out = engine.transcribe("x.wav", denoise=False, vad_filter=True,
                            on_status=statuses.append)
    texts = [s["text"] for s in out]
    assert texts == ["Questa è l'idea di Matteo.", "In questo specifico caso, per esempio.",
                     "Grazie a tutti."]
    assert out[0]["confidence"] == pytest.approx(0.1)
    assert out[1]["start"] == pytest.approx(4.0)
    assert out[-1]["end"] <= 14.0
    assert captured[1]["vad_filter"] is False and captured[1]["language"] == "it"
    assert any("Recupero di 1 tratto" in m for m in statuses)


def test_recover_skipped_speech_replaces_stretched_words(monkeypatch):
    """Caso reale (Cappato reels 4, VAD spento): Whisper ripete "facendo così con
    l'orecchio" e stira le ultime parole su 27 s ("con" 32,54–48,96, "l" 48,96–56,6,
    "'orecchio." 56,6–59,94) al posto del parlato vero. Il tratto viene ritrascritto e le
    parole stirate lasciano il posto a quelle ritrascritte."""
    seg = _seg([_w(" facendo", 31.78, 32.4), _w(" così", 32.4, 32.54),
                _w(" con", 32.54, 48.96), _w(" l", 48.96, 56.6),
                _w("'orecchio.", 56.6, 59.94)])
    after = _seg([_w(" La", 59.98, 59.98), _w(" democrazia", 59.98, 60.48)])
    hole_words = [(" con", 32.6, 32.8), (" l'orecchio.", 32.8, 33.4), (" Se", 33.5, 33.7),
                  (" tu", 33.7, 33.9), (" devi", 33.9, 34.2), (" pagare", 34.2, 34.7),
                  (" firmare", 40.1, 40.6), (" una", 40.6, 40.8), (" proposta,", 40.8, 41.4),
                  (" chiedere", 55.5, 55.9), (" il", 55.9, 56.0), (" permesso.", 56.0, 56.5),
                  (" Quindi", 57.4, 57.7), (" è", 57.7, 57.8), (" chiaro", 57.8, 58.2)]
    monkeypatch.setattr(engine, "_vad_speech_spans", lambda pcm, opts: [(29.9, 61.0)])
    merged = engine._recover_skipped_speech(_SliceModel(hole_words), _Pcm(62.0),
                                            [seg, after], {}, {})
    assert _merged_words(merged) == [
        "facendo", "così", "con", "l'orecchio.", "Se", "tu", "devi", "pagare", "firmare",
        "una", "proposta,", "chiedere", "il", "permesso.", "Quindi", "è", "chiaro", "La",
        "democrazia"]
    for s in merged:
        for w in (s.words if hasattr(s, "words") else s["words"]):
            start = w.start if hasattr(w, "start") else w["start"]
            end = w.end if hasattr(w, "end") else w["end"]
            assert end - start < 3.0


def test_recover_keeps_stretched_words_when_nothing_is_recovered(monkeypatch):
    """Se la ritrascrizione non trova niente, le parole stirate restano: meglio un
    sottotitolo con tempi larghi che nessun sottotitolo."""
    seg = _seg([_w(" con", 2.0, 9.0)])
    monkeypatch.setattr(engine, "_vad_speech_spans", lambda pcm, opts: [(1.0, 10.0)])
    merged = engine._recover_skipped_speech(_SliceModel([]), _Pcm(11.0), [seg], {}, {})
    assert _merged_words(merged) == ["con"]


def test_transcribe_without_vad_still_recovers_skipped_speech(monkeypatch):
    """Con il filtro VAD spento Whisper salta ancora più spesso pezzi di parlato: il
    recupero (che usa il VAD solo per trovare i buchi) gira lo stesso."""
    first = _speech_seg(["Prima", "parte."], 0.0)
    last = _speech_seg(["Grazie."], 12.0)
    hole = [(" In", 4.0, 4.3), (" questo", 4.4, 4.8), (" caso.", 4.9, 5.5)]
    captured = []

    class Model:
        def transcribe(self, audio, **kwargs):
            captured.append(kwargs)
            if isinstance(audio, _Pcm):
                return _SliceModel(hole).transcribe(audio, **kwargs)
            return iter([first, last]), SimpleNamespace(duration=14.0, language="it",
                                                        language_probability=0.9)

    monkeypatch.setattr(engine, "_setup_environment", lambda: None)
    monkeypatch.setattr(engine, "_get_or_load_model", lambda *a, **k: Model())
    monkeypatch.setattr(engine, "_decode_pcm", lambda path: _Pcm(14.0))
    monkeypatch.setattr(engine, "_vad_speech_spans",
                        lambda pcm, opts: [(0.0, 0.8), (3.8, 6.0), (12.0, 12.5)])
    out = engine.transcribe("x.wav", denoise=False, vad_filter=False)
    assert [s["text"] for s in out] == ["Prima parte.", "In questo caso.", "Grazie."]
    assert captured[0]["vad_filter"] is False and "vad_parameters" not in captured[0]


# ── Cache modello thread-safe ─────────────────────────────────────────────────

@pytest.fixture
def fake_backends(monkeypatch):
    """Inietta moduli finti faster_whisper e ctranslate2."""
    calls = []
    lock = threading.Lock()

    class FakeWhisperModel:
        def __init__(self, path, **kwargs):
            time.sleep(0.05)
            with lock:
                calls.append((path, kwargs))
            self.path = path

    fw = types.ModuleType("faster_whisper")
    fw.WhisperModel = FakeWhisperModel
    ct2 = types.ModuleType("ctranslate2")
    ct2.cuda_count = 0
    ct2.get_cuda_device_count = lambda: ct2.cuda_count
    ct2.get_supported_compute_types = lambda device: {"int8", "float32"}
    monkeypatch.setitem(sys.modules, "faster_whisper", fw)
    monkeypatch.setitem(sys.modules, "ctranslate2", ct2)
    monkeypatch.setitem(engine._model_cache, "model", None)
    monkeypatch.setitem(engine._model_cache, "model_key", None)
    return SimpleNamespace(calls=calls, ct2=ct2)


def test_model_cache_concurrent_loads_once(fake_backends):
    results = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        results.append(engine._get_or_load_model("tiny"))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert len(fake_backends.calls) == 1
    assert len(results) == 2
    assert results[0] is results[1]
    assert results[0].path == "tiny"
    assert fake_backends.calls[0][1].get("num_workers") == 1


def test_model_cache_reload_on_different_key(fake_backends):
    m1 = engine._get_or_load_model("tiny")
    m2 = engine._get_or_load_model("tiny")
    m3 = engine._get_or_load_model("base")
    assert m1 is m2
    assert m3 is not m1
    assert len(fake_backends.calls) == 2


def test_get_optimal_device_uses_ctranslate2(fake_backends):
    assert engine.get_optimal_device() == ("cpu", "int8")
    fake_backends.ct2.cuda_count = 1
    assert engine.get_optimal_device() == ("cuda", "float16")


# ── Varie ─────────────────────────────────────────────────────────────────────

def test_check_cancel():
    engine._check_cancel(None)
    ev = threading.Event()
    engine._check_cancel(ev)
    ev.set()
    with pytest.raises(engine.TranscriptionCancelled, match="annullata dall'utente"):
        engine._check_cancel(ev)


def test_renamed_postprocessors():
    assert engine._postprocess_codeswitching("il macchina lerning") == "il machine learning"
    assert not hasattr(engine, "_postprocess_italian")
    assert not hasattr(engine, "_postprocess_italian_subs")


def test_dead_code_removed():
    for name in ("format_timestamp_srt", "wrap_subtitle_text", "generate_srt",
                 "write_srt", "_unique_output_path", "split_segment_by_words",
                 "SILENCE_THRESHOLD", "END_PAD_SPEECH", "END_PAD_SILENCE",
                 "READING_SPEED_CPS"):
        assert not hasattr(engine, name), name


def test_vad_params_constant():
    assert engine.VAD_PARAMS == dict(min_silence_duration_ms=150, speech_pad_ms=100,
                                     threshold=0.50)


def test_vad_error_classification():
    assert engine._is_vad_unavailable_error(ImportError("No module named 'onnxruntime'"))
    assert engine._is_vad_unavailable_error(
        RuntimeError("[ONNXRuntimeError] : 3 : NO_SUCHFILE silero_vad.onnx"))
    assert not engine._is_vad_unavailable_error(RuntimeError("out of memory"))
    assert not engine._is_vad_unavailable_error(FileNotFoundError("video.mp4"))


class _FakePopen:
    """Popen finto: ``communicate`` va in timeout finché non viene terminato."""

    instances = []

    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.stop = False
        _FakePopen.instances.append(self)

    def communicate(self, timeout=None):
        import subprocess
        if self.stop:
            self.returncode = 1 if self.returncode is None else self.returncode
            return "", "errore"
        time.sleep(min(timeout or 0.01, 0.01))
        raise subprocess.TimeoutExpired(self.cmd, timeout)

    def terminate(self):
        self.terminated = True
        self.stop = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.stop = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode


def test_preprocess_audio_failure_reports_status(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, "_FFMPEG_TIMEOUT_S", 0.3)
    monkeypatch.setattr(engine.subprocess, "Popen", _FakePopen)
    msgs = []
    assert engine.preprocess_audio(str(tmp_path / "x.mp4"), on_status=msgs.append) is None
    assert any("Pre-elaborazione audio non riuscita" in m for m in msgs)
    assert _FakePopen.instances[-1].terminated   # ffmpeg non resta in giro dopo il timeout


def test_preprocess_audio_uses_absolute_path(monkeypatch):
    _FakePopen.instances.clear()

    class Fail(_FakePopen):
        def communicate(self, timeout=None):
            self.returncode = 1
            return "", "errore"

    monkeypatch.setattr(engine.subprocess, "Popen", Fail)
    engine.preprocess_audio("-strano.mp4")
    cmd = _FakePopen.instances[-1].cmd
    i = cmd.index("-i")
    assert cmd[i + 1].startswith(("/", "\\")) or ":" in cmd[i + 1]


def test_preprocess_audio_cancel_terminates_ffmpeg_and_removes_temp(monkeypatch):
    _FakePopen.instances.clear()
    created = []
    real_ntf = engine.tempfile.NamedTemporaryFile

    def tracking_ntf(*a, **k):
        f = real_ntf(*a, **k)
        created.append(f.name)
        return f

    monkeypatch.setattr(engine.tempfile, "NamedTemporaryFile", tracking_ntf)
    monkeypatch.setattr(engine.subprocess, "Popen", _FakePopen)
    ev = threading.Event()
    threading.Timer(0.3, ev.set).start()
    t0 = time.monotonic()
    with pytest.raises(engine.TranscriptionCancelled):
        engine.preprocess_audio("x.mp4", cancel_event=ev)
    assert time.monotonic() - t0 < 3
    proc = _FakePopen.instances[-1]
    assert proc.terminated or proc.killed
    assert created and not os.path.exists(created[0])


def test_preprocess_audio_already_cancelled_does_not_leave_temp(monkeypatch):
    _FakePopen.instances.clear()
    monkeypatch.setattr(engine.subprocess, "Popen", _FakePopen)
    ev = threading.Event()
    ev.set()
    with pytest.raises(engine.TranscriptionCancelled):
        engine.preprocess_audio("x.mp4", cancel_event=ev)
    assert all(p.terminated or p.killed for p in _FakePopen.instances)


def test_transcribe_passes_cancel_event_to_preprocess(monkeypatch):
    seen = {}

    def fake_pre(path, on_status=None, cancel_event=None):
        seen["ev"] = cancel_event
        raise engine.TranscriptionCancelled()

    monkeypatch.setattr(engine, "_setup_environment", lambda: None)
    monkeypatch.setattr(engine, "preprocess_audio", fake_pre)
    ev = threading.Event()
    with pytest.raises(engine.TranscriptionCancelled):
        engine.transcribe("x.mp4", denoise=True, cancel_event=ev)
    assert seen["ev"] is ev


def test_transcribe_is_keyword_only():
    import inspect
    params = inspect.signature(engine.transcribe).parameters
    names = list(params)
    assert names[0] == "input_path"
    for name in names[1:]:
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY, name
    assert "language" in params


def test_check_ffmpeg_uses_which(monkeypatch):
    monkeypatch.setattr(engine, "get_bundled_ffmpeg", lambda: None)
    monkeypatch.setattr(engine.shutil, "which", lambda name: None)
    assert engine.check_ffmpeg() is False
    monkeypatch.setattr(engine.shutil, "which", lambda name: "/usr/bin/" + name)
    assert engine.check_ffmpeg() is True


# ── Lingua "auto" ─────────────────────────────────────────────────────────────

def _fake_whisper_model(detected: str, captured: dict):
    """Modello finto che cattura i kwargs di transcribe e rileva ``detected``."""
    word = _w("Machine", 0.0, 0.5)
    word2 = _w("learning", 0.5, 1.0)
    seg = _seg([word, word2], text="Machine learning", start=0.0, end=1.0)

    class FakeModel:
        def transcribe(self, audio, **kwargs):
            captured.update(kwargs)
            info = SimpleNamespace(duration=1.0, language=detected,
                                   language_probability=0.9)
            return iter([seg]), info

    return FakeModel()


def _run_transcribe(monkeypatch, language, detected="en"):
    captured = {}
    monkeypatch.setattr(engine, "_setup_environment", lambda: None)
    monkeypatch.setattr(engine, "_get_or_load_model",
                        lambda *a, **k: _fake_whisper_model(detected, captured))
    out = engine.transcribe("x.wav", denoise=False, vad_filter=False, language=language)
    return captured, out


@pytest.mark.parametrize("raw", ["auto", "", None])
def test_transcribe_auto_passes_none_language(monkeypatch, raw):
    captured, _ = _run_transcribe(monkeypatch, raw, detected="en")
    assert captured["language"] is None
    assert captured["initial_prompt"] is None


def test_transcribe_italian_uses_prompt(monkeypatch):
    captured, _ = _run_transcribe(monkeypatch, "it", detected="it")
    assert captured["language"] == "it"
    assert captured["initial_prompt"] == engine.ITALIAN_PROMPT


def test_transcribe_auto_detected_italian_applies_codeswitching(monkeypatch):
    calls = []
    monkeypatch.setattr(engine, "_postprocess_codeswitching",
                        lambda t: calls.append(t) or t)
    _run_transcribe(monkeypatch, "auto", detected="it")
    assert calls


def test_transcribe_auto_detected_english_skips_codeswitching(monkeypatch):
    calls = []
    monkeypatch.setattr(engine, "_postprocess_codeswitching",
                        lambda t: calls.append(t) or t)
    _run_transcribe(monkeypatch, "auto", detected="en")
    assert not calls


def test_normalize_language():
    from core.constants import normalize_language
    assert normalize_language("auto") is None
    assert normalize_language(None) is None
    assert normalize_language(" IT ") == "it"


# ── "Alta precisione" non disponibile: mai un ripiego silenzioso ─────────────

def test_high_accuracy_unavailable_is_reported(monkeypatch):
    captured, statuses = {}, []
    monkeypatch.setattr(engine, "_setup_environment", lambda: None)
    monkeypatch.setattr(engine, "_has_whisperx", lambda: False)
    monkeypatch.setattr(engine, "high_accuracy_unavailable_reason",
                        lambda: "WhisperX non è installato (pip install whisperx)")
    monkeypatch.setattr(engine, "_get_or_load_model",
                        lambda *a, **k: _fake_whisper_model("it", captured))
    out = engine.transcribe("x.wav", denoise=False, vad_filter=False, language="it",
                            high_accuracy=True, on_status=statuses.append)
    assert out, "deve comunque trascrivere in modalità standard"
    assert any("Alta precisione non disponibile" in s and "WhisperX" in s for s in statuses)


def test_high_accuracy_reason_when_package_missing(monkeypatch):
    import importlib.util
    monkeypatch.setattr(engine, "_is_frozen", lambda: False)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert "WhisperX" in engine.high_accuracy_unavailable_reason()
    assert engine.high_accuracy_available() is False
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    assert engine.high_accuracy_available() is True
    monkeypatch.setattr(engine, "_is_frozen", lambda: True)
    assert engine.high_accuracy_available() is False


# ── Correzioni di code-switching: mai toccare l'italiano normale ─────────────

_EVERYDAY_ITALIAN = [
    "Le api fanno il miele.",
    "Ho visto delle api sul balcone.",
    "Ho scritto una bella storia.",
    "Le storie dei nonni sono le più belle.",
    "Il codice è pronto.",
    "Ci vediamo dopo con i codici.",
    "Che stress, questa settimana.",
    "Il server ha risposto.",
    "Lo stream è iniziato.",
    "Ho guardato i Reels di ieri sera.",
    "La UIF ha ricevuto la segnalazione.",
    "Dobbiamo debuggare il codice prima di stasera.",
    "Abbiamo rifattorizzato il modulo.",
    "Il Web è cambiato molto.",
    "La data sette marzo va bene.",
    "Il marketing è importante.",
    "Ci vendiamo la macchina.",
]


@pytest.mark.parametrize("sentence", _EVERYDAY_ITALIAN)
def test_codeswitching_leaves_everyday_italian_unchanged(sentence):
    assert engine._postprocess_codeswitching(sentence) == sentence


@pytest.mark.parametrize("raw, fixed", [
    ("il macchina lerning", "il machine learning"),
    ("usiamo il dip lerning", "usiamo il deep learning"),
    ("un buon fremework", "un buon framework"),
    ("il beck end e il front end", "il backend e il frontend"),
    ("facciamo il deploi", "facciamo il deploy"),
    ("il docher e cubernetis", "il Docker e Kubernetes"),
    ("le API REST", "le API REST"),
    ("chiamo le api rest", "chiamo le API rest"),
    ("serve una api key", "serve una API key"),
    ("ho aperto una pull raquest", "ho aperto una pull request"),
    ("lo trovi su git hab", "lo trovi su GitHub"),
    ("un buon uik end", "un buon weekend"),
    ("una nuova featura", "una nuova feature"),
    ("la nostra codic base", "la nostra codebase"),
    ("abbiamo un sdk", "abbiamo un SDK"),
    ("Macchina lerning", "Machine learning"),
])
def test_codeswitching_intended_fixes_still_work(raw, fixed):
    assert engine._postprocess_codeswitching(raw) == fixed
